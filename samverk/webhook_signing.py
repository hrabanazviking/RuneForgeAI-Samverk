"""Webhook signing (S-249).

HMAC-SHA256 over the raw body, signature header,
verification documented with examples. S-247
stated the payload and its canonical bytes
(`payload_json`), S-248 built the subscriptions
that receive them; this slice states -- as pure
functions, plus the worked verification examples
in docs/WEBHOOK_EVENTS.md -- how a delivery is
signed and how a receiver checks the signature.
S-250's delivery worker signs through this
module and no other; none of the three invents
its own signing road.

- **The signed bytes are the raw body.** The
  signature covers exactly the bytes delivered:
  for an event payload, the UTF-8 encoding of
  S-247's `payload_json` (sorted keys, tight
  separators) and nothing else -- no re-serialised
  form, no added whitespace, no trailing newline.
  A receiver verifies over the exact bytes it
  received; re-serialising the parsed payload and
  verifying that is a different byte string and
  fails, by design (the battery proves it).
- **The header.** A signed delivery carries one
  header, `X-Samverk-Signature-256`, whose value
  is `sha256=` followed by the 64 lowercase hex
  characters of the HMAC-SHA256 -- the shape
  receivers already know from other forges,
  under Samverk's own header name. The hex is
  compared in constant time on verification.
- **The key is the stored digest, honestly.**
  S-248's law stores a subscription's secret
  only as its SHA-256 digest (the S-006 law):
  the raw secret exists at creation, in the
  creator's hands, and in the receiver's
  configuration -- never in Samverk's database,
  and no later face can recover it. A signing
  road that needed the raw secret could therefore
  never run. So the HMAC key is the secret's
  SHA-256 digest itself (its 32 raw bytes): the
  sender signs with the digest S-248 stored, and
  the receiver -- who holds the raw secret --
  derives the identical key by hashing the
  secret once. `sign_payload` (from a raw
  secret) and `sign_payload_with_digest` (from
  the stored digest) agree byte for byte, and
  the battery pins that agreement. The honest
  price, stated wherever this is documented:
  the stored digest is itself a signing
  credential. A leaked database lets a thief
  sign deliveries (and learn nothing else: the
  raw secret is not recoverable from its digest
  and cannot be replayed anywhere the secret
  itself is the credential -- S-248's
  `secret_matches` question still needs the raw
  secret's own digest to match, which is the
  same value, so treat the digest with the same
  care as the secret). Rotating the secret --
  delete the subscription, create its successor
  (S-248's road) -- rotates the signing key
  with it.
- **Unsigned means unsigned.** A subscription
  with no secret carries no signature header at
  all -- `delivery_headers` answers an empty
  mapping -- and a receiver must not treat such
  a delivery as authenticated. There is no
  placeholder signature and no instance-wide
  fallback key: a signature Samverk cannot
  honestly make, it does not fake.
- **Verification answers one question.**
  `verify_signature` and its digest twin answer
  whether a presented header is this body's
  signature under this secret, and nothing else:
  a missing or malformed header, a wrong secret,
  a body altered by one byte, and a subscription
  with no secret all answer False, never an
  exception -- the same shape as S-248's
  `secret_matches`. The strict reader,
  `parse_signature_header`, names the refusal
  (`webhook_signature_missing` /
  `webhook_signature_malformed`) for faces that
  want the reason in words.
- **A pure road, like S-247.** This module holds
  no store, writes no row and audits nothing:
  signing is arithmetic over bytes the caller
  already holds. No migration (schema 96
  stands), no new taxonomy event (131 stand).
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from pathlib import Path

from .escaping import escape_html_text
from .event_store import CanonicalEvent
from .webhook_events import payload_json
from .webhook_subscriptions import (
    WebhookSubscriptionError, secret_digest, validate_secret)

__all__ = [
    "SIGNATURE_ALGORITHM", "SIGNATURE_HEADER",
    "SIGNATURE_PREFIX", "WebhookSigningAudit",
    "WebhookSigningError", "audit_webhook_signing",
    "body_bytes", "delivery_headers",
    "parse_signature_header", "render_webhook_signing_page",
    "sign_event", "sign_event_with_digest", "sign_payload",
    "sign_payload_with_digest", "signature_header",
    "signature_header_with_digest", "signing_key",
    "signing_key_from_digest", "verify_event_signature",
    "verify_event_signature_with_digest", "verify_signature",
    "verify_signature_with_digest",
]

#: The one header a signed delivery carries.
SIGNATURE_HEADER = "X-Samverk-Signature-256"

#: The value's prefix, naming the digest algorithm
#: (the shape other forges' receivers already parse).
SIGNATURE_PREFIX = "sha256="

#: The algorithm, said in words wherever a face
#: states it: HMAC with SHA-256, keyed as the
#: module docstring states.
SIGNATURE_ALGORITHM = "HMAC-SHA256"

_HEX = frozenset("0123456789abcdef")


class WebhookSigningError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


# -- the bytes --------------------------------------


def body_bytes(body: object) -> bytes:
    """The exact bytes a signature covers: a
    `bytes` body is itself, unchanged; a `str`
    body is its UTF-8 encoding, verbatim (no
    newline added, nothing re-serialised).
    Anything else is refused
    `webhook_body_invalid` -- a signature over a
    guessed serialisation would be a lie about
    what was delivered."""
    if isinstance(body, bytes):
        return body
    if isinstance(body, bytearray):
        return bytes(body)
    if isinstance(body, str):
        return body.encode("utf-8")
    raise WebhookSigningError(
        "webhook_body_invalid",
        "A webhook body to sign is bytes or text.")


# -- the key ----------------------------------------


def signing_key(secret: object) -> bytes:
    """The HMAC key for a raw secret: the 32 raw
    bytes of its SHA-256 digest -- the very value
    S-248 stores, so the sender's stored form and
    the receiver's held secret derive one key.
    The secret is judged by S-248's own validator;
    no secret at all is refused
    `webhook_signing_secret_required`."""
    if secret is None:
        raise WebhookSigningError(
            "webhook_signing_secret_required",
            "Signing needs the subscription's secret; "
            "a subscription with no secret is unsigned.")
    try:
        checked = validate_secret(secret)
    except WebhookSubscriptionError as exc:
        raise WebhookSigningError(exc.reason, str(exc)) from exc
    return bytes.fromhex(secret_digest(checked))


def signing_key_from_digest(stored_digest: object) -> bytes:
    """The HMAC key for a stored digest (S-248's
    `secret_digest` hex): its 32 raw bytes. A
    value that is not exactly one SHA-256 hex
    digest is refused
    `webhook_signing_digest_invalid` -- signing
    with a misread key would mint signatures no
    receiver can ever verify."""
    if (not isinstance(stored_digest, str)
            or len(stored_digest) != 64
            or any(c not in _HEX for c in stored_digest.lower())):
        raise WebhookSigningError(
            "webhook_signing_digest_invalid",
            "A stored webhook secret digest is 64 hex "
            "characters.")
    return bytes.fromhex(stored_digest.lower())


def _hmac_hex(key: bytes, body: object) -> str:
    return hmac.new(key, body_bytes(body), hashlib.sha256).hexdigest()


# -- signing ----------------------------------------


def sign_payload(body: object, secret: object) -> str:
    """The signature itself, as 64 lowercase hex
    characters: HMAC-SHA256 over the raw body,
    keyed by the secret's digest. This is the
    receiver-side road (the receiver holds the
    raw secret); it agrees byte for byte with
    `sign_payload_with_digest`."""
    return _hmac_hex(signing_key(secret), body)


def sign_payload_with_digest(body: object,
                             stored_digest: object) -> str:
    """The signature itself, from the stored
    digest alone -- the sender-side road S-250
    runs, since the raw secret is never
    available to it (S-248's law)."""
    return _hmac_hex(signing_key_from_digest(stored_digest), body)


def signature_header(body: object, secret: object) -> str:
    """The header value for one body under one
    raw secret: `sha256=` plus the signature."""
    return SIGNATURE_PREFIX + sign_payload(body, secret)


def signature_header_with_digest(body: object,
                                 stored_digest: object) -> str:
    """The header value for one body under one
    stored digest."""
    return SIGNATURE_PREFIX + sign_payload_with_digest(
        body, stored_digest)


def delivery_headers(body: object,
                     stored_digest: object) -> dict[str, str]:
    """The headers one delivery carries, judged
    from the subscription's stored digest alone:
    the signature header when a secret is set,
    and an empty mapping when none is -- an
    unsigned delivery carries no header rather
    than a fake one. A malformed stored digest
    is refused, as `signing_key_from_digest`
    refuses it."""
    if stored_digest is None or stored_digest == "":
        return {}
    return {SIGNATURE_HEADER: signature_header_with_digest(
        body, stored_digest)}


def sign_event(event: CanonicalEvent, secret: object) -> str:
    """The header value for one canonical event
    under one raw secret: the signed bytes are
    S-247's `payload_json` exactly (a withheld
    verb is refused there, as there)."""
    return signature_header(payload_json(event), secret)


def sign_event_with_digest(event: CanonicalEvent,
                           stored_digest: object) -> str:
    """The header value for one canonical event
    under one stored digest -- S-250's road."""
    return signature_header_with_digest(
        payload_json(event), stored_digest)


# -- verification -----------------------------------


def parse_signature_header(value: object) -> str:
    """One presented header value, read strictly:
    its 64 hex characters, lowercased. A missing
    value is refused `webhook_signature_missing`;
    anything present but not `sha256=` plus one
    hex digest is `webhook_signature_malformed`."""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise WebhookSigningError(
            "webhook_signature_missing",
            "This delivery carries no signature header.")
    if not isinstance(value, str):
        raise WebhookSigningError(
            "webhook_signature_malformed",
            "That signature header is not valid.")
    text = value.strip()
    if not text.startswith(SIGNATURE_PREFIX):
        raise WebhookSigningError(
            "webhook_signature_malformed",
            "That signature header is not valid.")
    hexpart = text[len(SIGNATURE_PREFIX):].lower()
    if len(hexpart) != 64 or any(c not in _HEX for c in hexpart):
        raise WebhookSigningError(
            "webhook_signature_malformed",
            "That signature header is not valid.")
    return hexpart


def verify_signature(body: object, header_value: object,
                     secret: object) -> bool:
    """Whether *header_value* is *body*'s
    signature under the raw *secret*, compared
    in constant time. Every failure -- a missing
    or malformed header, an unusable secret, a
    body of the wrong shape -- answers False;
    verification asks one question and its answer
    is yes or no."""
    try:
        presented = parse_signature_header(header_value)
        expected = sign_payload(body, secret)
    except (WebhookSigningError, WebhookSubscriptionError):
        return False
    return hmac.compare_digest(expected, presented)


def verify_signature_with_digest(body: object, header_value: object,
                                 stored_digest: object) -> bool:
    """Whether *header_value* is *body*'s
    signature under the stored digest -- the
    same question, from the sender's side of
    S-248's law."""
    try:
        presented = parse_signature_header(header_value)
        expected = sign_payload_with_digest(body, stored_digest)
    except (WebhookSigningError, WebhookSubscriptionError):
        return False
    return hmac.compare_digest(expected, presented)


def verify_event_signature(event: CanonicalEvent, header_value: object,
                           secret: object) -> bool:
    """Whether *header_value* signs one canonical
    event's canonical bytes under the raw secret."""
    try:
        body = payload_json(event)
    except Exception:
        return False
    return verify_signature(body, header_value, secret)


def verify_event_signature_with_digest(
        event: CanonicalEvent, header_value: object,
        stored_digest: object) -> bool:
    """Whether *header_value* signs one canonical
    event's canonical bytes under the stored
    digest."""
    try:
        body = payload_json(event)
    except Exception:
        return False
    return verify_signature_with_digest(body, header_value, stored_digest)


# -- the audit --------------------------------------


@dataclass(frozen=True)
class WebhookSigningAudit:
    """The signing road checked against itself and
    its document: the two key roads agree, a
    known-answer recomputation holds, a tampered
    body fails, and docs/WEBHOOK_EVENTS.md states
    the header, the algorithm and the key law.
    Ratified only when every check holds."""
    checks: int
    problems: tuple[str, ...]

    @property
    def ratified(self) -> bool:
        return not self.problems


def audit_webhook_signing() -> WebhookSigningAudit:
    """Check this module against the live document
    and an independent recomputation. Pure read:
    arithmetic and one file read only."""
    problems: list[str] = []
    checks = 0
    probe_body = b'{"event":"repo.issue.create","number":1}'
    probe_secret = "audit probe secret"
    probe_digest = secret_digest(probe_secret)
    checks += 1
    independent = hmac.new(
        hashlib.sha256(probe_secret.encode("utf-8")).digest(),
        probe_body, hashlib.sha256).hexdigest()
    if sign_payload(probe_body, probe_secret) != independent:
        problems.append("known-answer")
    checks += 1
    if (sign_payload(probe_body, probe_secret)
            != sign_payload_with_digest(probe_body, probe_digest)):
        problems.append("key-roads-agree")
    checks += 1
    good = signature_header(probe_body, probe_secret)
    if not verify_signature(probe_body, good, probe_secret):
        problems.append("verify-accepts")
    checks += 1
    if verify_signature(probe_body + b" ", good, probe_secret):
        problems.append("verify-rejects-tamper")
    checks += 1
    if delivery_headers(probe_body, "") != {}:
        problems.append("unsigned-law")
    doc_path = (Path(__file__).resolve().parent.parent
                / "docs" / "WEBHOOK_EVENTS.md")
    try:
        doc_text = doc_path.read_text(encoding="utf-8")
    except OSError:
        doc_text = ""
        problems.append("docs:missing")
    if doc_text:
        for needle, tag in (
                (SIGNATURE_HEADER, "docs:header"),
                (SIGNATURE_ALGORITHM, "docs:algorithm"),
                ("## Signing (S-249)", "docs:section"),
                ("sha256=", "docs:prefix")):
            checks += 1
            if needle not in doc_text:
                problems.append(tag)
    return WebhookSigningAudit(checks=checks, problems=tuple(problems))


# -- the rendered face -------------------------------


def render_webhook_signing_page(
        audit: WebhookSigningAudit | None = None) -> str:
    """The signing road, rendered where integrators
    find it: the header, the key law stated
    honestly, the unsigned law, and the
    verification steps. Every value escaped
    through S-010; no secret or digest ever
    appears -- the page teaches with names, not
    credentials."""
    parts = [
        "<h1>Webhook signing</h1>",
        "<p>Every signed webhook delivery carries one "
        "header, "
        f"{escape_html_text(SIGNATURE_HEADER)}, whose "
        "value is "
        f"{escape_html_text(SIGNATURE_PREFIX)} followed "
        "by the 64 hex characters of an "
        f"{escape_html_text(SIGNATURE_ALGORITHM)} over "
        "the exact bytes delivered -- for an event "
        "payload, the canonical JSON of "
        "docs/WEBHOOK_EVENTS.md. Verify over the raw "
        "bytes you received; never re-serialise the "
        "payload first.</p>",
        "<p>The signing key is the SHA-256 digest of "
        "the subscription's secret (its 32 raw bytes): "
        "Samverk stores only that digest (S-248), so "
        "the sender signs with the stored digest and "
        "a receiver derives the same key by hashing "
        "the secret it holds. Treat the stored digest "
        "as a signing credential. A subscription with "
        "no secret is unsigned: its deliveries carry "
        "no signature header and must not be treated "
        "as authenticated.</p>",
        "<p>To verify: hash your secret once with "
        "SHA-256 and use the raw digest as the HMAC "
        "key; compute HMAC-SHA256 over the raw "
        "request body; compare with the header's hex "
        "in constant time. Worked examples, in Python "
        "and with openssl, live in "
        "docs/WEBHOOK_EVENTS.md.</p>",
    ]
    if audit is not None:
        if audit.ratified:
            parts.append(
                "<p>Checked, not just claimed: the two "
                "key roads were compared and agree, a "
                "known-answer recomputation holds, a "
                "one-byte-tampered body fails "
                "verification, and the document states "
                "this header and algorithm.</p>")
        else:
            problems = ", ".join(audit.problems)
            parts.append(
                "<p>Checked, and no longer exact: the "
                "signing road disagrees with itself or "
                "its document -- "
                f"{escape_html_text(problems)} "
                "-- and that is a defect against "
                "S-249, to be fixed where it lies.</p>")
    return "\n".join(parts)
