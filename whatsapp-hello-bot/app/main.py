import json
import logging
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeSerializer
from starlette.middleware.sessions import SessionMiddleware

from app.config import (
    ADMIN_PASSWORD,
    BASE_DIR,
    GUIDED_ENABLED,
    SECRET_KEY,
    TEMPLATES_DIR,
    WHATSAPP_VERIFY_TOKEN,
    credential_status,
)
from app.event_link_store import event_link_view, set_event_link_settings
from app.faq_admin import (
    FAQ_USAGE_TEXT,
    HELP_TEXT,
    append_faq_entry,
    format_parent_answer,
    is_faq_admin,
    is_faq_command,
    is_help_command,
    is_opener_message,
    parse_faq_command,
)
from app.faq_rag import rebuild_index
from app.faq_service import answer_faq_question
from app.faq_store import clear_faq_cache, faq_storage_label, get_faq_text, set_faq_text
from app.greeting_store import get_greeting, set_greeting
from app.guided_engine import advance as advance_guided
from app.guided_engine import preview_topic
from app.guided_metrics import get_guided_metrics
from app.guided_router import begin_guided, route_message
from app.guided_state import already_seen_message, get_session as get_guided_session
from app.guided_store import (
    get_topic,
    guided_storage_label,
    list_topics,
    set_topic,
    set_topic_enabled,
)
from app.metrics import get_metrics, record_question
from app.whatsapp import send_choices, send_text_message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="WhatsApp Hello Bot", docs_url="/docs")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, session_cookie="hello_bot_session")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
signer = URLSafeSerializer(SECRET_KEY, salt="admin-auth")

BRANDING_DIR = BASE_DIR / "data" / "branding"
if BRANDING_DIR.is_dir():
    app.mount(
        "/static/branding",
        StaticFiles(directory=str(BRANDING_DIR)),
        name="branding",
    )

BRANDING = {
    "logo_url": "/static/branding/crone_logo.png",
    "favicon_url": "/static/branding/crone_favicon.png",
    "pin_poster_url": "/static/branding/crone-ptsa-assistant-pin.png",
    "pin_poster_filename": "crone-ptsa-assistant-pin.png",
}


@app.on_event("startup")
async def log_credential_status() -> None:
    status = credential_status()
    logger.info("Startup credential check: %s", status)
    if not status["access_token_len"] or not status["phone_number_id_set"]:
        logger.warning(
            "WhatsApp send will fail until WHATSAPP_ACCESS_TOKEN and "
            "WHATSAPP_PHONE_NUMBER_ID are set in .env and uvicorn is restarted."
        )
    if not status["openai_api_key_set"]:
        logger.warning(
            "OPENAI_API_KEY is missing. FAQ answers will use the parent-friendly "
            "fallback until it is set in .env and uvicorn is restarted."
        )
    if not status["faq_file_exists"] and not status.get("faq_gcs_bucket"):
        logger.warning("FAQ file is missing: data/science_olympiad_faq.txt")
    logger.info("FAQ storage: %s", faq_storage_label())
    try:
        from app.faq_store import get_faq_text

        warmed = get_faq_text()
        logger.info("Warmed FAQ cache (%s chars)", len(warmed))
    except Exception:
        logger.exception("Could not warm FAQ cache on startup")


def _is_logged_in(request: Request) -> bool:
    token = request.session.get("admin")
    if not token:
        return False
    try:
        return signer.loads(token) == "ok"
    except BadSignature:
        return False


def _login(request: Request) -> None:
    request.session["admin"] = signer.dumps("ok")


def _logout(request: Request) -> None:
    request.session.clear()


@app.get("/", response_class=PlainTextResponse)
async def root() -> str:
    return (
        "WhatsApp Hello Bot is running.\n"
        "Admin: /admin\n"
        "  Group link: /admin/link\n"
        "  Intro: /admin/intro\n"
        "  FAQ: /admin/faq\n"
        "Webhook: /webhook\n"
        "Health: /health\n"
        "Metrics: /metrics\n"
        f"FAQ storage: {faq_storage_label()}\n"
    )


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_policy() -> HTMLResponse:
    path = Path(__file__).resolve().parent.parent / "privacy-policy.html"
    return HTMLResponse(path.read_text(encoding="utf-8"))


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics")
async def metrics() -> dict[str, object]:
    """Simple usage counters for local/prod inspection."""
    data = get_metrics()
    data["guided"] = get_guided_metrics()
    data["guided_enabled"] = GUIDED_ENABLED
    return data


