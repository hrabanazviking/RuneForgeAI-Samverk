"""Output-escaping and sanitisation standard (S-010).

**One seam.** Every byte of user-controlled text that reaches a page
goes through this module — and only this module. Templates and
handlers never call `html.escape` (or a library equivalent) directly;
the mechanical battery in tests/test_escaping.py enforces that, in
the same way S-002's battery keeps platform reads behind the
platform seam. One seam means one place to audit, one place to fix,
and no route that "forgot" to escape.

Three contexts, three functions — escaping is context-shaped, and a
single generic escaper used in the wrong context is a stored-XSS
hole with good intentions:

- `escape_html_text` — element content: `&`, `<`, `>` become
  entities, so stored markup renders as visible text, never as tags.
- `escape_html_attr` — double-quoted attribute values: additionally
  escapes both quote characters, so a value cannot break out of its
  attribute and smuggle in an event handler.
- `safe_url` — `href`/`src` values: a *sanitiser*, not an escaper.
  Only `http`, `https`, and `mailto` absolute URLs survive, plus
  instance-relative references (`/…`, `./…`, `../…`, `#…`, `?…`, and
  plain relative paths). Everything else — `javascript:`, `data:`,
  `vbscript:`, control-character- or whitespace-obfuscated schemes,
  and protocol-relative `//host/…` references that would silently
  leave the instance — is refused and returns None, so the caller
  renders no link at all. (Callers embedding a surviving URL in an
  attribute still pass it through `escape_html_attr`; with `&`
  escaped, entity-smuggled schemes like `&#106;avascript:` decode
  to inert text, never to a scheme.)

There is deliberately **no** JavaScript-string escaper here: values
are never interpolated into inline scripts (S-016's CSP will forbid
them outright). A seam that does not exist cannot be misused.
"""

from __future__ import annotations

import html
import re

_ALLOWED_SCHEMES = frozenset({"http", "https", "mailto"})
_SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*):")


def _raw_url_is_safe(url: str) -> bool:
    # Any control character makes the value untrustworthy as a URL:
    # browsers ignore embedded controls when resolving a scheme, so
    # `java\tscript:` and friends must die here, not downstream.
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in url):
        return False
    if url.startswith("//"):
        # Protocol-relative: silently leaves the instance under
        # whatever scheme the page used. Refused.
        return False
    match = _SCHEME_RE.match(url)
    if match is not None:
        return match.group(1).lower() in _ALLOWED_SCHEMES
    # No scheme: a relative reference, but only if the part before
    # any ':'-free path really contains no colon at all — a colon
    # later in the string with no valid scheme in front of it means
    # the scheme was obfuscated. The head before the first /, ?, or #
    # is what a browser would try to read as a scheme.
    head = re.split(r"[/?#]", url, maxsplit=1)[0]
    return ":" not in head


def _as_text(value: object) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def escape_html_text(value: object) -> str:
    """Escape *value* for HTML element content."""
    text = _as_text(value)
    # & first, always: escaping it later would double-escape the
    # entities the other replacements just produced.
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def escape_html_attr(value: object) -> str:
    """Escape *value* for a (single- or double-) quoted HTML
    attribute value."""
    return (
        escape_html_text(value)
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def safe_url(value: object) -> str | None:
    """Return *value* if it is a URL Samverk may link to, else None.

    The check runs on the raw string with surrounding whitespace
    stripped first — browsers ignore that when resolving a scheme,
    so the sanitiser must too. It then runs again on the
    HTML-entity-decoded form: a value like ``&#106;avascript:…``
    hides its scheme behind an entity, and any value whose decoded
    form would be refused is refused in its raw form too (defence in
    depth for a caller that forgets the attribute escape; in the
    full pipeline the escape alone already renders it inert).
    """
    if value is None:
        return None
    url = str(value).strip()
    if not url:
        return None
    if not _raw_url_is_safe(url):
        return None
    decoded = html.unescape(url)
    if decoded != url and not _raw_url_is_safe(decoded.strip()):
        return None
    return url
