import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeSerializer
from starlette.middleware.sessions import SessionMiddleware

from app.config import (
    ADMIN_PASSWORD,
    SECRET_KEY,
    TEMPLATES_DIR,
    WHATSAPP_VERIFY_TOKEN,
    credential_status,
)
from app.faq_service import answer_faq_question
from app.greeting_store import get_greeting, set_greeting
from app.whatsapp import send_text_message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="WhatsApp Hello Bot", docs_url="/docs")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, session_cookie="hello_bot_session")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
signer = URLSafeSerializer(SECRET_KEY, salt="admin-auth")


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
    if not status["faq_file_exists"]:
        logger.warning("FAQ file is missing: data/science_olympiad_faq.txt")


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
        "Webhook: /webhook\n"
        "Health: /health\n"
        "FAQ: data/science_olympiad_faq.txt\n"
    )


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_policy() -> HTMLResponse:
    path = Path(__file__).resolve().parent.parent / "privacy-policy.html"
    return HTMLResponse(path.read_text(encoding="utf-8"))


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request, saved: int = 0) -> Response:
    logged_in = _is_logged_in(request)
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "logged_in": logged_in,
            "message": get_greeting() if logged_in else "",
            "saved": bool(saved) and logged_in,
            "error": None,
        },
    )


@app.post("/admin/login", response_class=HTMLResponse)
async def admin_login(request: Request, password: str = Form(...)) -> Response:
    if password != ADMIN_PASSWORD:
        return templates.TemplateResponse(
            request,
            "admin.html",
            {
                "logged_in": False,
                "message": "",
                "saved": False,
                "error": "Wrong password.",
            },
            status_code=401,
        )
    _login(request)
    return RedirectResponse(url="/admin", status_code=303)


@app.get("/admin/logout")
async def admin_logout(request: Request) -> Response:
    _logout(request)
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/message")
async def admin_save_message(request: Request, message: str = Form(...)) -> Response:
    if not _is_logged_in(request):
        return RedirectResponse(url="/admin", status_code=303)
    set_greeting(message)
    return RedirectResponse(url="/admin?saved=1", status_code=303)


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
    """Receive inbound WhatsApp messages and reply with an FAQ-grounded answer."""
    try:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", []) or []
                for message in messages:
                    if message.get("type") != "text":
                        continue
                    from_phone = message.get("from")
                    if not from_phone:
                        continue
                    question = (message.get("text") or {}).get("body") or ""
                    logger.info(
                        "Answering FAQ for %s (question_len=%s)",
                        from_phone,
                        len(question),
                    )
                    answer = answer_faq_question(question)
                    await send_text_message(from_phone, answer)
    except Exception:
        # Always acknowledge quickly so Meta does not disable the webhook.
        logger.exception("Error while handling webhook")
    return {"status": "ok"}