def _extract_inbound_text(message: dict[str, Any]) -> str:
    mtype = message.get("type")
    if mtype == "text":
        return ((message.get("text") or {}).get("body") or "").strip()
    if mtype == "interactive":
        interactive = message.get("interactive") or {}
        itype = interactive.get("type")
        if itype == "button_reply":
            reply = interactive.get("button_reply") or {}
            return (reply.get("id") or reply.get("title") or "").strip()
        if itype == "list_reply":
            reply = interactive.get("list_reply") or {}
            return (reply.get("id") or reply.get("title") or "").strip()
    return ""


async def _send_guided_result(phone: str, result: dict[str, Any]) -> None:
    messages = result.get("messages") or []
    choices = result.get("choices")
    if not messages:
        return
    # Send all but last as plain text; attach choices to the final prompt.
    for body in messages[:-1]:
        await send_text_message(phone, body)
    await send_choices(phone, messages[-1], choices)


def _branding_context() -> dict[str, str]:
    return dict(BRANDING)


def _link_context(*, saved: bool = False, error: str | None = None) -> dict[str, object]:
    link = event_link_view()
    return {
        **_branding_context(),
        "bot_phone": link["bot_phone"] or "",
        "prefill_text": link["prefill_text"] or "",
        "wa_me_link": link["wa_me_link"],
        "group_message": link["group_message"] or "",
        "link_storage": link["storage"],
        "saved": saved,
        "error": error,
    }


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request) -> Response:
    if _is_logged_in(request):
        return RedirectResponse(url="/admin/link", status_code=303)
    return templates.TemplateResponse(
        request,
        "admin.html",
        {**_branding_context(), "error": None},
    )


@app.post("/admin/login", response_class=HTMLResponse)
async def admin_login(request: Request, password: str = Form(...)) -> Response:
    if password != ADMIN_PASSWORD:
        return templates.TemplateResponse(
            request,
            "admin.html",
            {**_branding_context(), "error": "Wrong password."},
            status_code=401,
        )
    _login(request)
    return RedirectResponse(url="/admin/link", status_code=303)


@app.get("/admin/logout")
async def admin_logout(request: Request) -> Response:
    _logout(request)
    return RedirectResponse(url="/admin", status_code=303)


@app.get("/admin/link", response_class=HTMLResponse)
async def admin_link_page(request: Request, saved: int = 0) -> Response:
    if not _is_logged_in(request):
        return RedirectResponse(url="/admin", status_code=303)
    return templates.TemplateResponse(
        request,
        "admin_link.html",
        _link_context(saved=bool(saved)),
    )


@app.post("/admin/link", response_class=HTMLResponse)
async def admin_link_save(
    request: Request,
    bot_phone: str = Form(""),
    prefill_text: str = Form(...),
    group_message: str = Form(""),
) -> Response:
    if not _is_logged_in(request):
        return RedirectResponse(url="/admin", status_code=303)
    try:
        set_event_link_settings(
            bot_phone=bot_phone,
            prefill_text=prefill_text,
            group_message=group_message,
        )
    except Exception as exc:
        logger.exception("Failed saving WhatsApp link settings")
        return templates.TemplateResponse(
            request,
            "admin_link.html",
            _link_context(error=f"Could not save link settings: {exc}"),
            status_code=400,
        )
    return RedirectResponse(url="/admin/link?saved=1", status_code=303)


@app.get("/admin/intro", response_class=HTMLResponse)
async def admin_intro_page(request: Request, saved: int = 0) -> Response:
    if not _is_logged_in(request):
        return RedirectResponse(url="/admin", status_code=303)
    return templates.TemplateResponse(
        request,
        "admin_intro.html",
        {
            **_branding_context(),
            "message": get_greeting(),
            "saved": bool(saved),
        },
    )


@app.post("/admin/intro")
async def admin_intro_save(request: Request, message: str = Form(...)) -> Response:
    if not _is_logged_in(request):
        return RedirectResponse(url="/admin", status_code=303)
    set_greeting(message)
    return RedirectResponse(url="/admin/intro?saved=1", status_code=303)


# Keep old greeting save URL working for a bit.
@app.post("/admin/message")
async def admin_save_message(request: Request, message: str = Form(...)) -> Response:
    if not _is_logged_in(request):
        return RedirectResponse(url="/admin", status_code=303)
    set_greeting(message)
    return RedirectResponse(url="/admin/intro?saved=1", status_code=303)


@app.get("/admin/faq", response_class=HTMLResponse)
async def admin_faq_page(request: Request, saved: int = 0) -> Response:
    if not _is_logged_in(request):
        return RedirectResponse(url="/admin", status_code=303)
    error = None
    faq_text = ""
    try:
        # Always re-read durable storage in admin so uploads/edits aren't hidden
        # by the process-local FAQ cache.
        clear_faq_cache()
        faq_text = get_faq_text()
    except Exception as exc:
        logger.exception("Failed loading FAQ for admin UI")
        error = str(exc)
    return templates.TemplateResponse(
        request,
        "admin_faq.html",
        {
            **_branding_context(),
            "faq_text": faq_text,
            "saved": bool(saved),
            "error": error,
            "storage": faq_storage_label(),
        },
    )


