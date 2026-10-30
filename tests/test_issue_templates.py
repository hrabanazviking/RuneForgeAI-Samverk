"""S-129 acceptance battery: issue templates.

Acceptance (roadmap S-129): Markdown templates and YAML
issue forms rendered as guided forms; blank issues can be
disallowed by owners.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.issue_templates import (
    IssueTemplateStore, TemplateError, assemble_body, compose_issue,
    parse_yaml_subset, render_choice_list, render_guided_form)
from samverk.issues import IssueError, IssueStore
from samverk.labels import LabelError, LabelStore
from samverk.repositories import RepositoryStore

FORM = """name: Bug report
description: File a bug report
title: "[Bug]: "
labels: [bug]
body:
  - type: markdown
    attributes:
      value: Thanks for taking the time to report this.
  - type: input
    id: version
    attributes:
      label: Version
      description: The version you were running.
      placeholder: e.g. 1.2.3
    validations:
      required: true
  - type: textarea
    id: what_happened
    attributes:
      label: What happened
  - type: dropdown
    id: severity
    attributes:
      label: Severity
      options:
        - low
        - high
    validations:
      required: true
  - type: checkboxes
    id: checks
    attributes:
      label: Checks
      options:
        - label: I searched existing issues
          required: true
        - label: I can reproduce this
