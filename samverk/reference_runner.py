"""Reference runner -- a small native runner
program (S-318).

Part XVI's seam, stated in S-313, is the
product: Samverk defines workflows and talks to
runners. S-316 wrote the contract a runner
speaks -- register, poll for work, stream logs,
report conclusion -- and S-317 built the
registration the contract's first movement
needs. This slice is the other end of the wire:
a small, native runner program (no Docker, no
container of any kind) that speaks the S-316
protocol end to end and actually executes the
job it is handed, in a working directory, under
environment discipline. It is the reference the
protocol is proven against: if this runner can
carry a job from poll to conclusion, the
contract is real, and any other runner speaking
the same seven messages can take its place.

- **A standalone program, not forge core.**
  S-014's subprocess law governs the forge's own
  spawns (git, and nothing else, no shell, ever)
  because the forge must never become a
  remote-code-execution service. A runner is
  the opposite shape by design: executing a
  job's shell steps IS its whole commission --
  the steps are the workflow author's own
  ``run:`` text, already judged data under
  S-313/S-315. So the runner keeps its own
  discipline, stated here, in place of borrowing
  the forge's: the shell is a fixed program the
  runner resolves itself (``sh``, then ``bash``,
  from PATH -- never a name the job supplies),
  every spawn is an argv vector with
  ``shell=False`` whose only variable part is
  the step's own text handed to the shell as
  data, every spawn carries a timeout, and
  every spawn runs in the job's own working
  directory under the environment law below.
- **Environment discipline.** A step inherits
  almost nothing. The child environment is
  built from nothing, in three parts and no
  fourth: the runner's context variables
  (``SAMVERK_RUN_ID``, ``SAMVERK_JOB_ID``,
  ``SAMVERK_WORKFLOW``, ``SAMVERK_REPOSITORY``
  and ``SAMVERK_OID``, set by the runner from
  the assignment itself); a small allowlist of
  host variables a shell step cannot work
  without (``PATH``, ``LANG``, ``LC_ALL``,
  ``TZ`` -- pass-through of the operator's own
  values, named here, never widened by a job);
  and exactly the variables the assignment
  names in ``env_names``, whose values the
  runner holds locally. The assignment carries
  names, never values (S-316); values travel
  S-319's road when it lands -- until then the
  runner's operator supplies them locally (a
  mapping in process, a JSON file to the
  program), and this module never logs one.
  A named variable with no local value is
  refused (``runner_env_missing``), a local
  value the assignment never named is refused
  (``runner_env_unnamed`` -- values are never
  smuggled past the protocol), and a denylist
  of variables that redirect code loading or
  the shell itself (``LD_PRELOAD`` and kin,
  ``PYTHONPATH``, ``BASH_ENV``, the ``GIT_*``
  redirection family) is refused in any
  position (``runner_env_refused``), named or
  not.
- **Working-directory discipline.** Each job
  runs in one fresh directory under the
  runner's work root, named for its run and
  job and resolved before use: the resolved
  directory must sit inside the resolved work
  root (``runner_workdir_escape``), the work
  root must already exist (the runner creates
  job directories, never its root -- a missing
  root is an operator error, said in words),
  and a job directory that already holds
  anything is refused rather than reused
  (``runner_workdir_dirty``), so no job ever
  inherits another job's files.
- **The protocol, spoken whole.** The runner
  builds its register message and judges it
  with S-316's own parser (the token rides in
  the message and is kept nowhere on the
  runner), parses the forge's poll answer with
  ``parse_poll_response`` (a wait is honoured
  as a wait), judges the label law itself and
  declines in words when the job is not
  addressed to it, accepts before it runs,
  sends a heartbeat as each step starts, and
  streams each step's output as numbered
  ``log_chunk`` messages -- every outbound
  message judged by S-316's parsers before it
  is "sent", and the whole stream re-judged
  with ``validate_log_stream`` before the
  conclusion is built. Exactly one conclusion
  closes the job, built through
  ``aggregate_conclusion`` and judged against
  the assignment by ``parse_conclusion``, so
  the runner's final word cannot disagree
  with its own steps. Sending is a sink: a
  callable the operator supplies, or the
  runner's own record -- the transport (HTTP
  in a deployed runner) is the operator's
  seam, deliberately not invented here.
- **Execution law.** Steps run in order. A
  step that exits non-zero has failed; the
  steps after it are reported ``skipped``
  without running (a job does not walk past
  its own failure). The job's timeout budget
  is the assignment's ``timeout_minutes``
  shared across its steps, and an operator
  ceiling (``max_step_seconds``) may narrow
  any single step further; a step that
  overruns concludes ``timed_out`` and the
  rest are skipped. An operator cancellation
  (``cancel()``, the seam S-324's cancel will
  call) lands between steps: the running
  step's word stands, the rest are
  ``cancelled``. Output is captured per step
  and streamed stdout first, then stderr --
  honest limit: the two streams are not
  interleaved in real time, because capture
  is per step; the per-step sequence is the
  ordering law within each stream's chunks,
  and the chunking never splits a line except
  where one line alone exceeds the protocol's
  chunk bound.
- **Nothing stored, nothing witnessed.** The
  runner keeps no registry, writes no forge
  table and mints no token: its state is the
  work root's directories and its own message
  record. No migration (schema stays 129),
  no taxonomy event (135 stand: 33 auth /
  89 repo / 13 admin); executing a job is the
  runner's act on its own machine, witnessed
  by the protocol messages themselves, and
  S-321 owns landing the conclusion as a
  check run. The program face is
  ``python3 -m samverk.reference_runner``
  (``--work-root``, ``--assignment``,
  ``--env-file``, ``--out``): it reads one
  assignment as JSON, runs it, and writes
  every protocol message it spoke as JSON
  lines -- the end-to-end proof, runnable by
  hand.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .escaping import escape_html_text
from .runner_protocol import (
    LOG_STREAMS, MAX_LOG_CHUNK_CHARS, PROTOCOL_VERSION,
    RUNNER_CONCLUSIONS, AssignmentOffer, ConclusionReport,
    LogChunk, PollWait, RunnerProtocolError,
    aggregate_conclusion, check_assignment_labels,
    parse_assignment_reply, parse_conclusion, parse_heartbeat,
    parse_log_chunk, parse_poll, parse_poll_response,
    parse_registration, validate_log_stream)

__all__ = [
    "AGENT_VERSION", "BASE_ENV_ALLOWLIST", "ENV_DENYLIST",
    "MAX_ENV_VALUE_CHARS", "RUNNER_NAME", "ReferenceRunner",
    "ReferenceRunnerAudit", "ReferenceRunnerError", "RunResult",
    "audit_reference_runner", "build_child_env", "main",
    "render_reference_runner_page", "resolve_shell",
    "resolve_workdir", "split_log_text",
]

RUNNER_NAME = "samverk-reference-runner"
AGENT_VERSION = "reference-runner 1 (S-318)"

#: Host variables a shell step cannot work
#: without, passed through from the operator's
#: own environment. Named here, closed: a job
#: can never widen this list.
BASE_ENV_ALLOWLIST = ("LANG", "LC_ALL", "PATH", "TZ")

#: Variables that redirect code loading, the
#: shell's own startup, or another program's
#: repository: refused in any position, whether
#: the assignment names them or a local value
#: offers them.
ENV_DENYLIST = frozenset({
    "BASHOPTS", "BASH_ENV", "DYLD_INSERT_LIBRARIES",
    "DYLD_LIBRARY_PATH", "ENV", "GIT_DIR",
    "GIT_NAMESPACE", "GIT_WORK_TREE", "IFS",
    "LD_AUDIT", "LD_LIBRARY_PATH", "LD_PRELOAD",
    "NODE_OPTIONS", "PERL5OPT", "PYTHONHOME",
    "PYTHONPATH", "PYTHONSTARTUP", "RUBYOPT",
    "SHELLOPTS",
})

#: Variables the runner itself sets from the
#: assignment, so a step can know its own run.
CONTEXT_ENV_NAMES = (
    "SAMVERK_JOB_ID", "SAMVERK_OID",
    "SAMVERK_REPOSITORY", "SAMVERK_RUN_ID",
    "SAMVERK_WORKFLOW")

MAX_ENV_VALUE_CHARS = 8192

#: The shells the runner will resolve, in
#: order. Fixed by the runner; a job never
#: names its shell.
SHELL_CANDIDATES = ("sh", "bash")


class ReferenceRunnerError(ValueError):
    """One refusal of the reference runner: a
    machine-branchable reason with its human
    detail, in the house shape."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def _refused(reason: str, message: str) -> ReferenceRunnerError:
    return ReferenceRunnerError(reason, message)


