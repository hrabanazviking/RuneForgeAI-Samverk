"""Secret scanning patterns v1 (S-289).

A detector set for the major public token formats,
written from public documentation of their shapes —
the opening slice of Part XV's scanning line, and
the deliberate opposite of S-290's generic work:
every detector here names one provider's published
token shape, and nothing here judges entropy or
context. That judgement is S-290's, measured on its
labelled corpus; this slice is patterns only.

- **Shapes only, never secrets.** Each pattern is
  built from the provider's own public description
  of the format: a fixed prefix where the provider
  publishes one, the published character set, and
  the published length. The battery's examples are
  synthetic strings assembled to those shapes (a
  prefix plus repeated filler characters) — no real
  credential appears in this module, its tests, or
  its documentation, and none is needed: a shape is
  public, a secret is not.
- **The set, v1.** GitHub (classic personal access
  token `ghp_`, OAuth `gho_`, user-to-server `ghu_`,
  server-to-server `ghs_`, refresh `ghr_`, and the
  fine-grained `github_pat_` form), GitLab personal
  access tokens (`glpat-`), AWS access key IDs (the
  `AKIA` / `ASIA` / `ABIA` / `ACCA` families), Google
  API keys (`AIza…`) and OAuth client secrets
  (`GOCSPX-`), Slack tokens (`xox…`) and incoming
  webhook URLs, Stripe secret / restricted / webhook
  keys, SendGrid API keys, Twilio API keys, npm
  tokens, PyPI tokens, DigitalOcean tokens, Square
  tokens, Mailchimp keys, JSON Web Tokens in compact
  form, and PEM private-key block headers. A shape
  with no published fixed form (an AWS secret access
  key is forty unmarked characters) has no v1
  detector — honestly absent, not guessed at; the
  generic road is S-290's.
- **Findings never carry the secret.** A `Finding`
  holds the detector, the span (offset, line,
  column), a redacted preview that keeps only the
  published prefix and the match length, and a
  SHA-256 fingerprint of the matched text — enough
  to deduplicate and to say *where* and *what
  shape*, never enough to use. The matched text
  itself is not stored on the finding, never
  rendered, and never logged by this module. The
  page face follows the same law.
- **Scanning is pure and deterministic.** `scan_text`
  judges one string against the set with no storage
  read and no clock. Overlapping matches resolve
  deterministically: the earliest span wins, the
  longest match wins a shared start, and the
  registry order breaks any remaining tie — one
  span yields at most one finding, so a fine-grained
  GitHub token is reported once, under its own
  detector, never twice. Findings return in span
  order. A caller may narrow the set by detector id;
  an unknown id is refused `detector_unknown`,
  naming it — never silently dropped, because a
  dropped detector narrows the scan invisibly.
- **No storage, no audit event, no migration.**
  Scanning is a judgement over text handed to it;
  persistence, push protection, and alerting are
  later slices' work on top of this set. 133 events
  stand: 33 auth / 87 repo / 13 admin. Schema stands
  at 114.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


class SecretScanningError(Exception):
    """A scanning refusal, named by its `code`."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail or code


@dataclass(frozen=True)
class Detector:
    """One published token shape."""

    id: str
    provider: str
    label: str
    prefix: str
    pattern: re.Pattern
    shape: str


def _detector(id, provider, label, prefix, regex, shape):
    return Detector(
        id=id, provider=provider, label=label, prefix=prefix,
        pattern=re.compile(regex), shape=shape)


