"""S-319 acceptance battery: CI secrets.

Acceptance (roadmap S-319): CI secrets -- per-repo/org
secrets encrypted at rest under instance keys, injected
as env, masked in logs (S-018's filter reused).

The centre is samverk/ci_secrets.py: per-org and
per-repo secrets under the name law (canonical
uppercase env names; the SAMVERK_ prefix reserved;
S-318's env denylist and the GIT_CONFIG family
refused), values sealed v1: under a caller-supplied
256-bit instance key (HMAC-SHA256 keystream and tag,
S-035's shape) so a tampered row or the wrong key
fails closed as ci_secret_unreadable and no key at
all refuses as encryption_unavailable; steward
guards per scope (org owner / repo admin / site
admin, a private-repo stranger answered
repo_not_found); set replacing a standing name in
place; resolve_env laying repo secrets over the
owning org's; masking through S-018's redact_text;
the acts witnessed on the standing scoped verbs
with name-only details; and the findability walk --
secrets home -> one click -> the scope's secrets
page. Migration 130 (schema 129 -> 130); taxonomy
unmoved at 135 (33 auth / 89 repo / 13 admin).

Counted with: python3 -m unittest tests.test_ci_secrets
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.ci_secrets import (
    MAX_SECRET_VALUE_CHARS, SECRET_AREAS, SECRET_SCOPES,
    SECRETS_HOME_PATH, CISecret, CISecretsError, CISecretsStore,
    audit_ci_secrets, ci_secret_areas, decrypt_value,
    encrypt_value, mask_text, render_secrets_home,
    render_secrets_page, secret_to_dict, secrets_page_path,
    validate_scope, validate_secret_name, validate_secret_value)
from samverk.db import schema_version
from samverk.organizations import OrganizationStore
from samverk.repositories import RepositoryStore

PW = "correct horse battery"
T0 = 1_700_000_000
KEY = bytes(range(32))
OTHER_KEY = bytes(reversed(range(32)))
SEEDED = "seeded-plaintext-marker-319"


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


def _reason(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except CISecretsError as exc:
        return exc.reason
    raise AssertionError("expected CISecretsError")


class PureLawTests(unittest.TestCase):
    def test_scope_law(self):
        self.assertEqual(tuple(SECRET_SCOPES), ("org", "repo"))
        for scope in SECRET_SCOPES:
            self.assertEqual(validate_scope(scope), scope)
        for bad in ("instance", "user", "", None, 7):
            self.assertEqual(
                _reason(validate_scope, bad),
                "ci_secret_scope_unknown", bad)

    def test_target_law(self):
        self.assertEqual(
            secrets_page_path("org", "Acme"),
            "/orgs/acme/settings/secrets")
        self.assertEqual(
            secrets_page_path("repo", "Volmarr/Widget"),
            "/volmarr/widget/settings/secrets")
        for scope, bad in (("org", "a/b"), ("org", ""),
                           ("repo", "widget"), ("repo", "a/b/c"),
                           ("repo", "")):
            self.assertEqual(
                _reason(secrets_page_path, scope, bad),
                "ci_secret_target_invalid", (scope, bad))

    def test_name_law_shape(self):
        self.assertEqual(validate_secret_name("api_key"), "API_KEY")
        self.assertEqual(validate_secret_name("_TOKEN"), "_TOKEN")
        self.assertEqual(validate_secret_name("A1"), "A1")
        self.assertEqual(
            validate_secret_name("Deploy_Token2"), "DEPLOY_TOKEN2")
        for bad in ("1ABC", "A-B", "A B", "A.B", "", None, 42):
            self.assertEqual(
                _reason(validate_secret_name, bad),
                "ci_secret_name_invalid", bad)

    def test_name_law_reserved_prefix(self):
        for name in ("SAMVERK_FOO", "samverk_x", "Samverk_Job"):
            self.assertEqual(
                _reason(validate_secret_name, name),
                "ci_secret_name_reserved", name)

    def test_name_law_denylist_and_git_config(self):
        for name in ("LD_PRELOAD", "ld_preload", "PYTHONPATH",
                     "NODE_OPTIONS", "BASH_ENV", "GIT_DIR",
                     "GIT_CONFIG", "GIT_CONFIG_COUNT",
                     "git_config_x", "Git_Config_Namespace"):
            self.assertEqual(
                _reason(validate_secret_name, name),
                "ci_secret_name_refused", name)

    def test_value_law(self):
        self.assertEqual(validate_secret_value("x"), "x")
        self.assertEqual(
            validate_secret_value("x" * MAX_SECRET_VALUE_CHARS),
            "x" * MAX_SECRET_VALUE_CHARS)
        for bad in ("", None, 42, "a\x00b",
                    "x" * (MAX_SECRET_VALUE_CHARS + 1)):
            self.assertEqual(
                _reason(validate_secret_value, bad),
                "ci_secret_value_invalid", repr(bad)[:30])

    def test_encryption_round_trip(self):
        for value in ("s3cr3t", SEEDED, "pässwörd-🔑", "x" * 5000):
            stored = encrypt_value(KEY, value)
            self.assertTrue(stored.startswith("v1:"))
            self.assertNotIn(value, stored)
            self.assertEqual(decrypt_value(KEY, stored), value)
        # A fresh nonce per value: same plaintext seals twice,
        # differently.
        self.assertNotEqual(
            encrypt_value(KEY, "same"), encrypt_value(KEY, "same"))

    def test_tamper_and_wrong_key_fail_closed(self):
        stored = encrypt_value(KEY, "topsecret-value")
        flipped = stored[:-1] + ("A" if stored[-1] != "A" else "B")
        self.assertEqual(
            _reason(decrypt_value, KEY, flipped),
            "ci_secret_unreadable")
        self.assertEqual(
            _reason(decrypt_value, KEY, stored[:12]),
            "ci_secret_unreadable")
        self.assertEqual(
            _reason(decrypt_value, OTHER_KEY, stored),
            "ci_secret_unreadable")
        for bad in ("v0:AAAA", "hello", "", None):
            self.assertEqual(
                _reason(decrypt_value, KEY, bad),
                "ci_secret_unreadable", bad)

    def test_mask_text_pure(self):
        out = mask_text(
            f"deploy used {SEEDED} twice {SEEDED}", (SEEDED,))
        self.assertNotIn(SEEDED, out)
        self.assertEqual(out.count("[REDACTED]"), 2)
        # S-018's standing layers ride along untouched.
        out2 = mask_text("password: hunter2pass", ())
        self.assertNotIn("hunter2pass", out2)
        self.assertIn("[REDACTED]", out2)

    def test_findability_map_is_data(self):
        areas = ci_secret_areas()
        self.assertEqual([a["scope"] for a in areas], ["org", "repo"])
        self.assertEqual(len(areas), len(SECRET_AREAS))
        self.assertEqual(SECRETS_HOME_PATH, "/settings/secrets")
        templates = {a["scope"]: a["path_template"] for a in areas}
        self.assertEqual(
            templates["org"], "/orgs/{target}/settings/secrets")
        self.assertEqual(
            templates["repo"], "/{target}/settings/secrets")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(
            self.conn, audit=self.audit, time_fn=self.clock)
        self.admin = self.accounts.register("admina", PW)
        with self.conn:
            self.conn.execute(
                "UPDATE users SET is_admin = 1 WHERE id = ?",
                (self.admin.id,))
        self.owner = self.accounts.register("volmarr", PW)
        self.mallory = self.accounts.register("mallory", PW)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.pub = self.repos.create_repository(
            self.owner.id, "volmarr", "widget", visibility="public")
        self.priv = self.repos.create_repository(
            self.owner.id, "volmarr", "secret", visibility="private")
        self.orgs = OrganizationStore(
            self.conn, self.accounts, audit=self.audit,
            time_fn=self.clock)
        self.org = self.orgs.create_organization(self.owner.id, "acme")
        # An org-owned repository row (the house direct-insert
        # shape): acme/anvil belongs to the organization.
        with self.conn:
            self.conn.execute(
                "INSERT INTO repositories (owner, owner_lower, name,"
                " name_lower, created_by, created_at, description,"
                " visibility) VALUES (?, ?, ?, ?, ?, ?, '', ?)",
                ("acme", "acme", "anvil", "anvil", self.owner.id, T0,
                 "public"))
        self.store = CISecretsStore(
            self.conn, self.accounts, self.repos,
            audit=self.audit, encryption_key=KEY, time_fn=self.clock)
        self.nokey = CISecretsStore(
            self.conn, self.accounts, self.repos,
            audit=self.audit, time_fn=self.clock)
        self.wrongkey = CISecretsStore(
            self.conn, self.accounts, self.repos,
            audit=self.audit, encryption_key=OTHER_KEY,
            time_fn=self.clock)

    def _audit(self, action):
        rows = self.conn.execute(
            "SELECT actor_id, target_kind, target_id, detail"
            " FROM audit_log WHERE action = ? ORDER BY seq",
            (action,)).fetchall()
        return [(r["actor_id"], r["target_kind"], r["target_id"],
                 json.loads(r["detail"]) if r["detail"] else {})
                for r in rows]

    # -- pins -------------------------------------------------

    def test_pins_hold(self):
        self.assertEqual(schema_version(self.conn), 132)
        self.assertEqual(db.MIGRATIONS[-1][0], 132)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 138)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 92)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        tables = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("ci_secrets", tables)

    # -- setting, resolving, and the value's roads -------------

    def test_set_and_resolve_repo_secret(self):
        secret = self.store.set_secret(
            self.owner.id, "repo", "Volmarr/Widget", "api_key",
            "repo-value-319")
        self.assertIsInstance(secret, CISecret)
        self.assertEqual(secret.scope, "repo")
        self.assertEqual(secret.target, "volmarr/widget")
        self.assertEqual(secret.name, "API_KEY")
        self.assertEqual(secret.created_by, self.owner.id)
        self.assertEqual(secret.created_at, T0)
        self.assertEqual(secret.updated_at, T0)
        self.assertEqual(
            self.store.resolve_env("volmarr/widget"),
            {"API_KEY": "repo-value-319"})
        got = self.store.get_secret(
            self.owner.id, "repo", "volmarr/widget", "api_key")
        self.assertEqual(got, secret)
        self.assertIsNone(self.store.get_secret(
            self.owner.id, "repo", "volmarr/widget", "MISSING"))

    def test_no_read_carries_a_value(self):
        secret = self.store.set_secret(
            self.owner.id, "repo", "volmarr/widget", "API_KEY",
            SEEDED)
        self.assertNotIn(SEEDED, repr(secret))
        face = secret_to_dict(secret)
        self.assertEqual(
            set(face), {"id", "scope", "target", "name",
                        "created_by", "created_at", "updated_at"})
        self.assertNotIn(SEEDED, str(face))
        listed = self.store.list_secrets(
            self.owner.id, "repo", "volmarr/widget")
        self.assertEqual([s.name for s in listed], ["API_KEY"])
        self.assertNotIn(SEEDED, str([secret_to_dict(s)
                                      for s in listed]))
        row = self.conn.execute(
            "SELECT value_enc FROM ci_secrets").fetchone()
        self.assertTrue(row["value_enc"].startswith("v1:"))
        self.assertNotIn(SEEDED, row["value_enc"])

    def test_db_file_swept_for_plaintext(self):
        self.store.set_secret(
            self.owner.id, "repo", "volmarr/widget", "API_KEY",
            SEEDED)
        self.store.set_secret(
            self.owner.id, "org", "acme", "ORG_TOKEN", SEEDED + "-org")
        db_bytes = (self.root / "samverk.db").read_bytes()
        self.assertNotIn(SEEDED.encode(), db_bytes)

    def test_replace_in_place(self):
        first = self.store.set_secret(
            self.owner.id, "repo", "volmarr/widget", "API_KEY",
            "first-value")
        self.clock.now = T0 + 600
        second = self.store.set_secret(
            self.admin.id, "repo", "volmarr/widget", "API_KEY",
            "second-value")
        self.assertEqual(second.id, first.id)
        self.assertEqual(second.created_at, T0)
        self.assertEqual(second.created_by, self.owner.id)
        self.assertEqual(second.updated_at, T0 + 600)
        self.assertEqual(
            len(self.store.list_secrets(
                self.owner.id, "repo", "volmarr/widget")), 1)
        self.assertEqual(
            self.store.resolve_env("volmarr/widget"),
            {"API_KEY": "second-value"})

    def test_set_judges_name_and_value_first(self):
        self.assertEqual(
            _reason(self.store.set_secret, self.owner.id, "repo",
                    "volmarr/widget", "LD_PRELOAD", "v"),
            "ci_secret_name_refused")
        self.assertEqual(
            _reason(self.store.set_secret, self.owner.id, "repo",
                    "volmarr/widget", "SAMVERK_X", "v"),
            "ci_secret_name_reserved")
        self.assertEqual(
            _reason(self.store.set_secret, self.owner.id, "repo",
                    "volmarr/widget", "GIT_CONFIG", "v"),
            "ci_secret_name_refused")
        self.assertEqual(
            _reason(self.store.set_secret, self.owner.id, "repo",
                    "volmarr/widget", "1BAD", "v"),
            "ci_secret_name_invalid")
        self.assertEqual(
            _reason(self.store.set_secret, self.owner.id, "repo",
                    "volmarr/widget", "FINE", ""),
            "ci_secret_value_invalid")
        self.assertEqual(
            _reason(self.store.set_secret, self.owner.id, "instance",
                    "", "FINE", "v"),
            "ci_secret_scope_unknown")
        self.assertEqual(
            self.store.list_secrets(
                self.owner.id, "repo", "volmarr/widget"), [])

    # -- steward guards ---------------------------------------

    def test_org_stewards_only(self):
        self.store.set_secret(
            self.owner.id, "org", "ACME", "ORG_TOKEN", "org-value")
        self.store.set_secret(
            self.admin.id, "org", "acme", "ADMIN_TOKEN", "admin-value")
        self.assertEqual(
            [s.name for s in self.store.list_secrets(
                self.owner.id, "org", "acme")],
            ["ADMIN_TOKEN", "ORG_TOKEN"])
        self.assertEqual(
            _reason(self.store.set_secret, self.mallory.id, "org",
                    "acme", "X", "v"), "ci_secret_not_permitted")
        self.assertEqual(
            _reason(self.store.list_secrets, self.mallory.id, "org",
                    "acme"), "ci_secret_not_permitted")
        self.assertEqual(
            _reason(self.store.get_secret, self.mallory.id, "org",
                    "acme", "ORG_TOKEN"), "ci_secret_not_permitted")
        self.assertEqual(
            _reason(self.store.delete_secret, self.mallory.id, "org",
                    "acme", "ORG_TOKEN"), "ci_secret_not_permitted")
        self.assertEqual(
            _reason(self.store.set_secret, self.owner.id, "org",
                    "ghost", "X", "v"), "org_not_found")

    def test_repo_stewards_only(self):
        self.store.set_secret(
            self.owner.id, "repo", "volmarr/widget", "A", "v1")
        self.store.set_secret(
            self.admin.id, "repo", "volmarr/secret", "B", "v2")
        # A reader of a public repo is not its admin.
        self.assertEqual(
            _reason(self.store.set_secret, self.mallory.id, "repo",
                    "volmarr/widget", "X", "v"),
            "ci_secret_not_permitted")
        self.assertEqual(
            _reason(self.store.list_secrets, self.mallory.id, "repo",
                    "volmarr/widget"), "ci_secret_not_permitted")
        # A stranger to a private repo learns nothing.
        self.assertEqual(
            _reason(self.store.set_secret, self.mallory.id, "repo",
                    "volmarr/secret", "X", "v"), "repo_not_found")
        self.assertEqual(
            _reason(self.store.list_secrets, self.mallory.id, "repo",
                    "volmarr/secret"), "repo_not_found")
        self.assertEqual(
            _reason(self.store.get_secret, self.mallory.id, "repo",
                    "volmarr/secret", "B"), "repo_not_found")
        self.assertEqual(
            _reason(self.store.delete_secret, self.mallory.id,
                    "repo", "volmarr/secret", "B"), "repo_not_found")
        self.assertEqual(
            _reason(self.store.set_secret, self.owner.id, "repo",
                    "volmarr/ghost", "X", "v"), "repo_not_found")
        self.assertEqual(
            _reason(self.store.set_secret, None, "repo",
                    "volmarr/widget", "X", "v"),
            "authentication_required")
        self.assertEqual(
            _reason(self.store.set_secret, 99999, "repo",
                    "volmarr/widget", "X", "v"), "no_such_user")

    # -- the key's law -------------------------------------------

    def test_no_key_refuses_set_and_resolve_but_not_metadata(self):
        self.assertEqual(
            _reason(self.nokey.set_secret, self.owner.id, "repo",
                    "volmarr/widget", "API_KEY", "v"),
            "encryption_unavailable")
        self.assertEqual(
            _reason(self.nokey.resolve_env, "volmarr/widget"),
            "encryption_unavailable")
        self.store.set_secret(
            self.owner.id, "repo", "volmarr/widget", "API_KEY", "v")
        self.assertEqual(
            [s.name for s in self.nokey.list_secrets(
                self.owner.id, "repo", "volmarr/widget")], ["API_KEY"])
        self.assertTrue(self.nokey.delete_secret(
            self.owner.id, "repo", "volmarr/widget", "API_KEY"))

    def test_tampered_row_and_wrong_key_fail_closed(self):
        self.store.set_secret(
            self.owner.id, "repo", "volmarr/widget", "API_KEY",
            "sealed-value")
        self.assertEqual(
            _reason(self.wrongkey.resolve_env, "volmarr/widget"),
            "ci_secret_unreadable")
        row = self.conn.execute(
            "SELECT value_enc FROM ci_secrets").fetchone()
        stored = row["value_enc"]
        tampered = stored[:-2] + ("AA" if not stored.endswith("AA")
                                  else "BB")
        with self.conn:
            self.conn.execute(
                "UPDATE ci_secrets SET value_enc = ?", (tampered,))
        self.assertEqual(
            _reason(self.store.resolve_env, "volmarr/widget"),
            "ci_secret_unreadable")
        audit = audit_ci_secrets(self.conn, KEY)
        self.assertFalse(audit.stands_cleanly)
        self.assertTrue(audit.problems)

    # -- delete and witness ---------------------------------------

    def test_delete_and_witness(self):
        self.store.set_secret(
            self.owner.id, "org", "acme", "ORG_TOKEN", "org-value",
            source_ip="192.0.2.7")
        self.store.set_secret(
            self.owner.id, "repo", "volmarr/widget", "API_KEY",
            "repo-value")
        org_rows = self._audit("auth.organization.update")
        org_sets = [d for _a, _k, _t, d in org_rows
                    if d.get("key") == "ci_secret.set"]
        self.assertEqual(len(org_sets), 1)
        self.assertEqual(org_sets[0]["scope"], "org")
        self.assertEqual(org_sets[0]["target"], "acme")
        self.assertEqual(org_sets[0]["name"], "ORG_TOKEN")
        self.assertNotIn("org-value", json.dumps(org_sets[0]))
        repo_rows = self._audit("repo.settings.change")
        repo_sets = [(k, t, d) for _a, k, t, d in repo_rows
                     if d.get("key") == "ci_secret.set"]
        self.assertEqual(len(repo_sets), 1)
        self.assertEqual(repo_sets[0][0], "repo")
        self.assertEqual(repo_sets[0][1], "volmarr/widget")
        self.assertEqual(repo_sets[0][2]["name"], "API_KEY")
        self.assertNotIn("repo-value", json.dumps(repo_sets[0][2]))
        self.assertTrue(self.store.delete_secret(
            self.owner.id, "repo", "volmarr/widget", "API_KEY"))
        self.assertFalse(self.store.delete_secret(
            self.owner.id, "repo", "volmarr/widget", "API_KEY"))
        self.assertEqual(
            self.store.resolve_env("volmarr/widget"), {})
        deletes = [d for _a, _k, _t, d in
                   self._audit("repo.settings.change")
                   if d.get("key") == "ci_secret.delete"]
        self.assertEqual(len(deletes), 1)
        self.assertEqual(deletes[0]["name"], "API_KEY")

    # -- resolution: precedence and names --------------------------

    def test_resolve_env_org_under_repo_precedence(self):
        self.store.set_secret(
            self.owner.id, "org", "acme", "SHARED", "org-shared")
        self.store.set_secret(
            self.owner.id, "org", "acme", "ORG_ONLY", "org-only")
        self.store.set_secret(
            self.admin.id, "repo", "acme/anvil", "SHARED",
            "repo-shared")
        self.store.set_secret(
            self.admin.id, "repo", "acme/anvil", "REPO_ONLY",
            "repo-only")
        self.assertEqual(
            self.store.resolve_env("acme/anvil"),
            {"SHARED": "repo-shared", "ORG_ONLY": "org-only",
             "REPO_ONLY": "repo-only"})
        self.assertEqual(
            self.store.resolve_scope_env("org", "acme"),
            {"SHARED": "org-shared", "ORG_ONLY": "org-only"})
        self.assertEqual(
            self.store.secret_names_for_repo("acme/anvil"),
            ["ORG_ONLY", "REPO_ONLY", "SHARED"])

    def test_user_owned_repo_gets_only_its_own(self):
        self.store.set_secret(
            self.owner.id, "org", "acme", "ORG_TOKEN", "org-value")
        self.store.set_secret(
            self.owner.id, "repo", "volmarr/widget", "API_KEY",
            "repo-value")
        self.assertEqual(
            self.store.resolve_env("volmarr/widget"),
            {"API_KEY": "repo-value"})
        self.assertEqual(
            self.store.secret_names_for_repo("volmarr/widget"),
            ["API_KEY"])
        self.assertEqual(
            self.store.secret_names_for_repo("volmarr/secret"), [])

    # -- masking ----------------------------------------------------

    def test_masking_roads(self):
        self.store.set_secret(
            self.owner.id, "org", "acme", "SHARED", "org-shared-319")
        self.store.set_secret(
            self.admin.id, "repo", "acme/anvil", "REPO_ONLY",
            "repo-only-319")
        line = "job env: org-shared-319 and repo-only-319 leaked"
        out = self.store.redact_for_repo(line, "acme/anvil")
        self.assertNotIn("org-shared-319", out)
        self.assertNotIn("repo-only-319", out)
        self.assertIn("[REDACTED]", out)
        out2 = self.store.redact_for_scope(
            "org says org-shared-319 repo-only-319", "org", "acme")
        self.assertNotIn("org-shared-319", out2)
        self.assertIn("repo-only-319", out2)
        out3 = self.store.redact_for_scope(
            "repo says repo-only-319", "repo", "acme/anvil")
        self.assertNotIn("repo-only-319", out3)

    # -- audit -------------------------------------------------------

    def test_audit_stands_cleanly_then_catches_damage(self):
        self.store.set_secret(
            self.owner.id, "repo", "volmarr/widget", "API_KEY", "v1")
        self.store.set_secret(
            self.owner.id, "org", "acme", "ORG_TOKEN", "v2")
        audit = audit_ci_secrets(self.conn, KEY)
        self.assertTrue(audit.stands_cleanly, audit.problems)
        self.assertEqual(audit.secrets_scanned, 2)
        audit_nokey = audit_ci_secrets(self.conn)
        self.assertTrue(audit_nokey.stands_cleanly)
        with self.conn:
            self.conn.execute(
                "INSERT INTO ci_secrets (scope, target, name,"
                " value_enc, created_by, created_at, updated_at)"
                " VALUES ('repo', 'volmarr/widget', 'PLAIN',"
                " 'not-a-sealed-blob', ?, ?, ?)",
                (self.owner.id, T0, T0))
        audit2 = audit_ci_secrets(self.conn, KEY)
        self.assertFalse(audit2.stands_cleanly)
        self.assertTrue(any("sealed" in p for p in audit2.problems))

    # -- pages ---------------------------------------------------------

    def test_pages_render_and_walk(self):
        home = render_secrets_home()
        self.assertIn("CI secrets", home)
        self.assertIn("/orgs/{target}/settings/secrets", home)
        self.assertIn("/{target}/settings/secrets", home)
        self.assertIn("Organization secrets", home)
        self.assertIn("Repository secrets", home)
        self.store.set_secret(
            self.owner.id, "repo", "volmarr/widget", "API_KEY",
            SEEDED)
        secrets = self.store.list_secrets(
            self.owner.id, "repo", "volmarr/widget")
        page = render_secrets_page(
            "repo", "volmarr/widget", secrets, csrf_token="csrf-x")
        self.assertIn("/volmarr/widget/settings/secrets/set", page)
        self.assertIn("/volmarr/widget/settings/secrets/delete", page)
        self.assertIn("API_KEY", page)
        self.assertIn("Set secret", page)
        self.assertIn(SECRETS_HOME_PATH, page)
        self.assertNotIn(SEEDED, page)
        empty = render_secrets_page("org", "acme", [])
        self.assertIn("No CI secrets set", empty)
        self.assertIn("/orgs/acme/settings/secrets/set", empty)


if __name__ == "__main__":
    unittest.main()
