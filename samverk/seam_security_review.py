"""Seam security review (S-379) -- the seam, attacked on purpose.

Part XIX. S-311's adversarial battery attacked the forge's own
scanners and signatures; this review extends the same treatment
to the Samtal seam's three trust surfaces:

- **Token exchange** (S-362 identity linking, S-363 SSO): forged
  signatures, tampered bodies, expired and over-long tokens,
  replay, and cross-purpose confusion (a link assertion at the
  SSO door, an SSO token at the link door) must all be refused
  with the standing reasons, and a refused attack must mint
  nothing -- no link, no session.
- **Link unfurling** (S-370): a private repo must not unfurl for
  a stranger or an anonymous viewer, traversal and foreign link
  shapes must not parse, missing things must say not_found, and
  stored payloads in repo text must render inert.
- **Event posting** (S-367): no delivery without opt-in, none
  while muted, no private-repo event into an open hall, no
  unknown kind, no missing idempotency key, and a replayed key
  delivers exactly once.

Findings FIXED in this slice (bug law):
- F-1 **Attribute breakout in both card renderers.**
  link_unfurl.render_card and hall_events.render_card placed
  link_path (and kind) inside double-quoted attributes escaped
  with escape_html_text, which does not escape quotes. A file
  path carrying %22, or any caller-supplied hall link with a
  quote, broke out of href and could smuggle an event handler
  into Samtal's hall. Both renderers now use escape_html_attr
  for every attribute context (the S-010 seam's own law:
  callers embedding a URL in an attribute pass it through
  escape_html_attr). The battery below proves the breakout is
  closed on both renderers.

Findings NAMED, not fixed (honest register):
- N-1 File unfurl does not verify the file stands: the card is
  a link, Samverk's own blob page decides when followed, and
  the card grants no access. Checking existence would put a
  git read on the conversation path for no access gain.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore
from .audit import AuditLog
from .hall_events import HallEventError, HallEventService
from .hall_events import render_card as render_hall_card
from .identity_linking import IdentityLinkStore
from .issues import IssueStore
from .link_unfurl import LinkUnfurlError, LinkUnfurlService
from .link_unfurl import render_card as render_unfurl_card
from .repositories import RepositoryStore
from .seam_identity import SeamIdentityError, SeamIdentityService, mint_link_token
from .seam_sso import SeamSsoError, SeamSsoService, mint_sso_token
from .sessions import SessionStore

FINDINGS_FIXED = (
    "F-1 attribute breakout in both seam card renderers: href and "
    "data-kind attribute contexts now use escape_html_attr",)
FINDINGS_NAMED = (
    "N-1 file unfurl does not verify the file stands; the card is a "
    "link and Samverk's blob page decides (no access is granted)",)
XSS = "<script>alert(1)</script>"


@dataclass(frozen=True)
class AttackOutcome:
    name: str
    family: str
    expected: str
    observed: str
    held: bool
    detail: str = ""


@dataclass
class ReviewReport:
    outcomes: tuple

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def held_count(self) -> int:
        return sum(1 for o in self.outcomes if o.held)

    @property
    def all_held(self) -> bool:
        return self.held_count == self.total

    def family_counts(self) -> dict:
        counts: dict = {}
        for o in self.outcomes:
            held, total = counts.get(o.family, (0, 0))
            counts[o.family] = (held + (1 if o.held else 0), total + 1)
        return counts

    def summary(self) -> str:
        if self.all_held:
            return f"seam security review: {self.held_count}/{self.total} attacks held"
        fell = ", ".join(o.name for o in self.outcomes if not o.held)
        return (f"seam security review: {self.held_count}/{self.total} "
                f"attacks held; FELL: {fell}")

    def to_dict(self) -> dict:
        return {"total": self.total, "held": self.held_count,
                "all_held": self.all_held,
                "families": {k: {"held": h, "total": t}
                             for k, (h, t) in self.family_counts().items()},
                "findings_fixed": list(FINDINGS_FIXED),
                "findings_named": list(FINDINGS_NAMED),
                "outcomes": [{"name": o.name, "family": o.family,
                              "expected": o.expected, "observed": o.observed,
                              "held": o.held, "detail": o.detail}
                             for o in self.outcomes]}


def _reason_of(exc_types, fn):
    """Run one attack; return its refusal reason, or NO-REFUSAL."""
    try:
        fn()
    except exc_types as exc:
        return getattr(exc, "reason", type(exc).__name__)
    except Exception as exc:  # a crash is an answer too, and not the right one
        return f"CRASH:{type(exc).__name__}"
    return "NO-REFUSAL"


class SeamSecurityReview:
    """Builds the seam's real services over the caller's stores
    and attacks them. Nothing here is a mock: tokens are really
    minted and judged, repos really stand, cards really post."""

    def __init__(self, conn, root: Path, accounts: AccountStore, *,
                 settings: dict | None = None, secret: bytes,
                 audit: AuditLog | None = None, time_fn=None):
        self._conn = conn
        self._root = Path(root)
        self._accounts = accounts
        self._settings = settings
        self._secret = secret
        self._audit = audit
        self._now = time_fn or (lambda: 5000)
        self._links = IdentityLinkStore(conn, accounts, audit=audit,
                                        time_fn=self._now)
        self._sessions = SessionStore(conn, time_fn=self._now)
        self._sso = SeamSsoService(self._links, accounts, self._sessions,
                                   secret=secret, settings=settings,
                                   time_fn=self._now)
        self._identity = SeamIdentityService(self._links, secret=secret,
                                             settings=settings,
                                             time_fn=self._now)
        self._unfurl = LinkUnfurlService(conn, self._root, accounts,
                                         settings=settings, audit=audit,
                                         time_fn=self._now)
        self._hall = HallEventService(conn, settings=settings)

    # -- fixture ------------------------------------------------
    def _fixture(self):
        a = self._accounts
        self._owner = a.register("review-owner", "a long enough passphrase")
        self._stranger = a.register("review-stranger", "a long enough passphrase")
        self._linkme = a.register("review-linkme", "a long enough passphrase")
        repos = RepositoryStore(self._conn, self._root, a)
        repos.create_repository(self._owner.id, "review-owner", "pub",
                                visibility="public", description=XSS)
        repos.create_repository(self._owner.id, "review-owner", "secret",
                                visibility="private", description="hidden")
        issues = IssueStore(self._conn, repos, a, audit=self._audit)
        issues.create_issue(self._owner, "review-owner", "pub", "A real issue")
        self._links.link(self._owner.id, "samtal", "seat-owner")
        self._hall.opt_in(self._owner, "hall-1", "review-owner/pub")

    def _sso_token(self, **over):
        call = dict(principal="seat-owner", now=4950, nonce="atk-1")
        call.update(over)
        return mint_sso_token(self._secret, **call)

    def _judge(self, out, family, name, expected, fn, exc_types):
        observed = _reason_of(exc_types, fn)
        out.append(AttackOutcome(name, family, expected, observed,
                                 observed == expected))

    # -- family 1: token exchange -------------------------------
    def _attack_tokens(self, out):
        fam, J = "token_exchange", self._judge
        J(out, fam, "forged_signature", "signature_invalid",
          lambda: self._sso.exchange(mint_sso_token(
              b"forged-secret-key", principal="seat-owner", now=4950,
              nonce="atk-f1")), SeamSsoError)
        def tampered():
            body_b64, sig = self._sso_token(nonce="atk-f2").split(".")
            claims = json.loads(base64.urlsafe_b64decode(
                body_b64 + "=" * (-len(body_b64) % 4)))
            claims["principal"] = "seat-owner"  # body re-cut, sig kept
            claims["expires_at"] = 999999
            body = json.dumps(claims, sort_keys=True,
                              separators=(",", ":")).encode()
            forged = base64.urlsafe_b64encode(body).rstrip(b"=").decode() + "." + sig
            return self._sso.exchange(forged)
        J(out, fam, "tampered_body", "signature_invalid", tampered, SeamSsoError)
        J(out, fam, "expired_token", "assertion_expired",
          lambda: self._sso.exchange(self._sso_token(now=1000, nonce="atk-f3")),
          SeamSsoError)
        J(out, fam, "overlong_ttl", "assertion_expired",
          lambda: self._sso.exchange(self._sso_token(nonce="atk-f4",
                                                     ttl_seconds=100000)),
          SeamSsoError)
        good = self._sso_token(nonce="atk-replay")
        self._sso.exchange(good)  # the honest first use lands
        J(out, fam, "replayed_token", "assertion_replay",
          lambda: self._sso.exchange(good), SeamSsoError)
        J(out, fam, "link_token_at_sso_door", "claim_mismatch",
          lambda: self._sso.exchange(mint_link_token(
              self._secret, principal="seat-owner", now=4950, nonce="atk-f5")),
          SeamSsoError)
        J(out, fam, "sso_token_at_link_door", "consent_required",
          lambda: self._identity.complete_link(self._linkme.id,
                                               self._sso_token(nonce="atk-f6")),
          SeamIdentityError)
        link_tok = mint_link_token(self._secret, principal="seat-linkme",
                                   now=4950, nonce="atk-link")
        self._identity.complete_link(self._linkme.id, link_tok)
        J(out, fam, "replayed_link_token", "assertion_replay",
          lambda: self._identity.complete_link(self._linkme.id, link_tok),
          SeamIdentityError)
        J(out, fam, "unlinked_principal", "link_required",
          lambda: self._sso.exchange(self._sso_token(principal="seat-ghost",
                                                     nonce="atk-f7")),
          SeamSsoError)
        off = SeamSsoService(self._links, self._accounts, self._sessions,
                             secret=self._secret, settings={},
                             time_fn=self._now)
        J(out, fam, "seam_disabled_exchange", "seam_disabled",
          lambda: off.exchange(self._sso_token(nonce="atk-f8")), SeamSsoError)
        for bad in ("", "x", "a.b.c", 7, None):
            J(out, fam, f"malformed_token_{type(bad).__name__}", "token_invalid",
              lambda b=bad: self._sso.exchange(b), SeamSsoError)

    # -- family 2: link unfurling -------------------------------
    def _attack_unfurl(self, out):
        fam, J = "link_unfurling", self._judge
        U = self._unfurl.unfurl
        J(out, fam, "private_repo_to_stranger", "permission_denied",
          lambda: U(self._stranger, "/review-owner/secret"), LinkUnfurlError)
        J(out, fam, "private_repo_to_anonymous", "permission_denied",
          lambda: U(None, "/review-owner/secret"), LinkUnfurlError)
        J(out, fam, "private_issue_to_stranger", "permission_denied",
          lambda: U(self._stranger, "/review-owner/secret/issues/1"),
          LinkUnfurlError)
        J(out, fam, "traversal_file_link", "link_unknown",
          lambda: U(self._owner, "/review-owner/pub/blob/main/../secret.txt"),
          LinkUnfurlError)
        J(out, fam, "foreign_hostile_link", "link_unknown",
          lambda: U(self._owner, "https://evil.example/phish"), LinkUnfurlError)
        J(out, fam, "script_scheme_link", "link_unknown",
          lambda: U(self._owner, "javascript:alert(1)"), LinkUnfurlError)
        J(out, fam, "missing_repo", "not_found",
          lambda: U(self._owner, "/review-owner/ghost"), LinkUnfurlError)
        J(out, fam, "missing_issue", "not_found",
          lambda: U(self._owner, "/review-owner/pub/issues/99"), LinkUnfurlError)
        # Stored payload in the repo description renders inert.
        card = U(self._stranger, "/review-owner/pub")
        html = render_unfurl_card(card)
        out.append(AttackOutcome(
            "stored_xss_in_description", fam, "no raw <script> in card",
            "inert" if "<script" not in html else "RAW SCRIPT SURVIVED",
            "<script" not in html and "&lt;script&gt;" in html))
        # F-1 proof: a quote in the file path cannot break href.
        qcard = U(self._owner, "/review-owner/pub/blob/main/a%22b.txt")
        qhtml = render_unfurl_card(qcard)
        out.append(AttackOutcome(
            "quote_breakout_in_file_path", fam, "href quote escaped (&quot;)",
            "escaped" if "a&quot;b.txt" in qhtml else "UNESCAPED QUOTE",
            "a&quot;b.txt" in qhtml
            and 'blob/main/a"b.txt"' not in qhtml))

    # -- family 3: event posting --------------------------------
    def _attack_events(self, out):
        fam, J = "event_posting", self._judge
        H = self._hall
        base = dict(kind="push", repo="review-owner/pub", title="3 commits",
                    link_path="/review-owner/pub", actor_name="review-owner")
        J(out, fam, "post_without_opt_in", "not_opted_in",
          lambda: H.post_event("hall-2", idempotency_key="e1", **base),
          HallEventError)
        J(out, fam, "private_event_into_open_hall", "privacy_leak",
          lambda: H.post_event("hall-1", repo_private=True,
                               idempotency_key="e2", **base), HallEventError)
        J(out, fam, "unknown_event_kind", "event_kind_unknown",
          lambda: H.post_event("hall-1", idempotency_key="e3",
                               **{**base, "kind": "teleport"}), HallEventError)
        J(out, fam, "missing_idempotency_key", "idempotency_required",
          lambda: H.post_event("hall-1", idempotency_key="", **base),
          HallEventError)
        J(out, fam, "blank_title", "title_required",
          lambda: H.post_event("hall-1", idempotency_key="e4",
                               **{**base, "title": "  "}), HallEventError)
        first = H.post_event("hall-1", idempotency_key="e-once", **base)
        again = H.post_event("hall-1", idempotency_key="e-once", **base)
        cards = H.cards_for("hall-1")
        out.append(AttackOutcome(
            "replayed_delivery_exactly_once", fam,
            "second post already_delivered, 1 card stands",
            f"already={again.already_delivered}, cards={len(cards)}",
            again.already_delivered and len(cards) == 1 and not first.already_delivered))
        H.mute(self._owner, "hall-1", "review-owner/pub")
        J(out, fam, "post_while_muted", "hall_muted",
          lambda: H.post_event("hall-1", idempotency_key="e5", **base),
          HallEventError)
        H.unmute(self._owner, "hall-1", "review-owner/pub")
        off = HallEventService(self._conn, settings={})
        J(out, fam, "seam_disabled_post", "seam_disabled",
          lambda: off.post_event("hall-1", idempotency_key="e6", **base),
          HallEventError)
        # F-1 proof on the hall renderer: caller-supplied link quote.
        evil = H.post_event("hall-1", idempotency_key="e7",
                            **{**base, "link_path": '/x" onclick="alert(1)'})
        ehtml = render_hall_card(evil)
        out.append(AttackOutcome(
            "quote_breakout_in_hall_link", fam, "href quote escaped (&quot;)",
            "escaped" if "&quot;" in ehtml else "UNESCAPED QUOTE",
            "&quot;" in ehtml and 'onclick="alert' not in ehtml))

    # -- the run --------------------------------------------------
    def run(self) -> ReviewReport:
        self._fixture()
        out: list = []
        self._attack_tokens(out)
        self._attack_unfurl(out)
        self._attack_events(out)
        return ReviewReport(tuple(out))