# ------------------------------------------------------------------
# Environment discipline.
# ------------------------------------------------------------------

def build_child_env(offer: AssignmentOffer,
                    values: dict | None = None,
                    base_env: dict | None = None) -> dict:
    """Build one job's child environment from
    nothing: the runner's context variables from
    the assignment, the allowlisted host
    variables, and exactly the variables the
    assignment names, valued from the runner's
    local ``values``. Refusals, each in words:
    runner_env_refused for a denylisted name in
    any position, runner_env_missing for a named
    variable with no local value, runner_env_
    unnamed for a local value the assignment
    never named, runner_invalid for a malformed
    name or value."""
    values = dict(values or {})
    base = os.environ if base_env is None else base_env
    for name in list(offer.env_names) + list(values):
        if not isinstance(name, str) or not name:
            raise _refused(
                "runner_invalid",
                "Environment: a variable name is text.")
        if name in ENV_DENYLIST or name.startswith("GIT_CONFIG"):
            raise _refused(
                "runner_env_refused",
                f"Environment: {name} is refused -- it "
                "redirects code loading, the shell itself "
                "or another program's repository, and no "
                "assignment may carry it.")
        if name in CONTEXT_ENV_NAMES:
            raise _refused(
                "runner_env_refused",
                f"Environment: {name} is the runner's own "
                "context variable; an assignment does not "
                "supply it.")
    env: dict = {}
    for name in BASE_ENV_ALLOWLIST:
        if base.get(name):
            env[name] = base[name]
    env["SAMVERK_RUN_ID"] = offer.run_id
    env["SAMVERK_JOB_ID"] = offer.job_id
    env["SAMVERK_WORKFLOW"] = offer.workflow
    env["SAMVERK_REPOSITORY"] = offer.repository
    env["SAMVERK_OID"] = offer.oid
    for name in offer.env_names:
        if name not in values:
            raise _refused(
                "runner_env_missing",
                f"Environment: the assignment names {name} "
                "and this runner holds no local value for "
                "it; values travel S-319's road, and until "
                "it lands the operator supplies them "
                "locally -- a named variable is never "
                "invented and never silently dropped.")
        value = values[name]
        if not isinstance(value, str) or "\x00" in value \
                or len(value) > MAX_ENV_VALUE_CHARS:
            raise _refused(
                "runner_invalid",
                f"Environment: the value for {name} is text "
                f"of at most {MAX_ENV_VALUE_CHARS} "
                "characters, with no NUL byte.")
        env[name] = value
    for name in values:
        if name not in offer.env_names:
            raise _refused(
                "runner_env_unnamed",
                f"Environment: a local value for {name} is "
                "held, and the assignment never named it; "
                "values are never smuggled past the "
                "protocol -- the assignment's env_names "
                "are the whole of what a job receives.")
    return env


