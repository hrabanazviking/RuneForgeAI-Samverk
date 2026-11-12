"""Generic secret detection (S-290).

Entropy and context heuristics for the secrets no
published pattern names — the deliberate complement
of S-289's pattern set. S-289 judges *shapes* a
provider published; this slice judges *unshaped*
strings: a candidate is suspicious when it carries
more information than ordinary text (Shannon entropy
per character), is long enough to hold a credential,
and sits in a context that agrees (an assignment to
a secret-named key), or is so entropic and so long
that no ordinary prose, hash, or identifier explains
it. A shape with a published form belongs to S-289;
an AWS secret access key — forty unmarked characters
— is exactly the kind of secret this slice exists
to catch.

- **The false-positive rate is measured, not vibes.**
  This module ships a labelled corpus
  (`build_labelled_corpus`): synthetic secret-shaped
  strings in realistic contexts, labelled secret, and
  ordinary repository text — prose, hashes in hash
  context, UUIDs, URLs, encoded-asset magic, version
  strings — labelled benign. `evaluate_corpus` runs
  the real detector over the corpus and counts true
  and false positives; the resulting rates are
  published below as `PUBLISHED_*` constants, and
  the battery re-measures and refuses any drift, so
  the published rate is the measured rate or the
  build is red. No real credential appears in the
  corpus: secret cases are hand-assembled random-
  looking strings, benign cases are ordinary text.
- **Findings never carry the secret.** A
  `GenericFinding` holds the span (offset, line,
  column), the measured entropy, the context verdict
  in words, a redacted preview that carries only the
  match length, and a SHA-256 fingerprint — the same
  law as S-289. The matched text is never stored,
  rendered, or logged.
- **Context cuts both ways.** Secret-named assignment
  keys raise the score; hash-named keys, placeholder
  markers (`example`, `changeme`, `your_…`, …), UUID
  shapes, base64 that decodes to ordinary printable
  prose (encoded text is not a secret), and known
  encoded-asset base64 magic
  (PNG/JPEG/GIF/ZIP headers) suppress or lower it —
  a git SHA in a `commit =` line is an identifier,
  not a credential, and the corpus proves the
  detector knows the difference.
- **The S-289 seam.** This slice stands alone on a
  base without S-289: nothing here imports
  `samverk.secret_scanning` at module load.
  `pattern_layer_available()` probes for it, and
  `combined_scan` merges S-289's pattern findings
  with these generic findings when the pattern layer
  is present, and returns the generic findings alone
  (saying so) when it is not. When S-289 banks, the
  combined road lights up with no change here.
- **No storage, no audit event, no migration.**
  Detection is a pure judgement over text handed to
  it; persistence and alerting are later slices.
  133 events stand: 33 auth / 87 repo / 13 admin.
  Schema stands at 114.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import math
import re
from dataclasses import dataclass, field


class GenericSecretError(Exception):
    """A generic-detection refusal, named by its code."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail or code


def shannon_entropy(text: str) -> float:
    """Shannon entropy of `text`, in bits per character."""
    if not text:
        return 0.0
    counts = {}
    for ch in text:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(text)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


@dataclass(frozen=True)
class DetectionConfig:
    """The detector's thresholds — one named place."""

    min_length: int = 12
    flag_score: int = 5
    entropy_floor: float = 3.8

    def validate(self) -> None:
        if self.min_length < 8:
            raise GenericSecretError(
                "config_invalid",
                "min_length below 8 cannot hold a credential")
        if self.flag_score < 1:
            raise GenericSecretError(
                "config_invalid", "flag_score must be positive")
        if not (0.0 < self.entropy_floor < 8.0):
            raise GenericSecretError(
                "config_invalid", "entropy_floor out of range")


DEFAULT_CONFIG = DetectionConfig()

_SECRET_KEY = re.compile(
    r"(api[_\-]?key|client[_\-]?secret|access[_\-]?key|"
    r"secret|password|passwd|credential|private[_\-]?key|"
    r"auth[_\-]?token|token|passwd|pwd)", re.IGNORECASE)
