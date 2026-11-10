"""Release signing seam (S-263).

A release (S-257) may carry **detached signatures**:
armoured signature text a signer made elsewhere --
with their own OpenPGP or SSH tool, over the release,
over one of its assets (S-259), or over its generated
checksums file (S-260) -- attached to the release and
shown beside it. This slice is the seam S-305's
signed-commit verification will stand on for
releases: it defines where a signature lives, what
it may claim to sign, and the words its trust is
spoken in. The laws:

- **Detached, and made elsewhere.** Samverk never
  signs here and holds no private key: a writer
  attaches signature text that already exists. The
  text must carry the armour of its declared kind --
  an OpenPGP signature between its ``PGP SIGNATURE``
  markers, an SSH signature between its
  ``SSH SIGNATURE`` markers -- judged at the door
  (`signature_invalid`), capped at
  ``SIGNATURE_MAX``, and stored verbatim, so the
  detached file a reader downloads back is the file
  that was attached, byte for byte.
- **A signature names its target.** Every signature
  signs exactly one thing, said in words on every
  face: the **release** itself (its tag and target
  commit), the **checksums file** (S-260's generated
  ``SHA256SUMS.txt``), or one named **asset** (the
  asset must stand on the release at attach time;
  its name is kept on the row, so the claim stays
  readable even if the asset is later deleted).
  The same signer may not attach the same kind of
  signature to the same target twice
  (`signature_taken`) -- a second, different
  signature is a new statement, not an edit.
- **Trust is spoken in S-305's words, never a bare
  tick.** A signature's standing is one of three
  states -- **verified**, **partial**, or
  **unverified** -- and every face carries the word
  and the signer, exactly as commit badges will:
  `TRUST_WORDS` is the vocabulary, and the rendered
  badge is text, never colour alone. The pure
  `decide_signature_trust` is the whole judgement:
  a cryptographic check that passed with the signer
  matched to a known key is verified; a check that
  passed without that match, or a check that only
  partly ran, is partial; anything else -- failed,
  or never checked -- is unverified.
- **Attaching proves nothing, and says so.** No
  cryptographic verifier stands in Samverk yet
  (that is Part XV, S-305), so every attached
  signature stands **unverified**, and the page
  says what that means in plain words: Samverk has
  not checked this signature against a known key;
  attaching it records that the named signer claims
  to have signed the target -- it does not prove
  they did. The seam for the verifier is
  `record_verification`: a machine act with no
  user door, which nothing calls until S-305's
  engine lands, so no person can talk a signature
  into a better word than the check earned.
- **Visibility is the release's own (S-258).**
  Attaching and detaching are writer acts; reading
  follows the release: a draft's signatures are
  private to writers (the uniform
  `release_not_found` for everyone else), a private
  repository's signatures answer the uniform
  `repo_not_found`, and a release that does not
  stand answers `release_not_found`. Permissions
  ride the repository's (S-054), exactly as the
  assets and checksums do.

Signature acts carry no verb of their own in the
frozen taxonomy vocabulary and are not witnessed --
no new taxonomy event: 131 stand (33 auth /
85 repo / 13 admin). Signatures live in migration
104's `release_signatures` row (schema 103 to 104).
Verification of the signatures themselves is S-305;
release packaging (S-400) builds on this seam.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_text
from .permissions import can_write
from .release_assets import ReleaseAssetStore
from .releases import Release, ReleaseError, ReleaseStore
from .repositories import Repository, RepositoryStore

SIGNATURE_MAX = 65536
SIGNER_MAX = 200
FINGERPRINT_MAX = 128

KINDS = ("openpgp", "ssh")
KIND_WORDS = {
    "openpgp": "OpenPGP",
    "ssh": "SSH",
}
_ARMOUR = {
    "openpgp": ("-----BEGIN PGP SIGNATURE-----",
                "-----END PGP SIGNATURE-----"),
    "ssh": ("-----BEGIN SSH SIGNATURE-----",
            "-----END SSH SIGNATURE-----"),
}

TARGET_KINDS = ("release", "checksums", "asset")
TARGET_WORDS = {
    "release": "the release",
    "checksums": "the checksums file",
    "asset": "an asset",
}

TRUST_STATES = ("verified", "partial", "unverified")
TRUST_WORDS = {
    "verified": "Verified",
    "partial": "Partially verified",
    "unverified": "Unverified",
}
CHECK_STATES = ("passed", "partial", "failed", "not_checked")

TRUST_RULE = (
    "Signatures are shown in words, with the signer "
    "named: verified, partially verified, or "
    "unverified -- never a bare tick. A signature "
    "Samverk has not checked against a known key is "
    "unverified: attaching one records who claims to "
    "have signed, it does not prove they did.")

__all__ = [
    "CHECK_STATES", "FINGERPRINT_MAX", "KINDS", "KIND_WORDS",
    "SIGNATURE_MAX", "SIGNER_MAX", "TARGET_KINDS",
    "TARGET_WORDS", "TRUST_RULE", "TRUST_STATES",
    "TRUST_WORDS", "ReleaseSignature",
    "ReleaseSignatureError", "ReleaseSignatureStore",
    "decide_signature_trust", "render_signature",
    "render_signatures_section", "signature_target_words",
    "signature_to_dict", "signature_trust",
    "trust_words", "validate_fingerprint",
    "validate_kind", "validate_signature_text",
    "validate_signer", "validate_target_kind",
]


class ReleaseSignatureError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class ReleaseSignature:
    id: int
    release_id: int
    repo_id: int
    target_kind: str
    asset_id: int | None
    asset_name: str
    signer: str
    kind: str
    fingerprint: str
    signature: str
    trust: str
    verified_signer: str
    attached_by: int
    created_at: int


def _row_to_signature(row: sqlite3.Row) -> ReleaseSignature:
    return ReleaseSignature(
        id=row["id"], release_id=row["release_id"],
        repo_id=row["repo_id"], target_kind=row["target_kind"],
        asset_id=row["asset_id"], asset_name=row["asset_name"],
        signer=row["signer"], kind=row["kind"],
        fingerprint=row["fingerprint"],
        signature=row["signature"], trust=row["trust"],
        verified_signer=row["verified_signer"],
        attached_by=row["attached_by"],
        created_at=row["created_at"])


def validate_signer(signer: object) -> str:
    if not isinstance(signer, str) or not signer.strip():
        raise ReleaseSignatureError(
            "signer_required",
            "A signature names who claims to have signed.")
    text = signer.strip()
    if len(text) > SIGNER_MAX or any(
            ord(c) < 0x20 or ord(c) == 0x7F for c in text):
        raise ReleaseSignatureError(
            "signer_invalid",
            f"A signer name is at most {SIGNER_MAX} characters "
            "of plain text.")
    return text


def validate_kind(kind: object) -> str:
    if kind not in KINDS:
        raise ReleaseSignatureError(
            "signature_kind_invalid",
            "A detached signature is OpenPGP or SSH.")
    return str(kind)


def validate_target_kind(target_kind: object) -> str:
    if target_kind not in TARGET_KINDS:
        raise ReleaseSignatureError(
            "signature_target_invalid",
            "A signature signs the release, its checksums "
            "file, or one of its assets.")
    return str(target_kind)


def validate_signature_text(text: object, kind: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise ReleaseSignatureError(
            "signature_required",
            "A detached signature is armoured text.")
    body = text.strip()
    if len(body) > SIGNATURE_MAX:
        raise ReleaseSignatureError(
            "signature_too_large",
            f"A detached signature is at most {SIGNATURE_MAX} "
            "characters of armoured text.")
    begin, end = _ARMOUR[kind]
    if begin not in body or end not in body:
        raise ReleaseSignatureError(
            "signature_invalid",
            f"Not an armoured {KIND_WORDS[kind]} detached "
            "signature: its begin and end markers must stand "
            "in the text.")
    return body


def validate_fingerprint(fingerprint: object) -> str:
    if fingerprint is None:
        return ""
    if not isinstance(fingerprint, str):
        raise ReleaseSignatureError(
            "fingerprint_invalid",
            "A fingerprint is plain text.")
    text = fingerprint.strip()
    if len(text) > FINGERPRINT_MAX or any(
            ord(c) < 0x20 or ord(c) == 0x7F for c in text):
        raise ReleaseSignatureError(
            "fingerprint_invalid",
            f"A fingerprint is at most {FINGERPRINT_MAX} "
            "characters of plain text.")
    return text


def decide_signature_trust(check: object,
                           signer_known: object) -> str:
    """The whole trust judgement, pure (S-305's seam):
    a cryptographic check that passed with the signer
    matched to a known key is `verified`; a passed
    check without that match, or a check that only
    partly ran, is `partial`; a failed check, or one
    that never ran, is `unverified`. An unknown check
    state is refused, never guessed."""
    if check not in CHECK_STATES or not isinstance(
            signer_known, bool):
        raise ReleaseSignatureError(
            "check_invalid",
            "A verification states its check -- passed, "
            "partial, failed, or not checked -- and whether "
            "the signer matched a known key.")
    if check == "passed":
        return "verified" if signer_known else "partial"
    if check == "partial":
        return "partial"
    return "unverified"


def signature_trust(signature: ReleaseSignature) -> str:
    """One signature's standing, in the vocabulary:
    a stored state outside it reads as unverified --
    the honest default, never a better word."""
    if signature.trust in TRUST_STATES:
        return signature.trust
    return "unverified"


def trust_words(state: object) -> str:
    if state not in TRUST_STATES:
        return TRUST_WORDS["unverified"]
    return TRUST_WORDS[str(state)]


def signature_target_words(signature: ReleaseSignature,
                           tag: str = "") -> str:
    """What this signature claims to sign, in words."""
    if signature.target_kind == "asset":
        return f"asset {signature.asset_name}"
    if signature.target_kind == "checksums":
        return "the checksums file SHA256SUMS.txt"
    return f"the release {tag}".rstrip()


def signature_to_dict(signature: ReleaseSignature,
                      full_name: str = "",
                      tag: str = "") -> dict:
    """One attached signature as the API answers it:
    the claim, its target, and its trust in words."""
    trust = signature_trust(signature)
    return {
        "repository": full_name,
        "tag": tag,
        "id": signature.id,
        "target_kind": signature.target_kind,
        "target": signature_target_words(signature, tag),
        "asset_name": signature.asset_name,
        "signer": signature.signer,
        "kind": signature.kind,
        "kind_words": KIND_WORDS[signature.kind],
        "fingerprint": signature.fingerprint,
        "signature": signature.signature,
        "trust": trust,
        "trust_words": trust_words(trust),
        "verified_signer": signature.verified_signer,
        "attached_by": signature.attached_by,
        "created_at": signature.created_at,
    }


def _trust_sentence(signature: ReleaseSignature,
                    tag: str) -> str:
    trust = signature_trust(signature)
    target = signature_target_words(signature, tag)
    if trust == "verified":
        signer = signature.verified_signer or signature.signer
        return (
            "Samverk has checked this signature against a "
            f"known key for {signer}, and it proves "
            f"{signer} signed {target}.")
    if trust == "partial":
        return (
            "Samverk has checked this signature only in "
            f"part: the signer is not fully matched to a "
            f"known key, so it does not yet prove "
            f"{signature.signer} signed {target}.")
    return (
        "Samverk has not checked this signature against "
        f"a known key. It records that {signature.signer} "
        f"claims to have signed {target}; it does not "
        "prove they did.")


def render_signature(signature: ReleaseSignature,
                     full_name: str = "",
                     tag: str = "") -> str:
    """One attached signature as HTML: the signer, the
    kind, the target, and the trust badge in words
    (never a bare tick, never colour alone), all
    fields escaped through S-010."""
    trust = signature_trust(signature)
    fingerprint = (
        " &middot; fingerprint "
        + escape_html_text(signature.fingerprint)
        if signature.fingerprint else "")
    return (
        '<article class="release-signature"><p>'
        + '<span class="signature-signer">'
        + escape_html_text(signature.signer) + "</span>"
        + " &middot; "
        + escape_html_text(KIND_WORDS[signature.kind])
        + " signature &middot; signed "
        + escape_html_text(
            signature_target_words(signature, tag))
        + fingerprint
        + ' &middot; <span class="signature-trust '
        + "signature-trust-" + escape_html_text(trust)
        + '">' + escape_html_text(trust_words(trust))
        + "</span></p><p>"
        + escape_html_text(_trust_sentence(signature, tag))
        + "</p></article>")


def render_signatures_section(
        full_name: str, tag: str,
        signatures: list[ReleaseSignature]) -> str:
    """The signatures section of a release page: the
    trust rule stated in words, then every attached
    signature with its badge, or the honest empty
    state."""
    if signatures:
        body = "".join(
            render_signature(s, full_name, tag)
            for s in signatures)
    else:
        body = ("<p>No signatures are attached to this "
                "release yet.</p>")
    return (
        '<section class="release-signatures">'
        "<h4>Signatures</h4><p>"
        + escape_html_text(TRUST_RULE) + "</p>"
        + body + "</section>")


class ReleaseSignatureStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        releases: ReleaseStore,
        assets: ReleaseAssetStore,
        accounts: AccountStore | None = None,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._releases = releases
        self._assets = assets
        self._accounts = accounts
        self._audit = audit
        self._now = time_fn

    # -- gates ------------------------------------------------
    def _release_for_read(self, viewer: User | None,
                          owner: object, repo: object,
                          tag: object) -> Release:
        try:
            return self._releases.get_release(
                viewer, owner, repo, tag)
        except ReleaseError as exc:
            raise ReleaseSignatureError(
                exc.reason, str(exc)) from None

    def _release_for_write(self, actor: User, owner: object,
                           repo: object,
                           tag: object) -> Release:
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise ReleaseSignatureError(
                "repo_not_found", "No such repository.")
        release = self._release_for_read(actor, owner, repo, tag)
        if not can_write(actor, current):
            raise ReleaseSignatureError(
                "permission_denied",
                "Only a repository writer can manage release "
                "signatures.")
        return release

    def _by_id(self, signature_id: object,
               release_id: int) -> ReleaseSignature:
        if isinstance(signature_id, bool) or not isinstance(
                signature_id, int):
            raise ReleaseSignatureError(
                "signature_not_found", "No such signature.")
        row = self._conn.execute(
            "SELECT * FROM release_signatures WHERE id = ? "
            "AND release_id = ?", (signature_id, release_id),
        ).fetchone()
        if row is None:
            raise ReleaseSignatureError(
                "signature_not_found", "No such signature.")
        return _row_to_signature(row)

    # -- acts -------------------------------------------------
    def attach_signature(
            self, actor: User, owner: object, repo: object,
            tag: object, *, target_kind: object = "release",
            asset_name: object = None,
            signer: object = None, kind: object = None,
            signature: object = None,
            fingerprint: object = "") -> ReleaseSignature:
        """Attach a detached signature to a release:
        writer only, the target named and standing,
        the armour of its kind, stored verbatim and
        standing unverified until a verifier (S-305)
        checks it."""
        release = self._release_for_write(actor, owner, repo, tag)
        target = validate_target_kind(target_kind)
        signer_text = validate_signer(signer)
        kind_text = validate_kind(kind)
        body = validate_signature_text(signature, kind_text)
        fingerprint_text = validate_fingerprint(fingerprint)
        asset_id: int | None = None
        asset_label = ""
        if target == "asset":
            if not isinstance(asset_name, str) or not (
                    asset_name.strip()):
                raise ReleaseSignatureError(
                    "asset_not_found",
                    "An asset signature names its asset.")
            try:
                standing = self._assets.list_assets(
                    actor, owner, repo, tag)
            except Exception as exc:
                reason = getattr(exc, "reason", None)
                if reason is None:
                    raise
                raise ReleaseSignatureError(
                    reason, str(exc)) from None
            match = next(
                (a for a in standing
                 if a.name == asset_name.strip()), None)
            if match is None:
                raise ReleaseSignatureError(
                    "asset_not_found",
                    f"No asset named {asset_name.strip()!r} "
                    "stands on this release.")
            asset_id = match.id
            asset_label = match.name
        now = int(self._now())
        try:
            with self._conn:
                cur = self._conn.execute(
                    "INSERT INTO release_signatures "
                    "(release_id, repo_id, target_kind, "
                    "asset_id, asset_name, signer, kind, "
                    "fingerprint, signature, trust, "
                    "verified_signer, attached_by, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, "
                    "'unverified', '', ?, ?)",
                    (release.id, release.repo_id, target,
                     asset_id, asset_label, signer_text,
                     kind_text, fingerprint_text, body,
                     actor.id, now))
        except sqlite3.IntegrityError:
            raise ReleaseSignatureError(
                "signature_taken",
                f"{signer_text} has already attached a "
                f"{KIND_WORDS[kind_text]} signature to this "
                "target on this release.") from None
        return self._by_id(int(cur.lastrowid), release.id)

    def detach_signature(self, actor: User, owner: object,
                         repo: object, tag: object,
                         signature_id: object
                         ) -> ReleaseSignature:
        """Remove one attached signature: writer only.
        The removed row is returned, as deletions in
        this family answer the thing removed."""
        release = self._release_for_write(actor, owner, repo, tag)
        found = self._by_id(signature_id, release.id)
        with self._conn:
            self._conn.execute(
                "DELETE FROM release_signatures WHERE id = ?",
                (found.id,))
        return found

    def get_signature(self, viewer: User | None, owner: object,
                      repo: object, tag: object,
                      signature_id: object) -> ReleaseSignature:
        release = self._release_for_read(viewer, owner, repo, tag)
        return self._by_id(signature_id, release.id)

    def list_signatures(self, viewer: User | None,
                        owner: object, repo: object,
                        tag: object) -> list[ReleaseSignature]:
        """Every signature attached to this release, in
        attach order, under the release's own
        visibility."""
        release = self._release_for_read(viewer, owner, repo, tag)
        rows = self._conn.execute(
            "SELECT * FROM release_signatures "
            "WHERE release_id = ? ORDER BY created_at ASC, "
            "id ASC", (release.id,)).fetchall()
        return [_row_to_signature(r) for r in rows]

    def record_verification(
            self, owner: object, repo: object, tag: object,
            signature_id: object, *, check: object,
            signer_known: object,
            verified_signer: object = "") -> ReleaseSignature:
        """The verifier's seam (S-305): record what a
        cryptographic check earned. This is a machine
        act with no user door -- nothing calls it until
        the Part XV verifier lands, so until then every
        attached signature honestly stands unverified.
        The trust written is `decide_signature_trust`'s
        word alone; a caller cannot name a better one."""
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise ReleaseSignatureError(
                "repo_not_found", "No such repository.")
        row = self._conn.execute(
            "SELECT id FROM releases WHERE repo_id = ? "
            "AND tag = ?", (current.id, tag)).fetchone() \
            if isinstance(tag, str) else None
        if row is None:
            raise ReleaseSignatureError(
                "release_not_found", "No such release.")
        found = self._by_id(signature_id, int(row["id"]))
        trust = decide_signature_trust(check, signer_known)
        signer_text = found.signer
        if verified_signer:
            signer_text = validate_signer(verified_signer)
        with self._conn:
            self._conn.execute(
                "UPDATE release_signatures SET trust = ?, "
                "verified_signer = ? WHERE id = ?",
                (trust,
                 signer_text if trust == "verified" else "",
                 found.id))
        return self._by_id(found.id, found.release_id)
