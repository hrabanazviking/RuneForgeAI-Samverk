"""The Samtal seam contract, frozen (S-361).

Part XIX opens here. Research file 39 designed the seam;
S-045 landed its identity-link data shape; this slice
reviews that design against the landed Samverk codebase
and freezes it as the contract every later Part XIX slice
(S-362..S-380) builds against. The full ratification
record is docs/SEAM_CONTRACT.md.

The contract in one breath: two sovereign applications,
one village. Samverk stays whole without Samtal and
Samtal stays whole without Samverk; the seam is optional
and disabled by default; federation between villages is
refused permanently.

Frozen sections:
1. IDENTITY LINK - a Samtal principal links to a Samverk
   account by mutual proof: a short-lived, audience-bound
   signed assertion (S-249's HMAC road), replay refused by
   nonce, explicit consent on both sides. The link record
   lives under each application's own authority on the
   S-045 shape (provider 'samtal'); the external id is an
   identifier, never a credential. Unlinking is one action
   on either side and cascades nothing destructively.
2. EMBED CONTRACT - Samtal renders, Samverk decides.
   Embeds and unfurls are served by Samverk's API and
   judged against the VIEWER's Samverk rights at request
   time; an embed confers no access of its own.
3. EVENT BRIDGE - pushes, pull requests, issues and
   releases may post into a chosen hall as concise cards:
   per-hall opt-in and mute, idempotency-keyed delivery,
   exactly-once at the seam (S-226's rule), payloads
   privacy-filtered so a private repo's events never
   reach a hall whose members lack rights.
4. SOVEREIGNTY - direct Samverk login, Git transports and
   admin recovery never depend on Samtal; killing Samtal
   mid-push loses no Git data and no audit event; the
   seam disables cleanly from either side's admin
   (S-372) and the disablement is audit-logged both sides.

This module is the contract as code: pure judgements only,
no storage, no network, no migration, no taxonomy event.
Later slices implement against these names and numbers;
changing them is a contract change, named as such.
"""
from __future__ import annotations

CONTRACT_VERSION = 1
SEAM_PROVIDER = "samtal"
SEAM_AUDIENCE = "samverk"
LINK_ASSERTION_MAX_AGE_SECONDS = 300
EMBED_KINDS = ("repo", "file", "pull_request", "issue", "gist", "release")
EVENT_KINDS = ("push", "pull_request", "issue", "release")
CONTRACT_SECTIONS = ("identity_link", "embed", "event_bridge", "sovereignty")


class SeamContractError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def seam_enabled(settings: dict | None) -> bool:
    """The seam is optional and disabled by default: only an
    explicit True under 'seam.samtal.enabled' turns it on."""
    if not settings:
        return False
    return settings.get("seam.samtal.enabled") is True


def validate_link_assertion(a: dict, *, now: int, seen_nonces: set) -> dict:
    """Judge a linking assertion under section 1. Returns the
    cleaned claim or raises SeamContractError with a reason:
    audience_mismatch / assertion_expired / assertion_replay /
    consent_required / provider_mismatch / claim_incomplete."""
    if not isinstance(a, dict):
        raise SeamContractError("claim_incomplete", "Assertion must be a mapping.")
    if a.get("provider") != SEAM_PROVIDER:
        raise SeamContractError("provider_mismatch", "Only the samtal provider links here.")
    if a.get("audience") != SEAM_AUDIENCE:
        raise SeamContractError("audience_mismatch", "Assertion was not issued for Samverk.")
    if a.get("consent") is not True:
        raise SeamContractError("consent_required", "Linking needs explicit consent.")
    exp = a.get("expires_at")
    iat = a.get("issued_at")
    nonce = a.get("nonce")
    principal = a.get("principal")
    if not isinstance(exp, int) or not isinstance(iat, int) or not nonce or not principal:
        raise SeamContractError("claim_incomplete", "Assertion lacks required claims.")
    if exp < iat or exp - iat > LINK_ASSERTION_MAX_AGE_SECONDS or now > exp:
        raise SeamContractError("assertion_expired", "Assertion is expired or over-long.")
    if nonce in seen_nonces:
        raise SeamContractError("assertion_replay", "Assertion nonce already used.")
    return {"provider": SEAM_PROVIDER, "principal": str(principal), "nonce": str(nonce)}


def validate_event_envelope(e: dict) -> dict:
    """Judge an outbound event under section 3. Every envelope
    carries an idempotency key (exactly-once at the seam), a
    frozen kind, and a privacy verdict: a private repo's event
    must be marked hall-restricted or it does not cross."""
    if not isinstance(e, dict):
        raise SeamContractError("envelope_incomplete", "Envelope must be a mapping.")
    kind = e.get("kind")
    if kind not in EVENT_KINDS:
        raise SeamContractError("event_kind_unknown", "That event kind does not cross the seam.")
    if not e.get("idempotency_key"):
        raise SeamContractError("idempotency_required", "Seam events need an idempotency key.")
    if e.get("repo_private") is True and e.get("hall_restricted") is not True:
        raise SeamContractError("privacy_leak", "A private repo event cannot enter an open hall.")
    return {"kind": kind, "idempotency_key": str(e["idempotency_key"])}


def decide_embed(kind: object, *, viewer_may_view: bool) -> dict:
    """Judge an embed/unfurl under section 2: Samverk decides
    by the viewer's own rights; the embed itself grants none."""
    if kind not in EMBED_KINDS:
        raise SeamContractError("embed_kind_unknown", "That kind does not embed.")
    if not viewer_may_view:
        raise SeamContractError("permission_denied", "The viewer has no Samverk right to this.")
    return {"kind": kind, "render": "card", "decided_by": "samverk"}


def ratification_anchors() -> dict:
    """The landed Samverk modules each frozen section rests on,
    named so a later slice (or auditor) can re-run the review.
    Samtal-side anchors are honestly absent: no Samtal codebase
    stands on this seat, so the Samtal-side review is recorded
    NOT PROVEN in docs/SEAM_CONTRACT.md, never claimed."""
    return {
        "identity_link": ("samverk.identity_linking", "samverk.webhook_signing"),
        "embed": ("samverk.gist_embed", "samverk.api_contract"),
        "event_bridge": ("samverk.webhook_events", "samverk.inbox"),
        "sovereignty": ("samverk.login", "samverk.whole_instance_export"),
    }