_BENIGN_KEY = re.compile(
    r"(sha\d*|md5|checksum|digest|hash|uuid|guid|etag|"
    r"commit|revision|fingerprint|blob)", re.IGNORECASE)
_PLACEHOLDER = re.compile(
    r"(example|placeholder|changeme|change[_\-]me|your[_\-]|"
    r"dummy|sample[_\-]|redacted|lorem|xxxx|\*\*\*\*|"
    r"todo|fixme|insert[_\-])", re.IGNORECASE)
_UUID_SHAPE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_ASSET_MAGIC = ("iVBORw0KGgo", "/9j/", "R0lGOD", "UEsDB", "PHN2Zy")
_URL_USERINFO = re.compile(r"://[^/\s:]+:([^@\s]+)@")
_TOKEN = re.compile(r"[A-Za-z0-9+/=_\-]{12,}")
_KEY_BEFORE = re.compile(
    r"([A-Za-z0-9_.\-]{2,40})\s*[:=]", re.IGNORECASE)


@dataclass(frozen=True)
class Candidate:
    """One candidate string in its line context."""

    value: str
    start: int
    end: int
    line: int
    column: int
    key_name: str
    secret_context: bool
    benign_context: bool
    placeholder: bool
    url_userinfo: bool = False


@dataclass(frozen=True)
class Assessment:
    """The scored judgement of one candidate."""

    candidate: Candidate
    entropy: float
    score: int
    flagged: bool
    suppressed: str
    reasons: tuple


def _line_col(text: str, start: int) -> tuple:
    line = text.count("\n", 0, start) + 1
    last_nl = text.rfind("\n", 0, start)
    return line, start - last_nl


def _in_url_password(line_text: str, offset: int, value: str) -> bool:
    """True when the candidate sits in a URL's password slot."""
    m = _URL_USERINFO.search(line_text)
    if m is None:
        return False
    return m.start(1) <= offset and offset + len(value) <= m.end(1) + 1 and value in m.group(1)


def _line_span(text: str, start: int, end: int) -> tuple:
    lo = text.rfind("\n", 0, start) + 1
    hi = text.find("\n", end)
    if hi == -1:
        hi = len(text)
    return lo, hi


def extract_candidates(text: str,
                       config: DetectionConfig = DEFAULT_CONFIG,
                       ) -> list:
    """Every token-shaped candidate of judged length."""
    config.validate()
    out = []
    for m in _TOKEN.finditer(text):
        value = m.group(0).strip("=_-")
        if len(value) < config.min_length:
            continue
        start = m.start() + (len(m.group(0)) - len(m.group(0).lstrip("=_-")))
        lo, hi = _line_span(text, m.start(), m.end())
        line_text = text[lo:hi]
        key_name = ""
        km = None
        for km in _KEY_BEFORE.finditer(line_text[:m.start() - lo]):
            pass
        if km is not None:
            key_name = km.group(1)
        line_no, col = _line_col(text, start)
        out.append(Candidate(
            value=value, start=start, end=start + len(value),
            line=line_no, column=col, key_name=key_name,
            secret_context=bool(_SECRET_KEY.search(key_name)),
            benign_context=bool(_BENIGN_KEY.search(key_name)),
            placeholder=bool(_PLACEHOLDER.search(value)
                             or _PLACEHOLDER.search(line_text)),
            url_userinfo=_in_url_password(line_text, m.start() - lo, value)))
    return out


def _decodes_to_prose(value: str) -> bool:
    """True when the value is base64 of ordinary text.

    A random credential base64-decodes to random bytes;
    encoded prose decodes to printable words. Encoded
    ordinary text is not a secret, however entropic its
    encoding looks.
    """
    if len(value) < 16 or len(value) % 4 == 1:
        return False
    padded = value + "=" * (-len(value) % 4)
    try:
        raw = base64.b64decode(padded, altchars=b"-_",
                               validate=True)
    except (binascii.Error, ValueError):
        return False
    if len(raw) < 8 or b" " not in raw:
        return False
    printable = sum(1 for b in raw if 32 <= b < 127
                    or b in (9, 10, 13))
    return printable / len(raw) >= 0.9


