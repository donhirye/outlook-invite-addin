import json
import logging
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, Request, Response, UploadFile
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeSerializer
from starlette.middleware.sessions import SessionMiddleware

from app.calendar_store import (
    ensure_calendar_seeded,
    get_calendar_meta,
    import_calendar_csv_text,
    list_events,
)
from app.config import (
    ADMIN_PASSWORD,
    BASE_DIR,
    IS_STAGING,
    SECRET_KEY,
    TEMPLATES_DIR,
    WHATSAPP_VERIFY_TOKEN,
    credential_status,
    staging_config_problems,
)
from app.engine_config import get_selected_engine_id, set_selected_engine_id
from app.engines.pipeline import process_message
from app.engines.registry import list_engines
from app.event_link_store import event_link_view, set_event_link_settings
from app.faq_records import (
    ensure_faq_records_seeded,
    get_conflicts,
    import_faq_csv_text,
    list_records,
)
from app.faq_rag import rebuild_index
from app.faq_store import clear_faq_cache, faq_storage_label, get_faq_text, set_faq_text
from app.guided_state import already_seen_message
from app.metrics import get_metrics, record_question
from app.observability.product_metrics import (
    compute_engine_analytics,
    compute_product_analytics,
)
from app.observability.tracing import get_trace, load_traces
from app.whatsapp import mark_as_read_with_typing, send_choices, send_text_message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="WhatsApp Hello Bot",
    # Staging exposes no unauthenticated API docs.
    docs_url=None if IS_STAGING else "/docs",
    redoc_url=None if IS_STAGING else "/redoc",
    openapi_url=None if IS_STAGING else "/openapi.json",
)
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
    problems = staging_config_problems()
    if problems:
        # Fail closed: a misconfigured staging service must not start.
        raise RuntimeError("Unsafe staging configuration: " + "; ".join(problems))
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
    try:
        faq_seed = ensure_faq_records_seeded()
        cal_seed = ensure_calendar_seeded()
        logger.info("FAQ records seed: %s", faq_seed)
        logger.info("Calendar seed: %s", cal_seed)
    except Exception:
        logger.exception("Failed seeding FAQ records / school calendar")
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


@app.get("/metrics", response_model=None)
async def metrics(request: Request) -> Response | dict[str, object]:
    """Simple usage counters for local/prod inspection."""
    if IS_STAGING and not _is_logged_in(request):
        return JSONResponse({"error": "login required"}, status_code=401)
    data = get_metrics()
    data["guided_enabled"] = False
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


async def _send_answer_result(phone: str, messages: list[str], choices: Any) -> None:
    if not messages:
        return
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


@app.api_route("/admin/intro", methods=["GET", "POST"], response_class=PlainTextResponse)
@app.api_route("/admin/message", methods=["GET", "POST"], response_class=PlainTextResponse)
async def admin_intro_removed() -> PlainTextResponse:
    return PlainTextResponse("Intro / greeting messages have been removed.", status_code=404)


@app.get("/admin/faq", response_class=HTMLResponse)
async def admin_faq_page(request: Request, saved: int = 0) -> Response:
    if not _is_logged_in(request):
        return RedirectResponse(url="/admin", status_code=303)
    error = None
    records: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    try:
        ensure_faq_records_seeded()
        records = list_records(include_inactive=True)
        conflicts = get_conflicts()
    except Exception as exc:
        logger.exception("Failed loading FAQ records for admin UI")
        error = str(exc)
    return templates.TemplateResponse(
        request,
        "admin_faq.html",
        {
            **_branding_context(),
            "records": records,
            "record_count": len([r for r in records if str(r.get("status", "")).lower() == "active"]),
            "conflicts": conflicts,
            "saved": bool(saved),
            "error": error,
        },
    )


@app.post("/admin/faq/import", response_class=HTMLResponse)
async def admin_faq_import(
    request: Request,
    csv_file: UploadFile = File(...),
) -> Response:
    if not _is_logged_in(request):
        return RedirectResponse(url="/admin", status_code=303)
    try:
        raw = await csv_file.read()
        text = raw.decode("utf-8-sig")
        result = import_faq_csv_text(text)
        logger.info("Admin FAQ CSV import: %s", result)
    except Exception as exc:
        logger.exception("Failed importing FAQ CSV")
        records = list_records(include_inactive=True)
        return templates.TemplateResponse(
            request,
            "admin_faq.html",
            {
                **_branding_context(),
                "records": records,
                "record_count": len(records),
                "conflicts": get_conflicts(),
                "saved": False,
                "error": f"Could not import FAQ CSV: {exc}",
            },
            status_code=400,
        )
    return RedirectResponse(url="/admin/faq?saved=1", status_code=303)


@app.get("/admin/calendar", response_class=HTMLResponse)
async def admin_calendar_page(request: Request, saved: int = 0) -> Response:
    if not _is_logged_in(request):
        return RedirectResponse(url="/admin", status_code=303)
    error = None
    try:
        ensure_calendar_seeded()
        events = list_events()
        meta = get_calendar_meta()
    except Exception as exc:
        logger.exception("Failed loading school calendar for admin UI")
        error = str(exc)
        events = []
        meta = {}
    return templates.TemplateResponse(
        request,
        "admin_calendar.html",
        {
            **_branding_context(),
            "events": events,
            "meta": meta,
            "saved": bool(saved),
            "error": error,
        },
    )


