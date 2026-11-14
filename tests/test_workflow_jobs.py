"""S-315 acceptance battery: workflow jobs and steps model.

Acceptance (roadmap S-315): Jobs and steps model
-- jobs of shell steps on a runner, needs-graph
between jobs, matrix expansion honestly scoped.

The centre is the pure planner: a jobs mapping
parses into exact JobDefs (steps in document
order, runner labels, timeout, env), the
needs-graph orders jobs deterministically and
in waves with unknown needs, self-needs and
cycles refused by name, a matrix expands to its
cartesian product in declaration order with
exclude applied and every dishonest shortcut
refused -- include by name, past-the-limit
expansions whole rather than truncated, an
exclude-all expansion as an error rather than
an empty success -- and a run plan wires each
instance to every instance of the jobs it
needs. Integration: S-313 definitions lift into
the model whole, and the audit checks the model
against the live instance with a planted
workflow-jobs table proving it would catch one
arriving ahead of its slice.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.db import schema_version
from samverk.workflow_format import parse_workflow
from samverk.workflow_jobs import (
    MAX_JOBS_PER_WORKFLOW, MAX_MATRIX_AXES,
    MAX_MATRIX_COMBINATIONS, MAX_MATRIX_VALUES_PER_AXIS,
    MAX_STEPS_PER_JOB, JobDef, JobsError,
    audit_workflow_jobs, build_run_plan, expand_job,
    expand_matrix, jobs_from_definition, parse_jobs,
    parse_matrix, render_workflow_jobs_page,
    schedule_order, schedule_waves)

ROOT = Path(__file__).resolve().parent.parent


def _reason(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except JobsError as exc:
        return exc.reason
    raise AssertionError("expected JobsError")


def _job(**overrides):
    spec = {"runner": "linux",
            "steps": [{"run": "echo hi"}]}
    spec.update(overrides)
    return spec


class JobModelTests(unittest.TestCase):
    def test_minimal_job_parses(self):
        jobs = parse_jobs({"test": _job()})
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job.id, "test")
        self.assertEqual(job.runner, ("linux",))
        self.assertEqual(job.needs, ())
        self.assertEqual(job.steps[0].run, "echo hi")
        self.assertIsNone(job.matrix)
        self.assertTrue(job.fail_fast)

    def test_steps_keep_document_order_and_fields(self):
        jobs = parse_jobs({"build": _job(steps=[
            {"name": "One", "run": "make one",
             "working-directory": "src", "shell": "bash",
             "env": {"CC": "cc"}},
            {"run": "make two"}])})
        steps = jobs[0].steps
        self.assertEqual([s.run for s in steps],
                         ["make one", "make two"])
        self.assertEqual(steps[0].name, "One")
        self.assertEqual(steps[0].working_directory, "src")
        self.assertEqual(steps[0].shell, "bash")
        self.assertEqual(steps[0].env, (("CC", "cc"),))
        self.assertEqual(steps[1].name, "")

    def test_runner_list_and_job_fields(self):
        jobs = parse_jobs({"test": _job(
            runner=["linux", "self-hosted"], name="Tests",
            **{"timeout-minutes": 30}, env={"CI": "1"})})
        job = jobs[0]
        self.assertEqual(job.runner, ("linux", "self-hosted"))
        self.assertEqual(job.name, "Tests")
        self.assertEqual(job.timeout_minutes, 30)
        self.assertEqual(job.env, (("CI", "1"),))

    def test_uses_refused_by_name(self):
        self.assertEqual(
            _reason(parse_jobs, {"t": _job(
                steps=[{"uses": "actions/checkout@v4"}])}),
            "jobs_uses_refused")
        self.assertEqual(
            _reason(parse_jobs, {"t": _job(uses="x/y@v1")}),
            "jobs_uses_refused")

    def test_expression_refused(self):
        self.assertEqual(
            _reason(parse_jobs, {"t": _job(
                steps=[{"run": "echo ${{ secrets.X }}"}])}),
            "jobs_expression_refused")

    def test_shape_refusals(self):
        self.assertEqual(_reason(parse_jobs, {}), "jobs_invalid")
        self.assertEqual(_reason(parse_jobs, {"t": _job(steps=[])}),
                         "jobs_invalid")
        self.assertEqual(
            _reason(parse_jobs, {"t": _job(runner="")}),
            "jobs_invalid")
        self.assertEqual(
            _reason(parse_jobs, {"bad id!": _job()}), "jobs_invalid")
        self.assertEqual(
            _reason(parse_jobs, {"t": _job(bogus=1)}), "jobs_invalid")
        self.assertEqual(
            _reason(parse_jobs, {"t": _job(
                **{"timeout-minutes": 0})}), "jobs_invalid")
        self.assertEqual(
            _reason(parse_jobs, {"t": _job(
                **{"timeout-minutes": True})}), "jobs_invalid")

    def test_step_cap_refuses_whole(self):
        steps = [{"run": f"echo {i}"}
                 for i in range(MAX_STEPS_PER_JOB + 1)]
        self.assertEqual(
            _reason(parse_jobs, {"t": _job(steps=steps)}),
            "jobs_too_large")

    def test_job_cap_refuses_whole(self):
        many = {f"j{i}": _job()
                for i in range(MAX_JOBS_PER_WORKFLOW + 1)}
        self.assertEqual(_reason(parse_jobs, many), "jobs_too_large")


class NeedsGraphTests(unittest.TestCase):
    def test_diamond_order_and_waves(self):
        jobs = parse_jobs({
            "a": _job(),
            "b": _job(needs="a"),
            "c": _job(needs=["a"]),
            "d": _job(needs=["b", "c"])})
        self.assertEqual(schedule_order(jobs), ("a", "b", "c", "d"))
        self.assertEqual(schedule_waves(jobs),
                         (("a",), ("b", "c"), ("d",)))

    def test_declaration_order_breaks_ties(self):
        jobs = parse_jobs({
            "z": _job(), "m": _job(), "a": _job()})
        self.assertEqual(schedule_order(jobs), ("z", "m", "a"))
        self.assertEqual(schedule_waves(jobs), (("z", "m", "a"),))

    def test_chain_waves(self):
        jobs = parse_jobs({
            "a": _job(), "b": _job(needs="a"),
            "c": _job(needs="b")})
        self.assertEqual(schedule_waves(jobs),
                         (("a",), ("b",), ("c",)))

    def test_unknown_need_refused(self):
        self.assertEqual(
            _reason(parse_jobs, {"a": _job(needs="ghost")}),
            "jobs_needs_unknown")

    def test_self_need_refused(self):
        self.assertEqual(
            _reason(parse_jobs, {"a": _job(needs="a")}),
            "jobs_needs_self")

    def test_cycle_refused_and_named(self):
        with self.assertRaises(JobsError) as ctx:
            parse_jobs({"a": _job(needs="b"),
                        "b": _job(needs="a")})
        self.assertEqual(ctx.exception.reason, "jobs_cycle")
        self.assertIn("a", str(ctx.exception))
        self.assertIn("b", str(ctx.exception))

    def test_duplicate_need_refused(self):
        self.assertEqual(
            _reason(parse_jobs, {"a": _job(),
                                 "b": _job(needs=["a", "a"])}),
            "jobs_invalid")


class MatrixTests(unittest.TestCase):
    def _matrix_job(self, matrix, **kw):
        return parse_jobs({"test": _job(
            strategy={"matrix": matrix}, **kw)})[0]

    def test_expansion_order_and_instance_names(self):
        job = self._matrix_job(
            {"os": ["linux", "macos"], "py": ["3.11", "3.12"]})
        instances = expand_job(job)
        self.assertEqual(
            [i.id for i in instances],
            ["test (linux, 3.11)", "test (linux, 3.12)",
             "test (macos, 3.11)", "test (macos, 3.12)"])
        self.assertEqual(
            instances[0].matrix_values,
            (("os", "linux"), ("py", "3.11")))

    def test_non_matrix_job_expands_to_one(self):
        job = parse_jobs({"solo": _job()})[0]
        instances = expand_job(job)
        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0].id, "solo")
        self.assertEqual(instances[0].matrix_values, ())

    def test_exclude_removes_matching_only(self):
        job = self._matrix_job({
            "os": ["linux", "macos"], "py": ["3.11", "3.12"],
            "exclude": [{"os": "macos", "py": "3.11"}]})
        self.assertEqual(
            [i.id for i in expand_job(job)],
            ["test (linux, 3.11)", "test (linux, 3.12)",
             "test (macos, 3.12)"])

    def test_include_refused_by_name(self):
        self.assertEqual(
            _reason(self._matrix_job,
                    {"os": ["linux"],
                     "include": [{"os": "linux", "extra": "1"}]}),
            "matrix_include_not_carried")

    def test_combination_limit_refuses_whole(self):
        axes = {f"a{i}": [0, 1] for i in range(9)}  # 512 combos
        with self.assertRaises(JobsError) as ctx:
            self._matrix_job(axes)
        self.assertEqual(ctx.exception.reason, "matrix_too_large")
        self.assertIn(str(MAX_MATRIX_COMBINATIONS),
                      str(ctx.exception))
        self.assertIn("512", str(ctx.exception))

    def test_axis_and_value_limits(self):
        too_many_axes = {f"a{i}": [1]
                         for i in range(MAX_MATRIX_AXES + 1)}
        self.assertEqual(
            _reason(self._matrix_job, too_many_axes),
            "matrix_too_large")
        too_many_values = {"os": list(
            range(MAX_MATRIX_VALUES_PER_AXIS + 1))}
        self.assertEqual(
            _reason(self._matrix_job, too_many_values),
            "matrix_too_large")

    def test_matrix_shape_refusals(self):
        self.assertEqual(
            _reason(self._matrix_job, {}), "matrix_invalid")
        self.assertEqual(
            _reason(self._matrix_job, {"os": []}), "matrix_invalid")
        self.assertEqual(
            _reason(self._matrix_job, {"os": ["linux", "linux"]}),
            "matrix_invalid")
        self.assertEqual(
            _reason(self._matrix_job, {"os": [{"x": 1}]}),
            "matrix_invalid")
        self.assertEqual(
            _reason(self._matrix_job,
                    {"os": ["linux"],
                     "exclude": [{"os": "windows"}]}),
            "matrix_invalid")
        self.assertEqual(
            _reason(self._matrix_job,
                    {"os": ["linux"],
                     "exclude": [{"nope": "linux"}]}),
            "matrix_invalid")

    def test_exclude_everything_refused(self):
        job = self._matrix_job(
            {"os": ["linux"], "exclude": [{"os": "linux"}]})
        self.assertEqual(
            _reason(expand_job, job), "matrix_empty")

    def test_fail_fast_carried_and_validated(self):
        job = parse_jobs({"t": _job(strategy={
            "matrix": {"os": ["linux"]}, "fail-fast": False})})[0]
        self.assertFalse(job.fail_fast)
        self.assertEqual(
            _reason(parse_jobs, {"t": _job(strategy={
                "matrix": {"os": ["linux"]},
                "fail-fast": "yes"})}), "jobs_invalid")
        self.assertEqual(
            _reason(parse_jobs, {"t": _job(strategy={
                "max-parallel": 2,
                "matrix": {"os": ["linux"]}})}), "jobs_invalid")

    def test_expand_matrix_direct(self):
        spec = parse_matrix({"x": [1, 2], "y": ["a"]}, "j")
        self.assertEqual(spec.combinations, 2)
        self.assertEqual(
            expand_matrix(spec, "j"),
            ((("x", 1), ("y", "a")), (("x", 2), ("y", "a"))))


class RunPlanTests(unittest.TestCase):
    def test_plan_wires_instance_needs_to_whole_matrix(self):
        jobs = parse_jobs({
            "test": _job(strategy={
                "matrix": {"os": ["linux", "macos"]}}),
            "ship": _job(needs="test")})
        plan = build_run_plan(jobs)
        ship = [i for i in plan.instances if i.id == "ship"][0]
        self.assertEqual(
            ship.needs, ("test (linux)", "test (macos)"))
        self.assertEqual(plan.order,
                         ("test (linux)", "test (macos)", "ship"))
        self.assertEqual(
            plan.waves,
            (("test (linux)", "test (macos)"), ("ship",)))

    def test_plan_from_s313_definition(self):
        definition = parse_workflow(
            "name: CI\n"
            "on: push\n"
            "jobs:\n"
            "  test:\n"
            "    runner: linux\n"
            "    steps:\n"
            "      - run: python3 -m unittest discover -s tests\n"
            "  lint:\n"
            "    runner: linux\n"
            "    needs: test\n"
            "    steps:\n"
            "      - run: echo lint\n")
        jobs = jobs_from_definition(definition)
        self.assertEqual([j.id for j in jobs], ["test", "lint"])
        plan = build_run_plan(jobs)
        self.assertEqual(plan.order, ("test", "lint"))
        self.assertEqual(plan.instances[0].steps[0].run,
                         "python3 -m unittest discover -s tests")
        self.assertTrue(all(j.matrix is None for j in jobs))

    def test_s313_document_with_strategy_still_refused_there(self):
        # Honest scope: S-313's door does not admit
        # strategy yet; S-315 judges job mappings.
        with self.assertRaises(Exception):
            parse_workflow(
                "on: push\n"
                "jobs:\n"
                "  test:\n"
                "    runner: linux\n"
                "    strategy:\n"
                "      matrix:\n"
                "        os: [linux]\n"
                "    steps:\n"
                "      - run: echo hi\n")

    def test_yaml_subset_jobs_mapping_end_to_end(self):
        from samverk.issue_templates import parse_yaml_subset
        parsed = parse_yaml_subset(
            "jobs:\n"
            "  test:\n"
            "    runner: linux\n"
            "    strategy:\n"
            "      matrix:\n"
            "        os: [linux, macos]\n"
            "    steps:\n"
            "      - run: echo hi\n")
        jobs = parse_jobs(parsed["jobs"])
        self.assertEqual(
            [i.id for i in expand_job(jobs[0])],
            ["test (linux)", "test (macos)"])


class PinsAndAuditTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.addCleanup(self.conn.close)

    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 128)
        self.assertEqual(db.MIGRATIONS[-1][0], 128)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)
        families = {}
        for event in taxonomy.AUDIT_EVENTS:
            families[event.split(".")[0]] = (
                families.get(event.split(".")[0], 0) + 1)
        self.assertEqual(
            families, {"auth": 33, "repo": 89, "admin": 13})
        self.assertFalse(
            any("workflow" in e for e in taxonomy.AUDIT_EVENTS))

    def test_limits_are_the_stated_ones(self):
        self.assertEqual(MAX_MATRIX_COMBINATIONS, 256)
        self.assertEqual(MAX_MATRIX_AXES, 16)
        self.assertEqual(MAX_MATRIX_VALUES_PER_AXIS, 64)
        self.assertEqual(MAX_JOBS_PER_WORKFLOW, 256)
        self.assertEqual(MAX_STEPS_PER_JOB, 100)

    def test_audit_stands_cleanly_on_fresh_instance(self):
        audit = audit_workflow_jobs(self.conn)
        self.assertTrue(audit.stands_cleanly)
        self.assertTrue(audit.limits_ok)
        self.assertGreater(audit.tables_scanned, 0)
        self.assertEqual(audit.events_scanned, 135)
        self.assertEqual(audit.offending_tables, ())
        self.assertEqual(audit.offending_columns, ())
        self.assertEqual(audit.offending_events, ())

    def test_audit_catches_planted_workflow_jobs_table(self):
        self.conn.execute(
            "CREATE TABLE workflow_jobs (id INTEGER PRIMARY KEY)")
        self.conn.commit()
        audit = audit_workflow_jobs(self.conn)
        self.assertFalse(audit.stands_cleanly)
        self.assertIn("workflow_jobs", audit.offending_tables)

    def test_render_page_states_scope_and_audit(self):
        page = render_workflow_jobs_page(
            audit_workflow_jobs(self.conn))
        self.assertIn("S-315", page)
        self.assertIn("stands cleanly", page)
        self.assertIn("never", page)
        self.assertIn("truncated", page)
        bare = render_workflow_jobs_page()
        self.assertIn("Matrix, honestly scoped", bare)


if __name__ == "__main__":
    unittest.main()
