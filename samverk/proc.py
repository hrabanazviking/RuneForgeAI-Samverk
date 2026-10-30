"""Subprocess discipline (S-014).

Samverk shells out to exactly one external program in its core —
git — and it does so under law, because a forge that builds argv
from user input without discipline is a remote-code-execution
service with extra steps (threat model: injection class).

The law:

1. **No shell, ever.** Every spawn is an argv vector passed to the
   OS with `shell=False`. Shell metacharacters in an argument are
   inert bytes inside that one argument — `; rm -rf /` is a (bad)
   revision name, never a second command.
2. **argv position 0 is never user input.** Callers name a program
   *logically* (``"git"``); this module resolves the executable
   from its own allowlist via `shutil.which`. A name containing a
   path separator, or a program not on the allowlist, is refused
   before any spawn.
3. **Argument allowlists.** For git, the first argument is the
   subcommand and must be on `GIT_SUBCOMMANDS` — so no global
   option (`-c`, `--git-dir`, …) can be smuggled into the global
   position, and unlisted subcommands (``clone`` from an arbitrary
   transport, ``config`` writes, …) do not exist as far as callers
   are concerned. A slice that needs a new subcommand extends the
   list *here*, with its reason, never at the call site. On top of
   that, a set of dangerous flags is refused in *any* position:
   the ones that redirect git at another program or another
   repository (`--upload-pack`, `--receive-pack`, `--exec-path`,
   `--git-dir`, `--work-tree`, `--namespace`, `-c`/`--config*`).
4. **The repository is a trusted parameter, not an argument.**
   `run_git_in` takes the repository path (which the caller got
   from S-013's resolver) and inserts ``--git-dir`` itself; user
   arguments can never name a repository.
5. **Environment hygiene.** `GIT_DIR`, `GIT_WORK_TREE`,
   `GIT_NAMESPACE`, and the `GIT_CONFIG_*` injection family are
   stripped from the inherited environment — a hostile or merely
   odd operator environment must not redirect a spawn — and
   `GIT_TERMINAL_PROMPT=0` guarantees git can never hang the
   server waiting for a credential prompt that will never come.
6. **Timeouts are mandatory.** Every spawn carries one; there is
   no unbounded wait anywhere in this module.

This module is where the platform seam's promised `spawn`
primitive (S-002 notes) landed: process creation needed its policy
home first, and this is it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ALLOWED_PROGRAMS = frozenset({"git"})

# The git subcommands Samverk's core may run. Part III (git core)
# and the transport slices extend this list here, with reasons,
# as they land — never at a call site.
GIT_SUBCOMMANDS = frozenset({
    "init",           # S-049 bare repository creation
    "rev-parse",      # ref / object resolution
    "rev-list",       # history walks
    "cat-file",       # object reads
    "hash-object",    # object writes (blobs)
    "log",            # history display
    "show",           # object display
    "diff",           # change display
    "diff-tree",      # change display (plumbing)
    "ls-tree",        # tree listings
    "for-each-ref",   # ref listings
    "show-ref",       # ref resolution
    "symbolic-ref",   # HEAD / ref indirection
    "update-ref",     # ref writes (push path, Part III)
    "name-rev",       # human names for revisions
    "describe",       # tag-relative names
    "merge-base",     # ancestry questions
    "status",         # worktree questions (mirror checks)
    "upload-pack",    # fetch/clone serving (Part III transport)
    "receive-pack",   # push serving (Part III transport)
    "version",        # capability probe
    "gc",             # S-059 garbage collection (off-path runner only)
    "count-objects",  # S-059/object diagnostics (read-only counts)
    "archive",        # S-063 archive downloads (streamed, read-only)
    "mktree",         # S-064 template README substitution (tree rebuild)
    "commit-tree",    # S-064 template substitution commit
})

# Refused in any argument position, as a whole token or as a
# `--flag=value` prefix: each one redirects git at a different
# program, repository, or configuration than the caller chose.
_DANGEROUS_TOKENS = ("-c", "--git-dir", "--work-tree", "--namespace")
_DANGEROUS_PREFIXES = (
    "--upload-pack", "--receive-pack", "--exec-path",
    "--git-dir=", "--work-tree=", "--namespace=",
    "--config", "--config-env", "--super-prefix",
)

_ENV_EXACT_STRIP = frozenset({
    "GIT_DIR", "GIT_WORK_TREE", "GIT_NAMESPACE", "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CONFIG", "GIT_CONFIG_COUNT", "GIT_AUTHOR_DATE",
    "GIT_COMMITTER_DATE",
})
_ENV_PREFIX_STRIP = ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_", "GIT_CONFIG_PARAM_")


class ProcRefused(ValueError):
    """A spawn refused by the S-014 law; `reason` is a stable code."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


def _clean_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        k: v for k, v in os.environ.items()
        if k not in _ENV_EXACT_STRIP
        and not k.startswith(_ENV_PREFIX_STRIP)
    }
    env["GIT_TERMINAL_PROMPT"] = "0"
    if extra:
        env.update(extra)
    return env


def _validate_args(args: list[str]) -> list[str]:
    validated = []
    for arg in args:
        if not isinstance(arg, str):
            raise ProcRefused("non_string_argument", repr(arg))
        if "\x00" in arg:
            raise ProcRefused("nul_in_argument")
        validated.append(arg)
    return validated