# ------------------------------------------------------------------
# Working-directory and shell discipline.
# ------------------------------------------------------------------

def resolve_workdir(work_root: Path,
                    offer: AssignmentOffer) -> Path:
    """Resolve one job's working directory under
    the work root and create it, fresh. The root
    must already exist (runner_workdir_missing);
    the resolved job directory must sit inside
    the resolved root (runner_workdir_escape);
    a job directory already holding anything is
    refused (runner_workdir_dirty)."""
    root = Path(work_root)
    if not root.is_dir():
        raise _refused(
            "runner_workdir_missing",
            f"Working directory: the work root {root} "
            "does not exist; the runner creates job "
            "directories under its root, never the root "
            "itself -- a missing root is an operator "
            "error.")
    resolved_root = root.resolve()
    candidate = (resolved_root
                 / f"{offer.run_id}--{offer.job_id}")
    resolved = candidate.resolve()
    if resolved != resolved_root \
            and resolved_root not in resolved.parents:
        raise _refused(
            "runner_workdir_escape",
            "Working directory: the job's directory "
            "resolves outside the work root; a job runs "
            "inside its root or not at all.")
    if candidate.exists() and any(candidate.iterdir()):
        raise _refused(
            "runner_workdir_dirty",
            "Working directory: this job's directory "
            "already holds files; no job inherits "
            "another job's files, so the directory is "
            "refused rather than reused.")
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def resolve_shell() -> str:
    """Resolve the runner's shell from its fixed
    candidate list. A machine with no shell from
    the list cannot run shell steps, and the
    runner says so (runner_shell_missing) rather
    than improvising one."""
    for candidate in SHELL_CANDIDATES:
        found = shutil.which(candidate)
        if found:
            return found
    raise _refused(
        "runner_shell_missing",
        "Shell: none of " + ", ".join(SHELL_CANDIDATES)
        + " is on this machine's PATH; the reference "
        "runner runs shell steps and cannot improvise "
        "a shell.")


