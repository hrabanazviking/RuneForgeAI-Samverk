#!/usr/bin/env python3
"""S-395 — Performance verification runner (pure stdlib + samverk).

Re-measures the S-073 clone budget, the S-217 search budgets
and the S-395 browse budget on the hardware it runs on, and
publishes the numbers as JSON: the clone of S-073's reference
repository (1,000 commits / 2,000 blobs, built with git
fast-import), S-217's reference corpus searched through
S-208's executor, and the root tree of a corpus repository
browsed through S-120's FileBrowser. The publication claims
only this machine's hardware class; every other class is
published unmeasured — NOT PROVEN.

Usage: python3 tools/run_perf_verification.py --out PATH
       [--repetitions 5]
"""
import argparse, json, os, subprocess, sys, tempfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from samverk import db
from samverk.accounts import AccountStore
from samverk.code_indexing import CodeIndexer
from samverk.code_search import CodeSearch
from samverk.file_browser import FileBrowser
from samverk.perf_verification import measure_browse, publication
from samverk.repo_budgets import measure_local_clone
from samverk.repositories import RepositoryStore
from samverk.search_budgets import corpus_files, corpus_spec, measure_searches

PW = "correct horse battery"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "A U Thor", "GIT_AUTHOR_EMAIL": "a@example.com",
    "GIT_COMMITTER_NAME": "A U Thor",
    "GIT_COMMITTER_EMAIL": "a@example.com",
}


def run_git(cwd, *args):
    env = dict(os.environ); env.update(GIT_ENV)
    out = subprocess.run(["git", *args], cwd=cwd,
                         capture_output=True, env=env)
    if out.returncode != 0:
        raise AssertionError(out.stderr.decode("utf-8", "replace"))
    return out.stdout.decode("utf-8", "replace").strip()


def build_reference_repo(path: Path) -> None:
    """S-073's reference shape (1,000 commits, 2,000 blobs)
    as one git fast-import stream — the same builder shape
    as tests/test_repo_budgets.py."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--bare", "-b", "main", str(path)],
                   check=True, capture_output=True)
    parts = []
    marks = []
    blob_mark = 0
    for c in range(1000):
        for f in range(2):
            blob_mark += 1
            data = (f"reference payload {c}/{f}\n" * 8).encode()
            parts.append(f"blob\nmark :{blob_mark}\ndata {len(data)}\n".encode() + data)
            marks.append((c, f, blob_mark))
    by_commit = {}
    for c, f, m in marks:
        by_commit.setdefault(c, []).append((f, m))
    for c in range(1000):
        lines = [f"commit refs/heads/main\nmark :{100000 + c}\n"
                 f"author A U Thor <a@e.c> 1700000000 +0000\n"
                 f"committer A U Thor <a@e.c> 1700000000 +0000\n"
                 f"data 4\nmsg\n"]
        if c:
            lines.append(f"from :{100000 + c - 1}\n")
        for f, m in by_commit[c]:
            lines.append(f"M 100644 :{m} file-{c}-{f}.txt\n")
        parts.append("".join(lines).encode())
    proc = subprocess.run(["git", f"--git-dir={path}", "fast-import", "--quiet"],
                          input=b"".join(parts), capture_output=True)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr.decode("utf-8", "replace"))


def commit_and_push(root: Path, work: Path, bare: Path, files, when: int):
    work.mkdir(parents=True, exist_ok=True)
    run_git(work, "init", "-b", "main")
    for name, text in files:
        p = work / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    run_git(work, "add", "-A")
    env = dict(os.environ); env.update(GIT_ENV)
    env["GIT_AUTHOR_DATE"] = str(when); env["GIT_COMMITTER_DATE"] = str(when)
    out = subprocess.run(["git", "commit", "-m", "mirror corpus"],
                         cwd=work, capture_output=True, env=env)
    if out.returncode != 0:
        raise AssertionError(out.stderr.decode("utf-8", "replace"))
    run_git(work, "push", str(bare), "main")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--repetitions", type=int, default=5)
    args = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix="perf-s395-") as td:
        root = Path(td)
        # Clone leg (S-073).
        src = root / "reference.git"
        build_reference_repo(src)
        clone = measure_local_clone(src, root / "clone-out")
        # Search + browse world (S-217 corpus, S-120 browser).
        home = root / "home"; home.mkdir()
        conn = db.init_db(home / "samverk.db")
        accounts = AccountStore(conn)
        owner = accounts.register("volmarr", PW)
        repos = RepositoryStore(conn, home, accounts)
        indexer = CodeIndexer(conn, repos)
        by_repo = {}
        for repo, path, text in corpus_files():
            by_repo.setdefault(repo, []).append((path, text))
        for i, (repo, files) in enumerate(sorted(by_repo.items())):
            repos.create_repository(owner.id, "volmarr", repo,
                                    visibility="public",
                                    description=f"Mirror corpus {repo}")
            commit_and_push(home, home / ("work-" + repo),
                            repos.path_for("volmarr", repo),
                            files, 1700000100 + i)
            indexer.index_repository("volmarr", repo)
        search = CodeSearch(conn, repos)
        searches = measure_searches(search, owner,
                                    repetitions=args.repetitions)
        browse = measure_browse(FileBrowser(repos), owner,
                                "volmarr", "mirror-00",
                                repetitions=args.repetitions)
        pub = publication(clone=clone, searches=searches, browse=browse)
        pub["corpus"] = {"repos": corpus_spec().repos,
                         "files": corpus_spec().files}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(pub, indent=2) + "\n", encoding="utf-8")
    print(f"class={pub['hardware_class']} machine={pub['machine']}")
    for e in pub["entries"]:
        print(e["kind"], "within_budget=", e["within_budget"], e)
    print("classes:", pub["classes"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
