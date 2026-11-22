"""S-316 acceptance battery: runner protocol.

Acceptance (roadmap S-316): Runner protocol --
the contract a runner speaks: register, poll
for work, stream logs, report conclusion
(documented before any runner is built).

The centre is the pure judge: a register
message is judged for scope, labels and the
shape of its one-time token (carried, never
kept); a poll is answered wait (bounded) or one
assignment whose required labels must be among
the poll's labels, whose steps are shell-only
and whose environment travels as names, never
values; log chunks form a per-step numbered
stream with gaps refused; a conclusion speaks
S-246's vocabulary and must agree with its own
steps; and the audit checks the contract
against the live instance -- no table, column
or audit event carries a runner surface -- with
a planted runner table proving the audit would
catch one arriving ahead of its slice.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.api_checks import CHECK_RUN_CONCLUSIONS
from samverk.db import schema_version
from samverk.runner_protocol import (
    MESSAGE_KINDS, PROTOCOL_VERSION, RUNNER_CONCLUSIONS,
    RUNNER_SCOPES, RunnerProtocolError,
    aggregate_conclusion, audit_runner_protocol,
    check_assignment_labels, parse_assignment,
    parse_assignment_reply, parse_conclusion,
    parse_heartbeat, parse_log_chunk, parse_message,
    parse_poll, parse_poll_response, parse_registration,
    render_runner_protocol_page, validate_log_stream)

ROOT = Path(__file__).resolve().parent.parent

TOKEN = "one-time-token-0123456789"


def _reason(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except RunnerProtocolError as exc:
        return exc.reason
    raise AssertionError("expected RunnerProtocolError")


def _register(**over):
    msg = {"kind": "register", "protocol": 1,
           "name": "longship-1", "labels": ["linux", "x64"],
           "scope": "repo", "target": "hrabanazviking/samverk",
           "registration_token": TOKEN,
           "agent_version": "0.1.0"}
    msg.update(over)
    return msg


def _poll(**over):
    msg = {"kind": "poll", "protocol": 1,
           "runner": "longship-1", "labels": ["linux", "x64"]}
    msg.update(over)
    return msg


def _offer(**over):
    msg = {"kind": "assignment", "protocol": 1,
           "response": "assignment", "run_id": "run-1",
           "job_id": "test", "workflow": "CI",
           "repository": "hrabanazviking/samverk",
           "oid": "a" * 40,
           "steps": [{"name": "unit", "run": "python3 -m unittest"},
                     {"name": "", "run": "make lint"}],
           "runner_labels": ["linux"],
           "env_names": ["CI", "SAMVERK_TOKEN"],
           "timeout_minutes": 30}
    msg.update(over)
    return msg


def _chunk(**over):
    msg = {"kind": "log_chunk", "protocol": 1,
           "run_id": "run-1", "job_id": "test",
           "step_index": 1, "sequence": 1,
           "stream": "stdout", "text": "hello\n"}
    msg.update(over)
    return msg


def _conclusion(**over):
    msg = {"kind": "conclusion", "protocol": 1,
           "run_id": "run-1", "job_id": "test",
           "conclusion": "success",
           "steps": [{"index": 1, "name": "unit",
                      "conclusion": "success"},
                     {"index": 2, "name": "",
                      "conclusion": "skipped"}],
           "duration_seconds": 42, "summary": ""}
    msg.update(over)
    return msg


class VocabularyTests(unittest.TestCase):
    def test_vocabulary_is_the_contracts_own(self):
        self.assertEqual(PROTOCOL_VERSION, 1)
        self.assertEqual(
            MESSAGE_KINDS,
            ("register", "poll", "assignment",
             "assignment_reply", "heartbeat", "log_chunk",
             "conclusion"))
        self.assertEqual(RUNNER_SCOPES,
                         ("instance", "org", "repo"))

    def test_conclusions_are_s246s_words(self):
        self.assertEqual(tuple(CHECK_RUN_CONCLUSIONS),
                         tuple(RUNNER_CONCLUSIONS))


class RegistrationTests(unittest.TestCase):
    def test_repo_registration_parses(self):
        reg = parse_registration(_register())
        self.assertEqual(reg.name, "longship-1")
        self.assertEqual(reg.labels, ("linux", "x64"))
        self.assertEqual(reg.scope, "repo")
        self.assertEqual(reg.target, "hrabanazviking/samverk")
        self.assertFalse(hasattr(reg, "registration_token"))

    def test_instance_and_org_scopes(self):
        reg = parse_registration(_register(scope="instance",
                                           target=""))
        self.assertEqual(reg.target, "")
        reg = parse_registration(_register(scope="org",
                                           target="forge-fellowship"))
        self.assertEqual(reg.scope, "org")
        self.assertEqual(
            _reason(parse_registration,
                    _register(scope="instance", target="x")),
            "runner_invalid")
        self.assertEqual(
            _reason(parse_registration,
                    _register(scope="repo", target="noslash")),
            "runner_invalid")

    def test_scope_and_token_refusals(self):
        self.assertEqual(
            _reason(parse_registration, _register(scope="team")),
            "runner_scope_unknown")
        self.assertEqual(
            _reason(parse_registration,
                    _register(registration_token="short")),
            "runner_token_refused")
        msg = _register()
        del msg["registration_token"]
        self.assertEqual(_reason(parse_registration, msg),
                         "runner_token_refused")

    def test_version_and_kind_refusals(self):
        self.assertEqual(
            _reason(parse_registration, _register(protocol=2)),
            "runner_version_refused")
        self.assertEqual(
            _reason(parse_registration, _register(kind="poll")),
            "runner_kind_unknown")

    def test_label_law(self):
        self.assertEqual(
            _reason(parse_registration,
                    _register(labels=["linux", "linux"])),
            "runner_invalid")
        self.assertEqual(
            _reason(parse_registration, _register(labels=[])),
            "runner_invalid")
        self.assertEqual(
            _reason(parse_registration,
                    _register(labels=["not a label"])),
            "runner_invalid")

    def test_unknown_key_refused_by_name(self):
        self.assertEqual(
            _reason(parse_registration, _register(bogus=1)),
            "runner_key_unknown")


class PollAndAssignmentTests(unittest.TestCase):
    def test_poll_parses_idle_and_busy(self):
        poll = parse_poll(_poll())
        self.assertEqual(poll.running_run_id, "")
        poll = parse_poll(_poll(running="run-9"))
        self.assertEqual(poll.running_run_id, "run-9")

    def test_wait_response_is_bounded(self):
        wait = parse_poll_response(
            {"kind": "poll", "protocol": 1,
             "response": "wait", "wait_seconds": 45})
        self.assertEqual(wait.wait_seconds, 45)
        wait = parse_poll_response(
            {"kind": "poll", "protocol": 1, "response": "wait"})
        self.assertEqual(wait.wait_seconds, 20)
        self.assertEqual(
            _reason(parse_poll_response,
                    {"kind": "poll", "protocol": 1,
                     "response": "wait", "wait_seconds": 9999}),
            "runner_invalid")

    def test_assignment_parses(self):
        offer = parse_assignment(_offer())
        self.assertEqual(offer.run_id, "run-1")
        self.assertEqual(len(offer.steps), 2)
        self.assertEqual(offer.steps[0].run,
                         "python3 -m unittest")
        self.assertEqual(offer.env_names, ("CI", "SAMVERK_TOKEN"))
        self.assertEqual(offer.timeout_minutes, 30)

    def test_assignment_never_carries_values(self):
        self.assertEqual(
            _reason(parse_assignment,
                    _offer(env={"SAMVERK_TOKEN": "value"})),
            "runner_invalid")
        self.assertEqual(
            _reason(parse_assignment, _offer(secrets=["x"])),
            "runner_invalid")

    def test_assignment_shape_refusals(self):
        self.assertEqual(
            _reason(parse_assignment, _offer(oid="xyz")),
            "runner_invalid")
        self.assertEqual(
            _reason(parse_assignment, _offer(steps=[])),
            "runner_invalid")
        self.assertEqual(
            _reason(parse_assignment,
                    _offer(steps=[{"uses": "actions/checkout"}])),
            "runner_invalid")
        self.assertEqual(
            _reason(parse_assignment,
                    _offer(env_names=["not a name"])),
            "runner_invalid")

    def test_label_law_between_poll_and_assignment(self):
        poll = parse_poll(_poll())
        offer = parse_assignment(_offer())
        self.assertIsNone(check_assignment_labels(offer, poll))
        arm_offer = parse_assignment(
            _offer(runner_labels=["linux", "arm"]))
        self.assertEqual(
            _reason(check_assignment_labels, arm_offer, poll),
            "runner_label_mismatch")
        busy = parse_poll(_poll(running="run-9"))
        self.assertEqual(
            _reason(check_assignment_labels, offer, busy),
            "runner_invalid")

    def test_reply_law(self):
        reply = parse_assignment_reply(
            {"kind": "assignment_reply", "protocol": 1,
             "run_id": "run-1", "job_id": "test",
             "decision": "accept"})
        self.assertEqual(reply.decision, "accept")
        self.assertEqual(
            _reason(parse_assignment_reply,
                    {"kind": "assignment_reply", "protocol": 1,
                     "run_id": "run-1", "job_id": "test",
                     "decision": "decline"}),
            "runner_invalid")
        reply = parse_assignment_reply(
            {"kind": "assignment_reply", "protocol": 1,
             "run_id": "run-1", "job_id": "test",
             "decision": "decline",
             "reason": "no arm builder free"})
        self.assertEqual(reply.reason, "no arm builder free")


class LogStreamTests(unittest.TestCase):
    def test_chunk_parses_and_sequence_is_checked(self):
        chunk = parse_log_chunk(_chunk(), expected_sequence=1)
        self.assertEqual(chunk.text, "hello\n")
        self.assertEqual(
            _reason(parse_log_chunk, _chunk(sequence=3),
                    expected_sequence=2),
            "runner_log_sequence")

    def test_chunk_shape_refusals(self):
        self.assertEqual(
            _reason(parse_log_chunk, _chunk(stream="merged")),
            "runner_invalid")
        self.assertEqual(
            _reason(parse_log_chunk, _chunk(text="")),
            "runner_invalid")
        self.assertEqual(
            _reason(parse_log_chunk,
                    _chunk(text="x" * 20000)),
            "runner_invalid")

    def test_stream_must_be_gapless_and_in_order(self):
        chunks = [parse_log_chunk(_chunk(sequence=1)),
                  parse_log_chunk(_chunk(sequence=2,
                                         text="world\n")),
                  parse_log_chunk(_chunk(step_index=2,
                                         sequence=1,
                                         stream="stderr",
                                         text="warn\n"))]
        self.assertEqual(validate_log_stream(chunks),
                         len("hello\nworld\nwarn\n"))
        gapped = [parse_log_chunk(_chunk(sequence=1)),
                  parse_log_chunk(_chunk(sequence=3))]
        self.assertEqual(
            _reason(validate_log_stream, gapped),
            "runner_log_sequence")
        backwards = [
            parse_log_chunk(_chunk(step_index=2, sequence=1)),
            parse_log_chunk(_chunk(step_index=1, sequence=1))]
        self.assertEqual(
            _reason(validate_log_stream, backwards),
            "runner_log_sequence")

    def test_heartbeat_parses(self):
        beat = parse_heartbeat(
            {"kind": "heartbeat", "protocol": 1,
             "run_id": "run-1", "job_id": "test",
             "step_index": 0, "elapsed_seconds": 5})
        self.assertEqual(beat.step_index, 0)
        self.assertEqual(
            _reason(parse_heartbeat,
                    {"kind": "heartbeat", "protocol": 1,
                     "run_id": "run-1", "job_id": "test",
                     "step_index": -1, "elapsed_seconds": 5}),
            "runner_invalid")


class ConclusionTests(unittest.TestCase):
    def test_aggregate_precedence(self):
        self.assertEqual(
            aggregate_conclusion(["success", "skipped"]),
            "success")
        self.assertEqual(
            aggregate_conclusion(["skipped", "skipped"]),
            "skipped")
        self.assertEqual(
            aggregate_conclusion(["cancelled", "failure"]),
            "failure")
        self.assertEqual(
            aggregate_conclusion(["cancelled", "timed_out"]),
            "timed_out")
        self.assertEqual(
            _reason(aggregate_conclusion, []), "runner_invalid")

    def test_conclusion_parses_against_its_offer(self):
        offer = parse_assignment(_offer())
        report = parse_conclusion(_conclusion(), offer)
        self.assertEqual(report.conclusion, "success")
        self.assertEqual(report.duration_seconds, 42)
        self.assertEqual(len(report.steps), 2)

    def test_conclusion_must_agree_with_steps(self):
        lying = _conclusion(
            steps=[{"index": 1, "name": "unit",
                    "conclusion": "failure"},
                   {"index": 2, "name": "",
                    "conclusion": "success"}],
            summary="unit failed")
        self.assertEqual(_reason(parse_conclusion, lying),
                         "runner_conclusion_mismatch")
        softened = _conclusion(
            conclusion="neutral",
            steps=[{"index": 1, "name": "unit",
                    "conclusion": "failure"},
                   {"index": 2, "name": "",
                    "conclusion": "success"}],
            summary="unit failed")
        self.assertEqual(_reason(parse_conclusion, softened),
                         "runner_conclusion_mismatch")

    def test_failure_needs_its_summary(self):
        report = _conclusion(
            conclusion="failure",
            steps=[{"index": 1, "name": "unit",
                    "conclusion": "failure"},
                   {"index": 2, "name": "",
                    "conclusion": "skipped"}],
            summary="unit tests failed: 3 errors")
        self.assertEqual(parse_conclusion(report).conclusion,
                         "failure")
        report["summary"] = ""
        self.assertEqual(_reason(parse_conclusion, report),
                         "runner_invalid")

    def test_conclusion_against_wrong_offer_refused(self):
        offer = parse_assignment(_offer(run_id="run-2"))
        self.assertEqual(
            _reason(parse_conclusion, _conclusion(), offer),
            "runner_conclusion_mismatch")
        short = _conclusion(
            steps=[{"index": 1, "name": "unit",
                    "conclusion": "success"}])
        self.assertEqual(
            _reason(parse_conclusion, short,
                    parse_assignment(_offer())),
            "runner_conclusion_mismatch")


class EnvelopeTests(unittest.TestCase):
    def test_dispatcher_judges_every_kind(self):
        self.assertEqual(
            parse_message(_register()).name, "longship-1")
        self.assertEqual(parse_message(_poll()).runner,
                         "longship-1")
        self.assertEqual(parse_message(_offer()).job_id, "test")
        self.assertEqual(parse_message(_chunk()).sequence, 1)
        self.assertEqual(
            parse_message(_conclusion()).conclusion, "success")
        wait = parse_message({"kind": "poll", "protocol": 1,
                              "response": "wait",
                              "wait_seconds": 10})
        self.assertEqual(wait.wait_seconds, 10)

    def test_unknown_kind_refused(self):
        self.assertEqual(
            _reason(parse_message,
                    {"kind": "teleport", "protocol": 1}),
            "runner_kind_unknown")
        self.assertEqual(
            _reason(parse_message, {"protocol": 1}),
            "runner_kind_unknown")


class AuditAndPageTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.addCleanup(self.conn.close)

    def test_pins_hold(self):
        self.assertEqual(schema_version(self.conn), 140)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 142)

    def test_audit_clean_on_live_instance(self):
        audit = audit_runner_protocol(self.conn)
        self.assertTrue(audit.protocol_ok)
        self.assertTrue(audit.stands_cleanly, audit)
        self.assertEqual(audit.events_scanned, 142)
        self.assertGreater(audit.tables_scanned, 0)

    def test_audit_catches_planted_table(self):
        self.conn.execute(
            "CREATE TABLE runner_backdoor (id INTEGER)")
        audit = audit_runner_protocol(self.conn)
        self.assertFalse(audit.stands_cleanly)
        self.assertIn(
            "runner_backdoor", audit.offending_tables)
        self.conn.execute("DROP TABLE runner_backdoor")
        self.conn.execute(
            "CREATE TABLE runs (runner_id TEXT)")
        audit = audit_runner_protocol(self.conn)
        self.assertFalse(audit.stands_cleanly)
        self.assertIn("runs.runner_id", audit.offending_columns)

    def test_page_says_the_contract_in_words(self):
        audit = audit_runner_protocol(self.conn)
        page = render_runner_protocol_page(audit)
        self.assertIn("stands cleanly", page)
        self.assertIn("Runner protocol (S-316)", page)
        self.assertIn("registers", page)
        self.assertNotIn("<script", page)


if __name__ == "__main__":
    unittest.main()