def _char_classes(value: str) -> int:
    classes = 0
    if any(c.islower() for c in value):
        classes += 1
    if any(c.isupper() for c in value):
        classes += 1
    if any(c.isdigit() for c in value):
        classes += 1
    if any(c in "+/=_-" for c in value):
        classes += 1
    return classes


def assess_candidate(candidate: Candidate,
                     config: DetectionConfig = DEFAULT_CONFIG,
                     ) -> Assessment:
    """Score one candidate: entropy + length + context."""
    value = candidate.value
    entropy = shannon_entropy(value)
    if candidate.placeholder:
        return Assessment(candidate, entropy, 0, False,
                          "placeholder", ("placeholder marker",))
    if _UUID_SHAPE.match(value):
        return Assessment(candidate, entropy, 0, False,
                          "uuid_shape", ("UUID shape",))
    if _decodes_to_prose(value):
        return Assessment(candidate, entropy, 0, False,
                          "encoded_prose",
                          ("base64 of ordinary printable text",))
    if value.startswith(_ASSET_MAGIC):
        return Assessment(candidate, entropy, 0, False,
                          "asset_magic",
                          ("encoded-asset magic prefix",))
    score = 0
    reasons = []
    if entropy >= 4.5:
        score += 3
        reasons.append("entropy >= 4.5")
    elif entropy >= 4.2:
        score += 2
        reasons.append("entropy >= 4.2")
    elif entropy >= 3.8:
        score += 1
        reasons.append("entropy >= 3.8")
    if len(value) >= 32:
        score += 2
        reasons.append("length >= 32")
    elif len(value) >= 20:
        score += 1
        reasons.append("length >= 20")
    if _char_classes(value) >= 3:
        score += 1
        reasons.append("three or more character classes")
    if candidate.secret_context:
        score += 3
        reasons.append("secret-named assignment context")
    if candidate.url_userinfo:
        score += 3
        reasons.append("password position in URL userinfo")
    if candidate.benign_context:
        score -= 3
        reasons.append("hash/identifier-named context")
    flagged = (score >= config.flag_score
               and entropy >= config.entropy_floor)
    return Assessment(candidate, entropy, score, flagged, "",
                      tuple(reasons))


@dataclass(frozen=True)
class GenericFinding:
    """One generic secret judgement. Never the secret."""

    start: int
    end: int
    line: int
    column: int
    entropy: float
    score: int
    context: str
    redacted: str
    fingerprint: str

    def to_dict(self) -> dict:
        return {
            "start": self.start, "end": self.end,
            "line": self.line, "column": self.column,
            "entropy": self.entropy, "score": self.score,
            "context": self.context,
            "redacted": self.redacted,
            "fingerprint": self.fingerprint,
        }


def redact_candidate(value: str) -> str:
    """The only printable form: length, never content."""
    return f"generic…[{len(value)} chars]"


def scan_generic(text: str,
                 config: DetectionConfig = DEFAULT_CONFIG) -> list:
    """Every generically-detected secret in `text`."""
    findings = []
    for cand in extract_candidates(text, config):
        a = assess_candidate(cand, config)
        if not a.flagged:
            continue
        context = ("secret-named assignment"
                   if cand.secret_context else "bare high-entropy")
        findings.append(GenericFinding(
            start=cand.start, end=cand.end, line=cand.line,
            column=cand.column, entropy=round(a.entropy, 3),
            score=a.score, context=context,
            redacted=redact_candidate(cand.value),
            fingerprint=hashlib.sha256(
                cand.value.encode("utf-8")).hexdigest()))
    findings.sort(key=lambda f: f.start)
    return findings