def _check_dangerous(subcommand: str, args: list[str]) -> None:
    for arg in args:
        # `git rev-parse --git-dir` is a read-only *query* (print the
        # git dir), not a redirect: git only honours --git-dir as a
        # global option *before* the subcommand, and that position
        # is already closed by the subcommand allowlist. The query
        # form is therefore allowed for rev-parse alone; every
        # `--git-dir=<path>` form stays refused everywhere.
        if subcommand == "rev-parse" and arg == "--git-dir":
            continue
        if arg in _DANGEROUS_TOKENS or arg.startswith(_DANGEROUS_PREFIXES):
            raise ProcRefused("dangerous_flag", arg)


def resolve_program(logical_name: object) -> Path:
    """Resolve an allowlisted logical program name to its
    executable. Anything else — another program, or any name
    carrying a path — is refused: argv[0] is never user input."""
    if not isinstance(logical_name, str) or not logical_name:
        raise ProcRefused("empty_program")
    if "/" in logical_name or "\\" in logical_name:
        raise ProcRefused("program_path_refused", logical_name)
    if logical_name not in ALLOWED_PROGRAMS:
        raise ProcRefused("program_not_allowlisted", logical_name)
    found = shutil.which(logical_name)
    if found is None:
        raise ProcRefused("program_not_found", logical_name)
    return Path(found)


def run_program(
    logical_name: str,
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: float = 30.0,
    input_bytes: bytes | None = None,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Run an allowlisted program with an argv vector, no shell.

    Returns the completed process (bytes stdout/stderr). A timeout
    raises `subprocess.TimeoutExpired` — callers decide what a slow
    git means; the law only guarantees the wait is bounded.
    """
    executable = resolve_program(logical_name)
    argv = [str(executable), *_validate_args(list(args))]
    return subprocess.run(
        argv,
        shell=False,
        cwd=str(cwd) if cwd is not None else None,
        timeout=timeout,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_clean_env(env_extra),
    )


def _validate_git_args(args: list[str]) -> list[str]:
    args = _validate_args(list(args))
    if not args:
        raise ProcRefused("empty_git_invocation")
    if args[0] == "--version":
        if len(args) != 1:
            raise ProcRefused("bad_version_invocation")
        return args
    if args[0] not in GIT_SUBCOMMANDS:
        raise ProcRefused("subcommand_not_allowlisted", args[0])
    _check_dangerous(args[0], args[1:])
    return args


def run_git(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: float = 30.0,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess:
    """Run git under the S-014 law (no repository context)."""
    return run_program(
        "git", _validate_git_args(args),
        cwd=cwd, timeout=timeout, input_bytes=input_bytes,
    )


def run_git_clone_local(
    source_path: Path,
    dest_path: Path,
    *,
    timeout: float = 120.0,
) -> subprocess.CompletedProcess:
    """Clone one local bare repository to another local path —
    the S-055 fork seam, and the *only* clone in Samverk.

    Generic `clone` deliberately stays off `GIT_SUBCOMMANDS`:
    `run_git(["clone", <url>])` is refused, exactly as S-014's
    battery demands, because a clone source taken from a string
    is a remote-code-fetch primitive. Here both paths are
    trusted `Path` parameters the caller resolved through
    S-013 — never strings, never URLs — and this function
    builds the argv itself, so no caller-supplied argument
    exists at all.
    """
    for value in (source_path, dest_path):
        if not isinstance(value, Path) or not value.is_absolute():
            raise ProcRefused(
                "clone_path_not_trusted",
                "clone paths must be resolved local Path objects")
    executable = resolve_program("git")
    argv = [str(executable), "clone", "--bare",
            str(source_path), str(dest_path)]
    return subprocess.run(
        argv, shell=False, timeout=timeout,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=_clean_env())


def run_git_in(
    repo_path: Path,
    args: list[str],
    *,
    timeout: float = 30.0,
    input_bytes: bytes | None = None,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Run git against *repo_path* — a bare-repository path the
    caller resolved through S-013. `--git-dir` is inserted here,
    from that trusted parameter; the caller's arguments follow the
    subcommand allowlist as usual and can never name a repository
    themselves."""
    args = _validate_git_args(args)
    if args[0] in {"--version", "version", "init"}:
        raise ProcRefused(
            "subcommand_not_repo_scoped", args[0])
    executable = resolve_program("git")
    argv = [str(executable), f"--git-dir={Path(repo_path)}", *args]
    return subprocess.run(
        argv,
        shell=False,
        timeout=timeout,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_clean_env(env_extra),
    )


def popen_git_in(
    repo_path: Path,
    args: list[str],
) -> subprocess.Popen:
    """Spawn git against *repo_path* for streamed output (S-063).

    Same validation, allowlist, dangerous-flag and environment
    law as `run_git_in`; the difference is only that the caller
    consumes stdout incrementally instead of receiving one
    buffered result. The caller owns the process: it must read
    stdout to EOF, enforce its own deadline (killing the child
    on expiry), and check the exit status — there is no
    unbounded helper here that hides that duty.
    """
    args = _validate_git_args(args)
    if args[0] in {"--version", "version", "init"}:
        raise ProcRefused(
            "subcommand_not_repo_scoped", args[0])
    executable = resolve_program("git")
    argv = [str(executable), f"--git-dir={Path(repo_path)}", *args]
    return subprocess.Popen(
        argv,
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_clean_env(),
    )
