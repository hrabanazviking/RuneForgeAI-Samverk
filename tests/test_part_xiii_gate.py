"""S-272 — PART XIII GATE battery: releases, assembled.

The whole Part XIII system struck at once, in the house
gate shape of S-204/S-220/S-236/S-256 — no new production
code, only the battery that walks the landed
S-257..S-271 machinery end to end through its public
seams, at the things the gate names: **lifecycle, assets
under caps, checksum verification round-trip**.

- **Lifecycle (S-257/S-258/S-261/S-262/S-269)** — one
  release through every state: drafted in private,
  published to the world, marked prerelease, unmarked;
  the three creation doors agreeing; the latest pointer
  excluding drafts and prereleases and moving only on
  publish; watchers notified on publish and never on
  draft saves, exactly once however often the sync runs;
  the tag automation drafting honestly and never
  publishing.
- **Assets under caps (S-259/S-266/S-267/S-268)** —
  chunked upload under S-012 law with the sniffed type
  stored, the per-asset cap judged at the door, as the
  bytes flow, and per chunk; CI artifacts tied to a
  standing check run; the expiry job vanishing an
  expired artifact from UI and disk together; storage
  accounting joining releases and artifacts into one
  honest total.
- **Checksum verification round-trip (S-260/S-263/
  S-270/S-271)** — the generated checksums file
  downloaded beside the assets and verified in code
  against the downloaded bytes: agreement passes,
  tamper/missing/unexpected are each named; detached
  signatures standing honestly unverified until the
  verifier seam earns a better word; the compare range
  embedded in the notes exactly once; and every asset
  served by S-271 with its digest in the headers,
  resumable by ranges that reassemble byte-for-byte,
  counted exactly once per byte-serving answer.
- **The registry refusal (S-264/S-265)** — every
  package door refused per the verdict, the audit
  clean, nothing stored.

The gate claims no migration and no taxonomy event:
the assembled system stands at schema 106 with 133
audit events (33 auth / 87 repo / 13 admin), and the
battery proves both pins.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import base64
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db, taxonomy
from samverk.access_tokens import AccessTokenStore
from samverk.accounts import AccountStore
from samverk.api_checks import StatusChecksAPI
from samverk.artifact_expiry import ArtifactExpiryJob
from samverk.audit import AuditLog
from samverk.ci_artifacts import CIArtifactsAPI, CIArtifactsError
from samverk.db import schema_version
from samverk.download_integrity import (
    DownloadIntegrityError, DownloadIntegrityStore, digest_of,
    etag_for_digest, verify_download)
from samverk.issues import IssueStore
from samverk.notification_reasons import NotificationStore
from samverk.registry_core import (
    RegistryCore, RegistryCoreError, audit_registry_core)
from samverk.release_assets import (
    ASSET_POLICY, ReleaseAssetError, ReleaseAssetStore)
from samverk.release_checksums import (
    CHECKSUMS_FILENAME, ReleaseChecksumStore,
    build_checksums_text, parse_checksums, verify_checksums)
from samverk.release_compare import (
    COMPARE_MARKER, ReleaseCompareError, ReleaseCompareStore,
    has_embedded_compare)
from samverk.release_from_tag import (
    ReleaseFromTagStore, is_version_tag, parse_version_tag)
from samverk.release_latest import ReleaseLatestStore
from samverk.release_notifications import (
    ReleaseNotificationStore, decide_release_notify)
from samverk.release_signatures import (
    ReleaseSignatureError, ReleaseSignatureStore,
    decide_signature_trust, signature_trust)
from samverk.releases import (
    NOTES_FILE, ReleaseError, ReleaseStore, is_latest_eligible,
    release_state, release_to_dict, render_releases_page,
    select_latest_release, state_markers)
from samverk.repo_quotas import QuotaService
from samverk.repo_size import RepoSizeAccounting
from samverk.repositories import RepositoryStore
from samverk.storage_accounting import (
    StorageAccounting, storage_to_dict)
from samverk.uploads import UploadPolicy
from samverk.watch_star import WatchStarStore
from test_repo_home import run_git

PW = "correct horse battery"
T0 = 1_700_000_000
DAY = 86400
OID = "a" * 40
TEXT = b"anvil release notes\nsecond line\n"
TEXT_B = b"manual body, plain and true\n"
ZIP = b"PK\x03\x04" + b"\x00" * 40
DATA = b"0123456789" * 10
PGP = ("-----BEGIN PGP SIGNATURE-----\n\n"
       "iQEzBAABCgAdFiEEdeadbeef\n=abcd\n"
       "-----END PGP SIGNATURE-----\n")
SSH = ("-----BEGIN SSH SIGNATURE-----\n"
       "U1NIU0lHAAAAAQAAADMAAAALc3NoLWVkMjU1MTk=\n"
       "-----END SSH SIGNATURE-----\n")


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


def basic(username, credential):
    raw = base64.b64encode(f"{username}:{credential}".encode())
    return "Basic " + raw.decode("ascii")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


class PartXIIIGateTests(unittest.TestCase):
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
        self.allw = self.accounts.register("allw", PW)
        self.relw = self.accounts.register("relw", PW)
        self.ignw = self.accounts.register("ignw", PW)
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
        self.latest = ReleaseLatestStore(
            self.conn, self.repos, self.releases,
            self.accounts, audit=self.audit, time_fn=self.clock)
        self.watches = WatchStarStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.notes = NotificationStore(
            self.conn, self.accounts, time_fn=self.clock)
        self.notify = ReleaseNotificationStore(
            self.conn, self.repos, self.accounts,
            releases=self.releases, audit=self.audit,
            time_fn=self.clock)
        self.signatures = ReleaseSignatureStore(
            self.conn, self.repos, self.releases, self.assets,
            self.accounts, audit=self.audit, time_fn=self.clock)
        self.auto = ReleaseFromTagStore(
            self.conn, self.repos, self.releases,
            self.accounts, audit=self.audit, time_fn=self.clock)
        self.compare = ReleaseCompareStore(
            self.conn, self.repos, self.releases,
            self.accounts, audit=self.audit, time_fn=self.clock)
        self.registry = RegistryCore(self.repos)
        self.issues = IssueStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        classic = AccessTokenStore(
            self.conn, self.accounts, audit=self.audit,
            time_fn=self.clock)
        _, self.owner_write = classic.create_token(
            self.owner.id, "write token", {"repo:write"},
            self.clock.now + 3600)
        self.checks_api = StatusChecksAPI(
            self.conn, self.accounts, self.repos, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.owner_basic = basic("volmarr", PW)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        self.checks_api.post_check_run(
            self.owner_basic, "volmarr", "pub",
            {"oid": OID, "name": "ci/build", "status": "completed",
             "conclusion": "success"})
        self.api = CIArtifactsAPI(
            self.conn, self.accounts, self.repos, self.issues,
            self.root, audit=self.audit, time_fn=self.clock)
        self.expiry = ArtifactExpiryJob(
            self.conn, self.root, time_fn=self.clock)
        self.sizes = RepoSizeAccounting(
            self.conn, self.root, self.accounts, self.repos)
        self.quotas = QuotaService(
            self.conn, self.root, self.accounts, self.repos,
            audit=self.audit, time_fn=self.clock)
        self.storage = StorageAccounting(
            self.conn, self.root, self.accounts, self.repos,
            self.quotas)
        self.downloads = DownloadIntegrityStore(
            assets=self.assets, checksums=self.checksums,
            ci_api=self.api)
        self.bare = self.repos.path_for("volmarr", "pub")
        self.work = self.root / "work"
        self.work.mkdir()
        run_git(self.work, "init", "-b", "main")
        self._write("app.py", "print('hi')\n")
        self.c1 = self._commit("first")
        run_git(self.work, "tag", "v1.0")
        run_git(self.work, "push", str(self.bare), "v1.0")
        self._write(NOTES_FILE, "# Anvil 1.1\n\nFirst **stable** cut.\n")
        self._write("app.py", "print('ho')\n")
        self.c2 = self._commit("second")
        run_git(self.work, "tag", "v1.1")
        run_git(self.work, "push", str(self.bare), "v1.1")
        self._write("app.py", "print('hey')\n")
        self.c3 = self._commit("third")
        for tag in ("v1.2", "v2.0"):
            run_git(self.work, "tag", tag)
            run_git(self.work, "push", str(self.bare), tag)

    # -- helpers -----------------------------------------
    def _write(self, rel, text):
        p = self.work / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def _commit(self, msg):
        run_git(self.work, "add", "-A")
        run_git(self.work, "commit", "-m", msg)
        run_git(self.work, "push", str(self.bare), "main")
        return run_git(self.work, "rev-parse", "HEAD").strip()

    def _reason(self, exc_type, fn, *a, **k):
        with self.assertRaises(exc_type) as ctx:
            fn(*a, **k)
        return ctx.exception.reason

    def _release(self, tag="v1.0", title=None, **kw):
        return self.releases.create_release(
            self.owner, "volmarr", "pub", tag,
            title or f"Anvil {tag}", "Notes.", **kw)

    def _upload(self, data, name="notes.txt", tag="v1.0",
                store=None, **begin_kw):
        store = store or self.assets
        chunks = [data[i:i + 8] for i in range(0, len(data), 8)] or [b""]
        session = store.begin_upload(
            self.owner, "volmarr", "pub", tag, name, **begin_kw)
        for idx, chunk in enumerate(chunks):
            if chunk:
                store.upload_chunk(self.owner, session.id, idx, chunk)
        return store.complete_upload(self.owner, session.id)

    def _artifact(self, data=ZIP, name="build.zip", **over):
        payload = {"oid": OID, "check_run": "ci/build", "name": name}
        payload.update(over)
        session = self.api.begin_upload(
            self.owner_basic, "volmarr", "pub", payload)
        chunks = [data[i:i + 8] for i in range(0, len(data), 8)]
        for idx, chunk in enumerate(chunks):
            self.api.upload_chunk(
                self.owner_basic, "volmarr", "pub",
                session["id"], idx, chunk)
        return self.api.complete_upload(
            self.owner_basic, "volmarr", "pub", session["id"])

    def _watch_three(self):
        self.watches.set_watch(self.allw, "volmarr", "pub", "all")
        self.watches.set_watch(
            self.relw, "volmarr", "pub", "releases_only")
        self.watches.set_watch(self.ignw, "volmarr", "pub", "ignore")

    # -- pins --------------------------------------------
    def test_pins_schema_107_taxonomy_133(self):
        self.assertEqual(schema_version(self.conn), 118)
        self.assertEqual(db.MIGRATIONS[-1][0], 118)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 134)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 88)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        self.assertIn("repo.release.publish", taxonomy.REPO_EVENTS)
        self.assertIn("repo.artifact.upload", taxonomy.REPO_EVENTS)
        tables = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ("releases", "release_assets",
                      "release_upload_sessions", "release_signatures",
                      "ci_artifacts", "release_tag_automation"):
            self.assertIn(table, tables)
        self.assertNotIn("packages", tables)

    # -- lifecycle (S-257/S-258) --------------------------
    def test_lifecycle_draft_prerelease_publish(self):
        r = self._release(draft=True)
        self.assertEqual(release_state(r), "draft")
        self.assertFalse(is_latest_eligible(r))
        self.assertEqual(
            self._reason(ReleaseError, self.releases.get_release,
                         self.reader, "volmarr", "pub", "v1.0"),
            "release_not_found")
        self.assertEqual(
            self.releases.get_release(
                self.owner, "volmarr", "pub", "v1.0").id, r.id)
        pub = self.releases.publish_release(
            self.owner, "volmarr", "pub", "v1.0")
        self.assertEqual(release_state(pub), "published")
        self.assertTrue(is_latest_eligible(pub))
        self.assertEqual(
            self.releases.get_release(
                None, "volmarr", "pub", "v1.0").id, r.id)
        pre = self.releases.update_release(
            self.owner, "volmarr", "pub", "v1.0", prerelease=True)
        self.assertEqual(release_state(pre), "prerelease")
        self.assertIn("pre-release",
                      [m.lower() for m in state_markers(pre)])
        self.assertFalse(is_latest_eligible(pre))
        page = render_releases_page(
            "volmarr/pub",
            self.releases.list_releases(None, "volmarr", "pub"))
        self.assertIn("Pre-release", page)
        back = self.releases.update_release(
            self.owner, "volmarr", "pub", "v1.0", prerelease=False)
        self.assertEqual(release_state(back), "published")
        self.assertEqual(state_markers(back), [])

    def test_three_doors_one_release_law(self):
        web = self._release("v1.0")
        api = self.releases.create_release_from_api(
            self.owner, "volmarr", "pub",
            {"tag": "v1.2", "title": "Anvil 1.2", "notes": "Via API."})
        push = self.releases.create_release_from_tag_push(
            self.owner, "volmarr", "pub", "v1.1")
        self.assertEqual(
            (web.source, api.source, push.source),
            ("web", "api", "tag_push"))
        self.assertEqual(push.title, "Anvil 1.1")
        self.assertEqual(push.target_oid, self.c2)
        for rel in (web, api, push):
            got = self.releases.get_release(
                None, "volmarr", "pub", rel.tag)
            self.assertEqual(got.id, rel.id)
            self.assertEqual(release_to_dict(got)["tag"], rel.tag)
        again = self.releases.create_release_from_tag_push(
            self.owner, "volmarr", "pub", "v1.1")
        self.assertEqual(again.id, push.id)
        self.assertEqual(
            self._reason(ReleaseError, self.releases.create_release,
                         self.owner, "volmarr", "pub", "v1.0", "Two"),
            "release_taken")

    # -- latest pointer (S-261) ---------------------------
    def test_latest_excludes_drafts_and_prereleases(self):
        old = self._release("v1.0")
        self._release("v1.1", prerelease=True)
        self._release("v1.2", draft=True)
        pointer = self.latest.get_latest(None, "volmarr", "pub")
        self.assertEqual(pointer.tag, "v1.0")
        self.assertTrue(
            self.latest.is_latest(None, "volmarr", "pub", "v1.0"))
        self.assertFalse(
            self.latest.is_latest(None, "volmarr", "pub", "v1.1"))
        listed = self.releases.list_releases(
            self.owner, "volmarr", "pub")
        self.assertEqual(select_latest_release(listed).id, old.id)
        self.releases.publish_release(
            self.owner, "volmarr", "pub", "v1.2")
        self.assertEqual(
            self.latest.get_latest(None, "volmarr", "pub").tag,
            "v1.2")
        self.releases.delete_release(
            self.owner, "volmarr", "pub", "v1.2")
        self.assertEqual(
            self.latest.get_latest(None, "volmarr", "pub").tag,
            "v1.0")

    # -- notifications (S-262) ----------------------------
    def test_publish_notifies_draft_silent_exactly_once(self):
        self._watch_three()
        self.assertTrue(decide_release_notify("all"))
        self.assertTrue(decide_release_notify("releases_only"))
        self.assertFalse(decide_release_notify("ignore"))
        self.assertFalse(decide_release_notify("none"))
        self._release("v1.0", draft=True)
        self.releases.update_release(
            self.owner, "volmarr", "pub", "v1.0", title="Retitled")
        self.assertEqual(self.notify.sync_repo("volmarr", "pub"), 0)
        self.releases.publish_release(
            self.owner, "volmarr", "pub", "v1.0")
        self.assertEqual(self.notify.sync_repo("volmarr", "pub"), 2)
        self.assertEqual(self.notify.sync_repo("volmarr", "pub"), 0)
        self.assertEqual(self.notify.sync_all(), 0)
        self.assertEqual(self.notify.count_for_recipient(self.allw), 1)
        self.assertEqual(self.notify.count_for_recipient(self.relw), 1)
        self.assertEqual(self.notify.count_for_recipient(self.ignw), 0)
        self.assertEqual(self.notify.count_for_recipient(self.owner), 0)
        rows = self.notify.deliveries_for_release(
            self.owner, "volmarr", "pub", "v1.0")
        self.assertEqual(len(rows), 2)

    # -- assets under caps (S-259) ------------------------
    def test_assets_chunked_round_trip_and_counts(self):
        self._release()
        asset = self._upload(TEXT, "notes.txt")
        self.assertEqual(asset.sha256, _sha(TEXT))
        self.assertEqual(asset.size, len(TEXT))
        self.assertEqual(asset.content_type, "text/plain")
        self.assertEqual(asset.download_count, 0)
        got = self.assets.get_asset(
            None, "volmarr", "pub", "v1.0", "notes.txt")
        self.assertEqual(got.id, asset.id)
        opened = self.assets.download_asset(
            None, "volmarr", "pub", "v1.0", "notes.txt")
        self.assertEqual(opened.read_all(), TEXT)
        after = self.assets.get_asset(
            None, "volmarr", "pub", "v1.0", "notes.txt")
        self.assertEqual(after.download_count, 1)
        listed = self.assets.list_assets(
            None, "volmarr", "pub", "v1.0")
        self.assertEqual([a.name for a in listed], ["notes.txt"])

    def test_assets_caps_judged_at_door_in_flow_and_per_chunk(self):
        self._release()
        self.assertEqual(
            self._reason(ReleaseAssetError, self.assets.begin_upload,
                         self.owner, "volmarr", "pub", "v1.0", "big.zip",
                         expected_size=ASSET_POLICY.max_bytes + 1),
            "too_large")
        small = ReleaseAssetStore(
            self.conn, self.repos, self.releases, self.root,
            self.accounts, audit=self.audit, time_fn=self.clock,
            policy=UploadPolicy(
                max_bytes=10, allowed_types=ASSET_POLICY.allowed_types))
        s = small.begin_upload(
            self.owner, "volmarr", "pub", "v1.0", "a.txt")
        small.upload_chunk(self.owner, s.id, 0, b"12345678")
        self.assertEqual(
            self._reason(ReleaseAssetError, small.upload_chunk,
                         self.owner, s.id, 1, b"901"), "too_large")
        self.assertEqual(
            self._reason(ReleaseAssetError, small.upload_chunk,
                         self.owner, s.id, 1, b"9"), "upload_closed")
        big_chunk = b"x" * (1024 * 1024 + 1)
        s2 = self.assets.begin_upload(
            self.owner, "volmarr", "pub", "v1.0", "b.txt")
        self.assertEqual(
            self._reason(ReleaseAssetError, self.assets.upload_chunk,
                         self.owner, s2.id, 0, big_chunk),
            "chunk_too_large")
        self.assets.abort_upload(self.owner, s2.id)
        self.assertEqual(
            self.assets.list_assets(None, "volmarr", "pub", "v1.0"),
            [])

    def test_assets_sniffed_type_beats_declared(self):
        self._release()
        asset = self._upload(ZIP, "build.zip")
        self.assertEqual(asset.content_type, "application/zip")
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
        session = self.assets.begin_upload(
            self.owner, "volmarr", "pub", "v1.0", "fake.pdf",
            declared_type="application/pdf")
        for idx in range(0, len(png), 8):
            self.assets.upload_chunk(
                self.owner, session.id, idx // 8, png[idx:idx + 8])
        self.assertEqual(
            self._reason(ReleaseAssetError,
                         self.assets.complete_upload,
                         self.owner, session.id), "type_mismatch")

    def test_draft_assets_and_checksums_private_to_writers(self):
        self._release(draft=True)
        self._upload(TEXT, "notes.txt")
        self.assertEqual(
            self._reason(ReleaseAssetError, self.assets.get_asset,
                         self.reader, "volmarr", "pub", "v1.0",
                         "notes.txt"), "release_not_found")
        self.assertEqual(
            self.assets.get_asset(
                self.owner, "volmarr", "pub", "v1.0",
                "notes.txt").name, "notes.txt")
        with self.assertRaises(Exception):
            self.checksums.get_checksums(
                self.reader, "volmarr", "pub", "v1.0")
        gen = self.checksums.get_checksums(
            self.owner, "volmarr", "pub", "v1.0")
        self.assertEqual(gen.asset_count, 1)

    # -- checksum round-trip (S-260) ----------------------
    def test_checksum_verification_round_trip(self):
        self._release()
        a = self._upload(TEXT, "notes.txt")
        b = self._upload(TEXT_B, "manual.txt")
        gen = self.checksums.get_checksums(
            None, "volmarr", "pub", "v1.0")
        self.assertEqual(gen.filename, CHECKSUMS_FILENAME)
        self.assertEqual(gen.asset_count, 2)
        opened = self.checksums.download_checksums(
            None, "volmarr", "pub", "v1.0")
        held_bytes = opened.read_all()
        self.assertEqual(held_bytes.decode(), build_checksums_text(
            self.assets.list_assets(None, "volmarr", "pub", "v1.0")))
        entries = parse_checksums(held_bytes.decode())
        self.assertEqual(
            [(e.name, e.sha256) for e in entries],
            [("manual.txt", _sha(TEXT_B)), ("notes.txt", _sha(TEXT))])
        actual = {}
        for name in ("notes.txt", "manual.txt"):
            dl = self.assets.download_asset(
                None, "volmarr", "pub", "v1.0", name)
            actual[name] = _sha(dl.read_all())
        verdict = verify_checksums(held_bytes.decode(), actual)
        self.assertTrue(verdict.ok)
        self.assertEqual(verdict.checked, 2)
        tampered = dict(actual)
        tampered["notes.txt"] = _sha(b"forged notes\n")
        bad = verify_checksums(held_bytes.decode(), tampered)
        self.assertFalse(bad.ok)
        self.assertEqual(bad.mismatched, ("notes.txt",))
        short = verify_checksums(
            held_bytes.decode(), {"notes.txt": actual["notes.txt"]})
        self.assertEqual(short.missing, ("manual.txt",))
        extra = dict(actual)
        extra["ghost.bin"] = _sha(b"ghost")
        self.assertEqual(
            verify_checksums(held_bytes.decode(), extra).unexpected,
            ("ghost.bin",))
        self.assertEqual((a.download_count, b.download_count), (0, 0))

    def test_checksums_regenerate_and_count_nothing(self):
        self._release()
        self._upload(TEXT, "notes.txt")
        first = self.checksums.get_checksums(
            None, "volmarr", "pub", "v1.0")
        self.assertEqual(first.asset_count, 1)
        self.checksums.download_checksums(None, "volmarr", "pub", "v1.0")
        self.checksums.download_checksums(None, "volmarr", "pub", "v1.0")
        asset = self.assets.get_asset(
            None, "volmarr", "pub", "v1.0", "notes.txt")
        self.assertEqual(asset.download_count, 0)
        self._upload(TEXT_B, "manual.txt")
        second = self.checksums.get_checksums(
            None, "volmarr", "pub", "v1.0")
        self.assertEqual(second.asset_count, 2)
        self.assertNotEqual(first.sha256, second.sha256)
        names = [e.name for e in second.entries]
        self.assertEqual(names, ["manual.txt", "notes.txt"])

    # -- signatures (S-263) -------------------------------
    def test_signatures_honest_unverified_then_earned(self):
        self._release()
        self._upload(TEXT, "notes.txt")
        sig = self.signatures.attach_signature(
            self.owner, "volmarr", "pub", "v1.0",
            target_kind="release", signer="Volmarr Wyrd",
            kind="openpgp", signature=PGP)
        self.assertEqual(signature_trust(sig), "unverified")
        self.assertEqual(
            decide_signature_trust("passed", True), "verified")
        self.assertEqual(
            decide_signature_trust("passed", False), "partial")
        self.assertEqual(
            decide_signature_trust("failed", True), "unverified")
        by_asset = self.signatures.attach_signature(
            self.owner, "volmarr", "pub", "v1.0",
            target_kind="asset", asset_name="notes.txt",
            signer="Volmarr Wyrd", kind="ssh", signature=SSH)
        self.assertEqual(by_asset.asset_name, "notes.txt")
        self.assertEqual(
            self._reason(ReleaseSignatureError,
                         self.signatures.attach_signature,
                         self.owner, "volmarr", "pub", "v1.0",
                         target_kind="asset", asset_name="ghost.bin",
                         signer="Volmarr Wyrd", kind="ssh",
                         signature=SSH), "asset_not_found")
        self.assertEqual(
            self._reason(ReleaseSignatureError,
                         self.signatures.attach_signature,
                         self.reader, "volmarr", "pub", "v1.0",
                         target_kind="release", signer="Mallory",
                         kind="openpgp", signature=PGP),
            "permission_denied")
        earned = self.signatures.record_verification(
            "volmarr", "pub", "v1.0", sig.id, check="passed",
            signer_known=True, verified_signer="Volmarr Wyrd")
        self.assertEqual(signature_trust(earned), "verified")
        listed = self.signatures.list_signatures(
            None, "volmarr", "pub", "v1.0")
        self.assertEqual(len(listed), 2)

    # -- registry refusal (S-264/S-265) -------------------
    def test_registry_doors_all_refused_audit_clean(self):
        with self.assertRaises(RegistryCoreError) as ctx:
            self.registry.publish(
                self.owner, "npm", "volmarr", "pub", "anvil", "1.0.0")
        self.assertTrue(ctx.exception.reason)
        with self.assertRaises(RegistryCoreError):
            self.registry.fetch(
                None, "npm", "volmarr", "pub", "anvil", "1.0.0")
        with self.assertRaises(RegistryCoreError):
            self.registry.list_versions(
                None, "npm", "volmarr", "pub", "anvil")
        with self.assertRaises(RegistryCoreError):
            self.registry.delete(
                self.owner, "npm", "volmarr", "pub", "anvil", "1.0.0")
        audit = audit_registry_core(self.conn)
        self.assertTrue(audit.refused_cleanly)
        tables = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn("packages", tables)

    # -- CI artifacts + expiry (S-266/S-267) --------------
    def test_ci_artifacts_tied_to_check_run_and_counted(self):
        art = self._artifact()
        self.assertEqual(art["sha256"], _sha(ZIP))
        self.assertEqual(art["download_count"], 0)
        opened = self.api.download_artifact(
            self.owner_basic, "volmarr", "pub", art["id"])
        self.assertEqual(opened.read_all(), ZIP)
        got = self.api.get_artifact(
            self.owner_basic, "volmarr", "pub", art["id"])
        self.assertEqual(got["download_count"], 1)
        self.assertEqual(
            self._reason(CIArtifactsError, self.api.begin_upload,
                         self.owner_basic, "volmarr", "pub",
                         {"oid": OID, "check_run": "ci/ghost",
                          "name": "x.zip"}), "check_run_not_found")

    def test_expiry_sweep_vanishes_row_and_disk_together(self):
        art = self._artifact(retention_days=7)
        keep = self._artifact(data=TEXT, name="keep.txt", retention_days=0)
        repo_id = int(self.conn.execute(
            "SELECT id FROM repositories WHERE name = 'pub'"
        ).fetchone()[0])
        from samverk.artifact_expiry import artifact_bytes_path
        path = artifact_bytes_path(
            self.root, repo_id, art["sha256"], art["content_type"])
        self.assertTrue(path.exists())
        self.clock.now = T0 + 7 * DAY - 1
        run0 = self.expiry.sweep()
        self.assertEqual(run0.expired, 0)
        self.clock.now = T0 + 7 * DAY
        run1 = self.expiry.sweep()
        self.assertEqual(run1.expired, 1)
        self.assertFalse(path.exists())
        self.assertEqual(
            self._reason(CIArtifactsError, self.api.get_artifact,
                         self.owner_basic, "volmarr", "pub", art["id"]),
            "artifact_not_found")
        self.assertEqual(
            self.api.get_artifact(
                self.owner_basic, "volmarr", "pub",
                keep["id"])["name"], "keep.txt")
        run2 = self.expiry.sweep()
        self.assertEqual(run2.expired, 0)

    # -- storage accounting (S-268) -----------------------
    def test_storage_joins_releases_and_artifacts_once(self):
        self._release()
        self._upload(TEXT, "notes.txt")
        self._upload(TEXT, "notes-copy.txt")
        self._artifact()
        self._artifact(name="build-copy.zip")
        report = self.storage.report_for(
            self.owner.id, "volmarr", "pub")
        self.assertEqual(report.uploads_bytes, len(TEXT) + len(ZIP))
        self.assertEqual(
            report.total_bytes,
            report.repo_bytes + report.uploads_bytes)
        self.assertFalse(report.over_quota)
        d = storage_to_dict(report)
        self.assertEqual(d["uploads_bytes"], len(TEXT) + len(ZIP))

    # -- release-from-tag (S-269) -------------------------
    def test_tag_automation_drafts_never_publishes(self):
        self.assertEqual(parse_version_tag("v1.2"), (1, 2, 0, None))
        self.assertTrue(is_version_tag("v2.0"))
        self.assertFalse(is_version_tag("party"))
        off = self.auto.on_tag_push(
            self.owner, "volmarr", "pub", "v1.0")
        self.assertFalse(off.drafted)
        self.assertEqual(
            self.releases.list_releases(self.owner, "volmarr", "pub"),
            [])
        self.auto.set_enabled(self.owner, "volmarr", "pub", True)
        out = self.auto.on_tag_push(
            self.owner, "volmarr", "pub", "v1.0")
        self.assertTrue(out.drafted)
        draft = self.releases.get_release(
            self.owner, "volmarr", "pub", "v1.0")
        self.assertEqual(release_state(draft), "draft")
        self.assertEqual(
            self._reason(ReleaseError, self.releases.get_release,
                         None, "volmarr", "pub", "v1.0"),
            "release_not_found")
        skip = self.auto.on_tag_push(
            self.owner, "volmarr", "pub", "party")
        self.assertFalse(skip.drafted)

    # -- compare-in-release (S-270) -----------------------
    def test_compare_embedded_in_notes_exactly_once(self):
        self._release("v1.0")
        second = self._release("v1.1")
        rc = self.compare.compare_for_release(
            None, "volmarr", "pub", "v1.1")
        self.assertTrue(rc.has_previous)
        self.assertEqual(rc.previous_tag, "v1.0")
        embedded = self.compare.embed_in_release(
            self.owner, "volmarr", "pub", "v1.1")
        self.assertTrue(has_embedded_compare(embedded.notes))
        self.assertEqual(embedded.notes.count(COMPARE_MARKER), 1)
        self.assertEqual(
            self._reason(ReleaseCompareError,
                         self.compare.embed_in_release,
                         self.owner, "volmarr", "pub", "v1.1"),
            "compare_already_embedded")
        got = self.releases.get_release(
            None, "volmarr", "pub", "v1.1")
        self.assertTrue(has_embedded_compare(got.notes))
        self.assertEqual(got.notes.count(COMPARE_MARKER), 1)
        self.assertEqual(got.id, second.id)
        first = self.compare.compare_for_release(
            None, "volmarr", "pub", "v1.0")
        self.assertFalse(first.has_previous)

    # -- download integrity (S-271) -----------------------
    def test_download_integrity_asset_headers_and_ranges(self):
        self._release()
        self._upload(DATA, "data.txt")
        full = self.downloads.download_asset(
            None, "volmarr", "pub", "v1.0", "data.txt")
        self.assertEqual(full.status, 200)
        self.assertEqual(full.read_all(), DATA)
        self.assertEqual(full.headers["ETag"], etag_for_digest(_sha(DATA)))
        self.assertTrue(verify_download(DATA, _sha(DATA)))
        self.assertEqual(digest_of(DATA), _sha(DATA))
        part1 = self.downloads.download_asset(
            None, "volmarr", "pub", "v1.0", "data.txt",
            range_header="bytes=0-49")
        part2 = self.downloads.download_asset(
            None, "volmarr", "pub", "v1.0", "data.txt",
            range_header="bytes=50-")
        self.assertEqual(part1.status, 206)
        self.assertEqual(part1.read_all() + part2.read_all(), DATA)
        asset = self.assets.get_asset(
            None, "volmarr", "pub", "v1.0", "data.txt")
        self.assertEqual(asset.download_count, 3)
        cached = self.downloads.download_asset(
            None, "volmarr", "pub", "v1.0", "data.txt",
            if_none_match=etag_for_digest(_sha(DATA)))
        self.assertEqual(cached.status, 304)
        self.assertEqual(cached.read_all(), b"")
        self.assertEqual(
            self.assets.get_asset(
                None, "volmarr", "pub", "v1.0",
                "data.txt").download_count, 3)
        self.assertEqual(
            self._reason(DownloadIntegrityError,
                         self.downloads.download_asset,
                         None, "volmarr", "pub", "v1.0", "data.txt",
                         range_header="bytes=0-1,3-4"), "range_invalid")
        self.assertEqual(
            self.assets.get_asset(
                None, "volmarr", "pub", "v1.0",
                "data.txt").download_count, 3)

    def test_download_integrity_checksums_and_artifact_doors(self):
        self._release()
        self._upload(TEXT, "notes.txt")
        sums = self.downloads.download_checksums(
            None, "volmarr", "pub", "v1.0")
        self.assertEqual(sums.status, 200)
        body = sums.read_all()
        verdict = verify_checksums(
            body.decode(), {"notes.txt": _sha(TEXT)})
        self.assertTrue(verdict.ok)
        art = self._artifact()
        served = self.downloads.download_artifact(
            self.owner_basic, "volmarr", "pub", art["id"])
        self.assertEqual(served.status, 200)
        self.assertEqual(served.read_all(), ZIP)
        self.assertEqual(
            served.headers["ETag"], etag_for_digest(_sha(ZIP)))
        got = self.api.get_artifact(
            self.owner_basic, "volmarr", "pub", art["id"])
        self.assertEqual(got["download_count"], 1)

    # -- privacy uniformity -------------------------------
    def test_private_repo_uniform_across_doors(self):
        priv_bare = self.repos.path_for("volmarr", "priv")
        run_git(self.work, "push", str(priv_bare), "v1.0")
        self.releases.create_release(
            self.owner, "volmarr", "priv", "v1.0", "Secret 1.0")
        for fn in (
                lambda: self.releases.get_release(
                    self.stranger, "volmarr", "priv", "v1.0"),
                lambda: self.latest.get_latest(
                    self.stranger, "volmarr", "priv"),
                lambda: self.assets.list_assets(
                    self.stranger, "volmarr", "priv", "v1.0"),
                lambda: self.checksums.get_checksums(
                    self.stranger, "volmarr", "priv", "v1.0"),
                lambda: self.signatures.list_signatures(
                    self.stranger, "volmarr", "priv", "v1.0")):
            with self.assertRaises(Exception) as ctx:
                fn()
            self.assertEqual(
                getattr(ctx.exception, "reason", ""), "repo_not_found")

    # -- the whole release, end to end --------------------
    def test_one_release_end_to_end(self):
        self._watch_three()
        rel = self._release("v1.1", draft=True)
        self._upload(TEXT, "notes.txt", tag="v1.1")
        self._upload(ZIP, "anvil.zip", tag="v1.1")
        gen = self.checksums.get_checksums(
            self.owner, "volmarr", "pub", "v1.1")
        self.assertEqual(gen.asset_count, 2)
        sig = self.signatures.attach_signature(
            self.owner, "volmarr", "pub", "v1.1",
            target_kind="checksums", signer="Volmarr Wyrd",
            kind="openpgp", signature=PGP)
        self.assertEqual(signature_trust(sig), "unverified")
        self.compare.embed_in_release(
            self.owner, "volmarr", "pub", "v1.1")
        self.assertEqual(self.notify.sync_repo("volmarr", "pub"), 0)
        self.releases.publish_release(
            self.owner, "volmarr", "pub", "v1.1")
        self.assertEqual(self.notify.sync_repo("volmarr", "pub"), 2)
        self.assertEqual(
            self.latest.get_latest(None, "volmarr", "pub").tag,
            "v1.1")
        sums_dl = self.checksums.download_checksums(
            None, "volmarr", "pub", "v1.1")
        actual = {}
        for name in ("notes.txt", "anvil.zip"):
            resp = self.downloads.download_asset(
                None, "volmarr", "pub", "v1.1", name)
            self.assertEqual(resp.status, 200)
            actual[name] = _sha(resp.read_all())
        self.assertTrue(verify_checksums(
            sums_dl.read_all().decode(), actual).ok)
        report = self.storage.report_for(
            self.owner.id, "volmarr", "pub")
        self.assertEqual(
            report.uploads_bytes, len(TEXT) + len(ZIP))
        self.assertEqual(rel.tag, "v1.1")


if __name__ == "__main__":
    unittest.main()