DETECTORS = (
    _detector(
        "github_fine_grained_pat", "GitHub",
        "fine-grained personal access token", "github_pat_",
        r"github_pat_[A-Za-z0-9_]{82}",
        "github_pat_ plus 82 alphanumeric/underscore characters"),
    _detector(
        "github_pat_classic", "GitHub",
        "classic personal access token", "ghp_",
        r"ghp_[A-Za-z0-9]{36}",
        "ghp_ plus 36 alphanumeric characters"),
    _detector(
        "github_oauth_token", "GitHub", "OAuth access token", "gho_",
        r"gho_[A-Za-z0-9]{36}",
        "gho_ plus 36 alphanumeric characters"),
    _detector(
        "github_user_to_server", "GitHub",
        "user-to-server token", "ghu_",
        r"ghu_[A-Za-z0-9]{36}",
        "ghu_ plus 36 alphanumeric characters"),
    _detector(
        "github_server_to_server", "GitHub",
        "server-to-server token", "ghs_",
        r"ghs_[A-Za-z0-9]{36}",
        "ghs_ plus 36 alphanumeric characters"),
    _detector(
        "github_refresh_token", "GitHub", "refresh token", "ghr_",
        r"ghr_[A-Za-z0-9]{76}",
        "ghr_ plus 76 alphanumeric characters"),
    _detector(
        "gitlab_pat", "GitLab", "personal access token", "glpat-",
        r"glpat-[A-Za-z0-9_\-]{20}",
        "glpat- plus 20 alphanumeric/dash/underscore characters"),
    _detector(
        "aws_access_key_id", "AWS", "access key ID", "",
        r"(?:AKIA|ASIA|ABIA|ACCA)[A-Z0-9]{16}",
        "AKIA/ASIA/ABIA/ACCA plus 16 uppercase alphanumeric characters"),
    _detector(
        "google_api_key", "Google", "API key", "AIza",
        r"AIza[A-Za-z0-9_\-]{35}",
        "AIza plus 35 alphanumeric/dash/underscore characters"),
    _detector(
        "google_oauth_client_secret", "Google",
        "OAuth client secret", "GOCSPX-",
        r"GOCSPX-[A-Za-z0-9_\-]{28}",
        "GOCSPX- plus 28 alphanumeric/dash/underscore characters"),
    _detector(
        "slack_token", "Slack", "token", "xox",
        r"xox[baprs]-[A-Za-z0-9\-]{10,}",
        "xox plus one letter class, dashes and alphanumeric segments"),
    _detector(
        "slack_webhook", "Slack", "incoming webhook URL",
        "https://hooks.slack.com/services/",
        r"https://hooks\.slack\.com/services/T[A-Za-z0-9]{8,}/"
        r"B[A-Za-z0-9]{8,}/[A-Za-z0-9]{24}",
        "hooks.slack.com/services/ team, bot and 24-character key segments"),
    _detector(
        "stripe_secret_key", "Stripe", "secret key", "sk_",
        r"[sr]k_(?:live|test)_[A-Za-z0-9]{24,}",
        "sk_/rk_ plus live/test plus at least 24 alphanumeric characters"),
    _detector(
        "stripe_webhook_secret", "Stripe",
        "webhook signing secret", "whsec_",
        r"whsec_[A-Za-z0-9]{32,}",
        "whsec_ plus at least 32 alphanumeric characters"),
    _detector(
        "sendgrid_api_key", "SendGrid", "API key", "SG.",
        r"SG\.[A-Za-z0-9_\-]{22}\.[A-Za-z0-9_\-]{43}",
        "SG. plus 22 characters, a dot, and 43 characters"),
    _detector(
        "twilio_api_key", "Twilio", "API key", "SK",
        r"SK[0-9a-f]{32}",
        "SK plus 32 lowercase hex characters"),
    _detector(
        "npm_token", "npm", "access token", "npm_",
        r"npm_[A-Za-z0-9]{36}",
        "npm_ plus 36 alphanumeric characters"),
    _detector(
        "pypi_token", "PyPI", "API token", "pypi-",
        r"pypi-[A-Za-z0-9_\-]{16,}",
        "pypi- plus at least 16 token characters"),
    _detector(
        "digitalocean_token", "DigitalOcean",
        "personal access token", "dop_v1_",
        r"dop_v1_[0-9a-f]{64}",
        "dop_v1_ plus 64 lowercase hex characters"),
    _detector(
        "square_access_token", "Square", "access token", "sq0",
        r"sq0(?:atp|csp)-[A-Za-z0-9_\-]{22,}",
        "sq0atp-/sq0csp- plus at least 22 token characters"),
    _detector(
        "mailchimp_api_key", "Mailchimp", "API key", "",
        r"[0-9a-f]{32}-us\d{1,2}\b",
        "32 lowercase hex characters plus a -us data-centre suffix"),
    _detector(
        "jwt_compact", "JWT", "JSON Web Token (compact)", "eyJ",
        r"eyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+",
        "three base64url segments, header and payload opening eyJ"),
    _detector(
        "private_key_block", "PEM", "private key block",
        "-----BEGIN ",
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?"
        r"PRIVATE KEY-----",
        "a PEM BEGIN header naming a private key type"),
)

