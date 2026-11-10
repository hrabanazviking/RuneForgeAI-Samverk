"""S-260 acceptance battery: release checksums.

Acceptance (roadmap S-260): Checksums — a generated
checksums file per release (sha256), downloadable
beside the assets; verification instructions on
the page.

The centre is samverk/release_checksums.py:
ReleaseChecksumStore over S-259's asset rows. The
file (SHA256SUMS.txt) is generated fresh on every
read by the pure build_checksums_text — one
'<sha256>  <name>' line per asset in name order,
the digest S-259 stored at promotion — so it can
never drift from the assets, needs no migration
(schema 102 stands), and is itself never an asset.
Downloads ride the release's visibility (S-258)
through S-259's listing gate and count nothing.
Verification is stated on the rendered section
(sha256sum -c / shasum -a 256 -c) and checkable in
code through parse_checksums / verify_checksums.
No new taxonomy event — 131 stand.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import hashlib, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.release_assets import ReleaseAssetStore
from samverk.release_checksums import (
    CHECKSUMS_CONTENT_TYPE, CHECKSUMS_FILENAME,
    VERIFY_COMMAND_MACOS, VERIFY_COMMAND_POSIX,
    ReleaseChecksumError, ReleaseChecksumStore,
    build_checksums_text, checksums_bytes, checksums_to_dict,
    parse_checksums, render_checksums_section, verify_checksums)
from samverk.releases import ReleaseStore
from samverk.repositories import RepositoryStore
from test_repo_home import run_git

PW = "correct horse battery"
T0 = 1_700_000_000
TEXT_A = b"anvil release notes\nsecond line\n"
TEXT_B = b"manual body, plain and true\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40


class Clock:
    def __init__(self, now=T0):
        self.now = now
    def __call__(self):
        return self.now


def _sha(data):
    return hashlib.sha256(data).hexdigest()


class ReleaseChecksumTests(unittest.TestCase):
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
        self.checksums = ReleaseChecksumStore(
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
        self._write("app.py", "print('ho')\n")
        self._commit("second")
        run_git(self.work, "tag", "v1.1")
        run_git(self.work, "push", str(self.bare), "v1.1")
        self.releases.create_release(
            self.owner, "volmarr", "pub", "v1.0", "Anvil 1.0")
        self.releases.create_release(
            self.owner, "volmarr", "pub", "v1.1", "Anvil 1.1",
            draft=True)

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
        with self.assertRaises(ReleaseChecksumError) as ctx:
            fn(*a, **k)
        return ctx.exception.reason

    def _upload(self, data, name, tag="v1.0"):
        session = self.assets.begin_upload(
            self.owner, "volmarr", "pub", tag, name)
        for idx in range(0, max(len(data), 1), 8):
            chunk = data[idx:idx + 8]
            if chunk:
                self.assets.upload_chunk(
                    self.owner, session.id, idx // 8, chunk)
        return self.assets.complete_upload(self.owner, session.id)

    def _two_assets(self):
        b = self._upload(TEXT_B, "manual.txt")
        a = self._upload(TEXT_A, "anvil.txt")
        return a, b

    # -- pins ------------------------------------------
    def test_pins_schema_102_taxonomy_131_no_new_tables(self):
        self.assertEqual(schema_version(self.conn), 103)
        self.assertEqual(db.MIGRATIONS[-1][0], 103)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 131)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 85)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        self.assertEqual(CHECKSUMS_FILENAME, "SHA256SUMS.txt")

    # -- generation --------------------------------------
    def test_generated_lines_are_sha256sum_format_in_name_order(self):
        self._two_assets()
        gen = self.checksums.get_checksums(None, "volmarr", "pub", "v1.0")
        self.assertEqual(
            gen.text,
            f"{_sha(TEXT_A)}  anvil.txt\n{_sha(TEXT_B)}  manual.txt\n")
        self.assertEqual(gen.filename, CHECKSUMS_FILENAME)
        self.assertEqual(gen.content_type, CHECKSUMS_CONTENT_TYPE)
        self.assertEqual(gen.asset_count, 2)
        self.assertEqual([e.name for e in gen.entries],
                         ["anvil.txt", "manual.txt"])
        self.assertEqual(gen.release.tag, "v1.0")

    def test_digests_match_the_asset_bytes_exactly(self):
        asset = self._upload(PNG, "plate.png")
        gen = self.checksums.get_checksums(None, "volmarr", "pub", "v1.0")
        self.assertEqual(gen.entries[0].sha256, _sha(PNG))
        self.assertEqual(gen.entries[0].sha256, asset.sha256)

    def test_empty_release_has_empty_downloadable_file(self):
        gen = self.checksums.get_checksums(None, "volmarr", "pub", "v1.0")
        self.assertEqual((gen.text, gen.size, gen.asset_count), ("", 0, 0))
        dl = self.checksums.download_checksums(None, "volmarr", "pub", "v1.0")
        self.assertEqual(dl.read_all(), b"")
        self.assertEqual(dl.sha256, _sha(b""))

    def test_generation_is_deterministic(self):
        self._two_assets()
        first = self.checksums.get_checksums(None, "volmarr", "pub", "v1.0")
        second = self.checksums.get_checksums(None, "volmarr", "pub", "v1.0")
        self.assertEqual(first.data, second.data)
        assets = self.assets.list_assets(None, "volmarr", "pub", "v1.0")
        self.assertEqual(build_checksums_text(list(reversed(assets))),
                         first.text)
        self.assertEqual(checksums_bytes(assets), first.data)

    def test_file_regenerates_when_assets_change(self):
        self._upload(TEXT_A, "anvil.txt")
        before = self.checksums.get_checksums(None, "volmarr", "pub", "v1.0")
        self._upload(TEXT_B, "manual.txt")
        after = self.checksums.get_checksums(None, "volmarr", "pub", "v1.0")
        self.assertEqual(after.asset_count, before.asset_count + 1)
        self.assertNotEqual(after.sha256, before.sha256)
        self.assets.delete_asset(self.owner, "volmarr", "pub", "v1.0",
                                 "manual.txt")
        again = self.checksums.get_checksums(None, "volmarr", "pub", "v1.0")
        self.assertEqual(again.data, before.data)

    def test_checksums_file_is_not_itself_an_asset(self):
        self._two_assets()
        names = [a.name for a in
                 self.assets.list_assets(None, "volmarr", "pub", "v1.0")]
        self.assertNotIn(CHECKSUMS_FILENAME, names)
        gen = self.checksums.get_checksums(None, "volmarr", "pub", "v1.0")
        self.assertNotIn(CHECKSUMS_FILENAME,
                         [e.name for e in gen.entries])

    def test_uploaded_asset_sharing_the_name_is_ordinary(self):
        self._upload(TEXT_A, CHECKSUMS_FILENAME)
        gen = self.checksums.get_checksums(None, "volmarr", "pub", "v1.0")
        self.assertEqual([e.name for e in gen.entries],
                         [CHECKSUMS_FILENAME])
        self.assertEqual(gen.entries[0].sha256, _sha(TEXT_A))

    # -- download ----------------------------------------
    def test_download_shape_and_own_digest(self):
        self._two_assets()
        dl = self.checksums.download_checksums(None, "volmarr", "pub", "v1.0")
        self.assertEqual(dl.filename, CHECKSUMS_FILENAME)
        self.assertEqual(dl.content_type, CHECKSUMS_CONTENT_TYPE)
        self.assertEqual(dl.size, len(dl.read_all()))
        self.assertEqual(dl.sha256, _sha(dl.read_all()))
        self.assertEqual(dl.asset_count, 2)
        self.assertEqual(b"".join(dl), dl.read_all())

    def test_download_counts_nothing(self):
        self._two_assets()
        audit_before = self.conn.execute(
            "SELECT COUNT(*) c FROM audit_log").fetchone()["c"]
        self.checksums.download_checksums(None, "volmarr", "pub", "v1.0")
        self.checksums.get_checksums(None, "volmarr", "pub", "v1.0")
        counts = [a.download_count for a in
                  self.assets.list_assets(None, "volmarr", "pub", "v1.0")]
        self.assertEqual(counts, [0, 0])
        audit_after = self.conn.execute(
            "SELECT COUNT(*) c FROM audit_log").fetchone()["c"]
        self.assertEqual(audit_after, audit_before)

    def test_dict_shape(self):
        self._two_assets()
        gen = self.checksums.get_checksums(None, "volmarr", "pub", "v1.0")
        d = checksums_to_dict(gen, "volmarr/pub")
        self.assertEqual(set(d), {"repository", "tag", "filename",
                                  "content_type", "size", "sha256",
                                  "asset_count", "entries"})
        self.assertEqual(d["repository"], "volmarr/pub")
        self.assertEqual(d["tag"], "v1.0")
        self.assertEqual(d["entries"][0],
                         {"name": "anvil.txt", "sha256": _sha(TEXT_A)})

    # -- visibility ---------------------------------------
    def test_missing_release_and_private_repo_uniform(self):
        self.assertEqual(
            self._reason(self.checksums.get_checksums,
                         None, "volmarr", "pub", "v9.9"),
            "release_not_found")
        self.assertEqual(
            self._reason(self.checksums.get_checksums,
                         self.stranger, "volmarr", "priv", "v1.0"),
            "repo_not_found")
        self.assertEqual(
            self._reason(self.checksums.download_checksums,
                         None, "volmarr", "nope", "v1.0"),
            "repo_not_found")

    def test_draft_checksums_private_to_writers(self):
        self._upload(TEXT_A, "anvil.txt", tag="v1.1")
        self.assertEqual(
            self._reason(self.checksums.get_checksums,
                         self.reader, "volmarr", "pub", "v1.1"),
            "release_not_found")
        self.assertEqual(
            self._reason(self.checksums.get_checksums,
                         None, "volmarr", "pub", "v1.1"),
            "release_not_found")
        gen = self.checksums.get_checksums(
            self.owner, "volmarr", "pub", "v1.1")
        self.assertEqual(gen.asset_count, 1)
        self.releases.publish_release(self.owner, "volmarr", "pub", "v1.1")
        gen = self.checksums.get_checksums(None, "volmarr", "pub", "v1.1")
        self.assertEqual(gen.asset_count, 1)

    # -- parse + verify -----------------------------------
    def test_parse_roundtrip(self):
        self._two_assets()
        gen = self.checksums.get_checksums(None, "volmarr", "pub", "v1.0")
        entries = parse_checksums(gen.text)
        self.assertEqual([(e.name, e.sha256) for e in entries],
                         [("anvil.txt", _sha(TEXT_A)),
                          ("manual.txt", _sha(TEXT_B))])
        self.assertEqual(parse_checksums(""), [])

    def test_parse_refuses_malformed_lines(self):
        for bad in ("not-a-digest  anvil.txt\n",
                    f"{_sha(TEXT_A)} anvil.txt\n",
                    f"{_sha(TEXT_A).upper()}  anvil.txt\n",
                    f"{_sha(TEXT_A)}  anvil.txt\n{_sha(TEXT_B)}  anvil.txt\n",
                    "\n"):
            with self.assertRaises(ReleaseChecksumError) as ctx:
                parse_checksums(bad)
            self.assertEqual(ctx.exception.reason, "checksums_invalid")
        with self.assertRaises(ReleaseChecksumError):
            parse_checksums(b"bytes-not-text")

    def test_verify_ok_for_true_bytes(self):
        self._two_assets()
        gen = self.checksums.get_checksums(None, "volmarr", "pub", "v1.0")
        verdict = verify_checksums(
            gen.text, {"anvil.txt": _sha(TEXT_A),
                       "manual.txt": _sha(TEXT_B)})
        self.assertTrue(verdict.ok)
        self.assertEqual(verdict.checked, 2)

    def test_verify_names_tamper_missing_and_unexpected(self):
        self._two_assets()
        gen = self.checksums.get_checksums(None, "volmarr", "pub", "v1.0")
        verdict = verify_checksums(
            gen.text, {"anvil.txt": _sha(b"tampered"),
                       "extra.bin": _sha(b"x")})
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.mismatched, ("anvil.txt",))
        self.assertEqual(verdict.missing, ("manual.txt",))
        self.assertEqual(verdict.unexpected, ("extra.bin",))

    def test_verify_against_downloaded_asset_bytes(self):
        self._upload(TEXT_A, "anvil.txt")
        dl = self.assets.download_asset(None, "volmarr", "pub", "v1.0",
                                        "anvil.txt")
        gen = self.checksums.get_checksums(None, "volmarr", "pub", "v1.0")
        verdict = verify_checksums(
            gen.text, {"anvil.txt": _sha(dl.read_all())})
        self.assertTrue(verdict.ok)

    # -- page ----------------------------------------------
    def test_page_names_file_and_states_verification(self):
        self._two_assets()
        assets = self.assets.list_assets(None, "volmarr", "pub", "v1.0")
        html = render_checksums_section("volmarr/pub", "v1.0", assets)
        self.assertIn(CHECKSUMS_FILENAME, html)
        self.assertIn(VERIFY_COMMAND_POSIX, html)
        self.assertIn(VERIFY_COMMAND_MACOS, html)
        self.assertIn("Every asset must answer OK", html)
        self.assertIn("do not trust it", html)
        self.assertIn("lists 2 assets", html)
        self.assertIn(_sha(TEXT_A), html)

    def test_page_empty_release_and_singular(self):
        html = render_checksums_section("volmarr/pub", "v1.0", [])
        self.assertIn("no assets yet", html)
        self.assertIn(VERIFY_COMMAND_POSIX, html)
        self._upload(TEXT_A, "anvil.txt")
        assets = self.assets.list_assets(None, "volmarr", "pub", "v1.0")
        html = render_checksums_section("volmarr/pub", "v1.0", assets)
        self.assertIn("lists 1 asset.", html)

    def test_page_escapes_asset_names_but_file_stays_raw(self):
        self._upload(TEXT_A, "a<b>&c.txt")
        assets = self.assets.list_assets(None, "volmarr", "pub", "v1.0")
        html = render_checksums_section("volmarr/pub", "v1.0", assets)
        self.assertIn("a&lt;b&gt;&amp;c.txt", html)
        self.assertNotIn("a<b>&c.txt", html)
        gen = self.checksums.get_checksums(None, "volmarr", "pub", "v1.0")
        self.assertIn("a<b>&c.txt", gen.text)


if __name__ == "__main__":
    unittest.main()
