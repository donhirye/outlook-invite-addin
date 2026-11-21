"""Google OAuth for Gmail (readonly) + Drive (file). Never logs secrets."""

from __future__ import annotations

import logging
from pathlib import Path

from newsletter_archive.config import (
    GOOGLE_OAUTH_CLIENT_SECRETS,
    GOOGLE_OAUTH_TOKEN_PATH,
    OAUTH_SCOPES,
    ensure_local_dirs,
)

logger = logging.getLogger(__name__)


class GoogleAuthError(RuntimeError):
    pass


def _require_google_libs() -> tuple:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise GoogleAuthError(
            "Google API libraries are not installed. From whatsapp-hello-bot/ run:\n"
            "  pip install -r requirements-newsletter.txt"
        ) from exc
    return Request, Credentials, InstalledAppFlow


def get_credentials(
    *,
    client_secrets: str | Path | None = None,
    token_path: str | Path | None = None,
    scopes: tuple[str, ...] = OAUTH_SCOPES,
):
    """Load or refresh OAuth credentials. Opens a browser on first run."""
    Request, Credentials, InstalledAppFlow = _require_google_libs()
    ensure_local_dirs()

    secrets = Path(client_secrets or GOOGLE_OAUTH_CLIENT_SECRETS)
    token = Path(token_path or GOOGLE_OAUTH_TOKEN_PATH)

    if not secrets.exists():
        raise GoogleAuthError(
            "OAuth client secrets file not found.\n"
            f"  Expected: {secrets}\n"
            "Create a Google Cloud Desktop OAuth client, download the JSON, and either:\n"
            f"  - save it to that path, or\n"
            "  - set GOOGLE_OAUTH_CLIENT_SECRETS to the file path.\n"
            "Do not paste client secrets or tokens into chat.\n"
            "See docs/newsletter-archive.md for setup steps."
        )

    creds = None
    if token.exists():
        creds = Credentials.from_authorized_user_file(str(token), list(scopes))

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        logger.info("Refreshing Google OAuth token (token file=%s)", token.name)
        creds.refresh(Request())
    else:
        logger.info(
            "Starting Google OAuth installed-app flow (scopes=%s)",
            ",".join(scopes),
        )
        flow = InstalledAppFlow.from_client_secrets_file(str(secrets), list(scopes))
        creds = flow.run_local_server(port=0)

    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text(creds.to_json(), encoding="utf-8")
    logger.info("Saved OAuth token to %s (gitignored)", token)
    return creds