def render_generic_detection_page(findings, title="Generic secret detection"):
    """The findings face: measurements, never secrets."""
    from .escaping import escape_html_text

    rows = "".join(
        "<li>line " + str(f.line) + ", column " + str(f.column)
        + ": " + escape_html_text(f.redacted)
        + " (entropy " + str(f.entropy) + ", "
        + escape_html_text(f.context) + ")</li>"
        for f in findings)
    if not rows:
        rows = "<li>No generic secrets found.</li>"
    return (
        "<!DOCTYPE html><html><head><title>"
        + escape_html_text(title)
        + "</title></head><body><h1>"
        + escape_html_text(title)
        + "</h1><ul>" + rows + "</ul></body></html>")


# --- The S-289 seam: optional, lazy, never load-bearing. ---

def pattern_layer_available() -> bool:
    """True when S-289's pattern module is present."""
    try:
        import importlib.util
        return importlib.util.find_spec(
            "samverk.secret_scanning") is not None
    except Exception:
        return False


def combined_scan(text: str,
                  config: DetectionConfig = DEFAULT_CONFIG) -> dict:
    """Generic findings, plus S-289 patterns when present.

    On a base without S-289 the pattern side is None
    and `pattern_available` is False — the generic
    road stands alone and says so.
    """
    generic = scan_generic(text, config)
    patterns = None
    if pattern_layer_available():
        from .secret_scanning import scan_text as _scan_patterns
        patterns = [f.to_dict() for f in _scan_patterns(text)]
    return {
        "generic": [f.to_dict() for f in generic],
        "pattern_available": patterns is not None,
        "patterns": patterns,
    }


# --- The labelled corpus: the published rate's ground. ---

@dataclass(frozen=True)
class CorpusCase:
    """One labelled line: text, truth, and its family."""

    text: str
    is_secret: bool
    category: str


_SECRET_CASES = (
    ("api_key = \"xK9mQ2vR8nB4wZ7pL3sD6fG1hJ5kM0\"", "assigned_api_key"),
    ("aws_secret = \"wJalrXUtnFEMIK7MDENGbPxRfiCYz9q4sT2v\"", "assigned_cloud_secret"),
    ("password = \"Tr7kQ9wZ2xB8nM4vL6sD1fG3hJ5\"", "assigned_password"),
    ("leaked in log: mF9kQ2xR8vB4nZ7pL3sD6wG1hJ5tY0uI split", "bare_token_in_prose"),
    ("client_secret = \"9f2c4a7e1b8d0f3a5c6e7d8b9a0f1c2e\"", "assigned_hex_secret"),
    ("token = \"Q7vR8nB4wZ2pL9sD6fG1hJ3k\"", "assigned_token"),
    ("aT3kQ9wZ8xB2nM7vL4sD6fG9hJ1kM5pR8uW0yA3cE6gH", "bare_base64_blob"),
    ("dsn = postgres://svc:Kx9mQ2vR8nB4wZ7p@db.internal/app", "dsn_password"),
    ("SECRET_KEY=Zx8vB3nM6kQ9wR2tY5uI8oP1aS4dF7gH", "env_assignment"),
    ("Authorization: Bearer mF9kQ2xR8vB4nZ7pL3sD6wG1hJ5tY0", "bearer_header"),
    ("api_key = \"Kx9mQ2vR8nB4wZ7p\"", "short_assigned_key"),
    ("session_secret = \"dBjFTJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk\"", "assigned_session_secret"),
    ("passwd: H7kM2pR9wZ4xB8nQ3vL6sD", "assigned_passwd"),
    ("webhook_secret = \"R8nB4wZ7pL3sD6fG1hJ5kM0xQ2v9\"", "assigned_webhook_secret"),
    ("backup_code = \"W3xB8nM4vL6sD1fG9hJ2kM5pR7\"", "assigned_backup_code"),
    ("refresh = \"Z8xB2nM5vL9sD3fG6hJ1kM4pR7tW0yA2cE5gH8j\"", "assigned_refresh_token"),
)