@app.post("/admin/faq", response_class=HTMLResponse)
async def admin_faq_save(request: Request, faq_text: str = Form(...)) -> Response:
    if not _is_logged_in(request):
        return RedirectResponse(url="/admin", status_code=303)
    try:
        cleaned = set_faq_text(faq_text)
        rebuild_index(cleaned)
    except Exception as exc:
        logger.exception("Failed saving FAQ from admin UI")
        return templates.TemplateResponse(
            request,
            "admin_faq.html",
            {
                "faq_text": faq_text,
                "saved": False,
                "error": f"Could not save FAQ: {exc}",
                "storage": faq_storage_label(),
            },
            status_code=400,
        )
    return RedirectResponse(url="/admin/faq?saved=1", status_code=303)


@app.get("/admin/guided", response_class=HTMLResponse)
async def admin_guided_page(request: Request, saved: int = 0) -> Response:
    if not _is_logged_in(request):
        return RedirectResponse(url="/admin", status_code=303)
    topics = list_topics(enabled_only=False)
    topic_jsons = {
        t["id"]: json_dumps_topic(t)
        for t in topics
    }
    return templates.TemplateResponse(
        request,
        "admin_guided.html",
        {
            **_branding_context(),
            "topics": topics,
            "topic_jsons": topic_jsons,
            "metrics": get_guided_metrics(),
            "storage": guided_storage_label(),
            "guided_enabled": GUIDED_ENABLED,
            "saved": bool(saved),
            "error": None,
            "selected_id": topics[0]["id"] if topics else "",
            "preview_lines": None,
            "preview_path": "",
        },
    )


def json_dumps_topic(topic: dict[str, Any]) -> str:
    return json.dumps(topic, indent=2)


@app.post("/admin/guided/save", response_class=HTMLResponse)
async def admin_guided_save(
    request: Request,
    topic_id: str = Form(...),
    topic_json: str = Form(...),
) -> Response:
    if not _is_logged_in(request):
        return RedirectResponse(url="/admin", status_code=303)
    try:
        raw = json.loads(topic_json)
        if isinstance(raw, dict) and not raw.get("id"):
            raw["id"] = topic_id
        saved_topic = set_topic(raw)
        if saved_topic["id"] != topic_id and get_topic(topic_id):
            # Allow renaming via JSON id; keep explicit.
            pass
    except Exception as exc:
        logger.exception("Failed saving guided topic")
        topics = list_topics(enabled_only=False)
        return templates.TemplateResponse(
            request,
            "admin_guided.html",
            {
                **_branding_context(),
                "topics": topics,
                "topic_jsons": {t["id"]: json_dumps_topic(t) for t in topics},
                "metrics": get_guided_metrics(),
                "storage": guided_storage_label(),
                "guided_enabled": GUIDED_ENABLED,
                "saved": False,
                "error": f"Could not save topic: {exc}",
                "selected_id": topic_id,
                "preview_lines": None,
                "preview_path": "",
            },
            status_code=400,
        )
    return RedirectResponse(url="/admin/guided?saved=1", status_code=303)


@app.post("/admin/guided/toggle")
async def admin_guided_toggle(
    request: Request,
    topic_id: str = Form(...),
    enabled: str = Form("off"),
) -> Response:
    if not _is_logged_in(request):
        return RedirectResponse(url="/admin", status_code=303)
    set_topic_enabled(topic_id, enabled in {"1", "true", "on", "yes"})
    return RedirectResponse(url="/admin/guided?saved=1", status_code=303)


@app.get("/admin/guided/preview", response_class=HTMLResponse)
async def admin_guided_preview(
    request: Request,
    topic_id: str = "",
    path: str = "",
) -> Response:
    if not _is_logged_in(request):
        return RedirectResponse(url="/admin", status_code=303)
    choices_path = [p.strip() for p in (path or "").split("|") if p.strip()]
    lines = preview_topic(topic_id, choices_path or None)
    topics = list_topics(enabled_only=False)
    return templates.TemplateResponse(
        request,
        "admin_guided.html",
        {
            **_branding_context(),
            "topics": topics,
            "topic_jsons": {t["id"]: json_dumps_topic(t) for t in topics},
            "metrics": get_guided_metrics(),
            "storage": guided_storage_label(),
            "guided_enabled": GUIDED_ENABLED,
            "saved": False,
            "error": None,
            "selected_id": topic_id or (topics[0]["id"] if topics else ""),
            "preview_lines": lines,
            "preview_path": path,
        },
    )


