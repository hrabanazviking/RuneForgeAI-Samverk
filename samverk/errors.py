"""Error law (S-019).

What a client may learn from a failed request is a *code* and an
*opaque id* — never a stack trace, a filesystem path, an
exception message, or a secret. The id is the whole bridge
between the two worlds:

- The client sees ``{"error": <code>, "error_id": <id>}``.
- The server log carries the full detail (traceback included),
  redacted by S-018, **under the same id** — so an operator
  holding a user's error id can find the exact failure, and a
  user holding it learns nothing they did not already know.

Error codes are a frozen registry, like the audit taxonomy
(S-008): handlers raise `PublicError` with a registered code, or
return one through the server's error path; an unregistered code
is a programming error and raises here, never reaches a client.

One subtlety this module owns: Python's logging appends
tracebacks *after* filters run, so `logger.exception(...)` would
carry the exception's text past S-018's redacting filter.
`log_internal_error` therefore renders the traceback itself,
redacts the whole text, and logs it as a plain message — the
filter still applies, and the traceback is already clean before
it. Internal errors are logged through this function, never
through a bare `logger.exception` at a call site.
"""

from __future__ import annotations

import logging
import secrets
import traceback

from .log_redaction import redact_text

ERROR_CODES = frozenset({
    "bad_request",
    "csrf_failed",
    "internal",
    "method_not_allowed",
    "not_found",
    "rate_limited",
    "unauthorized",
})

_log = logging.getLogger("samverk.error")


class PublicError(Exception):
    """An error a handler *means* for the client: a registered
    code and an HTTP status. Everything it carries is safe to
    send; anything sensitive belongs in the server log instead,
    via `log_internal_error` under the same error id."""

    def __init__(self, code: str, status: int):
        if code not in ERROR_CODES:
            raise ValueError(f"unregistered error code {code!r} (S-019)")
        super().__init__(code)
        self.code = code
        self.status = status


def new_error_id() -> str:
    """A fresh opaque error id: 64 bits of CSPRNG, hex. It
    encodes nothing — no timestamp, no sequence, no location."""
    return secrets.token_hex(8)


def public_error_body(code: str, error_id: str | None = None) -> dict:
    """The exact body a client receives for *code*: two keys,
    nothing else."""
    if code not in ERROR_CODES:
        raise ValueError(f"unregistered error code {code!r} (S-019)")
    return {"error": code, "error_id": error_id or new_error_id()}


def log_internal_error(error_id: str, exc: BaseException) -> None:
    """Write *exc*'s full detail to the server log under
    *error_id*, redacted (S-018) before it is written."""
    rendered = "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__))
    _log.error("error_id=%s\n%s", error_id, redact_text(rendered))
