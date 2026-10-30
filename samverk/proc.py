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
    "bundle",         # S-074 repository backup primitive (create/verify)
    "fsck",           # S-075 corruption assessment (read-only check)
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
    # --no-hardlinks: a local clone otherwise hardlinks the
    # source's object files, so the clone would share inodes
    # with its source — S-055's fork-independence claim (and
    # S-073's clone measurement) require a real copy.
    argv = [str(executable), "clone", "--bare", "--no-hardlinks",
            str(source_path), str(dest_path)]
    return subprocess.run(
        argv, shell=False, timeout=timeout,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=_clean_env())


# Schemes a remote git address may use. `file:`, local paths,
# and git's `ext::` transport are deliberately absent: a clone
# source that can name a local path or an arbitrary command is
# a remote-code-execution primitive, not an import feature.
REMOTE_URL_SCHEMES = frozenset({"https", "http", "git", "ssh"})


def validate_remote_url(url: object) -> str:
    """Validate a remote git URL for the clone/fetch seams.

    The law: a remote scheme with a real host; no whitespace
    or control bytes; never a leading dash (it would be read
    as a flag); and **no credentials inside the URL** — a
    `user:password@host` address would leak its secret into
    every log, process list, and audit row that mentions it.
    Private imports pass their token through the credential
    seam of `run_git_clone_remote` instead, never the URL.
    """
    from urllib.parse import urlparse
    if not isinstance(url, str) or not url:
        raise ProcRefused("clone_url_invalid", "empty address")
    if url.startswith("-") or any(
            ord(c) <= 0x20 or ord(c) == 0x7F for c in url):
        raise ProcRefused("clone_url_invalid",
                           "address carries whitespace or controls")
    parsed = urlparse(url)
    if parsed.scheme not in REMOTE_URL_SCHEMES:
        raise ProcRefused("clone_url_invalid",
                          f"scheme {parsed.scheme!r} is not a remote "
                          "git transport")
    if not parsed.hostname:
        raise ProcRefused("clone_url_invalid", "address has no host")
    if parsed.username or parsed.password:
        raise ProcRefused(
            "clone_url_invalid",
            "credentials must never travel inside a URL; "
            "use the token seam")
    if parsed.fragment:
        raise ProcRefused("clone_url_invalid",
                          "address carries a fragment")
    if not parsed.path or parsed.path == "/":
        raise ProcRefused("clone_url_invalid",
                          "address names no repository")
    return url


def _askpass_env(token: str, token_username: str) -> tuple[dict[str, str], object]:
    """Build the credential environment for a private import.

    The token itself lives only in the child process's
    environment. A tiny askpass script — containing no secret,
    only the *names* of the environment variables — answers
    git's username/password prompts from that environment, so
    the token never appears in argv, in the URL, in a config
    file, or in any log line this module can produce. Returns
    (env_extra, tempdir) — the caller keeps the tempdir alive
    for the duration of the spawn and it is removed after.
    """
    import stat
    import tempfile
    tempdir = tempfile.TemporaryDirectory(prefix="samverk-askpass-")
    script = Path(tempdir.name) / "askpass.sh"
    script.write_text(
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "*Username*) printf '%s' \"$SAMVERK_IMPORT_USERNAME\" ;;\n"
        "*) printf '%s' \"$SAMVERK_IMPORT_TOKEN\" ;;\n"
        "esac\n")
    script.chmod(stat.S_IRWXU)
    env = {
        "GIT_ASKPASS": str(script),
        "GIT_TERMINAL_PROMPT": "0",
        "SAMVERK_IMPORT_TOKEN": token,
        "SAMVERK_IMPORT_USERNAME": token_username,
    }
    return env, tempdir


def run_git_clone_remote(
    url: str,
    dest_path: Path,
    *,
    timeout: float = 120.0,
    token: str | None = None,
    token_username: str = "x-access-token",
) -> subprocess.CompletedProcess:
    """Clone a *remote* repository — the S-069 import seam,
    and the only remote clone in Samverk.

    Generic `clone` stays off `GIT_SUBCOMMANDS` (S-014's
    battery still refuses `run_git(["clone", …])`): this
    function takes the address as a dedicated parameter,
    validates it through `validate_remote_url`, takes the
    destination as a trusted resolved `Path` from S-013, and
    builds its argv itself. A token, when given, travels
    only through the askpass environment (see `_askpass_env`)
    — never the URL, never argv, never output.
    """
    url = validate_remote_url(url)
    if not isinstance(dest_path, Path) or not dest_path.is_absolute():
        raise ProcRefused(
            "clone_path_not_trusted",
            "clone destination must be a resolved local Path object")
    executable = resolve_program("git")
    argv = [str(executable), "clone", "--bare", url, str(dest_path)]
    if token is None:
        return subprocess.run(
            argv, shell=False, timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=_clean_env())
    env_extra, tempdir = _askpass_env(token, token_username)
    try:
        return subprocess.run(
            argv, shell=False, timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=_clean_env(env_extra))
    finally:
        tempdir.cleanup()