def split_log_text(text: str) -> list:
    """Split one stream's captured text into
    protocol-sized chunks: whole lines while
    they fit, a single over-long line hard-split
    at the bound. An empty stream splits to no
    chunks -- an empty chunk says nothing and is
    not sent (S-316)."""
    if not text:
        return []
    chunks: list = []
    current = ""
    for line in text.splitlines(keepends=True):
        piece = line
        while len(piece) > MAX_LOG_CHUNK_CHARS:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(piece[:MAX_LOG_CHUNK_CHARS])
            piece = piece[MAX_LOG_CHUNK_CHARS:]
        if len(current) + len(piece) > MAX_LOG_CHUNK_CHARS:
            chunks.append(current)
            current = ""
        current += piece
    if current:
        chunks.append(current)
    return chunks


# ------------------------------------------------------------------
# The runner itself.
# ------------------------------------------------------------------

@dataclass(frozen=True)
class RunResult:
    """One job's outcome as the runner lived it:
    the reply it sent, every step's word in
    order, the terminal conclusion (None when
    the job was declined before it ran), the
    working directory it ran in (empty when it
    never ran), the duration, and every protocol
    message the runner spoke, in order."""
    run_id: str
    job_id: str
    decision: str
    step_conclusions: tuple
    conclusion: ConclusionReport | None
    workdir: str
    duration_seconds: int
    messages: tuple


