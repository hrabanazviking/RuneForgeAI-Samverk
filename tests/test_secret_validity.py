"""S-296 acceptance battery: validity checks seam.

Acceptance (roadmap S-296): Validity checks seam
-- where a provider offers a public validation
path, Samverk may check "still live?"; the
offline-honest default is *unknown*, displayed
as such.

The seam lives in samverk/secret_validity.py over
migration 119's standing validity columns on
S-291's secret_alerts plus the
secret_validity_checks record (schema 118 -> 119
on this base; S-293 and S-294 each claim migration
116 on their own bases -- the keeper renumbers at
banking). The registry holds one entry per S-289
detector: where the provider offers a public
validation path and where it honestly does not.
The pure judgement answers *unknown* -- with its
detail named -- for no path, no checker (the
offline default), no handed-in secret, and a
failing or unrecognised checker; only a checker
answering live / not live through a standing path
moves the answer. A performed check is judged by
S-190's permission engine (admin and maintain
only), recorded on the alert's own check record
in the same transaction that moves its standing
validity, and the handed-in secret is kept
nowhere. No new taxonomy event -- 134 stand
(33 auth / 88 repo / 13 admin); the battery proves
the audit log does not move.

Alerts are born through S-291's real scan road
(an injected scanner over an in-memory history)
with a real S-289 detector id, so the seam is
proven against the rows it will actually govern.

Counted with: python3 -m unittest tests.test_secret_validity
"""
from __future__ import annotations
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.hooks import RefUpdate
from samverk.outside_collaborators import OutsideCollaboratorStore
from samverk.push_scanning import PushScanStore, ScanFinding
from samverk.repositories import RepositoryStore
from samverk.secret_scanning import DETECTORS
from samverk.secret_validity import (
    ALERT_NOT_FOUND, DETAIL_CHECKED, DETAIL_CHECKER_FAILED,
    DETAIL_CHECKER_UNRECOGNISED, DETAIL_DETECTOR_UNKNOWN,
    DETAIL_NO_CHECKER, DETAIL_NO_PATH, DETAIL_NO_SECRET,
    DETECTOR_UNKNOWN, PERMITTED_ROLES, VALIDITIES,
    VALIDITY_LIVE, VALIDITY_NOT_LIVE, VALIDITY_NOT_PERMITTED,
    VALIDITY_UNKNOWN, SecretValidityStore, ValidityError,
    check_validity, decide_check, decide_validity,
    list_validation_paths, normalise_checker_result,
    render_validities_page, render_validity_page,
    validation_path_for, validity_word)

PW = "correct horse battery"
T0 = 1_700_000_000
ZERO = "0" * 40
SECRET = "hunter2-is-the-planted-secret"
GHP = "ghp_" + "A" * 36


def oid(n: int) -> str:
    return f"{n:040x}"


def github_scanner(text: str):
    """The injected scan seam: one S-289-shaped
    finding per planted GitHub token line."""
    out = []
    for i, line in enumerate(text.splitlines(), start=1):
        if GHP in line:
            out.append(ScanFinding(
                source="pattern", detector_id="github_pat_classic",
                line=i, column=line.index(GHP) + 1,
                redacted="ghp_...[36 chars]",
                fingerprint=hashlib.sha256(
                    GHP.encode()).hexdigest()))
    return out


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


class FakeHistory:
    def __init__(self):
        self.parents: dict = {}
        self.trees: dict = {}
        self.blobs: dict = {}
        self._next = 1000

    def add_blob(self, data: bytes) -> str:
        self._next += 1
        b = oid(self._next)
        self.blobs[b] = data
        return b

    def add_commit(self, parents=(), files=None) -> str:
        self._next += 1
        c = oid(self._next)
        tree = {}
        for path, data in (files or {}).items():
            tree[path] = ("100644", self.add_blob(data))
        self.parents[c] = tuple(parents)
        self.trees[c] = tree
        return c

    def commit_parents(self, o):
        return self.parents[o]

    def commit_tree(self, o):
        return o

    def flatten_tree(self, t):
        return dict(self.trees[t])

    def read_blob(self, o):
        return self.blobs[o]


class LiveChecker:
    """An injected provider checker with a memory:
    answers live for the planted token only."""

    def __init__(self, answer="live"):
        self.answer = answer
        self.calls: list = []

    def __call__(self, detector_id, secret):
        self.calls.append((detector_id, secret))
        if callable(self.answer):
            return self.answer(detector_id, secret)
        return self.answer


