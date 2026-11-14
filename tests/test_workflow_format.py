"""S-313 acceptance battery: workflow format decision.

Acceptance (roadmap S-313): Workflow format
decision -- Samverk's own YAML shape
(.samverk/workflows/), GitHub-familiar in
structure, documented as ours; the study file
records the mapping and the deliberate
differences.

The decision here is ADOPTED. The centre is the
validator plus the audit: real workflow documents
parse into definitions, every deliberate refusal
fires by name (uses:, ${{, unknown keys, the YAML
1.1 boolean-on trap), and the audit checks the
decision against the live instance -- no table,
column or audit event carries a workflow yet --
with a planted workflow table proving the audit
would catch one arriving ahead of S-314.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.db import schema_version
from samverk.workflow_format import (
    DECISION, DIFFERENCES, GITHUB_DIRECTORY, MAPPINGS,
    MUST_NOT_BREAK, TOP_LEVEL_KEYS, TRIGGER_EVENTS,
    WORKFLOW_DIRECTORY, WorkflowFormatError,
    audit_workflow_format, discover_workflows,
    get_difference, get_invariant, get_mapping,
    is_github_workflow_path, is_workflow_path,
    parse_workflow, render_workflow_format_page,
    validate_workflow)

ROOT = Path(__file__).resolve().parent.parent

EXPECTED_MAPPING_IDS = (
    "location", "name", "triggers", "jobs", "runs-on",
    "needs", "steps-run", "steps-uses", "env",
    "permissions", "concurrency", "expressions", "matrix")
EXPECTED_DIFFERENCE_IDS = (
    "ours-directory", "no-marketplace-actions",
    "runner-labels-not-images", "on-is-a-word",
    "no-expression-language-yet", "read-by-default",
    "unknown-keys-refused")
EXPECTED_INVARIANT_IDS = (
    "runner-is-not-the-forge", "no-docker-anywhere",
    "fork-safety-in-the-scheduler",
    "secrets-masked-and-scoped", "checks-bound-to-the-commit",
    "skipped-is-not-passed", "schedule-on-default-branch",
    "every-action-audited")
GOOD = (
    "name: CI\n"
    "on: [push, pull_request]\n"
    "permissions: read-all\n"
    "jobs:\n"
    "  test:\n"
    "    runner: [linux, self-hosted]\n"
    "    steps:\n"
    "      - name: Run the tests\n"
    "        run: python3 -m unittest discover -s tests\n")


class WorkflowFormatTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.conn = db.init_db(Path(self._td.name) / "samverk.db")
        self.addCleanup(self.conn.close)

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(WorkflowFormatError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    # pins
    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 128)
        self.assertEqual(db.MIGRATIONS[-1][0], 128)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)
        families = {}
        for event in taxonomy.AUDIT_EVENTS:
            families[event.split(".")[0]] = (
                families.get(event.split(".")[0], 0) + 1)
        self.assertEqual(families, {"auth": 33, "repo": 89, "admin": 13})
        self.assertFalse(any("workflow" in e for e in taxonomy.AUDIT_EVENTS))

    def test_decision_and_directories(self):
        self.assertEqual(DECISION, "adopted")
        self.assertEqual(WORKFLOW_DIRECTORY, ".samverk/workflows")
        self.assertEqual(GITHUB_DIRECTORY, ".github/workflows")
        self.assertEqual(
            TRIGGER_EVENTS,
            ("push", "pull_request", "tag", "schedule",
             "workflow_dispatch"))
        self.assertIn("on", TOP_LEVEL_KEYS)
        self.assertIn("jobs", TOP_LEVEL_KEYS)

    # the mapping and the differences
    def test_mapping_ids_exact_and_substantive(self):
        self.assertEqual(tuple(m.id for m in MAPPINGS), EXPECTED_MAPPING_IDS)
        for mapping in MAPPINGS:
            self.assertIn(mapping.relation,
                          {"same", "renamed", "ours", "not-carried"})
            self.assertGreater(len(mapping.note), 40, mapping.id)
            self.assertIs(get_mapping(mapping.id), mapping)
        self.assertEqual(get_mapping("runs-on").samverk, "runner")
        self.assertEqual(get_mapping("steps-uses").samverk, "")
        self.assertEqual(self._reason(get_mapping, "secrets"),
                         "mapping_unknown")

    def test_difference_ids_exact_and_substantive(self):
        self.assertEqual(
            tuple(d.id for d in DIFFERENCES), EXPECTED_DIFFERENCE_IDS)
        for difference in DIFFERENCES:
            self.assertTrue(difference.title.strip(), difference.id)
            self.assertGreater(len(difference.detail), 80, difference.id)
            self.assertIs(get_difference(difference.id), difference)
        self.assertEqual(self._reason(get_difference, "speed"),
                         "difference_unknown")

    def test_invariant_ids_exact(self):
        self.assertEqual(
            tuple(i.id for i in MUST_NOT_BREAK), EXPECTED_INVARIANT_IDS)
        for invariant in MUST_NOT_BREAK:
            self.assertIs(get_invariant(invariant.id), invariant)
            self.assertGreater(len(invariant.statement), 60, invariant.id)
        self.assertEqual(self._reason(get_invariant, "fast-runners"),
                         "invariant_unknown")

    def test_study_file_records_mapping_and_differences(self):
        text = (ROOT / "docs" / "WORKFLOW_FORMAT.md").read_text()
        for needle in (".samverk/workflows/", "runs-on", "runner",
                       "uses:", "${{", "read-only", "S-314", "S-320"):
            self.assertIn(needle, text)

    # paths
    def test_workflow_paths(self):
        self.assertTrue(is_workflow_path(".samverk/workflows/ci.yml"))
        self.assertTrue(is_workflow_path(".samverk/workflows/ci.yaml"))
        self.assertFalse(is_workflow_path(".github/workflows/ci.yml"))
        self.assertFalse(is_workflow_path(".samverk/workflows/deep/ci.yml"))
        self.assertFalse(is_workflow_path(".samverk/workflows/ci.txt"))
        self.assertFalse(is_workflow_path("samverk/workflows/ci.yml"))
        self.assertFalse(is_workflow_path(None))
        self.assertTrue(is_github_workflow_path(".github/workflows/ci.yml"))
        self.assertFalse(is_github_workflow_path(".samverk/workflows/ci.yml"))

    def test_discover_workflows(self):
        found = discover_workflows([
            ".github/workflows/old.yml", ".samverk/workflows/b.yml",
            "README.md", ".samverk/workflows/a.yaml",
            ".samverk/workflows/b.yml"])
        self.assertEqual(found, (".samverk/workflows/a.yaml",
                                 ".samverk/workflows/b.yml"))
        self.assertEqual(self._reason(discover_workflows, None),
                         "workflow_invalid")

    # the validator: happy paths
    def test_parse_good_workflow(self):
        definition = parse_workflow(GOOD)
        self.assertEqual(definition.name, "CI")
        self.assertEqual(definition.triggers, ("push", "pull_request"))
        self.assertEqual(len(definition.jobs), 1)
        job = definition.jobs[0]
        self.assertEqual(job.id, "test")
        self.assertEqual(job.runner, ("linux", "self-hosted"))
        self.assertEqual(job.steps[0].run,
                         "python3 -m unittest discover -s tests")

    def test_parse_trigger_forms(self):
        one = parse_workflow(
            "on: push\njobs:\n  a:\n    runner: linux\n"
            "    steps:\n      - run: echo hi\n")
        self.assertEqual(one.triggers, ("push",))
        mapped = parse_workflow(
            "on:\n  schedule:\n    - cron: '0 3 * * *'\n"
            "  workflow_dispatch:\njobs:\n  a:\n    runner: linux\n"
            "    steps:\n      - run: echo hi\n")
        self.assertEqual(mapped.triggers, ("schedule", "workflow_dispatch"))
        needs = parse_workflow(
            "on: push\njobs:\n  a:\n    runner: linux\n"
            "    steps:\n      - run: echo a\n"
            "  b:\n    runner: linux\n    needs: a\n"
            "    steps:\n      - run: echo b\n")
        self.assertEqual(needs.jobs[1].needs, ("a",))

    # the validator: the deliberate refusals
    def test_uses_refused_by_name(self):
        text = ("on: push\njobs:\n  a:\n    runner: linux\n"
                "    steps:\n      - uses: actions/checkout@v4\n")
        self.assertEqual(self._reason(parse_workflow, text),
                         "workflow_uses_refused")

    def test_expression_refused_by_name(self):
        text = ("on: push\njobs:\n  a:\n    runner: linux\n"
                "    steps:\n      - run: echo ${{ secrets.TOKEN }}\n")
        self.assertEqual(self._reason(parse_workflow, text),
                         "workflow_expression_refused")

    def test_boolean_on_trap_refused(self):
        parsed = {True: "push", "jobs": {
            "a": {"runner": "linux", "steps": [{"run": "echo hi"}]}}}
        self.assertEqual(self._reason(validate_workflow, parsed),
                         "workflow_invalid")
        try:
            validate_workflow(parsed)
        except WorkflowFormatError as exc:
            self.assertIn("YAML 1.1", str(exc))

    def test_unknown_keys_refused(self):
        base = "on: push\njobs:\n  a:\n    runner: linux\n    steps:\n      - run: echo hi\n"
        self.assertEqual(self._reason(parse_workflow,
            "strategy: x\n" + base), "workflow_invalid")
        self.assertEqual(self._reason(parse_workflow,
            base.replace("runner:", "runs-on:")), "workflow_invalid")
        self.assertEqual(self._reason(parse_workflow,
            base.replace("- run:", "- with: x\n        run:")),
            "workflow_invalid")

    def test_shape_refusals(self):
        self.assertEqual(self._reason(parse_workflow, "name: only\n"),
                         "workflow_invalid")
        self.assertEqual(self._reason(parse_workflow,
            "on: push\njobs:\n  a:\n    steps:\n      - run: echo hi\n"),
            "workflow_invalid")
        self.assertEqual(self._reason(parse_workflow,
            "on: push\njobs:\n  a:\n    runner: linux\n    steps: []\n"),
            "workflow_invalid")
        self.assertEqual(self._reason(parse_workflow,
            "on: [push, deploy]\njobs:\n  a:\n    runner: linux\n"
            "    steps:\n      - run: echo hi\n"), "workflow_invalid")
        self.assertEqual(self._reason(parse_workflow,
            "on: push\npermissions: everything\njobs:\n  a:\n"
            "    runner: linux\n    steps:\n      - run: echo hi\n"),
            "workflow_invalid")
        self.assertEqual(self._reason(parse_workflow, 42),
                         "workflow_invalid")
        self.assertEqual(self._reason(parse_workflow, "on: [push\n"),
                         "form_invalid")

    def test_needs_graph_refusals(self):
        head = "on: push\njobs:\n"
        self.assertEqual(self._reason(parse_workflow, head +
            "  a:\n    runner: linux\n    needs: ghost\n"
            "    steps:\n      - run: echo a\n"), "workflow_invalid")
        self.assertEqual(self._reason(parse_workflow, head +
            "  a:\n    runner: linux\n    needs: a\n"
            "    steps:\n      - run: echo a\n"), "workflow_invalid")
        self.assertEqual(self._reason(parse_workflow, head +
            "  a:\n    runner: linux\n    needs: b\n"
            "    steps:\n      - run: echo a\n"
            "  b:\n    runner: linux\n    needs: a\n"
            "    steps:\n      - run: echo b\n"), "workflow_invalid")

    # the audit
    def test_audit_clean_on_live_instance(self):
        audit = audit_workflow_format(self.conn)
        self.assertTrue(audit.decided_cleanly)
        self.assertEqual(audit.decision, "adopted")
        self.assertGreater(audit.tables_scanned, 50)
        self.assertEqual(audit.events_scanned, 135)
        self.assertEqual(audit.offending_tables, ())
        self.assertEqual(audit.offending_events, ())

    def test_audit_catches_planted_workflow_table(self):
        self.conn.execute(
            "CREATE TABLE workflow_runs (id INTEGER PRIMARY KEY, "
            "workflow_state TEXT)")
        audit = audit_workflow_format(self.conn)
        self.assertFalse(audit.decided_cleanly)
        self.assertIn("workflow_runs", audit.offending_tables)
        self.assertIn("workflow_runs.workflow_state",
                      audit.offending_columns)

    # rendering
    def test_render_page(self):
        page = render_workflow_format_page(audit_workflow_format(self.conn))
        self.assertIn("adopted", page)
        self.assertIn(".samverk/workflows/", page)
        self.assertIn("runs-on", page)
        self.assertIn("stands cleanly", page)
        bare = render_workflow_format_page()
        self.assertIn("deliberate differences", bare)
        self.assertNotIn("Checked against this instance", bare)


if __name__ == "__main__":
    unittest.main()