DETECTOR_IDS = tuple(d.id for d in DETECTORS)

_BY_ID = {d.id: d for d in DETECTORS}


def detector_by_id(detector_id: str) -> Detector:
    """The named detector, or a named refusal."""
    try:
        return _BY_ID[detector_id]
    except KeyError:
        raise SecretScanningError(
            "detector_unknown",
            f"unknown secret-scanning detector {detector_id!r}") from None


def list_detectors() -> tuple:
    """The v1 set, in registry order."""
    return DETECTORS


def redact_match(detector: Detector, matched: str) -> str:
    """The only printable form of a match: prefix + length."""
    keep = detector.prefix if detector.prefix else matched[:4]
    return f"{keep}…[{len(matched)} chars]"


@dataclass(frozen=True)
class Finding:
    """One detected shape in one text. Never the secret."""

    detector_id: str
    provider: str
    label: str
    start: int
    end: int
    line: int
    column: int
    redacted: str
    fingerprint: str

    def to_dict(self) -> dict:
        return {
            "detector_id": self.detector_id,
            "provider": self.provider,
            "label": self.label,
            "start": self.start,
            "end": self.end,
            "line": self.line,
            "column": self.column,
            "redacted": self.redacted,
            "fingerprint": self.fingerprint,
        }


def _line_col(text: str, start: int) -> tuple:
    line = text.count("\n", 0, start) + 1
    last_nl = text.rfind("\n", 0, start)
    return line, start - last_nl


def _select_detectors(detector_ids) -> tuple:
    if detector_ids is None:
        return DETECTORS
    return tuple(detector_by_id(d) for d in detector_ids)


def scan_text(text: str, detector_ids=None) -> list:
    """Every published-shape secret shape in `text`.

    Deterministic overlap law: earliest span first,
    longest match at a shared start, registry order
    as the final tiebreak; a claimed span yields no
    second finding.
    """
    detectors = _select_detectors(detector_ids)
    raw = []
    for order, det in enumerate(detectors):
        for m in det.pattern.finditer(text):
            raw.append((m.start(), -(m.end() - m.start()), order,
                        det, m))
    raw.sort(key=lambda r: (r[0], r[1], r[2]))
    findings = []
    claimed_end = -1
    for start, _neglen, _order, det, m in raw:
        if start < claimed_end:
            continue
        matched = m.group(0)
        line, column = _line_col(text, start)
        findings.append(Finding(
            detector_id=det.id, provider=det.provider,
            label=det.label, start=start, end=m.end(),
            line=line, column=column,
            redacted=redact_match(det, matched),
            fingerprint=hashlib.sha256(
                matched.encode("utf-8")).hexdigest()))
        claimed_end = m.end()
    findings.sort(key=lambda f: f.start)
    return findings


def scan_lines(lines, detector_ids=None) -> list:
    """Scan lines independently; line numbers are 1-based."""
    out = []
    for i, line_text in enumerate(lines, start=1):
        for f in scan_text(line_text, detector_ids=detector_ids):
            out.append(Finding(
                detector_id=f.detector_id, provider=f.provider,
                label=f.label, start=f.start, end=f.end, line=i,
                column=f.column, redacted=f.redacted,
                fingerprint=f.fingerprint))
    return out


def render_secret_scanning_page(findings, title="Secret scanning"):
    """The findings face: shapes and places, never secrets."""
    from .escaping import escape_html_text

    rows = "".join(
        "<li>"
        + escape_html_text(f.provider)
        + " "
        + escape_html_text(f.label)
        + " — line "
        + str(f.line)
        + ", column "
        + str(f.column)
        + ": "
        + escape_html_text(f.redacted)
        + "</li>"
        for f in findings)
    if not rows:
        rows = "<li>No secret shapes found.</li>"
    return (
        "<!DOCTYPE html><html><head><title>"
        + escape_html_text(title)
        + "</title></head><body><h1>"
        + escape_html_text(title)
        + "</h1><ul>"
        + rows
        + "</ul></body></html>")