def run_git_fetch_from(
    repo_path: Path,
    source: str | Path,
    *,
    timeout: float = 120.0,
    token: str | None = None,
    token_username: str = "x-access-token",
) -> subprocess.CompletedProcess:
    """Fetch every head and tag from one source into a bare
    repository — the S-070 mirror seam, and the only fetch
    in Samverk (generic `fetch` stays refused under S-014).

    The source is either a trusted local `Path` (an on-disk
    repository the caller resolved) or a remote URL string
    validated by `validate_remote_url`; the destination
    repository is likewise a trusted `Path` parameter. This
    function builds its argv itself — `--git-dir` from the
    parameter, a fixed mirror refspec — so no caller string
    can redirect the fetch. Tokens use the same askpass
    environment as the clone seam and are never logged.
    """
    if isinstance(source, Path):
        if not source.is_absolute():
            raise ProcRefused(
                "fetch_source_not_trusted",
                "a local fetch source must be a resolved Path object")
        source_arg = str(source)
    else:
        source_arg = validate_remote_url(source)
    if not isinstance(repo_path, Path) or not repo_path.is_absolute():
        raise ProcRefused(
            "fetch_path_not_trusted",
            "fetch destination must be a resolved local Path object")
    executable = resolve_program("git")
    argv = [str(executable), f"--git-dir={repo_path}", "fetch",
            "--prune", source_arg,
            "+refs/heads/*:refs/heads/*", "+refs/tags/*:refs/tags/*"]
    if token is None:
        return subprocess.run(
            argv, shell=False, timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=_clean_env())
    env_extra, tempdir = _askpass_env(token, token_username)
    try:
        return subprocess.run(
            argv, shell=False, timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=_clean_env(env_extra))
    finally:
        tempdir.cleanup()


PACK_PROGRAMS = frozenset({"upload-pack", "receive-pack"})


def run_git_pack(
    repo_path: Path,
    program: str,
    *,
    advertise: bool = False,
    stateless: bool = False,
    input_bytes: bytes | None = None,
    protocol_version: int | None = None,
    timeout: float = 120.0,
) -> subprocess.CompletedProcess:
    """Run a git pack program for a transport — the Part IV seam
    (S-077…S-080), built like the clone/fetch seams: the generic
    subcommand path cannot serve here, because `upload-pack` and
    `receive-pack` take the repository as their *positional*
    argument and do not honour the `--git-dir` global the way
    other plumbing does.

    The law, on top of S-014's:

    - *program* is one of `PACK_PROGRAMS`, named by the caller
      from its own service table — never from client input.
    - The only flags this seam can emit are `--advertise-refs`
      and `--stateless-rpc`, chosen by boolean parameters; no
      caller string reaches argv at all.
    - *repo_path* is a trusted resolved `Path` (S-013), passed
      as the final positional argument by this function itself.
    - Protocol v2 is an *environment* fact (`GIT_PROTOCOL`),
      set explicitly from *protocol_version* — and scrubbed
      when the caller did not ask for it, so an inherited
      environment can never silently change the dialect a
      transport speaks.
    """
    if program not in PACK_PROGRAMS:
        raise ProcRefused("pack_program_not_allowlisted", str(program))
    if not isinstance(repo_path, Path) or not repo_path.is_absolute():
        raise ProcRefused(
            "pack_path_not_trusted",
            "pack repository must be a resolved local Path object")
    if protocol_version not in (None, 0, 2):
        raise ProcRefused(
            "pack_protocol_invalid", repr(protocol_version))
    executable = resolve_program("git")
    argv = [str(executable), program]
    if stateless:
        argv.append("--stateless-rpc")
    if advertise:
        argv.append("--advertise-refs")
    argv.append(str(repo_path))
    env = _clean_env()
    env.pop("GIT_PROTOCOL", None)
    if protocol_version == 2:
        env["GIT_PROTOCOL"] = "version=2"
    return subprocess.run(
        argv, shell=False, timeout=timeout, input=input_bytes,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)


def run_git_pack_stdio(
    repo_path: Path,
    program: str,
    *,
    stdin=None,
    stdout=None,
    stderr=None,
    protocol_version: int | None = None,
) -> int:
    """Run a git pack program with the caller's streams attached
    (the SSH door, S-086/S-087): the SSH channel *is* the pack
    program's stdin/stdout, interactively, so nothing may be
    buffered through Python. Same law as `run_git_pack` — the
    program comes from `PACK_PROGRAMS` (named by the caller's
    own table, never by client input), no `--stateless-rpc`
    (an SSH session is stateful by nature), the repository is a
    trusted resolved Path passed as the final positional
    argument by this function itself, and `GIT_PROTOCOL` is set
    or scrubbed explicitly. Returns the program's exit code.
    The caller owns timeouts and limits (S-091's seam wraps
    this one); this helper hides no such duty.
    """
    if program not in PACK_PROGRAMS:
        raise ProcRefused("pack_program_not_allowlisted", str(program))
    if not isinstance(repo_path, Path) or not repo_path.is_absolute():
        raise ProcRefused(
            "pack_path_not_trusted",
            "pack repository must be a resolved local Path object")
    if protocol_version not in (None, 0, 2):
        raise ProcRefused(
            "pack_protocol_invalid", repr(protocol_version))
    executable = resolve_program("git")
    argv = [str(executable), program, str(repo_path)]
    env = _clean_env()
    env.pop("GIT_PROTOCOL", None)
    if protocol_version == 2:
        env["GIT_PROTOCOL"] = "version=2"
    proc = subprocess.Popen(
        argv, shell=False, stdin=stdin, stdout=stdout,
        stderr=stderr, env=env)
    return proc.wait()


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