"""

GOOD_VALUES = {
    "version": "1.2.3",
    "what_happened": "It crashed on save.",
    "severity": "high",
    "checks": ["I searched existing issues"],
}


class IssueTemplateTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.reader = self.accounts.register("yrsa", "correct horse battery")
        self.other = self.accounts.register("mallory", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.issues = IssueStore(self.conn, self.repos, self.accounts, audit=self.audit)
        self.labels = LabelStore(
            self.conn, self.repos, self.accounts, self.issues, audit=self.audit)
        self.templates = IssueTemplateStore(
            self.conn, self.repos, self.accounts, self.issues,
            labels=self.labels, audit=self.audit)
        self.repos.create_repository(self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(self.owner.id, "volmarr", "priv", visibility="private")

    # -- Markdown templates -------------------------------------------
    def test_markdown_template_crud_and_use(self):
        template = self.templates.create_markdown_template(
            self.owner, "volmarr", "pub", "Question",
            description="Ask a question", title="Question: ",
            body="## What I tried\n\n- ", labels=["question"])
        self.assertEqual(template.kind, "markdown")
        with self.assertRaises(TemplateError) as caught:
            self.templates.create_markdown_template(
                self.owner, "volmarr", "pub", "question", body="x")
        self.assertEqual(caught.exception.reason, "template_taken")
        issue = self.templates.create_issue_from_template(
            self.reader, "volmarr", "pub", "Question", {})
        self.assertEqual(issue.title, "Question:")
        self.assertIn("What I tried", issue.body)
        names = [label.name for label in
                 self.labels.labels_for_issue(None, "volmarr", "pub", issue.number)]
        self.assertEqual(names, ["question"])
        actions = [r["action"] for r in self.conn.execute(
            "SELECT action FROM audit_log"
            " WHERE action LIKE 'repo.issue_template.%'")]
        self.assertEqual(actions, ["repo.issue_template.create"])
        edited = self.templates.update_template(
            self.owner, "volmarr", "pub", "Question", body="## New body")
        self.assertEqual(edited.body, "## New body")
        gone = self.templates.delete_template(self.owner, "volmarr", "pub", "Question")
        self.assertEqual(gone.name, "Question")
        self.assertEqual(self.templates.list_templates(None, "volmarr", "pub"), [])
        with self.assertRaises(TemplateError) as caught:
            self.templates.create_markdown_template(
                self.owner, "volmarr", "pub", "Empty", body="  ")
        self.assertEqual(caught.exception.reason, "template_body_required")
        # A template naming a label that does not exist fails
        # whole at use time — no half-made issue behind it.
        self.templates.create_markdown_template(
            self.owner, "volmarr", "pub", "Broken", body="Body",
            title="Broken: ", labels=["nosuchlabel"])
        before = len(self.issues.list_issues(None, "volmarr", "pub"))
        with self.assertRaises(LabelError):
            self.templates.create_issue_from_template(
                self.reader, "volmarr", "pub", "Broken", {})
        self.assertEqual(
            len(self.issues.list_issues(None, "volmarr", "pub")), before)

    def test_markdown_guided_form_and_choice_list(self):
        self.templates.create_markdown_template(
            self.owner, "volmarr", "pub", "Bug <script>",
            description="Report a fault", title="[Bug]: ", body="Steps:\n")
        html = render_guided_form(
            self.templates.get_template(None, "volmarr", "pub", "Bug <script>"))
        self.assertIn("Bug &lt;script&gt;", html)
        self.assertIn('name="title"', html)
        self.assertIn("[Bug]:", html)
        self.assertIn('name="body"', html)
        self.assertIn("Title (required)", html)
        choices = render_choice_list(
            self.templates.list_templates(None, "volmarr", "pub"))
        self.assertIn("Report a fault", choices)
        self.assertIn("Blank issue", choices)
        choices = render_choice_list(
            self.templates.list_templates(None, "volmarr", "pub"),
            allow_blank=False)
        self.assertIn("Blank issues are turned off", choices)

    # -- YAML forms ------------------------------------------------------
    def test_form_parse_and_fields(self):
        template = self.templates.create_form_template(
            self.owner, "volmarr", "pub", FORM)
        self.assertEqual(template.kind, "form")
        self.assertEqual((template.name, template.title), ("Bug report", "[Bug]:"))
        self.assertEqual(template.labels, ("bug",))
        self.assertEqual(template.source, FORM)
        kinds = [(f.id, f.type) for f in template.fields]
        self.assertEqual(kinds, [("", "markdown"), ("version", "input"),
                                 ("what_happened", "textarea"),
                                 ("severity", "dropdown"),
                                 ("checks", "checkboxes")])
        version = template.fields[1]
        self.assertTrue(version.required)
        self.assertEqual(version.placeholder, "e.g. 1.2.3")
        checks = template.fields[4]
        self.assertEqual(checks.options,
                         ("I searched existing issues", "I can reproduce this"))
        self.assertEqual(checks.option_required, (True, False))

    def test_form_submission_assembles_issue(self):
        template = self.templates.create_form_template(
            self.owner, "volmarr", "pub", FORM)
        title, body = compose_issue(template, GOOD_VALUES)
        self.assertEqual(title, "[Bug]:")
        self.assertEqual(body, (
            "Thanks for taking the time to report this.\n\n"
            "### Version\n\n1.2.3\n\n"
            "### What happened\n\nIt crashed on save.\n\n"
            "### Severity\n\nhigh\n\n"
            "### Checks\n\n"
            "- [x] I searched existing issues\n"
            "- [ ] I can reproduce this"))
        issue = self.templates.create_issue_from_template(
            self.reader, "volmarr", "pub", "Bug report", GOOD_VALUES,
            title="Crash on save")
        self.assertEqual(issue.title, "Crash on save")
        names = [label.name for label in
                 self.labels.labels_for_issue(None, "volmarr", "pub", issue.number)]
        self.assertEqual(names, ["bug"])

    def test_form_submission_refusals_name_the_field(self):
        template = self.templates.create_form_template(
            self.owner, "volmarr", "pub", FORM)
        missing = dict(GOOD_VALUES); del missing["version"]
        with self.assertRaises(TemplateError) as caught:
            assemble_body(template, missing)
        self.assertEqual(caught.exception.reason, "field_required")
        self.assertIn("Version", str(caught.exception))
        bad_option = dict(GOOD_VALUES, severity="critical")
        with self.assertRaises(TemplateError) as caught:
            assemble_body(template, bad_option)
        self.assertEqual(caught.exception.reason, "field_option_invalid")
        unchecked = dict(GOOD_VALUES, checks=[])
        with self.assertRaises(TemplateError) as caught:
            assemble_body(template, unchecked)
        self.assertEqual(caught.exception.reason, "field_required")
        self.assertIn("I searched existing issues", str(caught.exception))
        unknown = dict(GOOD_VALUES, mood="calm")
        with self.assertRaises(TemplateError) as caught:
            assemble_body(template, unknown)
        self.assertEqual(caught.exception.reason, "field_unknown")

    def test_form_guided_rendering(self):
        template = self.templates.create_form_template(
            self.owner, "volmarr", "pub", FORM)
        html = render_guided_form(template)
        self.assertIn("Version (required)", html)
        self.assertIn("The version you were running.", html)
        self.assertIn('<select id="field-severity"', html)
        self.assertIn('<option value="high">high</option>', html)
        self.assertIn('name="checks"', html)
        self.assertIn("I searched existing issues (required)", html)
        self.assertIn("Thanks for taking the time", html)

    def test_yaml_subset_refusals(self):
        for bad in (
                "name: X\ndescription: Y\nbody:\n\t- type: markdown\n",
                "name: X\ndescription: Y\nbody: {type: markdown}\n",
                "name: X\ndescription: Y\nbody:\n  - type: wiki\n",
                "name: X\ndescription: Y\nbody:\n  - type: input\n"
                "    id: a\n    attributes:\n      placeholder: no label\n",
                "name: X\ndescription: Y\nbody:\n  - type: input\n"
                "    id: a\n    attributes:\n      label: A\n"
                "  - type: input\n    id: a\n    attributes:\n      label: B\n",
                'name: "unterminated\ndescription: Y\n'):
            with self.assertRaises(TemplateError, msg=bad) as caught:
                self.templates.create_form_template(
                    self.owner, "volmarr", "pub", bad)
            self.assertEqual(caught.exception.reason, "form_invalid", msg=bad)
        self.assertEqual(
            self.templates.list_templates(None, "volmarr", "pub"), [])

    def test_yaml_block_scalar_note(self):
        form = ("name: Note\ndescription: A note form\nbody:\n"
                "  - type: markdown\n    attributes:\n      value: |\n"
                "        First line\n        Second line\n")
        template = self.templates.create_form_template(
            self.owner, "volmarr", "pub", form)
        self.assertEqual(template.fields[0].value, "First line\nSecond line")
        parsed = parse_yaml_subset("a: [1, two, true]\nb: 'it''s'\n")
        self.assertEqual(parsed, {"a": [1, "two", True], "b": "it's"})

    def test_form_update_by_source_replacement(self):
        self.templates.create_form_template(self.owner, "volmarr", "pub", FORM)
        changed = FORM.replace("File a bug report", "Report a fault, guided")
        updated = self.templates.update_template(
            self.owner, "volmarr", "pub", "Bug report", source=changed)
        self.assertEqual(updated.description, "Report a fault, guided")
        with self.assertRaises(TemplateError) as caught:
            self.templates.update_template(
                self.owner, "volmarr", "pub", "Bug report", body="nope")
        self.assertEqual(caught.exception.reason, "template_body_invalid")

    # -- the blank-issue toggle -------------------------------------------
    def test_blank_issues_disallowed_by_owner(self):
        with self.assertRaises(TemplateError) as caught:
            self.templates.set_allow_blank_issues(
                self.owner, "volmarr", "pub", False)
        self.assertEqual(caught.exception.reason, "no_templates")
        self.templates.create_markdown_template(
            self.owner, "volmarr", "pub", "Bug", body="What happened?")
        self.assertTrue(self.templates.allow_blank_issues(None, "volmarr", "pub"))
        self.assertFalse(self.templates.set_allow_blank_issues(
            self.owner, "volmarr", "pub", False))
        with self.assertRaises(IssueError) as caught:
            self.issues.create_issue(self.reader, "volmarr", "pub", "Direct")
        self.assertEqual(caught.exception.reason, "blank_issue_not_allowed")
        issue = self.templates.create_issue_from_template(
            self.reader, "volmarr", "pub", "Bug", {}, title="Via template")
        self.assertEqual(issue.title, "Via template")
        row = self.conn.execute(
            "SELECT detail FROM audit_log WHERE action = 'repo.settings.change'"
            " ORDER BY seq DESC LIMIT 1").fetchone()
        self.assertIn('"allow_blank_issues"', row["detail"])
        self.assertTrue(self.templates.set_allow_blank_issues(
            self.owner, "volmarr", "pub", True))
        self.issues.create_issue(self.reader, "volmarr", "pub", "Direct again")

    # -- permissions ---------------------------------------------------------
    def test_permissions_and_private_uniform_answer(self):
        with self.assertRaises(TemplateError) as caught:
            self.templates.create_markdown_template(
                self.reader, "volmarr", "pub", "Nope", body="x")
        self.assertEqual(caught.exception.reason, "permission_denied")
        self.templates.create_markdown_template(
            self.owner, "volmarr", "priv", "Secret", body="Hidden body")
        self.assertEqual(len(self.templates.list_templates(
            self.owner, "volmarr", "priv")), 1)
        with self.assertRaises(TemplateError) as caught:
            self.templates.list_templates(self.other, "volmarr", "priv")
        self.assertEqual(caught.exception.reason, "repo_not_found")
        with self.assertRaises(TemplateError) as caught:
            self.templates.get_template(self.other, "volmarr", "priv", "Secret")
        self.assertEqual(caught.exception.reason, "repo_not_found")
        with self.assertRaises(TemplateError) as caught:
            self.templates.set_allow_blank_issues(
                self.reader, "volmarr", "pub", False)
        self.assertEqual(caught.exception.reason, "permission_denied")


if __name__ == "__main__":
    unittest.main()
