"""S-347 acceptance battery: data directory layout.

Acceptance (roadmap S-347): repos, LFS, assets,
database, keys, logs -- one tree, documented, movable
as a unit.

The centre is samverk/data_layout.py: SUBTREES names
every path directly under the data root with its
owning slice and standing; layout_for resolves them
all from one root, delegating to (or proven equal to)
the seams that spelled the paths first -- S-013's
repos_root, S-020's keys_dir, S-002's db_path, S-003's
default secrets file, S-060's LFS objects inside the
bare repo. judge_layout is pure over gathered facts
(present / missing / wrong-kind, unclaimed entries
named, tree sound / incomplete / damaged);
ensure_layout stands up the required skeleton;
plan_relocation is the honest move story -- writers
stop first, the tree moves as one unit, configuration
outside the tree stays behind and is named, the same
root and a move into itself are refused. Config.layout
is the canonical resolver; Config.db_path delegates
to it, unchanged. No migration (schema 139 stands);
no new taxonomy event (138 stand).
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import data_layout as dl
from samverk import keys as keys_mod
from samverk import repo_paths
from samverk.config import Config, load_config
from samverk.db import schema_version  # noqa: F401  (pin read below)
from samverk import taxonomy


class LayoutNamingTests(unittest.TestCase):
    def test_every_subtree_named_once_with_owner(self):
        names = [s.name for s in dl.SUBTREES]
        self.assertEqual(len(names), len(set(names)))
        for s in dl.SUBTREES:
            self.assertTrue(s.owner.startswith("S-"), s)
            self.assertTrue(s.purpose, s)
            self.assertIn(s.kind, ("dir", "file"))
            self.assertIn(s.standing,
                          (dl.REQUIRED, dl.ON_USE, dl.RESERVED))

    def test_roadmap_six_are_all_in_the_tree(self):
        names = {s.name for s in dl.SUBTREES}
        for needed in ("repos", "avatars", "release-assets",
                       "samverk.db", "keys", "logs"):
            self.assertIn(needed, names)
        # LFS is inside the bare repo, named in repos' purpose.
        self.assertIn("lfs/objects", dl.subtree("repos").purpose)

    def test_unknown_subtree_refused(self):
        with self.assertRaises(KeyError):
            dl.layout_for(Path("/x")).path("nope")

    def test_paths_agree_with_owning_seams(self):
        root = Path("/srv/samverk")
        layout = dl.layout_for(root)
        self.assertEqual(layout.repos_root, repo_paths.repos_root(root))
        self.assertEqual(layout.keys_dir, keys_mod.keys_dir(root))
        self.assertEqual(layout.db_path, root / "samverk.db")
        self.assertEqual(layout.secrets_file_default,
                         root / "secrets.env")
        repo = layout.repos_root / "owner" / "repo.git"
        self.assertEqual(layout.lfs_objects_dir(repo),
                         repo / "lfs" / "objects")

    def test_config_adopts_layout_without_breakage(self):
        cfg = Config(data_root=Path("/srv/samverk"))
        self.assertEqual(cfg.db_path, Path("/srv/samverk/samverk.db"))
        self.assertEqual(cfg.layout.root, Path("/srv/samverk"))
        cfg2 = load_config(env={"SAMVERK_DATA_ROOT": "/data/x"})
        self.assertEqual(cfg2.db_path, Path("/data/x/samverk.db"))
        self.assertEqual(cfg2.layout.path("keys"), Path("/data/x/keys"))


class LayoutCheckTests(unittest.TestCase):
    def test_missing_root_is_incomplete_not_damaged(self):
        with tempfile.TemporaryDirectory() as td:
            report = dl.check_layout(Path(td) / "absent")
        self.assertEqual(report.health, dl.INCOMPLETE)
        self.assertTrue(report.problems())

    def test_fresh_ensured_root_is_sound(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "data"
            dl.ensure_layout(root)
            report = dl.check_layout(root)
            self.assertEqual(report.health, dl.SOUND)
            self.assertEqual(report.unclaimed, ())
            for name in ("repos", "gists", "keys"):
                self.assertTrue((root / name).is_dir())

    def test_wrong_kind_is_damaged_and_named(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "repos").write_text("not a dir")
            report = dl.check_layout(root)
            self.assertEqual(report.health, dl.DAMAGED)
            bad = [e for e in report.entries if e.name == "repos"][0]
            self.assertEqual(bad.health, dl.WRONG_KIND)

    def test_unclaimed_entries_are_named(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            dl.ensure_layout(root)
            (root / "mystery.bin").write_bytes(b"?")
            (root / "samverk.db-wal").write_bytes(b"")  # sidecar: claimed
            report = dl.check_layout(root)
            self.assertEqual(report.unclaimed, ("mystery.bin",))
            self.assertEqual(report.health, dl.SOUND)

    def test_judge_is_pure_over_facts(self):
        facts = dl.LayoutFacts(
            root=Path("/x"), root_exists=True,
            entries=(dl.EntryFact("repos", True, True),),
            unclaimed=())
        report = dl.judge_layout(facts)
        self.assertEqual(report.health, dl.INCOMPLETE)  # gists/keys absent
        repos = [e for e in report.entries if e.name == "repos"][0]
        self.assertEqual(repos.health, dl.PRESENT)


class RelocationTests(unittest.TestCase):
    def test_same_root_refused(self):
        plan = dl.plan_relocation(Path("/a"), Path("/a"))
        self.assertFalse(plan.allowed)
        self.assertIn("nothing to move", plan.refusal)

    def test_move_into_itself_refused(self):
        plan = dl.plan_relocation(Path("/a"), Path("/a/inner"))
        self.assertFalse(plan.allowed)
        plan2 = dl.plan_relocation(Path("/a/inner"), Path("/a"))
        self.assertFalse(plan2.allowed)

    def test_honest_story(self):
        plan = dl.plan_relocation(Path("/old"), Path("/new"))
        self.assertTrue(plan.allowed)
        joined = " ".join(plan.stop_first)
        self.assertIn("server", joined)
        steps = " ".join(plan.steps)
        self.assertIn("one unit", steps)
        self.assertIn("SAMVERK_DATA_ROOT", steps)
        self.assertTrue(plan.proof)

    def test_outside_secret_stays_behind_named(self):
        plan = dl.plan_relocation(
            Path("/old"), Path("/new"),
            secret_file=Path("/etc/samverk/secrets.env"),
            tls_key_file=Path("/old/tls.key"))
        self.assertEqual(len(plan.stays_behind), 1)
        self.assertIn("secrets file", plan.stays_behind[0])

    def test_moved_tree_still_checks_sound(self):
        with tempfile.TemporaryDirectory() as td:
            old = Path(td) / "old"; new = Path(td) / "new"
            dl.ensure_layout(old)
            (old / "samverk.db").write_bytes(b"db")
            import shutil; shutil.copytree(old, new)
            self.assertEqual(dl.check_layout(new).health, dl.SOUND)
            plan = dl.plan_relocation(old, new)
            self.assertTrue(plan.allowed)


class PinsTests(unittest.TestCase):
    def test_no_migration_no_new_taxonomy_event(self):
        from samverk import db as db_mod
        self.assertEqual(db_mod.MIGRATIONS[-1][0], 139)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 138)


if __name__ == "__main__":
    unittest.main()
