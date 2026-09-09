"""encode_session_cookie/decode_session_cookie: round-trips a valid cookie,
rejects a tampered or malformed one, and rejects a cookie signed with a
different secret (simulating a rotated APP_SECRET_KEY)."""

from __future__ import annotations

from app.core.session import decode_session_cookie, encode_session_cookie, new_session_id


def test_new_session_id_is_unique() -> None:
    assert new_session_id() != new_session_id()


def test_round_trips_a_valid_cookie() -> None:
    session_id = new_session_id()
    cookie = encode_session_cookie(session_id, "secret-key")
    assert decode_session_cookie(cookie, "secret-key") == session_id


def test_rejects_tampered_session_id() -> None:
    session_id = new_session_id()
    cookie = encode_session_cookie(session_id, "secret-key")
    tampered = cookie.replace(session_id, "someone-elses-id" + session_id[-4:], 1)
    assert decode_session_cookie(tampered, "secret-key") is None


def test_rejects_cookie_signed_with_different_secret() -> None:
    cookie = encode_session_cookie(new_session_id(), "secret-key")
    assert decode_session_cookie(cookie, "different-secret") is None


def test_rejects_malformed_cookie() -> None:
    assert decode_session_cookie("not-a-valid-cookie-value", "secret-key") is None
    assert decode_session_cookie("", "secret-key") is None
