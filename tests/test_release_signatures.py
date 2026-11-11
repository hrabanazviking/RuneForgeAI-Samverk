"""S-263 acceptance battery: release signing seam.

Acceptance (roadmap S-263): Release signing seam --
detached signatures may be attached to a release and
shown with the same honest trust language as commit
badges (S-305).

The centre is samverk/release_signatures.py:
ReleaseSignatureStore over migration 104's
release_signatures rows. A writer attaches armoured
detached signature text (OpenPGP or SSH) naming its
target -- the release, its generated checksums file,
or one standing asset -- and its claimed signer.
Every signature stands unverified until a verifier
checks it: the trust vocabulary is S-305's own
(verified / partial / unverified, the signer always
named, never a bare tick), the pure
decide_signature_trust is the whole judgement, and
record_verification is the machine seam nothing
user-facing calls. Reads ride the release's own
visibility (S-258). No new taxonomy event -- 131
stand (schema 103 to 104).

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.release_assets import ReleaseAssetStore
from samverk.release_signatures import (
    SIGNATURE_MAX, TRUST_RULE, ReleaseSignature,
    ReleaseSignatureError, ReleaseSignatureStore,
    decide_signature_trust, render_signature,
    render_signatures_section, signature_to_dict,
    signature_trust, trust_words)
from samverk.releases import ReleaseStore
from samverk.repositories import RepositoryStore
from test_repo_home import run_git

PW = "correct horse battery"
T0 = 1_700_000_000
PGP = ("-----BEGIN PGP SIGNATURE-----\n\n"
       "iQEzBAABCgAdFiEEdeadbeef\n=abcd\n"
       "-----END PGP SIGNATURE-----\n")
SSH = ("-----BEGIN SSH SIGNATURE-----\n"
       "U1NIU0lHAAAAAQAAADMAAAALc3NoLWVkMjU1MTk=\n"
       "-----END SSH SIGNATURE-----\n")
TEXT_A = b"anvil release notes\nsecond line\n"


class Clock:
    def __init__(self, now=T0):
        self.now = now
    def __call__(self):
        return self.now


class ReleaseSignatureTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.clock = Clock()
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(
            self.conn, audit=self.audit, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", PW)
        self.reader = self.accounts.register("yrsa", PW)
        self.stranger = self.accounts.register("mallory", PW)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.releases = ReleaseStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.assets = ReleaseAssetStore(
            self.conn, self.repos, self.releases, self.root,
            self.accounts, audit=self.audit, time_fn=self.clock)
        self.signatures = ReleaseSignatureStore(
            self.conn, self.repos, self.releases, self.assets,
            self.accounts, audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        self.bare = self.repos.path_for("volmarr", "pub")
        self.work = self.root / "work"; self.work.mkdir()
        run_git(self.work, "init", "-b", "main")
        self._write("app.py", "print('hi')\n")
        self._commit("first")
        run_git(self.work, "tag", "v1.0")
        run_git(self.work, "push", str(self.bare), "v1.0")
        run_git(self.work, "tag", "v1.1")
        run_git(self.work, "push", str(self.bare), "v1.1")
        self.releases.create_release(
            self.owner, "volmarr", "pub", "v1.0", "Anvil 1.0")
        self.releases.create_release(
            self.owner, "volmarr", "pub", "v1.1", "Anvil 1.1",
            draft=True)
        bare_priv = self.repos.path_for("volmarr", "priv")
        run_git(self.work, "push", str(bare_priv), "v1.0")
        self.releases.create_release(
            self.owner, "volmarr", "priv", "v1.0", "Secret 1.0")

    def _write(self, rel, text):
        p = self.work / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def _commit(self, msg):
        run_git(self.work, "add", "-A")
        run_git(self.work, "commit", "-m", msg)
        run_git(self.work, "push", str(self.bare), "main")
        return run_git(self.work, "rev-parse", "HEAD")

    def _reason(self, fn, *a, **k):
        with self.assertRaises(ReleaseSignatureError) as ctx:
            fn(*a, **k)
        return ctx.exception.reason

    def _attach(self, **over):
        call = dict(target_kind="release", signer="Volmarr Wyrd",
                    kind="openpgp", signature=PGP)
        call.update(over)
        return self.signatures.attach_signature(
            self.owner, "volmarr", "pub", "v1.0", **call)

    def _upload_asset(self):
        session = self.assets.begin_upload(
            self.owner, "volmarr", "pub", "v1.0", "anvil.txt")
        self.assets.upload_chunk(self.owner, session.id, 0, TEXT_A)
        return self.assets.complete_upload(self.owner, session.id)

    # -- pins ------------------------------------------
    def test_pins_schema_104_taxonomy_133(self):
        self.assertEqual(schema_version(self.conn), 111)
        self.assertEqual(db.MIGRATIONS[-1][0], 111)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 133)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 87)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)

    # -- attach -----------------------------------------
    def test_attach_release_signature_stands_unverified(self):
        sig = self._attach(fingerprint="ABCD 1234")
        self.assertEqual(sig.target_kind, "release")
        self.assertEqual(sig.signer, "Volmarr Wyrd")
        self.assertEqual(sig.kind, "openpgp")
        self.assertEqual(sig.fingerprint, "ABCD 1234")
        self.assertEqual(sig.signature, PGP.strip())
        self.assertEqual(sig.trust, "unverified")
        self.assertEqual(signature_trust(sig), "unverified")
        self.assertEqual(sig.attached_by, self.owner.id)

    def test_attach_checksums_and_asset_targets(self):
        asset = self._upload_asset()
        by_asset = self._attach(
            target_kind="asset", asset_name="anvil.txt",
            kind="ssh", signature=SSH)
        self.assertEqual(by_asset.asset_id, asset.id)
        self.assertEqual(by_asset.asset_name, "anvil.txt")
        by_sums = self._attach(target_kind="checksums")
        self.assertEqual(by_sums.target_kind, "checksums")
        listed = self.signatures.list_signatures(
            None, "volmarr", "pub", "v1.0")
        self.assertEqual([s.id for s in listed],
                         [by_asset.id, by_sums.id])

    def test_asset_target_must_stand_on_the_release(self):
        self.assertEqual(
            self._reason(self._attach, target_kind="asset",
                         asset_name="ghost.bin"),
            "asset_not_found")
        self.assertEqual(
            self.signatures.list_signatures(
                None, "volmarr", "pub", "v1.0"), [])

    def test_duplicate_signature_refused_by_name(self):
        self._attach()
        self.assertEqual(self._reason(self._attach),
                         "signature_taken")
        other = self._attach(kind="ssh", signature=SSH)
        self.assertEqual(other.kind, "ssh")

    def test_armour_must_match_the_declared_kind(self):
        self.assertEqual(
            self._reason(self._attach, kind="ssh", signature=PGP),
            "signature_invalid")
        self.assertEqual(
            self._reason(self._attach, signature="plain text"),
            "signature_invalid")
        self.assertEqual(
            self._reason(self._attach, signature="   "),
            "signature_required")

    def test_validation_refusals_store_nothing(self):
        self.assertEqual(self._reason(self._attach, signer=" "),
                         "signer_required")
        self.assertEqual(
            self._reason(self._attach, signer="x" * 201),
            "signer_invalid")
        self.assertEqual(self._reason(self._attach, kind="x509"),
                         "signature_kind_invalid")
        self.assertEqual(
            self._reason(self._attach, target_kind="tag"),
            "signature_target_invalid")
        big = PGP.replace("deadbeef", "a" * SIGNATURE_MAX)
        self.assertEqual(self._reason(self._attach, signature=big),
                         "signature_too_large")
        self.assertEqual(
            self._reason(self._attach, fingerprint="x" * 129),
            "fingerprint_invalid")
        self.assertEqual(
            self.signatures.list_signatures(
                None, "volmarr", "pub", "v1.0"), [])

    # -- permissions and visibility ----------------------
    def test_attach_and_detach_are_writer_acts(self):
        sig = self._attach()
        self.assertEqual(
            self._reason(self.signatures.attach_signature,
                         self.reader, "volmarr", "pub", "v1.0",
                         signer="Yrsa", kind="ssh", signature=SSH),
            "permission_denied")
        self.assertEqual(
            self._reason(self.signatures.detach_signature,
                         self.reader, "volmarr", "pub", "v1.0",
                         sig.id),
            "permission_denied")

    def test_private_repo_and_missing_release_are_uniform(self):
        self.assertEqual(
            self._reason(self.signatures.list_signatures,
                         self.stranger, "volmarr", "priv", "v1.0"),
            "repo_not_found")
        self.assertEqual(
            self._reason(self.signatures.list_signatures,
                         None, "volmarr", "pub", "v9.9"),
            "release_not_found")

    def test_draft_signatures_are_private_to_writers(self):
        sig = self.signatures.attach_signature(
            self.owner, "volmarr", "pub", "v1.1",
            signer="Volmarr Wyrd", kind="openpgp", signature=PGP)
        self.assertEqual(
            self._reason(self.signatures.list_signatures,
                         self.reader, "volmarr", "pub", "v1.1"),
            "release_not_found")
        listed = self.signatures.list_signatures(
            self.owner, "volmarr", "pub", "v1.1")
        self.assertEqual([s.id for s in listed], [sig.id])

    # -- detach and get ----------------------------------
    def test_detach_returns_the_removed_signature(self):
        sig = self._attach()
        removed = self.signatures.detach_signature(
            self.owner, "volmarr", "pub", "v1.0", sig.id)
        self.assertEqual(removed.id, sig.id)
        self.assertEqual(
            self.signatures.list_signatures(
                None, "volmarr", "pub", "v1.0"), [])
        self.assertEqual(
            self._reason(self.signatures.detach_signature,
                         self.owner, "volmarr", "pub", "v1.0",
                         sig.id),
            "signature_not_found")

    def test_get_signature_is_scoped_to_its_release(self):
        sig = self._attach()
        got = self.signatures.get_signature(
            None, "volmarr", "pub", "v1.0", sig.id)
        self.assertEqual(got, sig)
        self.assertEqual(
            self._reason(self.signatures.get_signature,
                         self.owner, "volmarr", "pub", "v1.1",
                         sig.id),
            "signature_not_found")

    # -- trust language ----------------------------------
    def test_decide_signature_trust_is_the_whole_judgement(self):
        self.assertEqual(
            decide_signature_trust("passed", True), "verified")
        self.assertEqual(
            decide_signature_trust("passed", False), "partial")
        self.assertEqual(
            decide_signature_trust("partial", True), "partial")
        self.assertEqual(
            decide_signature_trust("failed", True), "unverified")
        self.assertEqual(
            decide_signature_trust("not_checked", False),
            "unverified")
        self.assertEqual(
            self._reason(decide_signature_trust, "waved", True),
            "check_invalid")
        self.assertEqual(trust_words("partial"),
                         "Partially verified")
        self.assertEqual(trust_words("nonsense"), "Unverified")

    def test_record_verification_writes_only_the_earned_word(self):
        sig = self._attach()
        partial = self.signatures.record_verification(
            "volmarr", "pub", "v1.0", sig.id,
            check="passed", signer_known=False)
        self.assertEqual(partial.trust, "partial")
        verified = self.signatures.record_verification(
            "volmarr", "pub", "v1.0", sig.id,
            check="passed", signer_known=True,
            verified_signer="Volmarr Wyrd")
        self.assertEqual(verified.trust, "verified")
        self.assertEqual(verified.verified_signer, "Volmarr Wyrd")
        fallen = self.signatures.record_verification(
            "volmarr", "pub", "v1.0", sig.id,
            check="failed", signer_known=True)
        self.assertEqual(fallen.trust, "unverified")
        self.assertEqual(fallen.verified_signer, "")

    def test_unverified_rendering_says_what_it_means(self):
        sig = self._attach()
        html = render_signature(sig, "volmarr/pub", "v1.0")
        self.assertIn("Unverified", html)
        self.assertIn("Volmarr Wyrd", html)
        self.assertIn("OpenPGP", html)
        self.assertIn("has not checked this signature", html)
        self.assertIn("does not prove they did", html)
        section = render_signatures_section(
            "volmarr/pub", "v1.0", [sig])
        self.assertIn(TRUST_RULE, section)
        empty = render_signatures_section("volmarr/pub", "v1.0", [])
        self.assertIn("No signatures are attached", empty)

    def test_verified_rendering_names_the_verified_signer(self):
        sig = self._attach()
        verified = self.signatures.record_verification(
            "volmarr", "pub", "v1.0", sig.id,
            check="passed", signer_known=True)
        html = render_signature(verified, "volmarr/pub", "v1.0")
        self.assertIn("Verified", html)
        self.assertIn("known key for Volmarr Wyrd", html)

    def test_rendering_escapes_the_signer(self):
        sig = self._attach(signer="<script>x</script>")
        html = render_signature(sig, "volmarr/pub", "v1.0")
        self.assertNotIn("<script>x</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_signature_to_dict_carries_trust_in_words(self):
        self._upload_asset()
        sig = self._attach(target_kind="asset",
                           asset_name="anvil.txt")
        shape = signature_to_dict(sig, "volmarr/pub", "v1.0")
        self.assertEqual(shape["target"], "asset anvil.txt")
        self.assertEqual(shape["target_kind"], "asset")
        self.assertEqual(shape["kind_words"], "OpenPGP")
        self.assertEqual(shape["trust"], "unverified")
        self.assertEqual(shape["trust_words"], "Unverified")
        self.assertEqual(shape["signature"], PGP.strip())
        self.assertEqual(shape["repository"], "volmarr/pub")
        self.assertEqual(shape["tag"], "v1.0")


if __name__ == "__main__":
    unittest.main()
