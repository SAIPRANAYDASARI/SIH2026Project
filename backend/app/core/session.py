"""Anonymous session identity via a lightweight signed cookie.

`Conversation.session_id` (see `app.models.conversation`) needs a stable
identifier for an anonymous visitor across requests, without requiring
login. Rather than add a dependency (`itsdangerous` is the usual choice)
for what is a single narrow need, this signs the session id with HMAC-SHA256
over `app_secret_key` using the standard library only (`hmac`, `hashlib`,
`secrets`) — enough to stop a client from forging or guessing another
session's id, which is all this cookie is trusted for. It is not a JWT and
carries no claims beyond the id itself; real authentication (Step 6+ auth,
if added) is a separate concern layered on top, not replaced by this.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets


def _signature(session_id: str, secret_key: str) -> str:
    return hmac.new(secret_key.encode(), session_id.encode(), hashlib.sha256).hexdigest()[:32]


def new_session_id() -> str:
    return secrets.token_urlsafe(24)


def encode_session_cookie(session_id: str, secret_key: str) -> str:
    return f"{session_id}.{_signature(session_id, secret_key)}"


def decode_session_cookie(cookie_value: str, secret_key: str) -> str | None:
    """Returns the session id if the cookie's signature is valid, else None
    (missing cookie, tampered value, or wrong secret — e.g. after rotating
    `APP_SECRET_KEY`) — callers should treat None as "issue a new session"."""
    try:
        session_id, signature = cookie_value.rsplit(".", 1)
    except ValueError:
        return None
    if not session_id or not hmac.compare_digest(signature, _signature(session_id, secret_key)):
        return None
    return session_id