@app.post("/admin/calendar/import", response_class=HTMLResponse)
async def admin_calendar_import(
    request: Request,
    csv_file: UploadFile = File(...),
) -> Response:
    if not _is_logged_in(request):
        return RedirectResponse(url="/admin", status_code=303)
    try:
        raw = await csv_file.read()
        text = raw.decode("utf-8-sig")
        result = import_calendar_csv_text(text)
        logger.info("Admin calendar CSV import: %s", result)
    except Exception as exc:
        logger.exception("Failed importing calendar CSV")
        return templates.TemplateResponse(
            request,
            "admin_calendar.html",
            {
                **_branding_context(),
                "events": list_events(),
                "meta": get_calendar_meta(),
                "saved": False,
                "error": f"Could not import calendar CSV: {exc}",
            },
            status_code=400,
        )
    return RedirectResponse(url="/admin/calendar?saved=1", status_code=303)


@app.api_route("/admin/guided", methods=["GET", "POST"], response_class=PlainTextResponse)
@app.api_route("/admin/guided/{rest:path}", methods=["GET", "POST"], response_class=PlainTextResponse)
async def admin_guided_removed(rest: str = "") -> Response:
    """Guided multi-step flows were removed; FAQ + calendar remain."""
    return PlainTextResponse("Guided conversations have been removed.", status_code=404)


@app.get("/admin/analytics", response_class=HTMLResponse)
async def admin_analytics_page(
    request: Request,
    tab: str = "product",
    days: int = 30,
    engine: str = "all",
) -> Response:
    if not _is_logged_in(request):
        return RedirectResponse(url="/admin", status_code=303)
    days = max(1, min(days, 365))
    product = compute_product_analytics(
        since_days=days,
        engine_id=None if engine == "all" else engine,
    )
    engine_stats = compute_engine_analytics(since_days=days)
    traces = load_traces(limit=50)
    eval_summary = _load_eval_summary()
    return templates.TemplateResponse(
        request,
        "admin_analytics.html",
        {
            **_branding_context(),
            "tab": tab if tab in {"product", "engine", "evaluations"} else "product",
            "days": days,
            "engine_filter": engine,
            "product": product,
            "engine_stats": engine_stats,
            "engines": list_engines(),
            "selected_engine": get_selected_engine_id(),
            "traces": traces,
            "eval_summary": eval_summary,
            "saved": False,
            "error": None,
        },
    )


@app.post("/admin/analytics/engine")
async def admin_analytics_set_engine(
    request: Request,
    engine_id: str = Form(...),
) -> Response:
    if not _is_logged_in(request):
        return RedirectResponse(url="/admin", status_code=303)
    try:
        set_selected_engine_id(engine_id)
    except ValueError as exc:
        return RedirectResponse(
            url=f"/admin/analytics?tab=engine&error={exc}",
            status_code=303,
        )
    return RedirectResponse(url="/admin/analytics?tab=engine", status_code=303)


@app.get("/admin/analytics/trace/{trace_id}", response_class=HTMLResponse)
async def admin_analytics_trace(request: Request, trace_id: str) -> Response:
    if not _is_logged_in(request):
        return RedirectResponse(url="/admin", status_code=303)
    trace = get_trace(trace_id)
    return templates.TemplateResponse(
        request,
        "admin_analytics_trace.html",
        {
            **_branding_context(),
            "trace": trace,
            "trace_id": trace_id,
        },
    )


def _load_eval_summary() -> dict[str, Any]:
    path = BASE_DIR / "evals" / "reports" / "latest_summary.json"
    if not path.exists():
        return {"empty": True}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"empty": True, "error": "Could not read evaluation summary"}


@app.get("/webhook")
async def verify_webhook(
    request: Request,
) -> Response:
    if IS_STAGING:
        return PlainTextResponse(content="Webhook disabled in staging", status_code=404)
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN and challenge:
        logger.info("Webhook verified")
        return PlainTextResponse(content=challenge, status_code=200)

    logger.warning("Webhook verification failed")
    return PlainTextResponse(content="Verification failed", status_code=403)


@app.post("/webhook", response_model=None)
async def receive_webhook(payload: dict[str, Any]) -> Response | dict[str, str]:
    """Receive inbound WhatsApp messages via shared answering-engine pipeline."""
    if IS_STAGING:
        # Staging never processes WhatsApp traffic.
        return JSONResponse({"status": "disabled in staging"}, status_code=404)
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
                    # Show typing while we answer (LLM FAQ can take several seconds).
                    if message_id:
                        try:
                            await mark_as_read_with_typing(message_id)
                        except Exception:
                            logger.exception(
                                "Typing indicator failed for message_id=%s",
                                message_id,
                            )
                    started = time.perf_counter()
                    result = process_message(
                        phone=from_phone,
                        text=question,
                        message_id=message_id,
                        message_type=mtype,
                    )
                    await _send_answer_result(
                        from_phone, list(result.messages or []), result.choices
                    )
                    e2e_ms = (time.perf_counter() - started) * 1000
                    record_question(from_phone, e2e_ms=e2e_ms)
                    logger.info(
                        "e2e_ms=%.1f kind=%s engine=%s",
                        e2e_ms,
                        result.route,
                        result.engine_id,
                    )
    except Exception:
        # Always acknowledge quickly so Meta does not disable the webhook.
        logger.exception("Error while handling webhook")
    return {"status": "ok"}


if IS_STAGING:
    # Staging-only: STAGING banner on every HTML page + browser Test Chat. In
    # production none of this is registered, so /admin/test-chat returns 404.
    from app.staging import StagingHtmlMiddleware
    from app.test_chat import register_test_chat

    app.add_middleware(StagingHtmlMiddleware)
    register_test_chat(
        app,
        is_logged_in=_is_logged_in,
        templates=templates,
        branding=_branding_context,
    )
