"""HTTP security baseline (S-009) — study 07 §4.4 as code.

Two defences, one module, so every later web slice builds on the
same baseline instead of reinventing it:

1. **Session cookies.** `HttpOnly` always (a script can never read
   the session token, so an XSS slip does not hand over the account);
   `Secure` whenever the operator says the instance is served over
   HTTPS (S-015 makes HTTPS the default and owns flipping the flag);
   `SameSite=Lax` (the browser withholds the cookie on cross-site
   POSTs — the first CSRF brake); `Path=/` scoped to the instance
   root; no `Domain` attribute (the cookie belongs to the exact host
   that set it); the name is a plain ``session`` — it carries no
   framework advertising.

2. **CSRF tokens (threat model T-07).** SameSite is a browser
   behaviour, not a guarantee — older browsers, same-site subdomains,
   and future spec drift must not be the whole defence. State-changing
   requests therefore also carry a synchroniser token: an
   HMAC-SHA256 over a fixed purpose string, keyed by the session
   token itself.

   Why keyed by the session token: the token is 256 bits of CSPRNG
   output (S-006), so the HMAC is unforgeable to anyone who does not
   already hold the session; the CSRF token is *not* the session
   token and reveals nothing about it; nothing extra is stored (the
   server recomputes the expected value per request); and the CSRF
   token rotates automatically whenever the session rotates, which
   study 07 §4.3 requires on every privilege change. Validation goes
   through the S-005 constant-time seam and **fails closed**: a
   missing, empty, malformed, or foreign-session token is refused,
   never waved through.

The server enforces this baseline before routing any state-changing
method (see server.py); forms in later slices embed the token as the
``csrf_token`` field, scripts send the ``X-CSRF-Token`` header.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

from .throttle import constant_time_equal

SESSION_COOKIE_NAME = "session"
CSRF_FORM_FIELD = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"

STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

_CSRF_PURPOSE = b"samverk-csrf-v1"
# Characters a cookie value may never carry: separators and controls
# would let a value break out of its own header.
_FORBIDDEN_IN_COOKIE_VALUE = set(';,="\\ \t\r\n\x0b\x0c')


def is_state_changing(method: str) -> bool:
    return method.upper() in STATE_CHANGING_METHODS


def build_session_cookie(
    token: str, *, secure: bool, max_age_seconds: int | None = None
) -> str:
    """The `Set-Cookie` value for a session token, baseline flags on.

    Raises ValueError on a token that could break the header — a
    caller bug must fail loudly here, never smuggle a second cookie
    or attribute into the response.
    """
    if not token or any(
        c in _FORBIDDEN_IN_COOKIE_VALUE or ord(c) < 0x20 or ord(c) == 0x7F
        for c in token
    ):
        raise ValueError("session token is not safe to place in a cookie")
    parts = [f"{SESSION_COOKIE_NAME}={token}", "Path=/", "HttpOnly",
             "SameSite=Lax"]
    if secure:
        parts.append("Secure")
    if max_age_seconds is not None:
        parts.append(f"Max-Age={int(max_age_seconds)}")
    return "; ".join(parts)


def build_clear_session_cookie(*, secure: bool) -> str:
    """The `Set-Cookie` value that ends a session in the browser:
    same name/path/flags, empty value, already expired."""
    parts = [f"{SESSION_COOKIE_NAME}=", "Path=/", "HttpOnly",
             "SameSite=Lax", "Max-Age=0",
             "Expires=Thu, 01 Jan 1970 00:00:00 GMT"]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def parse_cookie_header(header: str | None) -> dict[str, str]:
    """Parse a `Cookie` request header into a name→value dict.

    Tolerant by design: malformed segments are skipped, never fatal —
    a hostile or broken client header must not crash the handler, it
    simply yields no usable session cookie and requests fail closed
    further up.
    """
    cookies: dict[str, str] = {}
    if not header:
        return cookies
    for segment in header.split(";"):
        name, sep, value = segment.partition("=")
        if not sep:
            continue
        name = name.strip()
        if name:
            cookies[name] = value.strip()
    return cookies


def session_token_from_cookie_header(header: str | None) -> str | None:
    token = parse_cookie_header(header).get(SESSION_COOKIE_NAME)
    return token or None


def issue_csrf_token(session_token: str) -> str:
    """Mint the CSRF token bound to *session_token*."""
    if not session_token:
        raise ValueError("a CSRF token requires a session token")
    digest = hmac.new(
        session_token.encode("utf-8"), _CSRF_PURPOSE, hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii")


def validate_csrf_token(session_token: str | None, submitted: object) -> bool:
    """True only when *submitted* is exactly the CSRF token for this
    session. Every other case — no session, nothing submitted, a
    token minted for a different session, a tampered token — is
    False. Fails closed, compares in constant time."""
    if not session_token or not isinstance(submitted, str) or not submitted:
        return False
    try:
        expected = issue_csrf_token(session_token)
    except (ValueError, TypeError):
        return False
    return constant_time_equal(expected, submitted)