_BENIGN_CASES = (
    ("The quick brown fox jumps over the lazy dog near the river bank.", "prose"),
    ("commit = 9f2c4a7e1b8d0f3a5c6e7d8b9a0f1c2e3d4b5a69", "labelled_hash"),
    ("9f2c4a7e1b8d0f3a5c6e7d8b9a0f1c2e3d4b5a69", "bare_hash"),
    ("sha256 = e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "labelled_digest"),
    ("id = 550e8400-e29b-41d4-a716-446655440000", "uuid"),
    ("550e8400-e29b-41d4-a716-446655440000", "bare_uuid"),
    ("icon = data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "encoded_asset"),
    ("docs at https://example.org/guides/getting-started-with-version-control-systems today", "url"),
    ("version = 2.14.0 released on 2026-11-01 with configuration improvements", "version_prose"),
    ("Lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod", "lorem"),
    ("api_key = \"your_api_key_here_example\"", "placeholder_key"),
    ("password = \"changeme123456789\"", "placeholder_password"),
    ("color: #a1b2c3; font-family: incomprehensibilities, sans-serif;", "css_and_long_words"),
    ("greeting = aGVsbG8gd29ybGQgdGhpcyBpcyBhIHRlc3Q", "encoded_ordinary_text"),
    ("analytics_id = GA1.2.1234567890.9876543210", "analytics_id"),
    ("path = /home/volmarr/samverk-team-08/samverk/generic_secret_detection.py", "file_path"),
    ("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "repeated_filler"),
    ("call us at +1-555-014-2288 or write to the office before Friday", "contact_prose"),
    ("| name | description | internationalisation responsibilities |", "table_prose"),
    ("etag = \"5d41402abc4b2a76b9719d911017c592\"", "labelled_etag"),
    ("svg = data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciPjwvc3ZnPg==", "encoded_svg"),
    ("The harbourmaster counted forty-three longships before the winter storms arrived", "narrative_prose"),
    ("remote = https://volmarr@example.org/samverk.git", "url_userinfo_no_password"),
)


def build_labelled_corpus() -> tuple:
    """The labelled corpus, secrets first, then benign."""
    return tuple(
        [CorpusCase(t, True, c) for t, c in _SECRET_CASES]
        + [CorpusCase(t, False, c) for t, c in _BENIGN_CASES])


@dataclass(frozen=True)
class CorpusReport:
    """Measured detector quality on the labelled corpus."""

    total: int
    secret_cases: int
    benign_cases: int
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int
    false_positive_rate: float
    precision: float
    recall: float

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "secret_cases": self.secret_cases,
            "benign_cases": self.benign_cases,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "true_negatives": self.true_negatives,
            "false_negatives": self.false_negatives,
            "false_positive_rate": self.false_positive_rate,
            "precision": self.precision,
            "recall": self.recall,
        }


def evaluate_corpus(config: DetectionConfig = DEFAULT_CONFIG,
                    ) -> CorpusReport:
    """Run the real detector over the labelled corpus."""
    corpus = build_labelled_corpus()
    tp = fp = tn = fn = 0
    for case in corpus:
        flagged = bool(scan_generic(case.text, config))
        if case.is_secret and flagged:
            tp += 1
        elif case.is_secret:
            fn += 1
        elif flagged:
            fp += 1
        else:
            tn += 1
    benign = fp + tn
    secrets = tp + fn
    return CorpusReport(
        total=len(corpus), secret_cases=secrets,
        benign_cases=benign, true_positives=tp,
        false_positives=fp, true_negatives=tn,
        false_negatives=fn,
        false_positive_rate=(fp / benign) if benign else 0.0,
        precision=(tp / (tp + fp)) if (tp + fp) else 1.0,
        recall=(tp / secrets) if secrets else 0.0)


# Published measurements — re-measured by the battery
# on every run; any drift turns the build red.
PUBLISHED_CORPUS_SIZE = 39
PUBLISHED_FALSE_POSITIVE_RATE = 0.0
PUBLISHED_PRECISION = 1.0
PUBLISHED_RECALL = 1.0