class SecretValidityTests(unittest.TestCase):
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
        self.maintainer = self.accounts.register("yrsa", PW)
        self.writer = self.accounts.register("tess", PW)
        self.reader = self.accounts.register("runa", PW)
        self.stranger = self.accounts.register("mallory", PW)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.pub = self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.priv = self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        grants = OutsideCollaboratorStore(
            self.conn, self.accounts, audit=self.audit,
            time_fn=self.clock)
        for repo in (self.pub, self.priv):
            grants.grant(self.owner.id, repo.id, "yrsa", "maintain")
            grants.grant(self.owner.id, repo.id, "tess", "write")
            grants.grant(self.owner.id, repo.id, "runa", "read")
        self.scans = PushScanStore(
            self.conn, self.repos, time_fn=self.clock)
        self.validity = SecretValidityStore(
            self.conn, self.repos, self.accounts,
            time_fn=self.clock)

    # -- helpers -------------------------------------------------

    def make_alert(self, repo="pub", path="keys.txt"):
        # Distinct commit per alert: S-291 alert and
        # scan identity ride on the push's oids, and
        # this fake's oids repeat per history, so each
        # alert's history starts at its own offset.
        self._alert_n = getattr(self, "_alert_n", 0) + 1
        hist = FakeHistory()
        hist._next = 1000 + self._alert_n * 100
        commit = hist.add_commit(
            files={path: f"token = {GHP}\n".encode()})
        scan = self.scans.scan_push(
            "volmarr", repo,
            updates=[RefUpdate("refs/heads/main", ZERO, commit)],
            history=hist, scanner=github_scanner)
        alerts = self.scans.alerts_for_scan(scan.id)
        self.assertEqual(len(alerts), 1)
        return alerts[0]

    def audit_count(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()
        return int(row["n"])

    # -- pins ------------------------------------------------------

    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 123)
        self.assertEqual(db.MIGRATIONS[-1][0], 123)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 89)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)

    # -- the registry ----------------------------------------------

    def test_registry_covers_every_s289_detector(self):
        paths = list_validation_paths()
        self.assertEqual(
            [p.detector_id for p in paths],
            [d.id for d in DETECTORS])
        for p in paths:
            self.assertTrue(p.method)
            self.assertTrue(p.provider)

    def test_registry_paths_are_honest(self):
        self.assertTrue(
            validation_path_for("github_pat_classic").has_public_path)
        self.assertTrue(
            validation_path_for("slack_token").has_public_path)
        self.assertTrue(
            validation_path_for("stripe_secret_key").has_public_path)
        # No public path, said plainly:
        for did in ("aws_access_key_id", "google_api_key",
                    "stripe_webhook_secret", "jwt_compact",
                    "private_key_block", "slack_webhook",
                    "pypi_token"):
            self.assertFalse(
                validation_path_for(did).has_public_path, did)

    def test_unknown_detector_refused_loudly(self):
        with self.assertRaises(ValidityError) as cm:
            validation_path_for("no_such_detector")
        self.assertEqual(cm.exception.reason, DETECTOR_UNKNOWN)
        with self.assertRaises(ValidityError) as cm:
            decide_validity("no_such_detector", secret="x",
                            checker=LiveChecker())
        self.assertEqual(cm.exception.reason, DETECTOR_UNKNOWN)

    def test_validity_words(self):
        self.assertEqual(validity_word("unknown"), "unknown")
        self.assertEqual(validity_word("live"), "still live")
        self.assertEqual(validity_word("not_live"), "no longer live")
        # An unrecognised value is displayed as unknown,
        # never guessed at:
        self.assertEqual(validity_word("whatever"), "unknown")
        self.assertEqual(VALIDITIES,
                         frozenset({"unknown", "live", "not_live"}))

    # -- the pure judgement ------------------------------------------

    def test_offline_default_is_unknown(self):
        verdict = decide_validity("github_pat_classic", secret=GHP)
        self.assertEqual(verdict.validity, VALIDITY_UNKNOWN)
        self.assertEqual(verdict.detail, DETAIL_NO_CHECKER)
        self.assertEqual(verdict.words, "unknown")
        self.assertEqual(verdict.display, "Validity: unknown")

    def test_no_path_is_unknown_even_with_a_checker(self):
        checker = LiveChecker("live")
        verdict = decide_validity(
            "aws_access_key_id", secret="AKIA" + "A" * 16,
            checker=checker)
        self.assertEqual(verdict.validity, VALIDITY_UNKNOWN)
        self.assertEqual(verdict.detail, DETAIL_NO_PATH)
        # The checker is never even called where no
        # public path stands:
        self.assertEqual(checker.calls, [])

    def test_no_secret_is_unknown(self):
        # Samverk stores no secret, so a standing
        # alert alone cannot be checked:
        verdict = decide_validity(
            "github_pat_classic", checker=LiveChecker("live"))
        self.assertEqual(verdict.validity, VALIDITY_UNKNOWN)
        self.assertEqual(verdict.detail, DETAIL_NO_SECRET)

    def test_checker_live_and_not_live(self):
        live = check_validity(
            "github_pat_classic", secret=GHP,
            checker=LiveChecker("live"))
        self.assertEqual((live.validity, live.detail),
                         (VALIDITY_LIVE, DETAIL_CHECKED))
        self.assertEqual(live.words, "still live")
        dead = check_validity(
            "github_pat_classic", secret=GHP,
            checker=LiveChecker(False))
        self.assertEqual((dead.validity, dead.detail),
                         (VALIDITY_NOT_LIVE, DETAIL_CHECKED))
        self.assertEqual(dead.words, "no longer live")

    def test_checker_failure_is_unknown(self):
        def boom(detector_id, secret):
            raise RuntimeError("provider unreachable")

        verdict = decide_validity(
            "github_pat_classic", secret=GHP, checker=boom)
        self.assertEqual(verdict.validity, VALIDITY_UNKNOWN)
        self.assertEqual(verdict.detail, DETAIL_CHECKER_FAILED)

    def test_checker_unrecognised_is_unknown(self):
        verdict = decide_validity(
            "github_pat_classic", secret=GHP,
            checker=LiveChecker("perhaps"))
        self.assertEqual(verdict.validity, VALIDITY_UNKNOWN)
        self.assertEqual(verdict.detail,
                         DETAIL_CHECKER_UNRECOGNISED)

    def test_checker_answer_shapes_normalised(self):
        self.assertEqual(normalise_checker_result(True), "live")
        self.assertEqual(normalise_checker_result(False), "not_live")
        self.assertEqual(normalise_checker_result(None), "unknown")
        self.assertEqual(normalise_checker_result("revoked"), "not_live")
        self.assertEqual(
            normalise_checker_result({"validity": "live"}), "live")
        self.assertIsNone(normalise_checker_result("perhaps"))
        self.assertIsNone(normalise_checker_result(42))

    def test_verdict_never_carries_the_secret(self):
        verdict = decide_validity(
            "github_pat_classic", secret=GHP,
            checker=LiveChecker("live"))
        self.assertNotIn(GHP, repr(verdict))
        self.assertNotIn(GHP, repr(verdict.to_dict()))

    def test_decide_check_permission_words(self):
        yes = decide_check(
            role="maintain", source="collaborator",
            actor="yrsa", full_name="volmarr/pub")
        self.assertTrue(yes.may_check)
        no = decide_check(
            role="read", source="collaborator",
            actor="runa", full_name="volmarr/pub")
        self.assertFalse(no.may_check)
        self.assertEqual(no.code, VALIDITY_NOT_PERMITTED)
        self.assertIn("runa", no.reason)
        anon = decide_check(
            role=None, source="", actor=None,
            full_name="volmarr/pub")
        self.assertFalse(anon.may_check)
        self.assertEqual(PERMITTED_ROLES,
                         frozenset({"admin", "maintain"}))

    # -- the store ----------------------------------------------------

    def test_alert_is_born_unknown(self):
        alert = self.make_alert()
        view = self.validity.get_validity(
            self.owner, "volmarr", "pub", alert.id)
        self.assertEqual(view.validity, VALIDITY_UNKNOWN)
        self.assertEqual(view.words, "unknown")
        self.assertEqual(view.display, "Validity: unknown")
        self.assertIsNone(view.validity_checked_at)
        self.assertEqual(view.detector_id, "github_pat_classic")
        self.assertEqual(view.provider, "GitHub")
        self.assertEqual(self.validity.list_checks(
            self.owner, "volmarr", "pub", alert.id), ())

    def test_check_records_live_and_stands_on_alert(self):
        alert = self.make_alert()
        checker = LiveChecker("live")
        before = self.audit_count()
        view = self.validity.check_alert(
            self.maintainer, "volmarr", "pub", alert.id,
            secret=GHP, checker=checker)
        self.assertEqual(view.validity, VALIDITY_LIVE)
        self.assertEqual(view.words, "still live")
        self.assertEqual(view.validity_checked_at, T0)
        self.assertEqual(view.validity_detail, DETAIL_CHECKED)
        self.assertEqual(
            checker.calls, [("github_pat_classic", GHP)])
        checks = self.validity.list_checks(
            self.owner, "volmarr", "pub", alert.id)
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0].validity, VALIDITY_LIVE)
        self.assertEqual(checks[0].checked_by, "yrsa")
        self.assertEqual(checks[0].role, "maintain")
        # A validity check is unwitnessed:
        self.assertEqual(self.audit_count(), before)
        # The secret is kept nowhere:
        self.assertNotIn(GHP, repr(view.to_dict()))
        self.assertNotIn(GHP, repr(checks[0].to_dict()))
        row = self.conn.execute(
            "SELECT * FROM secret_validity_checks").fetchone()
        self.assertNotIn(GHP, repr(dict(row)))

    def test_check_offline_records_unknown(self):
        alert = self.make_alert()
        view = self.validity.check_alert(
            self.owner, "volmarr", "pub", alert.id, secret=GHP)
        self.assertEqual(view.validity, VALIDITY_UNKNOWN)
        self.assertEqual(view.validity_detail, DETAIL_NO_CHECKER)
        checks = self.validity.list_checks(
            self.owner, "volmarr", "pub", alert.id)
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0].detail, DETAIL_NO_CHECKER)

    def test_check_without_secret_records_unknown(self):
        alert = self.make_alert()
        view = self.validity.check_alert(
            self.owner, "volmarr", "pub", alert.id,
            checker=LiveChecker("live"))
        self.assertEqual(view.validity, VALIDITY_UNKNOWN)
        self.assertEqual(view.validity_detail, DETAIL_NO_SECRET)

    def test_recheck_moves_the_standing_answer(self):
        alert = self.make_alert()
        self.validity.check_alert(
            self.owner, "volmarr", "pub", alert.id,
            secret=GHP, checker=LiveChecker("live"))
        view = self.validity.check_alert(
            self.owner, "volmarr", "pub", alert.id,
            secret=GHP, checker=LiveChecker("not_live"))
        self.assertEqual(view.validity, VALIDITY_NOT_LIVE)
        checks = self.validity.list_checks(
            self.owner, "volmarr", "pub", alert.id)
        self.assertEqual([c.validity for c in checks],
                         [VALIDITY_LIVE, VALIDITY_NOT_LIVE])
        self.assertEqual(self.validity.count_validities(
            self.reader, "volmarr", "pub",
            validity=VALIDITY_NOT_LIVE), 1)
        self.assertEqual(self.validity.count_validities(
            self.reader, "volmarr", "pub",
            validity=VALIDITY_UNKNOWN), 0)

    def test_store_checker_used_when_no_per_call_checker(self):
        alert = self.make_alert()
        store = SecretValidityStore(
            self.conn, self.repos, self.accounts,
            time_fn=self.clock, checker=LiveChecker("live"),
            checker_name="house checker")
        view = store.check_alert(
            self.owner, "volmarr", "pub", alert.id, secret=GHP)
        self.assertEqual(view.validity, VALIDITY_LIVE)
        self.assertEqual(view.validity_checker, "house checker")

    def test_check_permission_refusals_write_nothing(self):
        alert = self.make_alert()
        checker = LiveChecker("live")
        for actor in (self.writer, self.reader, self.stranger, None):
            with self.assertRaises(ValidityError) as cm:
                self.validity.check_alert(
                    actor, "volmarr", "pub", alert.id,
                    secret=GHP, checker=checker)
            self.assertEqual(
                cm.exception.reason, VALIDITY_NOT_PERMITTED)
        # The checker was never called and nothing stands:
        self.assertEqual(checker.calls, [])
        view = self.validity.get_validity(
            self.owner, "volmarr", "pub", alert.id)
        self.assertEqual(view.validity, VALIDITY_UNKNOWN)
        self.assertEqual(self.validity.list_checks(
            self.owner, "volmarr", "pub", alert.id), ())

    def test_private_repo_stranger_gets_repo_not_found(self):
        alert = self.make_alert(repo="priv", path="priv.txt")
        with self.assertRaises(ValidityError) as cm:
            self.validity.check_alert(
                self.stranger, "volmarr", "priv", alert.id,
                secret=GHP, checker=LiveChecker("live"))
        self.assertEqual(cm.exception.reason, "repo_not_found")
        with self.assertRaises(ValidityError) as cm:
            self.validity.get_validity(
                self.stranger, "volmarr", "priv", alert.id)
        self.assertEqual(cm.exception.reason, "repo_not_found")
        # ...while a reader of the private repo may read:
        view = self.validity.get_validity(
            self.reader, "volmarr", "priv", alert.id)
        self.assertEqual(view.validity, VALIDITY_UNKNOWN)

    def test_unknown_alert_refused(self):
        with self.assertRaises(ValidityError) as cm:
            self.validity.get_validity(
                self.owner, "volmarr", "pub", 9999)
        self.assertEqual(cm.exception.reason, ALERT_NOT_FOUND)
        with self.assertRaises(ValidityError) as cm:
            self.validity.check_alert(
                self.owner, "volmarr", "pub", 9999,
                secret=GHP, checker=LiveChecker("live"))
        self.assertEqual(cm.exception.reason, ALERT_NOT_FOUND)

    def test_judge_is_pure(self):
        alert = self.make_alert()
        yes = self.validity.judge(
            self.maintainer, "volmarr", "pub", alert.id)
        self.assertTrue(yes.may_check)
        no = self.validity.judge(
            self.reader, "volmarr", "pub", alert.id)
        self.assertFalse(no.may_check)
        self.assertEqual(self.validity.list_checks(
            self.owner, "volmarr", "pub", alert.id), ())
        view = self.validity.get_validity(
            self.owner, "volmarr", "pub", alert.id)
        self.assertEqual(view.validity, VALIDITY_UNKNOWN)

    def test_unrecognised_detector_alert_answers_unknown(self):
        # An alert from an injected scan whose detector
        # the v1 registry does not name: the store road
        # records unknown / detector_unknown rather
        # than refusing a standing alert.
        hist = FakeHistory()
        commit = hist.add_commit(
            files={"x.txt": f"s = {SECRET}\n".encode()})

        def odd_scanner(text: str):
            out = []
            for i, line in enumerate(text.splitlines(), start=1):
                if SECRET in line:
                    out.append(ScanFinding(
                        source="injected",
                        detector_id="planted_secret",
                        line=i, column=line.index(SECRET) + 1,
                        redacted="planted...[redacted]",
                        fingerprint=hashlib.sha256(
                            SECRET.encode()).hexdigest()))
            return out

        scan = self.scans.scan_push(
            "volmarr", "pub",
            updates=[RefUpdate("refs/heads/main", ZERO, commit)],
            history=hist, scanner=odd_scanner)
        alert = self.scans.alerts_for_scan(scan.id)[0]
        view = self.validity.check_alert(
            self.owner, "volmarr", "pub", alert.id,
            secret=SECRET, checker=LiveChecker("live"))
        self.assertEqual(view.validity, VALIDITY_UNKNOWN)
        self.assertEqual(view.validity_detail,
                         DETAIL_DETECTOR_UNKNOWN)

    def test_list_and_filter(self):
        first = self.make_alert(path="a.txt")
        second = self.make_alert(path="b.txt")
        self.validity.check_alert(
            self.owner, "volmarr", "pub", first.id,
            secret=GHP, checker=LiveChecker("live"))
        views = self.validity.list_validities(
            self.reader, "volmarr", "pub")
        self.assertEqual(len(views), 2)
        live = self.validity.list_validities(
            self.reader, "volmarr", "pub", validity="live")
        self.assertEqual([v.id for v in live], [first.id])
        unknown = self.validity.list_validities(
            self.reader, "volmarr", "pub", validity="unknown")
        self.assertEqual([v.id for v in unknown], [second.id])
        with self.assertRaises(ValidityError) as cm:
            self.validity.list_validities(
                self.reader, "volmarr", "pub", validity="bogus")
        self.assertEqual(cm.exception.reason, "validity_invalid")

    # -- the page faces ----------------------------------------------

    def test_pages_display_unknown_as_unknown(self):
        alert = self.make_alert()
        view = self.validity.get_validity(
            self.owner, "volmarr", "pub", alert.id)
        page = render_validity_page(view)
        self.assertIn("Validity: unknown", page)
        self.assertNotIn("still live", page)
        listing = render_validities_page([view])
        self.assertIn("Validity: unknown", listing)
        checked = self.validity.check_alert(
            self.owner, "volmarr", "pub", alert.id,
            secret=GHP, checker=LiveChecker("live"))
        checks = self.validity.list_checks(
            self.owner, "volmarr", "pub", alert.id)
        page = render_validity_page(checked, checks)
        self.assertIn("Validity: still live", page)
        # No page ever carries the secret:
        self.assertNotIn(GHP, page)


if __name__ == "__main__":
    unittest.main()
