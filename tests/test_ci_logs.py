"""S-322 acceptance battery: CI logs.

Acceptance (roadmap S-322): Log streaming and
storage -- live log tail in the UI, stored logs
with retention (S-267's machinery), download as
text.

The centre is samverk/ci_logs.py:
`LogStreamingStore` lands a job's streamed
output as one stored log per (repository, run,
job) in migration 131's `ci_logs` row -- every
append redacted through S-018's `redact_text`
before it lands, retention one of S-266's
choices with the stamp `decide_expiry`
computes, reads gated through S-054's
`can_read` (a stranger to a private repository
gets the uniform `repository_not_found`),
expired logs answering every read as
`log_not_found` and removed whole by the
off-path `LogExpiryJob` in S-267's shape. The
tail answers the last N lines with totals for
a polling UI; the download answers the whole
text as text/plain under `<run_id>-<job_id>.log`.
Migration 131 (schema 130 -> 131); taxonomy
unmoved at 135 (33 auth / 89 repo / 13 admin);
no audit row is written by any face.

Counted with: python3 -m unittest tests.test_ci_logs
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.ci_artifacts import (
    DEFAULT_RETENTION_DAYS, RETENTION_CHOICES,
    decide_expiry, is_expired)
from samverk.ci_logs import (
    DEFAULT_TAIL_LINES, MAX_LOG_CHARS, MAX_TAIL_LINES,
    LogExpiryJob, LogStreamingError, LogStreamingStore,
    audit_log_streaming, count_lines,
    download_filename_for, is_log_expired, log_to_dict,
    main, render_log_page, tail_lines, tail_to_dict,
    validate_log_identity, validate_retention_days,
    validate_tail_lines)
from samverk.db import schema_version
from samverk.issues import IssueStore
from samverk.repositories import RepositoryStore
from samverk.runner_protocol import parse_log_chunk

PW = "correct horse battery"
T0 = 1_700_000_000
DAY = 86400


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


def _reason(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except LogStreamingError as exc:
        return exc.reason
    raise AssertionError("expected LogStreamingError")


def _payload(text="hello\n", sequence=1, step_index=1,
             stream="stdout", run_id="run-1", job_id="build"):
    return {
        "kind": "log_chunk", "protocol": 1,
        "run_id": run_id, "job_id": job_id,
        "step_index": step_index, "sequence": sequence,
        "stream": stream, "text": text}


class PureLawTests(unittest.TestCase):
    def test_retention_vocabulary_is_s266s(self):
        self.assertEqual(tuple(RETENTION_CHOICES),
                         (0, 7, 30, 90, 180, 365))
        self.assertEqual(DEFAULT_RETENTION_DAYS, 90)
        self.assertEqual(validate_retention_days(None), 90)
        for choice in RETENTION_CHOICES:
            self.assertEqual(validate_retention_days(choice),
                             choice)

    def test_retention_refuses_off_vocabulary(self):
        for bad in (45, 1, "90", True, 90.0, -7):
            self.assertEqual(
                _reason(validate_retention_days, bad),
                "retention_invalid")

    def test_expiry_stamp_law_is_s266s(self):
        self.assertIsNone(decide_expiry(0, T0))
        self.assertEqual(decide_expiry(90, T0), T0 + 90 * DAY)
        self.assertFalse(is_expired(None, T0 + 10 ** 9))
        self.assertFalse(is_expired(T0 + 10, T0 + 9))
        self.assertTrue(is_expired(T0 + 10, T0 + 10))
        self.assertTrue(is_log_expired(T0 + 10, T0 + 10))
        self.assertFalse(is_log_expired(None, T0 + 10 ** 9))

    def test_identity_law(self):
        self.assertEqual(validate_log_identity("run-1", "build"),
                         ("run-1", "build"))
        self.assertEqual(
            validate_log_identity("run_1.x", "test-2"),
            ("run_1.x", "test-2"))
        for bad in ("", "  ", "a b", "a/b", "-lead", None, 7):
            self.assertEqual(
                _reason(validate_log_identity, bad, "build"),
                "log_identity_invalid")
            self.assertEqual(
                _reason(validate_log_identity, "run-1", bad),
                "log_identity_invalid")

    def test_tail_window_validation(self):
        self.assertEqual(validate_tail_lines(None),
                         DEFAULT_TAIL_LINES)
        self.assertEqual(DEFAULT_TAIL_LINES, 100)
        self.assertEqual(validate_tail_lines(1), 1)
        self.assertEqual(validate_tail_lines(MAX_TAIL_LINES),
                         MAX_TAIL_LINES)
        for bad in (0, -1, MAX_TAIL_LINES + 1, True, "10", 2.5):
            self.assertEqual(
                _reason(validate_tail_lines, bad),
                "log_tail_invalid")

    def test_count_lines_law(self):
        self.assertEqual(count_lines(""), 0)
        self.assertEqual(count_lines("one"), 1)
        self.assertEqual(count_lines("one\n"), 1)
        self.assertEqual(count_lines("one\ntwo"), 2)
        self.assertEqual(count_lines("one\ntwo\n"), 2)
        self.assertEqual(count_lines("\n"), 1)

    def test_tail_lines_pure_window(self):
        text = "\n".join(f"line {i}" for i in range(1, 11))
        self.assertEqual(tail_lines(text, 3),
                         ("line 8", "line 9", "line 10"))
        self.assertEqual(tail_lines(text, 10),
                         tuple(f"line {i}" for i in range(1, 11)))
        self.assertEqual(tail_lines(text, 99),
                         tuple(f"line {i}" for i in range(1, 11)))
        self.assertEqual(tail_lines("", 5), ())

    def test_download_filename_is_bare(self):
        name = download_filename_for("run-1", "build")
        self.assertEqual(name, "run-1-build.log")
        self.assertNotIn("/", name)
        self.assertNotIn("\\", name)

    def test_pins_hold(self):
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 138)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 92)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)


class StoreCase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", PW)
        self.stranger = self.accounts.register("mallory", PW)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts)
        self.issues = IssueStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.logs = LogStreamingStore(
            self.conn, self.repos, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")

    # -- helpers -----------------------------------------------------

    def _append(self, text="hello\n", repo="pub", **kw):
        return self.logs.append_log(
            "volmarr", repo, "run-1", "build", text, **kw)

    def _count(self):
        return self.conn.execute(
            "SELECT COUNT(*) c FROM ci_logs").fetchone()["c"]

    def _audit_count(self):
        return self.conn.execute(
            "SELECT COUNT(*) c FROM audit_log").fetchone()["c"]

    # -- store + read round trip --------------------------------------

    def test_append_and_get_round_trip(self):
        record = self._append("step one\nstep two\n",
                              workflow="CI")
        self.assertEqual(record.full_name, "volmarr/pub")
        self.assertEqual(record.run_id, "run-1")
        self.assertEqual(record.job_id, "build")
        self.assertEqual(record.workflow, "CI")
        self.assertEqual(record.text, "step one\nstep two\n")
        self.assertEqual(record.line_count, 2)
        self.assertEqual(record.retention_days, 90)
        self.assertEqual(record.expires_at, T0 + 90 * DAY)
        self.assertEqual(record.created_at, T0)
        self.assertEqual(record.updated_at, T0)
        got = self.logs.get_log(
            self.owner, "volmarr", "pub", "run-1", "build")
        self.assertEqual(got, record)

    def test_appends_concatenate_verbatim(self):
        self._append("first ")
        self.clock.now += 30
        record = self._append("second\nthird\n")
        self.assertEqual(record.text, "first second\nthird\n")
        self.assertEqual(record.line_count, 2)
        self.assertEqual(record.created_at, T0)
        self.assertEqual(record.updated_at, T0 + 30)
        self.assertEqual(self._count(), 1)

    def test_two_jobs_two_logs(self):
        self._append("a\n")
        self.logs.append_log(
            "volmarr", "pub", "run-1", "test", "b\n")
        self.logs.append_log(
            "volmarr", "pub", "run-2", "build", "c\n")
        listed = self.logs.list_logs(
            self.owner, "volmarr", "pub")
        self.assertEqual(
            [(r.run_id, r.job_id) for r in listed],
            [("run-1", "build"), ("run-1", "test"),
             ("run-2", "build")])
        one_run = self.logs.list_logs(
            self.owner, "volmarr", "pub", run_id="run-1")
        self.assertEqual(len(one_run), 2)

    def test_chunk_and_payload_roads_land(self):
        chunk = parse_log_chunk(_payload("chunked\n"))
        record = self.logs.append_chunk(
            "volmarr", "pub", chunk, workflow="CI")
        self.assertEqual(record.text, "chunked\n")
        record = self.logs.append_payload(
            "volmarr", "pub",
            _payload("wired\n", sequence=2),
            expected_sequence=2)
        self.assertEqual(record.text, "chunked\nwired\n")
        self.assertEqual(
            _reason(self.logs.append_chunk,
                    "volmarr", "pub", "not-a-chunk"),
            "log_chunk_invalid")
        self.assertEqual(self._count(), 1)

    def test_payload_out_of_sequence_refused_stores_nothing(self):
        self.logs.append_payload(
            "volmarr", "pub", _payload("one\n", sequence=1),
            expected_sequence=1)
        self.assertEqual(
            _reason(self.logs.append_payload,
                    "volmarr", "pub",
                    _payload("three\n", sequence=3),
                    expected_sequence=2),
            "runner_log_sequence")
        got = self.logs.get_log(
            self.owner, "volmarr", "pub", "run-1", "build")
        self.assertEqual(got.text, "one\n")

    def test_append_writes_no_audit_row(self):
        before = self._audit_count()
        self._append("quiet\n")
        self.logs.sweep_expired()
        self.assertEqual(self._audit_count(), before)

    # -- redaction ------------------------------------------------------

    def test_redaction_strikes_secrets_before_storage(self):
        self._append(
            "token is hunter2secret\n"
            "Authorization: Bearer abc123token\n"
            "password=hunter2secret\n",
            extra_secrets=("hunter2secret",))
        got = self.logs.get_log(
            self.owner, "volmarr", "pub", "run-1", "build")
        self.assertNotIn("hunter2secret", got.text)
        self.assertNotIn("abc123token", got.text)
        self.assertIn("[REDACTED]", got.text)
        row = self.conn.execute(
            "SELECT log_text FROM ci_logs").fetchone()
        self.assertNotIn("hunter2secret", row["log_text"])
        download = self.logs.download_log(
            self.owner, "volmarr", "pub", "run-1", "build")
        self.assertNotIn("hunter2secret", download.text)
        tail = self.logs.tail_log(
            self.owner, "volmarr", "pub", "run-1", "build")
        self.assertNotIn(
            "hunter2secret", "\n".join(tail.lines))

    # -- the tail ---------------------------------------------------------

    def _ten_lines(self):
        self._append(
            "\n".join(f"line {i}" for i in range(1, 11)) + "\n")

    def test_tail_window_semantics(self):
        self._ten_lines()
        tail = self.logs.tail_log(
            self.owner, "volmarr", "pub", "run-1", "build",
            lines=3)
        self.assertEqual(tail.lines,
                         ("line 8", "line 9", "line 10"))
        self.assertEqual(tail.total_lines, 10)
        self.assertEqual(tail.first_line, 8)
        self.assertTrue(tail.truncated)
        self.assertIn("last 3 of 10 lines", tail.words)

    def test_tail_covering_whole_log_is_not_truncated(self):
        self._ten_lines()
        tail = self.logs.tail_log(
            self.owner, "volmarr", "pub", "run-1", "build",
            lines=10)
        self.assertEqual(len(tail.lines), 10)
        self.assertEqual(tail.first_line, 1)
        self.assertFalse(tail.truncated)
        default = self.logs.tail_log(
            self.owner, "volmarr", "pub", "run-1", "build")
        self.assertEqual(len(default.lines), 10)
        self.assertFalse(default.truncated)

    def test_tail_grows_between_polls(self):
        self._append("one\n")
        first = self.logs.tail_log(
            self.owner, "volmarr", "pub", "run-1", "build",
            lines=5)
        self.assertEqual(first.total_lines, 1)
        self.clock.now += 5
        self._append("two\nthree\n")
        second = self.logs.tail_log(
            self.owner, "volmarr", "pub", "run-1", "build",
            lines=5)
        self.assertEqual(second.total_lines, 3)
        self.assertEqual(second.lines,
                         ("one", "two", "three"))
        self.assertGreater(second.updated_at,
                           first.updated_at)

    def test_tail_refuses_unlawful_window(self):
        self._append("one\n")
        self.assertEqual(
            _reason(self.logs.tail_log, self.owner,
                    "volmarr", "pub", "run-1", "build", 0),
            "log_tail_invalid")
        self.assertEqual(
            _reason(self.logs.tail_log, self.owner,
                    "volmarr", "pub", "run-1", "ghost", 0),
            "log_tail_invalid")

    # -- download ---------------------------------------------------------

    def test_download_whole_text_with_filename(self):
        self._append("full\nlog\ntext\n")
        download = self.logs.download_log(
            self.owner, "volmarr", "pub", "run-1", "build")
        self.assertEqual(download.filename, "run-1-build.log")
        self.assertEqual(download.content_type, "text/plain")
        self.assertEqual(download.text, "full\nlog\ntext\n")
        self.assertEqual(download.size, len("full\nlog\ntext\n"))

    def test_dict_shapes(self):
        record = self._append("one\ntwo\n", workflow="CI")
        data = log_to_dict(record)
        self.assertEqual(data["repository"], "volmarr/pub")
        self.assertEqual(data["run_id"], "run-1")
        self.assertEqual(data["job_id"], "build")
        self.assertEqual(data["workflow"], "CI")
        self.assertEqual(data["text"], "one\ntwo\n")
        self.assertEqual(data["line_count"], 2)
        self.assertEqual(data["retention_days"], 90)
        self.assertEqual(data["expires_at"], T0 + 90 * DAY)
        tail = self.logs.tail_log(
            self.owner, "volmarr", "pub", "run-1", "build",
            lines=1)
        tdata = tail_to_dict(tail)
        self.assertEqual(tdata["lines"], ["two"])
        self.assertEqual(tdata["total_lines"], 2)
        self.assertEqual(tdata["first_line"], 2)
        self.assertTrue(tdata["truncated"])

    # -- permission --------------------------------------------------------

    def test_private_log_hidden_from_stranger(self):
        self.logs.append_log(
            "volmarr", "priv", "run-1", "build", "secret run\n")
        mine = self.logs.get_log(
            self.owner, "volmarr", "priv", "run-1", "build")
        self.assertEqual(mine.text, "secret run\n")
        for face in (self.logs.get_log, self.logs.tail_log,
                     self.logs.download_log):
            self.assertEqual(
                _reason(face, self.stranger,
                        "volmarr", "priv", "run-1", "build"),
                "repository_not_found")
        self.assertEqual(
            _reason(self.logs.list_logs, self.stranger,
                    "volmarr", "priv"),
            "repository_not_found")
        self.assertEqual(
            _reason(self.logs.get_log, None,
                    "volmarr", "priv", "run-1", "build"),
            "repository_not_found")

    def test_public_log_open_to_anonymous_and_stranger(self):
        self._append("open\n")
        for viewer in (None, self.stranger):
            got = self.logs.get_log(
                viewer, "volmarr", "pub", "run-1", "build")
            self.assertEqual(got.text, "open\n")

    def test_missing_repository_and_missing_log(self):
        self.assertEqual(
            _reason(self.logs.append_log,
                    "volmarr", "ghost", "run-1", "build", "x\n"),
            "repository_not_found")
        self.assertEqual(
            _reason(self.logs.get_log, self.owner,
                    "volmarr", "ghost", "run-1", "build"),
            "repository_not_found")
        self.assertEqual(
            _reason(self.logs.get_log, self.owner,
                    "volmarr", "pub", "run-1", "build"),
            "log_not_found")
        self.assertEqual(self._count(), 0)

    # -- retention ---------------------------------------------------------

    def test_expired_log_vanishes_from_every_read(self):
        self._append("short lived\n", retention_days=7)
        self.clock.now = T0 + 7 * DAY - 1
        got = self.logs.get_log(
            self.owner, "volmarr", "pub", "run-1", "build")
        self.assertEqual(got.text, "short lived\n")
        self.clock.now = T0 + 7 * DAY
        for face in (self.logs.get_log, self.logs.tail_log,
                     self.logs.download_log):
            self.assertEqual(
                _reason(face, self.owner,
                        "volmarr", "pub", "run-1", "build"),
                "log_not_found")
        self.assertEqual(
            self.logs.list_logs(self.owner, "volmarr", "pub"),
            [])
        self.assertEqual(self._count(), 1)  # row awaits the sweep

    def test_sweep_removes_expired_keeps_live_and_forever(self):
        self._append("old\n", retention_days=7)
        self.logs.append_log(
            "volmarr", "pub", "run-1", "test", "fresh\n",
            retention_days=90)
        self.logs.append_log(
            "volmarr", "pub", "run-2", "build", "forever\n",
            retention_days=0)
        self.clock.now = T0 + 30 * DAY
        run = self.logs.sweep_expired()
        self.assertEqual(run.expired, 1)
        self.assertEqual(run.rows_removed, 1)
        self.assertIn("1 expired, 1 rows removed", run.words)
        self.assertEqual(self._count(), 2)
        again = self.logs.sweep_expired()
        self.assertEqual(again.rows_removed, 0)
        job = LogExpiryJob(self.conn, time_fn=self.clock)
        self.assertEqual(job.expired_rows(), [])
        self.clock.now = T0 + 3650 * DAY
        run = job.sweep()
        self.assertEqual(run.rows_removed, 1)  # the 90-day log
        listed = self.logs.list_logs(
            self.owner, "volmarr", "pub")
        self.assertEqual([r.job_id for r in listed], ["build"])
        self.assertEqual(listed[0].run_id, "run-2")

    def test_append_after_expiry_starts_fresh(self):
        self._append("old text\n", retention_days=7)
        self.clock.now = T0 + 8 * DAY
        record = self._append("new text\n", retention_days=7)
        self.assertEqual(record.text, "new text\n")
        self.assertEqual(record.created_at, T0 + 8 * DAY)
        self.assertEqual(record.expires_at, T0 + 15 * DAY)
        self.assertEqual(self._count(), 1)

    def test_retention_and_workflow_stand_for_life(self):
        self._append("one\n", workflow="CI", retention_days=30)
        self.assertEqual(
            _reason(self._append, "two\n", retention_days=90),
            "log_retention_mismatch")
        self.assertEqual(
            _reason(self._append, "two\n", workflow="CD"),
            "log_workflow_mismatch")
        record = self._append("two\n", workflow="CI",
                              retention_days=30)
        self.assertEqual(record.text, "one\ntwo\n")
        self.assertEqual(record.retention_days, 30)

    # -- refusals store nothing ---------------------------------------------

    def test_invalid_appends_store_nothing(self):
        for text, kw, reason in (
                ("", {}, "log_text_invalid"),
                (None, {}, "log_text_invalid"),
                (7, {}, "log_text_invalid"),
                ("a\x00b", {}, "log_text_invalid"),
                ("x\n", {"retention_days": 45},
                 "retention_invalid"),
                ("x\n", {"workflow": 7},
                 "log_workflow_invalid")):
            self.assertEqual(
                _reason(self._append, text, **kw), reason)
        self.assertEqual(
            _reason(self.logs.append_log,
                    "volmarr", "pub", "bad id", "build", "x\n"),
            "log_identity_invalid")
        self.assertEqual(self._count(), 0)

    def test_oversize_append_refused_standing_log_untouched(self):
        half = "x" * (MAX_LOG_CHARS // 2) + "\n"
        self._append(half)
        self.assertEqual(
            _reason(self._append, half), "log_too_large")
        got = self.logs.get_log(
            self.owner, "volmarr", "pub", "run-1", "build")
        self.assertEqual(got.text, half)
        self.assertEqual(
            _reason(self.logs.append_log,
                    "volmarr", "pub", "run-9", "build",
                    "y" * (MAX_LOG_CHARS + 1)),
            "log_too_large")
        self.assertEqual(self._count(), 1)


class AuditAndPageTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.accounts = AccountStore(self.conn, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", PW)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts)
        self.logs = LogStreamingStore(
            self.conn, self.repos, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")

    def test_schema_pin(self):
        self.assertEqual(schema_version(self.conn), 139)
        self.assertEqual(db.MIGRATIONS[-1][0], 139)

    def test_audit_stands_cleanly(self):
        self.logs.append_log(
            "volmarr", "pub", "run-1", "build", "one\ntwo\n",
            retention_days=30)
        audit = audit_log_streaming(self.conn)
        self.assertTrue(audit.retention_ok)
        self.assertTrue(audit.schema_ok)
        self.assertTrue(audit.events_ok)
        self.assertTrue(audit.tables_ok)
        self.assertEqual(audit.rows_scanned, 1)
        self.assertEqual(audit.problems, ())
        self.assertTrue(audit.stands_cleanly)

    def test_audit_catches_a_planted_bad_row(self):
        self.logs.append_log(
            "volmarr", "pub", "run-1", "build", "one\n",
            retention_days=30)
        with self.conn:
            self.conn.execute(
                "UPDATE ci_logs SET expires_at = 1")
        audit = audit_log_streaming(self.conn)
        self.assertFalse(audit.stands_cleanly)
        self.assertTrue(any("expiry stamp" in p
                            for p in audit.problems))

    def test_page_renders_the_law(self):
        page = render_log_page()
        self.assertIn("Job log", page)
        self.assertIn("redacted before it lands", page)
        self.assertIn("downloaded as plain", page)

    def test_page_escapes_log_lines(self):
        self.logs.append_log(
            "volmarr", "pub", "run-1", "build",
            "<script>alert(1)</script>\n")
        tail = self.logs.tail_log(
            self.owner, "volmarr", "pub", "run-1", "build")
        page = render_log_page(tail=tail)
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("Showing all 1 lines", page)

    def test_cli_usage_and_sweep(self):
        self.assertEqual(main([]), 2)
        self.assertEqual(main(["a", "b"]), 2)
        self.logs.append_log(
            "volmarr", "pub", "run-1", "build", "old\n",
            retention_days=7)
        self.conn.close()
        # The CLI opens its own connection at the wall
        # clock (far past T0 + 7 days in epoch terms is
        # not guaranteed, so judge the exit code only).
        code = main([str(self.root / "samverk.db")])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