@app.get("/webhook")
async def verify_webhook(
    request: Request,
) -> Response:
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN and challenge:
        logger.info("Webhook verified")
        return PlainTextResponse(content=challenge, status_code=200)

    logger.warning("Webhook verification failed")
    return PlainTextResponse(content="Verification failed", status_code=403)


@app.post("/webhook")
async def receive_webhook(payload: dict[str, Any]) -> dict[str, str]:
    """Receive inbound WhatsApp messages and reply with FAQ or guided help."""
    try:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", []) or []
                for message in messages:
                    mtype = message.get("type")
                    if mtype not in {"text", "interactive"}:
                        continue
                    from_phone = message.get("from")
                    if not from_phone:
                        continue
                    message_id = (message.get("id") or "").strip()
                    if message_id and already_seen_message(message_id):
                        logger.info("Skipping duplicate WhatsApp message_id=%s", message_id)
                        continue

                    question = _extract_inbound_text(message)
                    if not question:
                        continue
                    started = time.perf_counter()

                    # Active guided session continues before help/FAQ routing.
                    if GUIDED_ENABLED and get_guided_session(from_phone):
                        result = advance_guided(from_phone, question)
                        await _send_guided_result(from_phone, result)
                        e2e_ms = (time.perf_counter() - started) * 1000
                        record_question(from_phone, e2e_ms=e2e_ms)
                        logger.info("e2e_ms=%.1f kind=guided_continue", e2e_ms)
                        continue

                    # Help / menu
                    if is_help_command(question):
                        await send_text_message(from_phone, HELP_TEXT)
                        e2e_ms = (time.perf_counter() - started) * 1000
                        record_question(from_phone, e2e_ms=e2e_ms)
                        logger.info("e2e_ms=%.1f kind=help", e2e_ms)
                        continue

                    # Prefill / greeting openers → PTSA intro (not FAQ search)
                    if mtype == "text" and is_opener_message(question):
                        await send_text_message(from_phone, get_greeting())
                        e2e_ms = (time.perf_counter() - started) * 1000
                        record_question(from_phone, e2e_ms=e2e_ms)
                        logger.info("e2e_ms=%.1f kind=greeting", e2e_ms)
                        continue

                    # Admin FAQ append
                    if is_faq_command(question):
                        if not is_faq_admin(from_phone):
                            await send_text_message(
                                from_phone,
                                "Only event admins can use /faq.",
                            )
                        else:
                            parsed = parse_faq_command(question)
                            if not parsed:
                                await send_text_message(from_phone, FAQ_USAGE_TEXT)
                            else:
                                q_text, a_text = parsed
                                confirmation = append_faq_entry(q_text, a_text)
                                await send_text_message(from_phone, confirmation)
                        e2e_ms = (time.perf_counter() - started) * 1000
                        record_question(from_phone, e2e_ms=e2e_ms)
                        logger.info("e2e_ms=%.1f kind=faq_admin", e2e_ms)
                        continue

                    # Guided conversations (feature-flagged)
                    if GUIDED_ENABLED:
                        decision = route_message(from_phone, question)
                        kind = decision.get("kind")
                        if kind == "start_guided":
                            result = begin_guided(from_phone, decision["topic_id"])
                            await _send_guided_result(from_phone, result)
                            e2e_ms = (time.perf_counter() - started) * 1000
                            record_question(from_phone, e2e_ms=e2e_ms)
                            logger.info(
                                "e2e_ms=%.1f kind=guided_start topic=%s",
                                e2e_ms,
                                decision["topic_id"],
                            )
                            continue
                        if kind == "human":
                            await send_text_message(
                                from_phone,
                                decision.get("reply")
                                or "Please contact the school office for help with that.",
                            )
                            e2e_ms = (time.perf_counter() - started) * 1000
                            record_question(from_phone, e2e_ms=e2e_ms)
                            logger.info("e2e_ms=%.1f kind=human", e2e_ms)
                            continue

                    # Normal parent FAQ question (Mode A)
                    logger.info(
                        "Answering FAQ for %s (question_len=%s)",
                        from_phone,
                        len(question),
                    )
                    answer = format_parent_answer(answer_faq_question(question))
                    await send_text_message(from_phone, answer)
                    e2e_ms = (time.perf_counter() - started) * 1000
                    record_question(from_phone, e2e_ms=e2e_ms)
                    logger.info("e2e_ms=%.1f kind=faq_answer", e2e_ms)
    except Exception:
        # Always acknowledge quickly so Meta does not disable the webhook.
        logger.exception("Error while handling webhook")
    return {"status": "ok"}
