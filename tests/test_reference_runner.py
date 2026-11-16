"""S-318 acceptance battery: reference runner.

Acceptance (roadmap S-318): Reference runner --
a small native runner program (no Docker) that
executes jobs in a working directory with
environment discipline; good enough to prove
the protocol end-to-end.

The centre is samverk/reference_runner.py: a
standalone runner speaking S-316 whole --
register and poll messages judged by S-316's
own parsers, the label law judged by the runner
itself (a decline in words, the job never run),
accept before running, a heartbeat per step,
numbered log chunks re-judged as one stream,
and exactly one conclusion built through
S-316's aggregate and judged against the
assignment. Environment discipline: the child
env is built from nothing -- runner context,
the closed host allowlist, and exactly the
assignment's env_names valued locally; denied
names refused in any position, a named value
missing refused, an unnamed value refused.
Working-directory discipline: one fresh
directory per job inside a root that must
already exist; a dirty directory refused.
Execution law: steps in order, failure skips
the rest, the shared timeout budget (narrowed
by an operator ceiling) concludes timed_out,
cancellation lands between steps. No migration
(schema 129 stands); taxonomy unmoved at 135
(33 auth / 89 repo / 13 admin).

Counted with: python3 -m unittest tests.test_reference_runner
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db, taxonomy
from samverk.db import schema_version
from samverk.reference_runner import (
    AGENT_VERSION, BASE_ENV_ALLOWLIST, ENV_DENYLIST,
    ReferenceRunner, ReferenceRunnerError,
    audit_reference_runner, build_child_env, main,
    render_reference_runner_page, resolve_workdir,
    split_log_text)
from samverk.runner_protocol import (
    MAX_LOG_CHUNK_CHARS, parse_assignment,
    parse_conclusion, parse_poll_response,
    validate_log_stream, parse_log_chunk)

OID = "a" * 40


def offer_payload(steps=None, labels=("self-hosted",),
                  env_names=(), run_id="run-1",
                  job_id="build", timeout=5):
    return {
        "kind": "assignment", "protocol": 1,
        "response": "assignment", "run_id": run_id,
        "job_id": job_id, "workflow": "CI",
        "repository": "octo/samverk", "oid": OID,
        "steps": steps if steps is not None else [
            {"name": "hello", "run": "echo hello-world"}],
        "runner_labels": list(labels),
        "env_names": list(env_names),
        "timeout_minutes": timeout,
    }


class RunnerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "work"
        self.root.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def runner(self, **kw):
        kw.setdefault("labels", ("self-hosted",))
        return ReferenceRunner(self.root, **kw)


class TestEndToEnd(RunnerCase):
    def test_success_speaks_the_protocol_whole(self):
        seen = []
        runner = self.runner(sink=seen.append)
        result = runner.run_assignment(offer_payload())
        self.assertEqual(result.decision, "accept")
        self.assertEqual(result.step_conclusions, ("success",))
        self.assertEqual(result.conclusion.conclusion, "success")
        kinds = [m["kind"] for m in result.messages]
        self.assertEqual(kinds[0], "assignment_reply")
        self.assertEqual(kinds[1], "heartbeat")
        self.assertIn("log_chunk", kinds)
        self.assertEqual(kinds[-1], "conclusion")
        self.assertEqual(seen, list(result.messages))
        texts = "".join(m["text"] for m in result.messages
                        if m["kind"] == "log_chunk")
        self.assertIn("hello-world", texts)
        # The conclusion re-judges against the offer.
        offer = parse_assignment(offer_payload())
        again = parse_conclusion(result.messages[-1], offer)
        self.assertEqual(again.conclusion, "success")

    def test_log_stream_rejudges_gapless(self):
        runner = self.runner()
        result = runner.run_assignment(offer_payload(steps=[
            {"name": "one", "run": "echo a; echo b"},
            {"name": "two", "run": "echo c >&2"},
        ]))
        chunks = [parse_log_chunk(m) for m in result.messages
                  if m["kind"] == "log_chunk"]
        total = validate_log_stream(chunks)
        self.assertGreater(total, 0)
        streams = {(c.step_index, c.stream) for c in chunks}
        self.assertIn((2, "stderr"), streams)

    def test_wait_answer_runs_nothing(self):
        runner = self.runner()
        answer = runner.handle_poll_response({
            "kind": "poll", "protocol": 1,
            "response": "wait", "wait_seconds": 7})
        self.assertEqual(answer.wait_seconds, 7)
        self.assertEqual(runner.messages, [])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_assignment_via_poll_response(self):
        runner = self.runner()
        result = runner.handle_poll_response(offer_payload())
        self.assertEqual(result.conclusion.conclusion, "success")

    def test_registration_and_poll_messages_judge(self):
        runner = self.runner()
        message = runner.registration_message(
            name="ref-1", scope="repo", target="octo/samverk",
            registration_token="x" * 24)
        self.assertEqual(message["agent_version"], AGENT_VERSION)
        self.assertFalse(hasattr(runner, "registration_token"))
        poll = runner.poll_message(name="ref-1")
        self.assertEqual(poll["labels"], ["self-hosted"])

    def test_workdir_is_the_jobs_own_and_steps_run_there(self):
        runner = self.runner()
        result = runner.run_assignment(offer_payload(steps=[
            {"name": "write", "run": "echo data > proof.txt"},
            {"name": "read", "run": "cat proof.txt"},
        ]))
        workdir = Path(result.workdir)
        self.assertTrue(workdir.is_dir())
        self.assertEqual(workdir.parent, self.root.resolve())
        self.assertEqual(
            (workdir / "proof.txt").read_text().strip(), "data")
        self.assertEqual(result.step_conclusions,
                         ("success", "success"))


class TestExecutionLaw(RunnerCase):
    def test_failure_skips_the_rest(self):
        runner = self.runner()
        result = runner.run_assignment(offer_payload(steps=[
            {"name": "ok", "run": "true"},
            {"name": "bad", "run": "echo oops >&2; exit 3"},
            {"name": "never", "run": "touch should-not-exist"},
        ]))
        self.assertEqual(result.step_conclusions,
                         ("success", "failure", "skipped"))
        self.assertEqual(result.conclusion.conclusion, "failure")
        self.assertIn("exit code 3", result.conclusion.summary)
        self.assertFalse(
            (Path(result.workdir) / "should-not-exist").exists())

    def test_timeout_concludes_timed_out(self):
        runner = self.runner(max_step_seconds=0.3)
        result = runner.run_assignment(offer_payload(steps=[
            {"name": "slow", "run": "sleep 5"},
            {"name": "after", "run": "true"},
        ]))
        self.assertEqual(result.step_conclusions,
                         ("timed_out", "skipped"))
        self.assertEqual(result.conclusion.conclusion, "timed_out")

    def test_cancel_lands_between_steps(self):
        runner = self.runner()
        def sink(message):
            if message["kind"] == "heartbeat" \
                    and message["step_index"] == 1:
                runner.cancel()
        runner.sink = sink
        result = runner.run_assignment(offer_payload(steps=[
            {"name": "one", "run": "true"},
            {"name": "two", "run": "touch should-not-exist"},
        ]))
        self.assertEqual(result.step_conclusions,
                         ("success", "cancelled"))
        self.assertEqual(result.conclusion.conclusion, "cancelled")
        self.assertFalse(
            (Path(result.workdir) / "should-not-exist").exists())

    def test_label_mismatch_declines_in_words(self):
        runner = self.runner(labels=("arm64",))
        result = runner.run_assignment(offer_payload())
        self.assertEqual(result.decision, "decline")
        self.assertIsNone(result.conclusion)
        self.assertEqual(result.step_conclusions, ())
        self.assertEqual(len(result.messages), 1)
        self.assertIn("self-hosted",
                      result.messages[0]["reason"])
        self.assertEqual(list(self.root.iterdir()), [])


class TestEnvironmentDiscipline(RunnerCase):
    def offer(self, env_names=()):
        return parse_assignment(offer_payload(env_names=env_names))

    def test_child_env_is_built_from_nothing(self):
        env = build_child_env(
            self.offer(env_names=("GREETING",)),
            {"GREETING": "hi"},
            base_env={"PATH": "/usr/bin", "HOME": "/home/x",
                      "SECRET_LEAK": "no", "LANG": "C"})
        self.assertEqual(env["GREETING"], "hi")
        self.assertEqual(env["PATH"], "/usr/bin")
        self.assertNotIn("HOME", env)
        self.assertNotIn("SECRET_LEAK", env)
        self.assertEqual(env["SAMVERK_RUN_ID"], "run-1")
        self.assertEqual(env["SAMVERK_OID"], OID)

    def test_named_value_missing_is_refused(self):
        with self.assertRaises(ReferenceRunnerError) as ctx:
            build_child_env(self.offer(env_names=("NEEDED",)), {})
        self.assertEqual(ctx.exception.reason, "runner_env_missing")

    def test_unnamed_value_is_refused(self):
        with self.assertRaises(ReferenceRunnerError) as ctx:
            build_child_env(self.offer(), {"SMUGGLED": "x"})
        self.assertEqual(ctx.exception.reason, "runner_env_unnamed")

    def test_denylisted_names_refused_in_any_position(self):
        for name in ("LD_PRELOAD", "PYTHONPATH", "BASH_ENV"):
            with self.assertRaises(ReferenceRunnerError) as ctx:
                build_child_env(self.offer(env_names=(name,)),
                                {name: "x"})
            self.assertEqual(ctx.exception.reason,
                             "runner_env_refused")
        self.assertFalse(set(BASE_ENV_ALLOWLIST) & ENV_DENYLIST)

    def test_context_names_cannot_be_supplied(self):
        with self.assertRaises(ReferenceRunnerError) as ctx:
            build_child_env(
                self.offer(env_names=("SAMVERK_OID",)),
                {"SAMVERK_OID": "b" * 40})
        self.assertEqual(ctx.exception.reason, "runner_env_refused")

    def test_step_sees_named_value_and_context_only(self):
        runner = self.runner()
        result = runner.run_assignment(
            offer_payload(
                steps=[{"name": "env",
                        "run": "echo val=$GREETING;"
                               "echo oid=$SAMVERK_OID;"
                               "echo leak=${LEAK_ME_NOT:-absent}"}],
                env_names=("GREETING",)),
            {"GREETING": "from-local"})
        texts = "".join(m["text"] for m in result.messages
                        if m["kind"] == "log_chunk")
        self.assertIn("val=from-local", texts)
        self.assertIn(f"oid={OID}", texts)
        self.assertIn("leak=absent", texts)
        self.assertEqual(result.conclusion.conclusion, "success")

    def test_missing_named_value_refuses_before_running(self):
        runner = self.runner()
        with self.assertRaises(ReferenceRunnerError) as ctx:
            runner.run_assignment(
                offer_payload(env_names=("NEEDED",)), {})
        self.assertEqual(ctx.exception.reason, "runner_env_missing")
        self.assertEqual(list(self.root.iterdir()), [])


class TestWorkdirDiscipline(RunnerCase):
    def test_missing_root_is_an_operator_error(self):
        offer = parse_assignment(offer_payload())
        with self.assertRaises(ReferenceRunnerError) as ctx:
            resolve_workdir(Path(self.tmp.name) / "nope", offer)
        self.assertEqual(ctx.exception.reason,
                         "runner_workdir_missing")

    def test_dirty_directory_is_refused(self):
        runner = self.runner()
        first = runner.run_assignment(offer_payload(steps=[
            {"name": "w", "run": "echo x > f.txt"}]))
        self.assertEqual(first.conclusion.conclusion, "success")
        with self.assertRaises(ReferenceRunnerError) as ctx:
            runner.run_assignment(offer_payload())
        self.assertEqual(ctx.exception.reason,
                         "runner_workdir_dirty")

    def test_distinct_jobs_get_distinct_directories(self):
        runner = self.runner()
        one = runner.run_assignment(offer_payload(run_id="run-1"))
        two = runner.run_assignment(offer_payload(run_id="run-2"))
        self.assertNotEqual(one.workdir, two.workdir)


class TestChunking(unittest.TestCase):
    def test_empty_text_splits_to_nothing(self):
        self.assertEqual(split_log_text(""), [])

    def test_lines_kept_whole_and_bounded(self):
        text = "".join(f"line {i}\n" for i in range(5000))
        chunks = split_log_text(text)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(
            len(c) <= MAX_LOG_CHUNK_CHARS for c in chunks))
        self.assertEqual("".join(chunks), text)

    def test_one_overlong_line_is_hard_split(self):
        text = "x" * (MAX_LOG_CHUNK_CHARS * 2 + 5)
        chunks = split_log_text(text)
        self.assertEqual("".join(chunks), text)
        self.assertTrue(all(
            len(c) <= MAX_LOG_CHUNK_CHARS for c in chunks))


class TestProgramFace(RunnerCase):
    def write_json(self, name, payload):
        path = Path(self.tmp.name) / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_main_runs_one_assignment(self):
        assignment = self.write_json("a.json", offer_payload())
        out = Path(self.tmp.name) / "out.jsonl"
        code = main(["--work-root", str(self.root),
                     "--assignment", str(assignment),
                     "--out", str(out)])
        self.assertEqual(code, 0)
        lines = [json.loads(line) for line
                 in out.read_text().splitlines()]
        self.assertEqual(lines[-1]["kind"], "conclusion")
        self.assertEqual(lines[-1]["conclusion"], "success")

    def test_main_exit_code_follows_the_conclusion(self):
        assignment = self.write_json("a.json", offer_payload(
            steps=[{"name": "bad", "run": "exit 2"}]))
        out = Path(self.tmp.name) / "out.jsonl"
        code = main(["--work-root", str(self.root),
                     "--assignment", str(assignment),
                     "--out", str(out)])
        self.assertEqual(code, 1)

    def test_module_runs_as_a_program(self):
        assignment = self.write_json("a.json", offer_payload())
        out = Path(self.tmp.name) / "out.jsonl"
        repo = Path(__file__).resolve().parent.parent
        done = subprocess.run(
            [sys.executable, "-m", "samverk.reference_runner",
             "--work-root", str(self.root),
             "--assignment", str(assignment),
             "--out", str(out)],
            cwd=str(repo), capture_output=True, text=True,
            timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(out.exists())


class TestInvariants(RunnerCase):
    def test_no_migration_and_taxonomy_unmoved(self):
        with db.init_db(Path(self.tmp.name) / "inv.db") as conn:
            db.migrate(conn)
            self.assertEqual(schema_version(conn), 132)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 138)

    def test_audit_stands_cleanly(self):
        with db.init_db(Path(self.tmp.name) / "inv.db") as conn:
            db.migrate(conn)
            audit = audit_reference_runner(conn)
        self.assertTrue(audit.stands_cleanly, audit)
        self.assertGreater(audit.tables_scanned, 0)

    def test_audit_catches_a_runner_table_by_a_back_door(self):
        with db.init_db(Path(self.tmp.name) / "inv.db") as conn:
            db.migrate(conn)
            conn.execute(
                "CREATE TABLE runner_jobs (id INTEGER)")
            audit = audit_reference_runner(conn)
        self.assertIn("runner_jobs", audit.offending_tables)
        self.assertFalse(audit.stands_cleanly)

    def test_page_says_the_discipline_in_words(self):
        page = render_reference_runner_page()
        self.assertIn("Reference runner (S-318)", page)
        self.assertIn("no Docker", page)
        with db.init_db(Path(self.tmp.name) / "inv.db") as conn:
            db.migrate(conn)
            page = render_reference_runner_page(
                audit_reference_runner(conn))
        self.assertIn("stands cleanly", page)


if __name__ == "__main__":
    unittest.main()