class ReferenceRunner:
    """The reference runner: one runner, one job
    at a time, speaking S-316 whole. ``sink`` is
    the transport seam -- a callable taking each
    protocol message as a mapping; every message
    is also kept on the runner's own record.
    ``clock`` and ``max_step_seconds`` are the
    operator's seams: the clock for tests, the
    step ceiling for an operator who caps any
    single step below the job's own budget."""

    def __init__(self, work_root, *, labels,
                 sink=None, clock=None,
                 max_step_seconds: float | None = None,
                 shell: str | None = None):
        self.work_root = Path(work_root)
        self.labels = tuple(labels)
        self.sink = sink
        self.clock = clock or time.monotonic
        self.max_step_seconds = max_step_seconds
        self.shell = shell
        self.messages: list = []
        self._cancelled = False

    # -- the wire ------------------------------------------------

    def _send(self, payload: dict, parser) -> None:
        """Judge one outbound message with
        S-316's own parser, then send it: a
        message the protocol would refuse is a
        runner bug, surfaced -- never sent."""
        parser(payload)
        self.messages.append(payload)
        if self.sink is not None:
            self.sink(payload)

    def registration_message(self, *, name: str,
                             scope: str, target: str,
                             registration_token: str
                             ) -> dict:
        """Build this runner's register message
        and judge it with S-316's parser. The
        token rides in the returned message and
        is kept nowhere on the runner."""
        payload = {
            "kind": "register",
            "protocol": PROTOCOL_VERSION,
            "name": name, "labels": list(self.labels),
            "scope": scope, "target": target,
            "registration_token": registration_token,
            "agent_version": AGENT_VERSION,
        }
        parse_registration(payload)
        return payload

    def poll_message(self, *, name: str,
                     running_run_id: str = "") -> dict:
        """Build this runner's poll message and
        judge it with S-316's parser."""
        payload = {
            "kind": "poll", "protocol": PROTOCOL_VERSION,
            "runner": name, "labels": list(self.labels),
            "running": running_run_id,
        }
        parse_poll(payload)
        return payload

    def cancel(self) -> None:
        """The operator's cancellation word, the
        seam S-324's cancel will call: it lands
        between steps -- the running step's word
        stands, the steps after it are cancelled
        and never run."""
        self._cancelled = True

    # -- the job -------------------------------------------------

    def handle_poll_response(self, payload):
        """Answer one poll response whole: a wait
        is returned as S-316's PollWait and
        nothing runs; an assignment is run and
        its RunResult returned. This is the
        protocol proven end to end in one call."""
        answer = parse_poll_response(payload)
        if isinstance(answer, PollWait):
            return answer
        return self.run_assignment(answer)

    def run_assignment(self, offer,
                       env_values: dict | None = None
                       ) -> RunResult:
        """Run one assignment (an AssignmentOffer,
        or a raw assignment mapping judged by
        S-316 first) under this runner's
        discipline, speaking the protocol as it
        goes, and return the job's RunResult."""
        if not isinstance(offer, AssignmentOffer):
            offer = parse_poll_response(offer)
            if not isinstance(offer, AssignmentOffer):
                raise _refused(
                    "runner_invalid",
                    "Assignment: a wait answer carries no "
                    "job to run.")
        started = self.clock()
        sent_from = len(self.messages)

        def elapsed() -> int:
            return max(0, int(self.clock() - started))

        poll = parse_poll({
            "kind": "poll", "protocol": PROTOCOL_VERSION,
            "runner": RUNNER_NAME,
            "labels": list(self.labels), "running": ""})
        try:
            check_assignment_labels(offer, poll)
        except RunnerProtocolError as exc:
            reply = {
                "kind": "assignment_reply",
                "protocol": PROTOCOL_VERSION,
                "run_id": offer.run_id,
                "job_id": offer.job_id,
                "decision": "decline", "reason": str(exc),
            }
            self._send(reply, parse_assignment_reply)
            return RunResult(
                run_id=offer.run_id, job_id=offer.job_id,
                decision="decline", step_conclusions=(),
                conclusion=None, workdir="",
                duration_seconds=elapsed(),
                messages=tuple(self.messages[sent_from:]))
        child_env = build_child_env(offer, env_values)
        workdir = resolve_workdir(self.work_root, offer)
        if self.shell is None:
            self.shell = resolve_shell()
        reply = {
            "kind": "assignment_reply",
            "protocol": PROTOCOL_VERSION,
            "run_id": offer.run_id, "job_id": offer.job_id,
            "decision": "accept", "reason": "",
        }
        self._send(reply, parse_assignment_reply)
        budget = float(offer.timeout_minutes) * 60.0
        words: list = []
        summaries: list = []
        chunks: list = []
        halted: str | None = None
        for index, step in enumerate(offer.steps, start=1):
            if halted is not None:
                words.append(halted)
                continue
            if self._cancelled:
                words.append("cancelled")
                halted = "cancelled"
                continue
            self._send({
                "kind": "heartbeat",
                "protocol": PROTOCOL_VERSION,
                "run_id": offer.run_id,
                "job_id": offer.job_id,
                "step_index": index,
                "elapsed_seconds": elapsed(),
            }, parse_heartbeat)
            remaining = budget - (self.clock() - started)
            limit = max(0.05, remaining)
            if self.max_step_seconds is not None:
                limit = min(limit, self.max_step_seconds)
            try:
                done = subprocess.run(
                    [self.shell, "-c", step.run],
                    shell=False, cwd=str(workdir),
                    env=child_env, timeout=limit,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True,
                    errors="replace")
                word = ("success" if done.returncode == 0
                        else "failure")
                out_text, err_text = done.stdout, done.stderr
                if word == "failure":
                    summaries.append(
                        f"Step {index} ({step.name or 'unnamed'})"
                        f" failed with exit code "
                        f"{done.returncode}.")
                    halted = "skipped"
            except subprocess.TimeoutExpired as exc:
                word = "timed_out"
                out_text = exc.stdout.decode(
                    "utf-8", "replace") \
                    if isinstance(exc.stdout, bytes) \
                    else (exc.stdout or "")
                err_text = exc.stderr.decode(
                    "utf-8", "replace") \
                    if isinstance(exc.stderr, bytes) \
                    else (exc.stderr or "")
                summaries.append(
                    f"Step {index} ({step.name or 'unnamed'})"
                    " exceeded its time budget and was "
                    "stopped.")
                halted = "skipped"
            words.append(word)
            for stream, text in (("stdout", out_text),
                                 ("stderr", err_text)):
                for sequence, piece in enumerate(
                        split_log_text(text), start=1):
                    payload = {
                        "kind": "log_chunk",
                        "protocol": PROTOCOL_VERSION,
                        "run_id": offer.run_id,
                        "job_id": offer.job_id,
                        "step_index": index,
                        "sequence": sequence,
                        "stream": stream, "text": piece,
                    }
                    chunk = parse_log_chunk(
                        payload, expected_sequence=sequence)
                    chunks.append(chunk)
                    self.messages.append(payload)
                    if self.sink is not None:
                        self.sink(payload)
        validate_log_stream(chunks)
        overall = aggregate_conclusion(words)
        summary = " ".join(summaries)
        if overall == "failure" and not summary:
            summary = "A step failed."
        conclusion_payload = {
            "kind": "conclusion",
            "protocol": PROTOCOL_VERSION,
            "run_id": offer.run_id, "job_id": offer.job_id,
            "conclusion": overall,
            "steps": [
                {"index": i, "name": step.name,
                 "conclusion": word}
                for i, (step, word) in enumerate(
                    zip(offer.steps, words), start=1)],
            "duration_seconds": elapsed(),
            "summary": summary,
        }
        report = parse_conclusion(conclusion_payload, offer)
        self.messages.append(conclusion_payload)
        if self.sink is not None:
            self.sink(conclusion_payload)
        return RunResult(
            run_id=offer.run_id, job_id=offer.job_id,
            decision="accept",
            step_conclusions=tuple(words),
            conclusion=report, workdir=str(workdir),
            duration_seconds=report.duration_seconds,
            messages=tuple(self.messages[sent_from:]))


