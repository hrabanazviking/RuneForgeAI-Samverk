"""S-066 acceptance battery: repository settings.

Acceptance (roadmap S-066): description, website, topics,
default branch rename with redirect of clones' HEAD
guidance.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import os, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.refs import RefStore
from samverk.repo_settings import RepoSettingsService, SettingsError
from samverk.repositories import RepositoryStore

def git(repo: Path, *args: str, input_bytes: bytes | None = None) -> str:
    env = dict(os.environ)
    env.update({"GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@e.c",
                "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@e.c"})
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         input=input_bytes, capture_output=True, env=env)
    if out.returncode != 0:
        raise AssertionError(out.stderr.decode())
    return out.stdout.decode().strip()

class SettingsTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.data_root = Path(self._td.name)
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.other = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "proj",
                                     visibility="public", description="old")
        self.path = self.repos.path_for("volmarr", "proj")
        blob = git(self.path, "hash-object", "-w", "--stdin", input_bytes=b"x\n")
        tree = git(self.path, "mktree", input_bytes=f"100644 blob {blob}\tx.txt\n".encode())
        self.commit = git(self.path, "commit-tree", tree, input_bytes=b"first\n")
        git(self.path, "update-ref", "refs/heads/main", self.commit)
        self.settings = RepoSettingsService(self.conn, self.data_root, self.accounts, self.repos)

    def test_website_and_topics_round_trip_and_normalise(self):
        s = self.settings.update_settings(
            self.owner.id, "volmarr", "proj",
            website="https://example.com/proj",
            topics=["Python", "git-forge", "python", "  Rust "])
        self.assertEqual(s.website, "https://example.com/proj")
        self.assertEqual(s.topics, ("python", "git-forge", "rust"))
        self.assertEqual(s.description, "old")
        again = self.settings.settings_for(self.other, "volmarr", "proj")
        self.assertEqual(again.topics, ("python", "git-forge", "rust"))
        cleared = self.settings.update_settings(
            self.owner.id, "volmarr", "proj", website="", topics=[])
        self.assertEqual((cleared.website, cleared.topics), ("", ()))

    def test_website_and_topic_validation(self):
        for bad_site in ("javascript:alert(1)", "data:text/html,x",
                         "mailto:a@b.c", "https://e.c/" + "x" * 200):
            with self.assertRaises(SettingsError) as caught:
                self.settings.update_settings(
                    self.owner.id, "volmarr", "proj", website=bad_site)
            self.assertEqual(caught.exception.reason, "website_invalid")
        for bad_topics in (["has space"], ["-lead"], ["a" * 51],
                           [f"t{i}" for i in range(21)], "notalist"):
            with self.assertRaises(SettingsError):
                self.settings.update_settings(
                    self.owner.id, "volmarr", "proj", topics=bad_topics)

    def test_description_flows_through_s050_and_owner_only(self):
        s = self.settings.update_settings(
            self.owner.id, "volmarr", "proj", description="new words")
        self.assertEqual(s.description, "new words")
        self.assertEqual(self.repos.get_repository("volmarr", "proj").description,
                         "new words")
        with self.assertRaises(SettingsError) as caught:
            self.settings.update_settings(
                self.other.id, "volmarr", "proj", description="hostile")
        self.assertEqual(caught.exception.reason, "not_repo_owner")

    def test_default_branch_rename_moves_ref_head_and_default(self):
        result = self.settings.rename_default_branch(
            self.owner.id, "volmarr", "proj", "trunk")
        self.assertEqual((result.old_branch, result.new_branch), ("main", "trunk"))
        refs = RefStore(self.path)
        self.assertEqual(refs.resolve("refs/heads/trunk"), self.commit)
        self.assertIsNone(refs.resolve("refs/heads/main"))
        self.assertEqual(refs.head_ref(), "refs/heads/trunk")
        self.assertEqual(self.repos.get_repository("volmarr", "proj").default_branch,
                         "trunk")
        self.assertIn("git remote set-head origin -a", result.clone_guidance)
        self.assertIn("git branch -m main trunk", result.clone_guidance)

    def test_rename_guidance_is_recorded_for_clones(self):
        self.assertIsNone(self.settings.rename_guidance(
            self.other, "volmarr", "proj", "main"))
        self.settings.rename_default_branch(self.owner.id, "volmarr", "proj", "trunk")
        guidance = self.settings.rename_guidance(self.other, "volmarr", "proj", "main")
        self.assertIsNotNone(guidance)
        self.assertEqual(guidance.new_branch, "trunk")
        self.assertIn("git branch -u origin/trunk trunk", guidance.clone_guidance)
        with self.assertRaises(SettingsError):
            self.settings.rename_default_branch(
                self.owner.id, "volmarr", "proj", "trunk")
        with self.assertRaises(SettingsError):
            self.settings.rename_default_branch(
                self.other.id, "volmarr", "proj", "side")

    def test_empty_repo_default_rename_is_metadata_only(self):
        self.repos.create_repository(self.owner.id, "volmarr", "blank",
                                     visibility="private")
        result = self.settings.rename_default_branch(
            self.owner.id, "volmarr", "blank", "dev")
        self.assertEqual(result.new_branch, "dev")
        blank = self.repos.get_repository("volmarr", "blank")
        self.assertEqual(blank.default_branch, "dev")
        refs = RefStore(self.repos.path_for("volmarr", "blank"))
        self.assertEqual(refs.head_ref(), "refs/heads/dev")

if __name__ == "__main__":
    unittest.main()
