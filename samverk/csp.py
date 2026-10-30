"""Content Security Policy for the web UI (S-016).

One policy, one module, sent on every response the server makes
(the server's single send path carries it, so a route added later
cannot forget it — the same by-construction shape as S-009's CSRF
gate and S-010's escaping seam).

The policy's stance:

- **Everything defaults to the instance itself** (`default-src
  'self'`, and the fetch directives spelled out individually so
  the intent survives a reader who only skims one line).
- **No inline anything.** `script-src 'self'` with no
  `'unsafe-inline'` and no `'unsafe-eval'` — this is the other
  half of S-010's promise that values are never interpolated
  into inline scripts: the browser is told to refuse them even
  if a template bug someday emits one. Styles are likewise
  external-only.
- **Nothing embeds us, nothing is embedded by us as a plugin:**
  `frame-ancestors 'none'` (clickjacking), `object-src 'none'`.
- **`base-uri 'self'` and `form-action 'self'`** close the two
  quiet redirect doors (a smuggled `<base>` or a form posting
  off-instance).

Modes: the header ships **enforced** by default
(`Content-Security-Policy`). An operator opening a new instance
(or a new page family) may set `csp_mode = report-only`, in
which case the identical policy travels as
`Content-Security-Policy-Report-Only` — the browser reports
violations and blocks nothing — and the roadmap's acceptance
shape is the lifecycle: report-only period clean on all core
pages, then the mode flips to enforced. The policy *value* is
the same in both modes; only the header name changes, so the
report-only period really does rehearse the enforced policy.
"""

from __future__ import annotations

ENFORCE = "enforce"
REPORT_ONLY = "report-only"
MODES = frozenset({ENFORCE, REPORT_ONLY})

_HEADER_NAMES = {
    ENFORCE: "Content-Security-Policy",
    REPORT_ONLY: "Content-Security-Policy-Report-Only",
}

# Ordered: the emitted header is stable byte-for-byte, so tests
# (and operators diffing configs) see one canonical policy.
DIRECTIVES: tuple[tuple[str, str], ...] = (
    ("default-src", "'self'"),
    ("script-src", "'self'"),
    ("style-src", "'self'"),
    ("img-src", "'self'"),
    ("font-src", "'self'"),
    ("connect-src", "'self'"),
    ("media-src", "'self'"),
    ("worker-src", "'self'"),
    ("manifest-src", "'self'"),
    ("object-src", "'none'"),
    ("frame-ancestors", "'none'"),
    ("base-uri", "'self'"),
    ("form-action", "'self'"),
)


def policy_value() -> str:
    """The canonical policy string, identical in both modes."""
    return "; ".join(f"{name} {value}" for name, value in DIRECTIVES)


def csp_header(mode: str = ENFORCE) -> tuple[str, str]:
    """Return (header_name, header_value) for *mode*.

    An unknown mode raises ValueError — a misspelled mode in a
    config file must fail loudly at startup, never silently ship
    no CSP at all.
    """
    try:
        name = _HEADER_NAMES[mode]
    except KeyError:
        raise ValueError(
            f"unknown CSP mode {mode!r}: expected one of "
            f"{sorted(MODES)}") from None
    return name, policy_value()
