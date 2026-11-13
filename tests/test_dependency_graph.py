"""S-297 acceptance battery: dependency graph.

Acceptance (roadmap S-297): Dependency graph --
manifests parsed on push (requirements.txt,
package.json, go.mod, Cargo.toml, and the study
file's list) into a dependency table per repo.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import os, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.db import schema_version
from samverk.dependency_graph import (
    Dependency, DependencyGraphError, DependencyGraphReport,
    DependencyGraphStore, GraphState, ManifestOutcome,
    ParsedDependency, is_exact_pin, is_manifest_path,
    is_vendored_path, manifest_kind_for, normalise_name,
    parse_cargo_toml, parse_go_mod, parse_manifest,
    parse_package_json, parse_requirements,
    redact_url_credentials, render_dependency_graph_page,
    render_dependency_table_page)
from samverk.hooks import RefUpdate
from samverk.repositories import RepositoryStore
from test_repo_home import run_git

ZERO = "0" * 40

REQ = (
    "# a comment\n"
    "requests==2.31.0\n"
    "Flask>=2.0\n"
    "numpy[all]==1.26.0 ; python_version >= '3.9'\n"
    "-e git+https://tokvalue@github.com/x/y#egg=ed\n"
    "--extra-index-url https://user:pass@example.com/simple\n"
    "!!! not a package\n"
    "localpkg @ https://user:pass@example.com/pkg-1.0.tar.gz\n"
    "bare-name\n")

PKG = (
    '{"name": "demo", "version": "1.0.0",'
    ' "dependencies": {"react": "18.2.0", "lodash": "^4.17.21"},'
    ' "devDependencies": {"jest": "29.0.0"},'
    ' "peerDependencies": {"react-dom": ">=18"},'
    ' "optionalDependencies": {"fsevents": "~2.3.2"}}')

GOMOD = (
    "module example.com/demo\n\n"
    "go 1.21\n\n"
    "require github.com/a/b v1.2.3\n\n"
    "require (\n"
    "\tgithub.com/c/d v0.5.0 // indirect\n"
    "\tgolang.org/x/e v2.0.0+incompatible\n"
    "\tbad/version notaversion\n"
    ")\n\n"
    "replace github.com/a/b => github.com/a/b v1.2.4\n")

CARGO = (
    '[dependencies]\n'
    'serde = { version = "=1.0.0", features = ["derive"] }\n'
    'tokio = "1"\n'
    'renamed = { package = "real-crate", version = "^2.0" }\n'
    'fromgit = { git = "https://tokvalue@github.com/x/y" }\n'
    'frompath = { path = "../local" }\n\n'
    '[dev-dependencies]\n'
    'criterion = "0.5"\n\n'
    '[build-dependencies]\n'
    'cc = "1.0"\n\n'
    '[target.\'cfg(unix)\'.dependencies]\n'
    'libc = "0.2"\n')


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


class PureLawTests(unittest.TestCase):
    def test_manifest_discovery(self):
        self.assertEqual(manifest_kind_for("requirements.txt"),
                         ("python", "requirements"))
        self.assertEqual(manifest_kind_for("web/package.json"),
                         ("npm", "package_json"))
        self.assertEqual(manifest_kind_for("a/b/go.mod"),
                         ("go", "go_mod"))
        self.assertEqual(manifest_kind_for("crates/x/Cargo.toml"),
                         ("rust", "cargo_toml"))
        self.assertIsNone(manifest_kind_for("Cargo.lock"))
        self.assertIsNone(manifest_kind_for("package-lock.json"))
        self.assertIsNone(manifest_kind_for("README.md"))
        self.assertIsNone(manifest_kind_for(""))
        self.assertTrue(is_manifest_path("sub/requirements.txt"))
        self.assertFalse(is_manifest_path("sub/go.sum"))
        self.assertTrue(is_vendored_path("node_modules/x/package.json"))
        self.assertTrue(is_vendored_path("a/node_modules/x/go.mod"))
        self.assertTrue(is_vendored_path("node_modules/package.json"))
        self.assertFalse(is_vendored_path("src/package.json"))

    def test_normalise_name(self):
        self.assertEqual(normalise_name("python", "Flask_SQLAlchemy.X"),
                         "flask-sqlalchemy-x")
        self.assertEqual(normalise_name("npm", "@Scope/Pkg"), "@scope/pkg")
        self.assertEqual(normalise_name("rust", "My_Crate"), "my-crate")
        self.assertEqual(normalise_name("go", "github.com/A/B"),
                         "github.com/A/B")

    def test_is_exact_pin_matrix(self):
        self.assertTrue(is_exact_pin("python", "==2.31.0"))
        self.assertFalse(is_exact_pin("python", "==2.*"))
        self.assertFalse(is_exact_pin("python", ">=2.0"))
        self.assertFalse(is_exact_pin("python", "~=2.0"))
        self.assertFalse(is_exact_pin("python", ""))
        self.assertFalse(is_exact_pin("python", "@ https://x/y"))
        self.assertTrue(is_exact_pin("npm", "18.2.0"))
        self.assertTrue(is_exact_pin("npm", "=18.2.0"))
        self.assertFalse(is_exact_pin("npm", "^4.17.21"))
        self.assertFalse(is_exact_pin("npm", "~2.3.2"))
        self.assertFalse(is_exact_pin("npm", "*"))
        self.assertFalse(is_exact_pin("npm", "latest"))
        self.assertFalse(is_exact_pin("npm", "file:../x"))
        self.assertTrue(is_exact_pin("go", "v1.2.3"))
        self.assertTrue(is_exact_pin("go", "v2.0.0+incompatible"))
        self.assertFalse(is_exact_pin("go", "1.2.3"))
        self.assertTrue(is_exact_pin("rust", "=1.0.0"))
        self.assertFalse(is_exact_pin("rust", "1.0.0"))
        self.assertFalse(is_exact_pin("rust", "^2.0"))
        self.assertFalse(is_exact_pin("rust", "git+https://x/y"))

    def test_redact_url_credentials(self):
        self.assertEqual(
            redact_url_credentials("https://user:pass@example.com/x"),
            "https://***@example.com/x")
        self.assertEqual(
            redact_url_credentials("git+https://tok@github.com/x/y"),
            "git+https://***@github.com/x/y")
        self.assertEqual(redact_url_credentials(">=2.0"), ">=2.0")
        self.assertEqual(
            redact_url_credentials("https://example.com/x"),
            "https://example.com/x")

    def test_parse_requirements(self):
        parsed = parse_requirements(REQ)
        by_key = {d.name_key: d for d in parsed.dependencies}
        self.assertEqual(sorted(by_key),
                         ["bare-name", "flask", "localpkg",
                          "numpy", "requests"])
        self.assertTrue(by_key["requests"].resolved)
        self.assertEqual(by_key["requests"].specifier, "==2.31.0")
        self.assertFalse(by_key["flask"].resolved)
        self.assertEqual(by_key["numpy"].extras, "all")
        self.assertEqual(by_key["numpy"].marker,
                         "python_version >= '3.9'")
        self.assertTrue(by_key["numpy"].resolved)
        self.assertFalse(by_key["localpkg"].resolved)
        self.assertEqual(by_key["localpkg"].specifier,
                         "@ https://***@example.com/pkg-1.0.tar.gz")
        self.assertFalse(by_key["bare-name"].resolved)
        self.assertEqual(by_key["bare-name"].specifier, "")
        self.assertEqual(
            [(s.line, s.reason) for s in parsed.skipped],
            [(5, "option_line"), (6, "option_line"),
             (7, "malformed_line")])
        for dep in parsed.dependencies:
            self.assertNotIn("pass", dep.specifier)
            self.assertNotIn("tokvalue", dep.specifier)

    def test_parse_requirements_continuation(self):
        parsed = parse_requirements(
            "longpkg==1.0 \\\n    ; python_version > '3.8'\n")
        self.assertEqual(len(parsed.dependencies), 1)
        self.assertEqual(parsed.dependencies[0].name_key, "longpkg")
        self.assertIn("python_version", parsed.dependencies[0].marker)

    def test_parse_package_json(self):
        parsed = parse_package_json(PKG)
        by_key = {(d.name_key, d.scope): d for d in parsed.dependencies}
        self.assertEqual(len(parsed.dependencies), 5)
        self.assertTrue(by_key[("react", "direct")].resolved)
        self.assertFalse(by_key[("lodash", "direct")].resolved)
        self.assertTrue(by_key[("jest", "dev")].resolved)
        self.assertFalse(by_key[("react-dom", "peer")].resolved)
        self.assertFalse(by_key[("fsevents", "optional")].resolved)
        self.assertEqual(parsed.skipped, ())

    def test_parse_package_json_refusals(self):
        with self.assertRaises(DependencyGraphError) as ctx:
            parse_package_json("{not json")
        self.assertEqual(ctx.exception.reason, "manifest_invalid")
        with self.assertRaises(DependencyGraphError) as ctx:
            parse_package_json("[1, 2]")
        self.assertEqual(ctx.exception.reason, "manifest_invalid")
        parsed = parse_package_json(
            '{"dependencies": {"ok": "1.0.0", "bad": 3},'
            ' "devDependencies": ["nope"]}')
        self.assertEqual([d.name_key for d in parsed.dependencies], ["ok"])
        self.assertEqual(
            [s.reason for s in parsed.skipped],
            ["specifier_not_string", "section_not_object"])

    def test_parse_go_mod(self):
        parsed = parse_go_mod(GOMOD)
        by_key = {d.name_key: d for d in parsed.dependencies}
        self.assertEqual(sorted(by_key),
                         ["github.com/a/b", "github.com/c/d",
                          "golang.org/x/e"])
        self.assertEqual(by_key["github.com/a/b"].scope, "direct")
        self.assertEqual(by_key["github.com/c/d"].scope, "indirect")
        self.assertTrue(all(d.resolved for d in parsed.dependencies))
        self.assertEqual([(s.line, s.reason) for s in parsed.skipped],
                         [(10, "malformed_line")])

    def test_parse_cargo_toml(self):
        parsed = parse_cargo_toml(CARGO)
        by_key = {d.name_key: d for d in parsed.dependencies}
        self.assertEqual(sorted(by_key),
                         ["cc", "criterion", "fromgit", "frompath",
                          "libc", "real-crate", "serde", "tokio"])
        self.assertTrue(by_key["serde"].resolved)
        self.assertEqual(by_key["serde"].scope, "direct")
        self.assertFalse(by_key["tokio"].resolved)
        self.assertEqual(by_key["real-crate"].name, "real-crate")
        self.assertEqual(by_key["fromgit"].specifier,
                         "git+https://***@github.com/x/y")
        self.assertFalse(by_key["fromgit"].resolved)
        self.assertEqual(by_key["frompath"].specifier, "path+../local")
        self.assertEqual(by_key["criterion"].scope, "dev")
        self.assertEqual(by_key["cc"].scope, "build")
        self.assertEqual(by_key["libc"].scope, "target")

    def test_parse_cargo_toml_refusal(self):
        with self.assertRaises(DependencyGraphError) as ctx:
            parse_cargo_toml("[dependencies\n")
        self.assertEqual(ctx.exception.reason, "manifest_invalid")

    def test_parse_manifest_dispatch(self):
        self.assertEqual(
            len(parse_manifest("x/go.mod", GOMOD).dependencies), 3)
        with self.assertRaises(DependencyGraphError) as ctx:
            parse_manifest("x/Pipfile", "whatever")
        self.assertEqual(ctx.exception.reason, "manifest_unknown")


class GraphTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.accounts = AccountStore(self.conn, time_fn=self.clock)
        self.owner = self.accounts.register(
            "volmarr", "correct horse battery")
        self.stranger = self.accounts.register(
            "mallory", "correct horse battery")
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts)
        self.store = DependencyGraphStore(
            self.conn, self.repos, self.accounts,
            time_fn=self.clock)
        self._seq = 0

    # -- fixture helpers --------------------------------------
    def _repo_with_files(self, name, files, visibility="public"):
        self._seq += 1
        self.repos.create_repository(
            self.owner.id, "volmarr", name, visibility=visibility)
        bare = self.repos.path_for("volmarr", name)
        work = self.root / f"work{self._seq}"
        work.mkdir()
        run_git(work, "init", "-b", "main")
        for rel, data in files.items():
            path = work / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(
                data if isinstance(data, bytes) else data.encode())
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "files")
        run_git(work, "push", str(bare), "main")
        return work, run_git(work, "rev-parse", "HEAD")

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(DependencyGraphError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    def _manifest_outcome(self, report, path):
        for outcome in report.outcomes:
            if outcome.path == path:
                return outcome
        raise AssertionError(f"no outcome for {path}")

    def _audit_count(self):
        return self.conn.execute(
            "SELECT COUNT(*) c FROM audit_log").fetchone()["c"]

    def _full_files(self):
        return {
            "requirements.txt": REQ,
            "web/package.json": PKG,
            "go.mod": GOMOD,
            "crates/app/Cargo.toml": CARGO,
            "sub/requirements.txt": "django==4.2\n",
            "node_modules/junk/package.json":
                '{"dependencies": {"evil": "1.0.0"}}',
            "broken/package.json": "{not json",
            "src/main.py": "print(1)\n",
        }

    # -- pins ---------------------------------------------------
    def test_pins_schema_117_taxonomy_134(self):
        self.assertEqual(schema_version(self.conn), 124)
        self.assertEqual(db.MIGRATIONS[-1][0], 124)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 89)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        tables = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertIn("dependency_graph_states", tables)
        self.assertIn("dependency_manifests", tables)
        self.assertIn("repo_dependencies", tables)

    def test_fresh_database_migrates_to_117(self):
        with tempfile.TemporaryDirectory() as td:
            conn = db.init_db(Path(td) / "fresh.db")
            self.assertEqual(db.schema_version(conn), 124)
            conn.close()

    def test_upgrade_from_116_creates_tables(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "old.db"
            conn = db.connect(path)
            for target, statements in db.MIGRATIONS:
                if target > 116:
                    continue
                with conn:
                    for stmt in statements:
                        conn.execute(stmt)
                    conn.execute(
                        "INSERT OR REPLACE INTO schema_meta"
                        " (key, value) VALUES ('version', ?)",
                        (str(target),))
            self.assertEqual(db.schema_version(conn), 116)
            self.assertEqual(db.migrate(conn), 124)
            names = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
            self.assertIn("repo_dependencies", names)
            conn.close()

    # -- graphing -------------------------------------------------
    def test_graph_tip_builds_table(self):
        _work, tip = self._repo_with_files("anvil", self._full_files())
        before = self._audit_count()
        report = self.store.graph_tip("volmarr", "anvil", tip)
        self.assertEqual(report.commit_oid, tip)
        self.assertEqual(report.previous_oid, "")
        self.assertEqual(report.status, "complete")
        self.assertEqual(self._manifest_outcome(report, "requirements.txt").status,
                         "parsed")
        self.assertEqual(
            self._manifest_outcome(report, "requirements.txt").dependencies_count, 5)
        vendored = self._manifest_outcome(report, "node_modules/junk/package.json")
        self.assertEqual((vendored.status, vendored.reason),
                         ("skipped", "vendored"))
        broken = self._manifest_outcome(report, "broken/package.json")
        self.assertEqual((broken.status, broken.reason),
                         ("skipped", "manifest_invalid"))
        # 5 root requirements + 5 npm + 3 go + 8 cargo + 1 nested = 22
        self.assertEqual(report.dependencies_count, 22)
        self.assertEqual(self._audit_count(), before)
        state = self.store.graph_state_for("volmarr", "anvil")
        self.assertEqual(state.commit_oid, tip)
        self.assertEqual(state.dependencies_count, 22)
        rows = self.store.dependencies_for("volmarr", "anvil")
        self.assertEqual(len(rows), 22)
        keys = {(r.dependency.ecosystem, r.dependency.name_key)
                for r in rows}
        self.assertIn(("python", "django"), keys)
        self.assertIn(("npm", "react"), keys)
        self.assertIn(("go", "github.com/c/d"), keys)
        self.assertIn(("rust", "serde"), keys)
        self.assertNotIn(("npm", "evil"), keys)
        manifests = self.store.manifests_for("volmarr", "anvil")
        self.assertEqual(len(manifests), 7)

    def test_dependencies_for_ecosystem_filter(self):
        _work, tip = self._repo_with_files("anvil", self._full_files())
        self.store.graph_tip("volmarr", "anvil", tip)
        py = self.store.dependencies_for(
            "volmarr", "anvil", ecosystem="python")
        self.assertEqual(len(py), 6)
        self.assertTrue(all(
            r.dependency.ecosystem == "python" for r in py))
        self.assertEqual(
            self._reason(self.store.dependencies_for,
                         "volmarr", "anvil", ecosystem="maven"),
            "ecosystem_unknown")

    def test_graph_is_exactly_once_per_snapshot(self):
        _work, tip = self._repo_with_files("anvil", self._full_files())
        self.store.graph_tip("volmarr", "anvil", tip)
        first = self.store.graph_state_for("volmarr", "anvil")
        self.clock.now += 5000
        again = self.store.graph_tip("volmarr", "anvil", tip)
        second = self.store.graph_state_for("volmarr", "anvil")
        self.assertEqual(again.commit_oid, tip)
        self.assertEqual(again.dependencies_count, 22)
        self.assertEqual(second.updated_at, first.updated_at)

    def test_regraph_replaces_table(self):
        work, tip = self._repo_with_files("anvil", self._full_files())
        self.store.graph_tip("volmarr", "anvil", tip)
        bare = self.repos.path_for("volmarr", "anvil")
        (work / "sub" / "requirements.txt").unlink()
        (work / "requirements.txt").write_text("requests==2.32.0\n")
        run_git(work, "add", "-A")
        run_git(work, "commit", "-m", "second")
        run_git(work, "push", str(bare), "main")
        tip2 = run_git(work, "rev-parse", "HEAD")
        report = self.store.graph_tip("volmarr", "anvil", tip2)
        self.assertEqual(report.previous_oid, tip)
        rows = self.store.dependencies_for("volmarr", "anvil")
        keys = {r.dependency.name_key for r in rows}
        self.assertNotIn("django", keys)
        req = [r for r in rows if r.dependency.name_key == "requests"]
        self.assertEqual(req[0].dependency.specifier, "==2.32.0")
        self.assertEqual(report.dependencies_count, 17)

    def test_graph_push_trigger_law(self):
        _work, tip = self._repo_with_files("anvil", self._full_files())
        other = RefUpdate("refs/heads/topic", ZERO, tip)
        self.assertIsNone(
            self.store.graph_push("volmarr", "anvil", [other]))
        self.assertIsNone(self.store.graph_state_for("volmarr", "anvil"))
        move = RefUpdate("refs/heads/main", ZERO, tip)
        report = self.store.graph_push("volmarr", "anvil", [move])
        self.assertEqual(report.dependencies_count, 22)
        delete = RefUpdate("refs/heads/main", tip, ZERO)
        cleared = self.store.graph_push("volmarr", "anvil", [delete])
        self.assertEqual(cleared.commit_oid, "")
        self.assertTrue(all(
            o.status == "removed" for o in cleared.outcomes))
        self.assertEqual(len(cleared.outcomes), 7)
        self.assertIsNone(self.store.graph_state_for("volmarr", "anvil"))
        self.assertEqual(
            self.store.dependencies_for("volmarr", "anvil"), ())

    def test_graph_repository_resolves_tip(self):
        self._repo_with_files("anvil", self._full_files())
        report = self.store.graph_repository("volmarr", "anvil")
        self.assertEqual(report.dependencies_count, 22)
        self.assertEqual(
            self.store.rebuild_repository("volmarr", "anvil").commit_oid,
            report.commit_oid)

    def test_damaged_repository_refuses_before_writing(self):
        _work, tip = self._repo_with_files("anvil", self._full_files())
        self.store.graph_tip("volmarr", "anvil", tip)
        self.assertEqual(
            self._reason(self.store.graph_tip,
                         "volmarr", "anvil", "f" * 40),
            "object_not_found")
        self.assertEqual(
            self._reason(self.store.graph_tip, "volmarr", "anvil", ""),
            "commit_not_found")
        self.assertEqual(
            self._reason(self.store.graph_tip, "volmarr", "ghost", tip),
            "repo_not_found")
        state = self.store.graph_state_for("volmarr", "anvil")
        self.assertEqual(state.commit_oid, tip)
        self.assertEqual(state.dependencies_count, 22)

    def test_oversized_and_binary_manifests_skipped(self):
        files = {
            "requirements.txt": b"a" * 1_000_001,
            "bin/package.json": b"\x00\x01\x02",
            "go.mod": GOMOD,
        }
        _work, tip = self._repo_with_files("heavy", files)
        report = self.store.graph_tip("volmarr", "heavy", tip)
        self.assertEqual(
            (self._manifest_outcome(report, "requirements.txt").status,
             self._manifest_outcome(report, "requirements.txt").reason),
            ("skipped", "oversized"))
        self.assertEqual(
            (self._manifest_outcome(report, "bin/package.json").status,
             self._manifest_outcome(report, "bin/package.json").reason),
            ("skipped", "binary"))
        self.assertEqual(report.dependencies_count, 3)

    def test_no_graph_yet_reads_honestly(self):
        self._repo_with_files("anvil", self._full_files())
        self.assertIsNone(self.store.graph_state_for("volmarr", "anvil"))
        self.assertEqual(self.store.manifests_for("volmarr", "anvil"), ())
        whole = self.store.dependency_graph("volmarr", "anvil")
        self.assertIsNone(whole["state"])
        self.assertEqual(whole["dependencies"], [])

    def test_dependency_graph_dict_shape(self):
        _work, tip = self._repo_with_files("anvil", self._full_files())
        self.store.graph_tip("volmarr", "anvil", tip)
        whole = self.store.dependency_graph("volmarr", "anvil")
        self.assertEqual(whole["repository"], "volmarr/anvil")
        self.assertEqual(whole["state"]["dependencies"], 22)
        self.assertEqual(len(whole["manifests"]), 7)
        self.assertEqual(len(whole["dependencies"]), 22)
        dep = next(d for d in whole["dependencies"]
                   if d["name_key"] == "serde")
        self.assertEqual(dep["manifest"], "crates/app/Cargo.toml")
        self.assertTrue(dep["resolved"])

    def test_remove_repository_purges(self):
        _work, tip = self._repo_with_files("anvil", self._full_files())
        self.store.graph_tip("volmarr", "anvil", tip)
        self.assertEqual(self.store.remove_repository("volmarr", "anvil"), 7)
        self.assertIsNone(self.store.graph_state_for("volmarr", "anvil"))

    # -- permission law -------------------------------------------
    def test_read_permission_law(self):
        _work, tip = self._repo_with_files(
            "vault", self._full_files(), visibility="private")
        self.store.graph_tip("volmarr", "vault", tip)
        self.assertEqual(
            self._reason(self.store.dependencies_for,
                         "volmarr", "vault", self.stranger),
            "repo_not_found")
        self.assertEqual(
            self._reason(self.store.dependencies_for,
                         "volmarr", "vault", None),
            "repo_not_found")
        self.assertEqual(
            len(self.store.dependencies_for(
                "volmarr", "vault", self.owner)), 22)
        self._repo_with_files("open", self._full_files())
        self.store.graph_repository("volmarr", "open")
        self.assertEqual(
            len(self.store.dependencies_for("volmarr", "open", None)), 22)
        self.assertEqual(
            len(self.store.dependencies_for(
                "volmarr", "open", self.stranger)), 22)

    # -- rendering --------------------------------------------------
    def test_rendering_escapes(self):
        evil = ParsedDependency(
            name="<script>alert(1)</script>", name_key="evil",
            ecosystem="npm", specifier="<b>1</b>", scope="direct",
            resolved=False)
        row = Dependency(id=1, repo_id=1, manifest_path="web/<x>.json",
                         kind="package_json", dependency=evil)
        state = GraphState(repo_id=1, full_name="volmarr/anvil",
                           commit_oid="abc", manifests_count=1,
                           dependencies_count=1, updated_at=1)
        page = render_dependency_table_page("volmarr/anvil", state, (row,))
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("range or reference", page)
        report = DependencyGraphReport(
            repo_id=1, full_name="volmarr/anvil", commit_oid="abc",
            previous_oid="", outcomes=(ManifestOutcome(
                path="web/<x>.json", ecosystem="npm",
                kind="package_json", status="parsed",
                dependencies_count=1),), dependencies=(evil,))
        page2 = render_dependency_graph_page(report)
        self.assertIn("&lt;x&gt;", page2)
        self.assertIn("lockfiles are not parsed", page2)
        empty = render_dependency_table_page("volmarr/anvil", None, ())
        self.assertIn("No dependency graph", empty)