# ------------------------------------------------------------------
# The audit: the runner checked against the live instance.
# ------------------------------------------------------------------

@dataclass(frozen=True)
class ReferenceRunnerAudit:
    """The reference runner checked against one
    live instance: its own discipline's integrity
    (the denylist and the allowlist never meet,
    the context names are the runner's five, the
    conclusions it can speak are S-316's), how
    much schema was inspected, and every
    runner-execution surface found in it. The
    runner stands cleanly while it has added no
    table of its own -- the lawful runner tables
    are S-317's two registry tables, and any
    other runner-named table or column is a
    surface arriving ahead of its slice."""
    discipline_ok: bool
    tables_scanned: int
    columns_scanned: int
    offending_tables: tuple
    offending_columns: tuple

    @property
    def stands_cleanly(self) -> bool:
        return (self.discipline_ok
                and not self.offending_tables
                and not self.offending_columns)


_LAWFUL_RUNNER_TABLES = frozenset({
    "runner_registration_tokens", "runners"})


def audit_reference_runner(conn) -> ReferenceRunnerAudit:
    """Check the reference runner against the
    live instance: its discipline holds in the
    module's own constants, and it has stored
    nothing -- no table or column beyond S-317's
    lawful registry names carries a runner's
    mark. Pure read."""
    discipline_ok = (
        not (set(BASE_ENV_ALLOWLIST) & ENV_DENYLIST)
        and not (set(CONTEXT_ENV_NAMES) & ENV_DENYLIST)
        and tuple(sorted(BASE_ENV_ALLOWLIST))
        == tuple(BASE_ENV_ALLOWLIST)
        and set(LOG_STREAMS) == {"stdout", "stderr"}
        and "failure" in RUNNER_CONCLUSIONS)
    tables = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master"
        " WHERE type = 'table' ORDER BY name").fetchall()]
    offending_tables: list = []
    offending_columns: list = []
    columns_scanned = 0
    for table in tables:
        if "runner" in table.lower() \
                and table not in _LAWFUL_RUNNER_TABLES:
            offending_tables.append(table)
        safe = table.replace('"', '""')
        for row in conn.execute(
                f'PRAGMA table_info("{safe}")').fetchall():
            columns_scanned += 1
            if "runner" in str(row[1]).lower() \
                    and table not in _LAWFUL_RUNNER_TABLES:
                offending_columns.append(f"{table}.{row[1]}")
    return ReferenceRunnerAudit(
        discipline_ok=discipline_ok,
        tables_scanned=len(tables),
        columns_scanned=columns_scanned,
        offending_tables=tuple(offending_tables),
        offending_columns=tuple(offending_columns))


