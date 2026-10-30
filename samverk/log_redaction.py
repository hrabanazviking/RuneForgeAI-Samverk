"""Log redaction (S-018).

Logs are where secrets go to be forgotten about — a session
token in a debug line, a password in a failed-login trace, a
cookie header in a request dump — and then the log file is
backed up, shipped, and grepped by people who never needed the
secret. This module is the filter that stands in front of every
log write: **a logger that may carry Samverk data carries this
filter**, installed by `install_redaction` (the server installs
it on the root logger at startup).

Three layers, applied in order by `redact_text`:

1. **Registered secrets.** Code that learns a secret value can
   `register_secret` it; the literal value is then struck from
   every redacted text wherever it appears, in any context.
   (Registration is defence in depth, not the primary defence:
   the law remains *do not log secrets at all* — this filter
   exists for the day someone does anyway.)
2. **Auth-scheme and header shapes.** `Bearer …`, `Basic …`,
   `Authorization: …`, and `Cookie:`/`Set-Cookie:` header values
   are struck whole — their values are credentials by shape,
   whatever the specific bytes.
3. **Sensitive keys.** `key=value`, `key: value`, and JSON
   `"key": "value"` pairs whose key names a credential
   (password, token, secret, session, csrf, api-key, …) keep
   their key — an operator can still see *that* a token was
   presented — and lose their value.

Deliberately **not** redacted: bare hex/base64-looking strings.
A git SHA is 40 hex characters and belongs in logs; a heuristic
that struck every long token-shaped string would blind exactly
the debugging logs exist for. Credential-shaped *contexts* are
the signal, not character classes.

The replacement marker is `[REDACTED]` — visible, countable,
and grep-able, so a redaction in a log is itself evidence the
filter was needed.
"""

from __future__ import annotations

import logging
import re

REDACTED = "[REDACTED]"
_MIN_SECRET_LENGTH = 4

_registered: set[str] = set()

_SENSITIVE_KEY = (
    r"password|passwd|pwd|token|secret|session|csrf|api[-_]?key|"
    r"auth|credential|cookie|private[-_]?key|access[-_]?key"
)
# A key is sensitive when a sensitive word is a whole segment of
# it, segments split on _ or - : `csrf_token`, `x-api-key`, and
# `auth_token` are sensitive; `author` is not (its only segment
# merely *contains* "auth").
_COMPOUND_KEY = (
    rf"(?:[A-Za-z0-9]+[_-])*(?:{_SENSITIVE_KEY})"
    rf"(?:[_-][A-Za-z0-9]+)*"
)
_JSON_PAIR_RE = re.compile(
    rf'(?i)("{_COMPOUND_KEY}"\s*:\s*")[^"]*(")')
_QUOTED_PAIR_RE = re.compile(
    rf"(?i)(?<![A-Za-z0-9_-])({_COMPOUND_KEY}\s*[:=]\s*)"
    rf"(\"[^\"]*\"|'[^']*')")
_PLAIN_PAIR_RE = re.compile(
    rf"(?i)(?<![A-Za-z0-9_-])({_COMPOUND_KEY}\s*[:=]\s*)"
    rf"[^\s&,;\"']+")
_AUTHORIZATION_RE = re.compile(r"(?i)(authorization\s*:\s*)\S+(?:\s+\S+)?")
_COOKIE_HEADER_RE = re.compile(r"(?i)((?:set-)?cookie\s*:\s*)[^\r\n]+")
_SCHEME_RE = re.compile(r"(?i)\b(bearer|basic)\s+\S+")


def register_secret(value: object) -> bool:
    """Register a literal secret value for striking. Returns
    False (and registers nothing) for values too short to strike
    safely — redacting a 2-character string would mangle prose."""
    if not isinstance(value, str) or len(value) < _MIN_SECRET_LENGTH:
        return False
    _registered.add(value)
    return True


def clear_registered_secrets() -> None:
    _registered.clear()


def redact_text(text: str, extra_secrets: tuple[str, ...] = ()) -> str:
    """Return *text* with credentials struck, per the layers in
    the module docstring."""
    out = _AUTHORIZATION_RE.sub(rf"\1{REDACTED}", text)
    out = _COOKIE_HEADER_RE.sub(rf"\1{REDACTED}", out)
    out = _SCHEME_RE.sub(rf"\1 {REDACTED}", out)
    out = _JSON_PAIR_RE.sub(rf"\1{REDACTED}\2", out)
    out = _QUOTED_PAIR_RE.sub(rf"\1{REDACTED}", out)
    out = _PLAIN_PAIR_RE.sub(rf"\1{REDACTED}", out)
    # Longest first: a registered secret that contains another
    # must be struck whole, not in pieces.
    for secret in sorted(_registered | set(extra_secrets),
                         key=len, reverse=True):
        if len(secret) >= _MIN_SECRET_LENGTH:
            out = out.replace(secret, REDACTED)
    return out


class RedactingFilter(logging.Filter):
    """A logging filter that redacts the fully-rendered record
    message (format args already applied) before any handler
    writes it."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
        except Exception:
            return True  # a broken record must not crash logging
        redacted = redact_text(rendered)
        if redacted != rendered:
            record.msg = redacted
            record.args = ()
        return True


def install_redaction(logger: logging.Logger | None = None) -> RedactingFilter:
    """Attach a RedactingFilter to *logger* (the root logger by
    default), once. Returns the filter in place."""
    target = logger if logger is not None else logging.getLogger()
    for existing in target.filters:
        if isinstance(existing, RedactingFilter):
            return existing
    redacting = RedactingFilter()
    target.addFilter(redacting)
    return redacting