def render_reference_runner_page(
        audit: ReferenceRunnerAudit | None = None) -> str:
    """The reference runner, rendered: what it
    is, the discipline it runs under, and the
    checked proof when an audit rides along --
    every value escaped, the state said in
    words, never colour-only."""
    parts = [
        "<h1>Reference runner (S-318)</h1>",
        "<p>A small native runner program -- no"
        " Docker, no container -- that speaks the"
        " S-316 protocol end to end: it registers,"
        " polls, accepts or declines in words,"
        " streams numbered log chunks, and reports"
        " exactly one conclusion that agrees with"
        " its steps.</p>",
        "<h2>Environment discipline</h2>",
        "<p>A step inherits almost nothing: the"
        " runner's own context variables, the"
        " allowlisted host variables ("
        + escape_html_text(", ".join(BASE_ENV_ALLOWLIST))
        + "), and exactly the variables the"
        " assignment names -- their values held"
        " locally by the runner, never carried in"
        " the assignment. Variables that redirect"
        " code loading or the shell itself are"
        " refused in any position.</p>",
        "<h2>Working directory</h2>",
        "<p>Each job runs in one fresh directory"
        " under the runner's work root, resolved"
        " inside the root before use; a directory"
        " that already holds files is refused"
        " rather than reused.</p>",
    ]
    if audit is not None:
        state = ("stands cleanly" if audit.stands_cleanly
                 else "does NOT stand cleanly")
        parts.append("<h2>Checked against this instance</h2>")
        parts.append(
            f"<p>The reference runner {escape_html_text(state)}: "
            f"{audit.tables_scanned} tables and "
            f"{audit.columns_scanned} columns scanned; "
            f"offending tables: "
            f"{escape_html_text(', '.join(audit.offending_tables) or 'none')}; "
            f"offending columns: "
            f"{escape_html_text(', '.join(audit.offending_columns) or 'none')}.</p>")
    return "\n".join(parts)


# ------------------------------------------------------------------
# The program face.
# ------------------------------------------------------------------

def main(argv=None) -> int:
    """The reference runner as a program: read
    one assignment (a poll-response mapping in
    S-316's shape) from a JSON file, run it in
    the work root, and write every protocol
    message spoken as one JSON object per line
    to --out (or stdout). The exit code is the
    job's word: 0 on success, 1 on any other
    conclusion or a decline."""
    parser = argparse.ArgumentParser(
        prog="samverk-reference-runner",
        description="Samverk's reference runner "
                    "(S-318): run one assigned job, "
                    "natively, under environment "
                    "discipline.")
    parser.add_argument("--work-root", required=True,
                        help="the runner's work root "
                             "(must already exist)")
    parser.add_argument("--assignment", required=True,
                        help="JSON file holding one "
                             "assignment message")
    parser.add_argument("--labels", default="self-hosted",
                        help="comma-separated runner "
                             "labels")
    parser.add_argument("--env-file",
                        help="JSON file of local env "
                             "values for the names the "
                             "assignment carries")
    parser.add_argument("--out",
                        help="write protocol messages "
                             "as JSON lines here "
                             "(default: stdout)")
    args = parser.parse_args(argv)
    payload = json.loads(
        Path(args.assignment).read_text(encoding="utf-8"))
    values = {}
    if args.env_file:
        values = json.loads(
            Path(args.env_file).read_text(encoding="utf-8"))
    runner = ReferenceRunner(
        args.work_root,
        labels=tuple(part.strip() for part
                     in args.labels.split(",") if part.strip()))
    if isinstance(payload, dict) \
            and payload.get("response") == "wait":
        result = runner.handle_poll_response(payload)
    else:
        result = runner.run_assignment(payload, values)
    lines = []
    if isinstance(result, PollWait):
        lines.append(json.dumps({
            "kind": "poll", "protocol": PROTOCOL_VERSION,
            "response": "wait",
            "wait_seconds": result.wait_seconds}))
        code = 0
    else:
        lines = [json.dumps(message)
                 for message in result.messages]
        code = 0 if (result.conclusion is not None
                     and result.conclusion.conclusion
                     == "success") else 1
    text = "\n".join(lines) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
