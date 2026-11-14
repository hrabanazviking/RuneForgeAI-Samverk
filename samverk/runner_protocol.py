"""Runner protocol -- the contract a runner
speaks (S-316).

Part XVI's seam, stated in S-313, is the product:
Samverk defines workflows and talks to runners;
it does not pretend a runner is a forge feature.
S-314 gave the triggers their firing law and
S-315 the jobs-and-steps model; this slice is
the wire law between the forge and any runner --
written and judged BEFORE any runner is built
(S-318), any registration token is minted
(S-317) or any secret is injected (S-319). It is
a complete slice in the established pure-module
shape: every message of the protocol is data
with a closed key set, every refusal is named
in words, and a pure validator judges each
message exactly as it would arrive.

- **Four movements, seven messages.** A runner
  *registers* once (``register``), presenting
  its name, its labels, its scope and a one-time
  registration token -- the token is carried,
  never stored or judged here; S-317 owns its
  minting and its page. A runner then *polls
  for work* (``poll``): the forge answers either
  ``wait`` with a bounded retry-after, or an
  ``assignment`` naming one job. The runner
  answers the assignment (``assignment_reply``:
  accept, or decline with the reason in words --
  a declined job returns to the queue, it is
  never silently dropped). While the job runs
  the runner *streams logs* (``log_chunk``) and
  may send a ``heartbeat``; at the end it
  *reports conclusion* (``conclusion``) --
  exactly one conclusion per assignment, and it
  is terminal: nothing may follow it for that
  run but the forge's own bookkeeping.
- **One job at a time, labels are the address.**
  A runner holds a single assignment; a poll
  that names a running run is a heartbeat in
  poll's clothing and offers it nothing new. An
  assignment's required labels must be a subset
  of the labels the poll stated
  (``runner_label_mismatch``) -- the scheduler
  may never hand a job to a runner that did not
  declare the labels the job's ``runner:`` names
  (S-313/S-315). Scopes are ``instance``,
  ``org`` and ``repo`` (S-317's three scopes):
  an instance runner names no target, an org or
  repo runner names exactly its target, a repo
  target in ``owner/name`` form.
- **The assignment carries names, never
  values.** An assignment names the workflow,
  the repository and commit, the job's steps as
  shell ``run`` text in S-315's shape, a timeout,
  and the *names* of environment variables the
  runner will be given -- never their values,
  and never a secret: ``env`` values and
  ``secrets`` in an assignment are refused in
  words, because values travel S-319's road
  when it lands, not this one's. A step is a
  shell ``run`` and nothing else, exactly as
  S-313 decided: no ``uses:`` exists here either.
- **Logs are a numbered stream, not a pile.**
  Each chunk carries its run, its job, its step
  index and a per-step sequence number starting
  at 1 with no gaps and no duplicates
  (``runner_log_sequence``), its stream
  (``stdout`` or ``stderr``) and bounded text.
  The sequence is the ordering law: a reader
  (S-322) rebuilds the log from the numbers
  alone, so a gap is a hole in the record and
  is refused, never papered over. Chunk text is
  log text -- S-319's masking rides on top of
  this contract when secrets land; the protocol
  itself never rewrites a runner's words.
- **A conclusion must agree with its steps.**
  Conclusions are S-246's check-run vocabulary,
  word for word (``RUNNER_CONCLUSIONS`` is
  pinned against it by the battery): success,
  failure, neutral, cancelled, skipped,
  timed_out, action_required -- so S-321 can
  land a conclusion as a check run without
  translation, and S-174's required checks can
  gate on it. A step concludes in the narrower
  step vocabulary. A report whose steps failed
  may not call itself success, a skipped report
  must show every step skipped, and failure and
  action_required carry a summary in words.
- **A pure contract, like S-313/S-314/S-315.**
  This module holds no store, keeps no runner
  registry, mints no token and runs no job: it
  judges messages, and judging changes nothing.
  No migration (schema stays 128), no taxonomy
  event (135 stand: 33 auth / 89 repo / 13
  admin). At S-316's landing no runner table,
  column or audit event existed yet; S-317 has
  since built registration on this contract, and
  the audit below admits exactly its two
  registry tables by name -- any other runner
  surface is still caught as a back door, and
  the battery plants one to prove it. S-318 the
  reference runner that
  speaks it end to end, S-321 the check-run
  landing, S-322 the log store and S-324
  re-run/cancel.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from . import taxonomy
from .escaping import escape_html_text

__all__ = [
    "LOG_STREAMS", "MAX_LABELS", "MAX_LOG_CHUNK_CHARS",
    "MAX_STEPS_PER_JOB", "MESSAGE_KINDS",
    "PROTOCOL_NAME", "PROTOCOL_VERSION",
    "RUNNER_CONCLUSIONS", "RUNNER_SCOPES",
    "STEP_CONCLUSIONS", "AssignmentOffer",
    "AssignmentReply", "ConclusionReport", "Heartbeat",
    "LogChunk", "OfferStep", "PollRequest",
    "PollWait", "RunnerProtocolAudit",
    "RunnerProtocolError", "RunnerRegistration",
    "StepConclusion", "aggregate_conclusion",
    "audit_runner_protocol", "check_assignment_labels",
    "parse_assignment", "parse_assignment_reply",
    "parse_conclusion", "parse_heartbeat",
    "parse_log_chunk", "parse_message", "parse_poll",
    "parse_poll_response", "parse_registration",
    "render_runner_protocol_page", "validate_log_stream",
]

PROTOCOL_NAME = "samverk-runner"
PROTOCOL_VERSION = 1

MESSAGE_KINDS = (
    "register", "poll", "assignment",
    "assignment_reply", "heartbeat", "log_chunk",
    "conclusion")

RUNNER_SCOPES = ("instance", "org", "repo")

#: S-246's check-run conclusions, word for word:
#: a runner's final word needs no translation to
#: land as a check run (S-321).
RUNNER_CONCLUSIONS = (
    "success", "failure", "neutral", "cancelled",
    "skipped", "timed_out", "action_required")

#: A single step's narrower vocabulary: a step
#: is never neutral and never asks for action.
STEP_CONCLUSIONS = (
    "success", "failure", "cancelled", "skipped",
    "timed_out")

LOG_STREAMS = ("stdout", "stderr")

MAX_LABELS = 16
MAX_STEPS_PER_JOB = 100
MAX_LOG_CHUNK_CHARS = 16384
MAX_SUMMARY_CHARS = 2000
MAX_TIMEOUT_MINUTES = 10080
DEFAULT_POLL_WAIT_SECONDS = 20
MIN_POLL_WAIT_SECONDS = 1
MAX_POLL_WAIT_SECONDS = 300
REGISTRATION_TOKEN_MIN_CHARS = 16

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_OID_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")

_ENVELOPE_KEYS = frozenset({"kind", "protocol"})
_REGISTER_KEYS = frozenset({
    "name", "labels", "scope", "target",
    "registration_token", "agent_version"})
_POLL_KEYS = frozenset({"runner", "labels", "running"})
_WAIT_KEYS = frozenset({"response", "wait_seconds"})
_OFFER_KEYS = frozenset({
    "response", "run_id", "job_id", "workflow",
    "repository", "oid", "steps", "runner_labels",
    "env_names", "timeout_minutes"})
_STEP_KEYS = frozenset({"name", "run"})
_REPLY_KEYS = frozenset({
    "run_id", "job_id", "decision", "reason"})
_HEARTBEAT_KEYS = frozenset({
    "run_id", "job_id", "step_index",
    "elapsed_seconds"})
_LOG_KEYS = frozenset({
    "run_id", "job_id", "step_index", "sequence",
    "stream", "text"})
_CONCLUSION_KEYS = frozenset({
    "run_id", "job_id", "conclusion", "steps",
    "duration_seconds", "summary"})
_STEP_RESULT_KEYS = frozenset({
    "index", "name", "conclusion"})


class RunnerProtocolError(ValueError):
    """One refused runner-protocol message: a
    machine-branchable reason with its human
    detail, in the house shape."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def _invalid(message: str) -> RunnerProtocolError:
    return RunnerProtocolError("runner_invalid", message)


def _check_envelope(payload: object, kind: str) -> dict:
    if not isinstance(payload, dict) or not payload:
        raise _invalid("A protocol message is a non-empty mapping.")
    if payload.get("kind") != kind:
        raise RunnerProtocolError(
            "runner_kind_unknown",
            f"A {kind} message carries kind: {kind!r}.")
    version = payload.get("protocol")
    if version != PROTOCOL_VERSION or isinstance(version, bool):
        raise RunnerProtocolError(
            "runner_version_refused",
            f"The runner protocol is version {PROTOCOL_VERSION}; "
            f"version {version!r} is not spoken here.")
    return payload


def _check_keys(payload: dict, allowed: frozenset,
                where: str) -> None:
    unknown = sorted(set(payload) - allowed - _ENVELOPE_KEYS)
    if unknown:
        raise RunnerProtocolError(
            "runner_key_unknown",
            f"{where}: unknown key(s): "
            + ", ".join(unknown) + ".")


def _name(value: object, where: str) -> str:
    if not isinstance(value, str) or not _NAME_RE.match(value):
        raise _invalid(f"{where}: a name is letters, digits, "
                       "'.', '_' or '-', starting alphanumeric.")
    return value


def _labels(value: object, where: str) -> tuple:
    if (not isinstance(value, list) or not value
            or len(value) > MAX_LABELS):
        raise _invalid(
            f"{where}: labels are a non-empty list of at most "
            f"{MAX_LABELS} labels.")
    out: list = []
    for label in value:
        if not isinstance(label, str) or not _NAME_RE.match(label):
            raise _invalid(f"{where}: label {label!r} is not a "
                           "valid runner label.")
        if label in out:
            raise _invalid(f"{where}: label {label!r} is stated "
                           "twice; a label is said once.")
        out.append(label)
    return tuple(out)


def _run_job(payload: dict, where: str) -> tuple:
    return (_name(payload.get("run_id"), f"{where} run_id"),
            _name(payload.get("job_id"), f"{where} job_id"))


def _positive_int(value: object, where: str,
                  maximum: int | None = None) -> int:
    if (not isinstance(value, int) or isinstance(value, bool)
            or value < 1):
        raise _invalid(f"{where}: a positive whole number.")
    if maximum is not None and value > maximum:
        raise _invalid(f"{where}: at most {maximum}.")
    return value


# ------------------------------------------------------------------
# Movement one: registration.
# ------------------------------------------------------------------

@dataclass(frozen=True)
class RunnerRegistration:
    """A runner introducing itself: who it is,
    what labels it answers to, the scope it
    serves and the agent version it runs. The
    registration token is presented with the
    message and judged for shape only -- it is
    deliberately NOT a field here: the protocol
    carries it, S-317 owns it, and nothing in
    this module keeps it."""
    name: str
    labels: tuple
    scope: str
    target: str
    agent_version: str


def parse_registration(payload: object) -> RunnerRegistration:
    """Judge one register message. Refusals:
    runner_version_refused for a protocol this
    forge does not speak, runner_scope_unknown
    for a scope outside the three, runner_token_
    refused for a missing or short-lived-looking
    token, runner_key_unknown / runner_invalid
    for the rest of the shape, each in words."""
    data = _check_envelope(payload, "register")
    _check_keys(data, _REGISTER_KEYS, "Registration")
    name = _name(data.get("name"), "Registration name")
    labels = _labels(data.get("labels"), "Registration")
    scope = data.get("scope")
    if scope not in RUNNER_SCOPES:
        raise RunnerProtocolError(
            "runner_scope_unknown",
            "Registration scope: one of "
            + ", ".join(RUNNER_SCOPES) + ".")
    target = data.get("target") or ""
    if not isinstance(target, str):
        raise _invalid("Registration target: text.")
    if scope == "instance" and target:
        raise _invalid(
            "Registration: an instance runner names no target; "
            "its scope is the whole instance.")
    if scope == "org":
        _name(target, "Registration org target")
    if scope == "repo":
        parts = target.split("/")
        if len(parts) != 2:
            raise _invalid(
                "Registration: a repo target is owner/name.")
        _name(parts[0], "Registration repo owner")
        _name(parts[1], "Registration repo name")
    token = data.get("registration_token")
    if (not isinstance(token, str)
            or len(token) < REGISTRATION_TOKEN_MIN_CHARS):
        raise RunnerProtocolError(
            "runner_token_refused",
            "Registration: a registration token is presented "
            "with the register message (S-317 mints it, one-time "
            "and short-lived); this message carries none that "
            "could be one.")
    version = data.get("agent_version")
    if not isinstance(version, str) or not version.strip():
        raise _invalid("Registration agent_version: the runner "
                       "software's version, as text.")
    return RunnerRegistration(
        name=name, labels=labels, scope=scope, target=target,
        agent_version=version.strip())


# ------------------------------------------------------------------
# Movement two: polling for work, and the forge's answer.
# ------------------------------------------------------------------

@dataclass(frozen=True)
class PollRequest:
    """A runner asking for work: its name, the
    labels it answers to on this poll, and the
    run it is still holding, if any. One job at
    a time is the protocol's law: a poll naming
    a running run is a liveness word, and the
    forge offers it nothing new."""
    runner: str
    labels: tuple
    running_run_id: str


def parse_poll(payload: object) -> PollRequest:
    """Judge one poll message."""
    data = _check_envelope(payload, "poll")
    _check_keys(data, _POLL_KEYS, "Poll")
    runner = _name(data.get("runner"), "Poll runner")
    labels = _labels(data.get("labels"), "Poll")
    running = data.get("running") or ""
    if not isinstance(running, str):
        raise _invalid("Poll running: the running run's id, "
                       "or nothing while idle.")
    if running:
        _name(running, "Poll running")
    return PollRequest(runner=runner, labels=labels,
                       running_run_id=running)


@dataclass(frozen=True)
class PollWait:
    """The forge's 'not yet': poll again after
    this many seconds -- bounded, so a runner is
    never told to sleep forever or to spin."""
    wait_seconds: int


@dataclass(frozen=True)
class OfferStep:
    """One step of an assignment, in S-315's
    shape: a name (possibly empty) and the shell
    it runs. Nothing else exists."""
    name: str
    run: str


@dataclass(frozen=True)
class AssignmentOffer:
    """The forge offering one job: the run and
    job it belongs to, the workflow, repository
    and commit, the steps in order, the runner
    labels the job requires, the environment
    NAMES the runner will receive (values travel
    S-319's road, never this one) and the job's
    timeout in minutes."""
    run_id: str
    job_id: str
    workflow: str
    repository: str
    oid: str
    steps: tuple
    runner_labels: tuple
    env_names: tuple
    timeout_minutes: int


def parse_poll_response(payload: object):
    """Judge the forge's answer to a poll: either
    a wait (``response: wait``) or one assignment
    (``response: assignment``). The envelope kind
    of an assignment answer is ``assignment``."""
    if not isinstance(payload, dict):
        raise _invalid("A poll response is a mapping.")
    response = payload.get("response")
    if response == "wait":
        _check_envelope(payload, "poll")
        _check_keys(payload, _WAIT_KEYS, "Poll wait")
        wait = payload.get("wait_seconds",
                           DEFAULT_POLL_WAIT_SECONDS)
        wait = _positive_int(wait, "Poll wait_seconds",
                             MAX_POLL_WAIT_SECONDS)
        if wait < MIN_POLL_WAIT_SECONDS:
            raise _invalid("Poll wait_seconds: at least "
                           f"{MIN_POLL_WAIT_SECONDS}.")
        return PollWait(wait_seconds=wait)
    if response == "assignment":
        return parse_assignment(payload)
    raise _invalid("A poll response is wait or assignment.")


def parse_assignment(payload: object) -> AssignmentOffer:
    """Judge one assignment message. An
    assignment carrying environment values or
    secrets is refused in words before its keys
    are judged: names travel here, values never
    do."""
    data = _check_envelope(payload, "assignment")
    if "env" in data or "secrets" in data:
        raise _invalid(
            "Assignment: env values and secrets never travel "
            "in an assignment; env_names names the variables "
            "and S-319 delivers their values.")
    _check_keys(data, _OFFER_KEYS, "Assignment")
    if data.get("response") != "assignment":
        raise _invalid("Assignment: response is assignment.")
    run_id, job_id = _run_job(data, "Assignment")
    workflow = data.get("workflow")
    if not isinstance(workflow, str) or not workflow.strip():
        raise _invalid("Assignment workflow: the workflow's "
                       "name, as text.")
    repository = data.get("repository")
    if not isinstance(repository, str):
        raise _invalid("Assignment repository: owner/name.")
    parts = repository.split("/")
    if len(parts) != 2:
        raise _invalid("Assignment repository: owner/name.")
    _name(parts[0], "Assignment repo owner")
    _name(parts[1], "Assignment repo name")
    oid = data.get("oid")
    if not isinstance(oid, str) or not _OID_RE.match(oid):
        raise _invalid("Assignment oid: the commit the job "
                       "runs on, as a hex object id.")
    raw_steps = data.get("steps")
    if (not isinstance(raw_steps, list) or not raw_steps
            or len(raw_steps) > MAX_STEPS_PER_JOB):
        raise _invalid(
            f"Assignment steps: a non-empty list of at most "
            f"{MAX_STEPS_PER_JOB} steps.")
    steps: list = []
    for index, item in enumerate(raw_steps, start=1):
        where = f"Assignment step {index}"
        if not isinstance(item, dict):
            raise _invalid(f"{where}: a step is a mapping.")
        if "uses" in item:
            raise _invalid(
                f"{where}: uses: is not part of Samverk's "
                "format -- a step is its run: shell (S-313).")
        _check_keys(item, _STEP_KEYS, where)
        run = item.get("run")
        if not isinstance(run, str) or not run.strip():
            raise _invalid(f"{where}: a step needs its run: "
                           "shell.")
        step_name = item.get("name") or ""
        if not isinstance(step_name, str):
            raise _invalid(f"{where}: a step name is text.")
        steps.append(OfferStep(name=step_name, run=run))
    labels = _labels(data.get("runner_labels"),
                     "Assignment runner_labels")
    env_raw = data.get("env_names") or []
    if not isinstance(env_raw, list):
        raise _invalid("Assignment env_names: a list of "
                       "variable names.")
    env_names: list = []
    for env_name in env_raw:
        if not isinstance(env_name, str) \
                or not _ENV_RE.match(env_name):
            raise _invalid(f"Assignment env_names: {env_name!r} "
                           "is not a variable name.")
        if env_name in env_names:
            raise _invalid(f"Assignment env_names: {env_name!r} "
                           "is named twice.")
        env_names.append(env_name)
    timeout = _positive_int(data.get("timeout_minutes"),
                            "Assignment timeout_minutes",
                            MAX_TIMEOUT_MINUTES)
    return AssignmentOffer(
        run_id=run_id, job_id=job_id,
        workflow=workflow.strip(), repository=repository,
        oid=oid, steps=tuple(steps), runner_labels=labels,
        env_names=tuple(env_names), timeout_minutes=timeout)


def check_assignment_labels(offer: AssignmentOffer,
                            poll: PollRequest) -> None:
    """The label law judged: every label the job
    requires must be among the labels the poll
    stated. Raises runner_label_mismatch naming
    the missing labels; returns None when the
    assignment may lawfully be taken."""
    missing = [label for label in offer.runner_labels
               if label not in poll.labels]
    if missing:
        raise RunnerProtocolError(
            "runner_label_mismatch",
            "Assignment requires label(s) the poll did not "
            "declare: " + ", ".join(missing) + ".")
    if poll.running_run_id:
        raise _invalid(
            "Poll: this runner is still holding run "
            f"{poll.running_run_id}; one job at a time -- it "
            "is offered nothing new until that run concludes.")


@dataclass(frozen=True)
class AssignmentReply:
    """The runner's answer to an assignment:
    accept, or decline with the reason in words.
    A decline is a first-class answer, never a
    disappearance: the job returns to the queue
    and the reason is the record of why."""
    run_id: str
    job_id: str
    decision: str
    reason: str


def parse_assignment_reply(payload: object) -> AssignmentReply:
    """Judge one assignment_reply message."""
    data = _check_envelope(payload, "assignment_reply")
    _check_keys(data, _REPLY_KEYS, "Assignment reply")
    run_id, job_id = _run_job(data, "Assignment reply")
    decision = data.get("decision")
    if decision not in ("accept", "decline"):
        raise _invalid("Assignment reply decision: accept or "
                       "decline.")
    reason = data.get("reason") or ""
    if not isinstance(reason, str):
        raise _invalid("Assignment reply reason: text.")
    if decision == "decline" and not reason.strip():
        raise _invalid(
            "Assignment reply: a decline carries its reason "
            "in words -- the job returns to the queue and the "
            "reason is the record of why.")
    if len(reason) > MAX_SUMMARY_CHARS:
        raise _invalid("Assignment reply reason: at most "
                       f"{MAX_SUMMARY_CHARS} characters.")
    return AssignmentReply(run_id=run_id, job_id=job_id,
                           decision=decision,
                           reason=reason.strip())


# ------------------------------------------------------------------
# Movement three: heartbeats and the log stream while work runs.
# ------------------------------------------------------------------

@dataclass(frozen=True)
class Heartbeat:
    """A running runner's liveness word: which
    run, which step it stands on (0 before the
    first step), and how long the job has run."""
    run_id: str
    job_id: str
    step_index: int
    elapsed_seconds: int


def parse_heartbeat(payload: object) -> Heartbeat:
    """Judge one heartbeat message."""
    data = _check_envelope(payload, "heartbeat")
    _check_keys(data, _HEARTBEAT_KEYS, "Heartbeat")
    run_id, job_id = _run_job(data, "Heartbeat")
    step_index = data.get("step_index")
    if (not isinstance(step_index, int)
            or isinstance(step_index, bool) or step_index < 0):
        raise _invalid("Heartbeat step_index: zero (before "
                       "the first step) or a step number.")
    elapsed = data.get("elapsed_seconds")
    if (not isinstance(elapsed, int)
            or isinstance(elapsed, bool) or elapsed < 0):
        raise _invalid("Heartbeat elapsed_seconds: a whole "
                       "number of seconds, zero or more.")
    return Heartbeat(run_id=run_id, job_id=job_id,
                     step_index=step_index,
                     elapsed_seconds=elapsed)


@dataclass(frozen=True)
class LogChunk:
    """One numbered piece of a job's log: its
    step, its per-step sequence (1-based, no gaps
    -- the ordering law), its stream and its
    text, bounded so no single chunk can flood
    the wire or the store (S-322)."""
    run_id: str
    job_id: str
    step_index: int
    sequence: int
    stream: str
    text: str


def parse_log_chunk(payload: object,
                    expected_sequence: int | None = None
                    ) -> LogChunk:
    """Judge one log_chunk message. When the
    caller knows the sequence it expects for this
    step, a chunk arriving out of turn is refused
    runner_log_sequence naming both numbers."""
    data = _check_envelope(payload, "log_chunk")
    _check_keys(data, _LOG_KEYS, "Log chunk")
    run_id, job_id = _run_job(data, "Log chunk")
    step_index = _positive_int(data.get("step_index"),
                               "Log chunk step_index")
    sequence = _positive_int(data.get("sequence"),
                             "Log chunk sequence")
    if expected_sequence is not None \
            and sequence != expected_sequence:
        raise RunnerProtocolError(
            "runner_log_sequence",
            f"Log chunk: step {step_index} expects sequence "
            f"{expected_sequence}, and this chunk says "
            f"{sequence}; the sequence is the ordering law "
            "and a gap is a hole in the record.")
    stream = data.get("stream")
    if stream not in LOG_STREAMS:
        raise _invalid("Log chunk stream: one of "
                       + ", ".join(LOG_STREAMS) + ".")
    text = data.get("text")
    if not isinstance(text, str) or not text:
        raise _invalid("Log chunk text: the chunk's log "
                       "text; an empty chunk says nothing "
                       "and is not sent.")
    if len(text) > MAX_LOG_CHUNK_CHARS:
        raise _invalid(
            f"Log chunk text: at most {MAX_LOG_CHUNK_CHARS} "
            "characters per chunk; split the stream, do not "
            "flood it.")
    return LogChunk(run_id=run_id, job_id=job_id,
                    step_index=step_index, sequence=sequence,
                    stream=stream, text=text)


def validate_log_stream(chunks) -> int:
    """Judge a whole run's chunks as one stream:
    a single run and job throughout, steps never
    going backwards, and each step's sequences
    running 1, 2, 3 ... with no gap and no
    duplicate (runner_log_sequence). Returns the
    stream's total characters."""
    total = 0
    seen: dict = {}
    identity: tuple | None = None
    highest_step = 0
    for chunk in chunks:
        if not isinstance(chunk, LogChunk):
            raise _invalid("A log stream is LogChunks.")
        if identity is None:
            identity = (chunk.run_id, chunk.job_id)
        elif (chunk.run_id, chunk.job_id) != identity:
            raise _invalid(
                "A log stream is one run's chunks; this chunk "
                "belongs to another run.")
        if chunk.step_index < highest_step:
            raise RunnerProtocolError(
                "runner_log_sequence",
                f"Log stream: step {chunk.step_index} arrives "
                f"after step {highest_step}; steps stream in "
                "order.")
        highest_step = max(highest_step, chunk.step_index)
        expected = seen.get(chunk.step_index, 0) + 1
        if chunk.sequence != expected:
            raise RunnerProtocolError(
                "runner_log_sequence",
                f"Log stream: step {chunk.step_index} expects "
                f"sequence {expected}, and this chunk says "
                f"{chunk.sequence}.")
        seen[chunk.step_index] = chunk.sequence
        total += len(chunk.text)
    return total


# ------------------------------------------------------------------
# Movement four: the conclusion -- exactly one, and terminal.
# ------------------------------------------------------------------

@dataclass(frozen=True)
class StepConclusion:
    """One step's final word, in the step
    vocabulary, at its 1-based index."""
    index: int
    name: str
    conclusion: str


@dataclass(frozen=True)
class ConclusionReport:
    """A job's conclusion: the overall word in
    S-246's vocabulary, every step's word in
    order, the run's duration, and -- for failure
    and action_required -- the summary in words.
    Exactly one report closes an assignment."""
    run_id: str
    job_id: str
    conclusion: str
    steps: tuple
    duration_seconds: int
    summary: str


def aggregate_conclusion(step_conclusions) -> str:
    """The overall word a set of step conclusions
    adds up to, by the stated precedence: any
    failure fails the job; else any timed_out;
    else any cancelled; else all-skipped is
    skipped; else success. An empty set has no
    word and is refused."""
    words = tuple(step_conclusions)
    if not words:
        raise _invalid("Step conclusions: at least one step "
                       "concluded.")
    for word in words:
        if word not in STEP_CONCLUSIONS:
            raise _invalid(f"Step conclusion {word!r}: one of "
                           + ", ".join(STEP_CONCLUSIONS) + ".")
    if "failure" in words:
        return "failure"
    if "timed_out" in words:
        return "timed_out"
    if "cancelled" in words:
        return "cancelled"
    if all(word == "skipped" for word in words):
        return "skipped"
    return "success"


def parse_conclusion(payload: object,
                     offer: AssignmentOffer | None = None
                     ) -> ConclusionReport:
    """Judge one conclusion message -- the run's
    terminal word. When the assignment it closes
    is given, the report's steps must be that
    assignment's steps, in order, each with its
    word. A report at war with its own steps is
    refused runner_conclusion_mismatch."""
    data = _check_envelope(payload, "conclusion")
    _check_keys(data, _CONCLUSION_KEYS, "Conclusion")
    run_id, job_id = _run_job(data, "Conclusion")
    if offer is not None \
            and (run_id, job_id) != (offer.run_id, offer.job_id):
        raise RunnerProtocolError(
            "runner_conclusion_mismatch",
            "Conclusion: this report closes run "
            f"{run_id} job {job_id}, not the assignment's "
            f"run {offer.run_id} job {offer.job_id}.")
    conclusion = data.get("conclusion")
    if conclusion not in RUNNER_CONCLUSIONS:
        raise _invalid("Conclusion: one of "
                       + ", ".join(RUNNER_CONCLUSIONS) + ".")
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise _invalid("Conclusion steps: every step's word, "
                       "in order.")
    if len(raw_steps) > MAX_STEPS_PER_JOB:
        raise _invalid(f"Conclusion steps: at most "
                       f"{MAX_STEPS_PER_JOB}.")
    steps: list = []
    for position, item in enumerate(raw_steps, start=1):
        where = f"Conclusion step {position}"
        if not isinstance(item, dict):
            raise _invalid(f"{where}: a step result is a "
                           "mapping.")
        _check_keys(item, _STEP_RESULT_KEYS, where)
        index = item.get("index")
        if index != position:
            raise _invalid(
                f"{where}: step results are numbered in "
                f"order; this one says {index!r}.")
        step_name = item.get("name") or ""
        if not isinstance(step_name, str):
            raise _invalid(f"{where}: a step name is text.")
        word = item.get("conclusion")
        if word not in STEP_CONCLUSIONS:
            raise _invalid(f"{where}: a step concludes "
                           + ", ".join(STEP_CONCLUSIONS) + ".")
        steps.append(StepConclusion(index=position,
                                    name=step_name,
                                    conclusion=word))
    if offer is not None:
        if len(steps) != len(offer.steps):
            raise RunnerProtocolError(
                "runner_conclusion_mismatch",
                f"Conclusion: the assignment has "
                f"{len(offer.steps)} steps and this report "
                f"covers {len(steps)}.")
        for result, offered in zip(steps, offer.steps):
            if result.name != offered.name:
                raise RunnerProtocolError(
                    "runner_conclusion_mismatch",
                    f"Conclusion step {result.index}: the "
                    f"assignment's step is {offered.name!r}, "
                    f"and this report names {result.name!r}.")
    duration = data.get("duration_seconds")
    if (not isinstance(duration, int)
            or isinstance(duration, bool) or duration < 0):
        raise _invalid("Conclusion duration_seconds: a whole "
                       "number of seconds, zero or more.")
    summary = data.get("summary") or ""
    if not isinstance(summary, str):
        raise _invalid("Conclusion summary: text.")
    if len(summary) > MAX_SUMMARY_CHARS:
        raise _invalid(f"Conclusion summary: at most "
                       f"{MAX_SUMMARY_CHARS} characters.")
    if conclusion in ("failure", "action_required") \
            and not summary.strip():
        raise _invalid(
            f"Conclusion: a {conclusion} report carries its "
            "summary in words -- what happened is the record.")
    aggregate = aggregate_conclusion(
        [step.conclusion for step in steps])
    if conclusion == "success" and aggregate != "success":
        raise RunnerProtocolError(
            "runner_conclusion_mismatch",
            f"Conclusion: the steps add up to {aggregate}, "
            "and this report says success; a job whose steps "
            "did not all pass has not succeeded.")
    if conclusion == "skipped" and aggregate != "skipped":
        raise RunnerProtocolError(
            "runner_conclusion_mismatch",
            "Conclusion: a skipped report must show every "
            f"step skipped; these steps add up to "
            f"{aggregate}.")
    if aggregate == "failure" \
            and conclusion in ("neutral", "skipped"):
        raise RunnerProtocolError(
            "runner_conclusion_mismatch",
            "Conclusion: a step failed, and this report says "
            f"{conclusion}; failure is never softened in "
            "the telling.")
    return ConclusionReport(
        run_id=run_id, job_id=job_id, conclusion=conclusion,
        steps=tuple(steps), duration_seconds=duration,
        summary=summary.strip())


# ------------------------------------------------------------------
# The envelope: any message, judged by its kind.
# ------------------------------------------------------------------

_PARSERS = {
    "register": parse_registration,
    "poll": parse_poll,
    "assignment": parse_assignment,
    "assignment_reply": parse_assignment_reply,
    "heartbeat": parse_heartbeat,
    "log_chunk": parse_log_chunk,
    "conclusion": parse_conclusion,
}


def parse_message(payload: object):
    """Judge any protocol message by its kind and
    return the parsed record. A wait answer is
    the one message whose kind stays ``poll``:
    it is judged by parse_poll_response, which
    this dispatcher hands it to when the payload
    carries a ``response`` and no steps."""
    if not isinstance(payload, dict) or not payload:
        raise _invalid("A protocol message is a non-empty "
                       "mapping.")
    kind = payload.get("kind")
    if kind == "poll" and payload.get("response") == "wait":
        return parse_poll_response(payload)
    if kind not in MESSAGE_KINDS:
        raise RunnerProtocolError(
            "runner_kind_unknown",
            "Message kind: one of "
            + ", ".join(MESSAGE_KINDS) + ".")
    return _PARSERS[kind](payload)


# ------------------------------------------------------------------
# The audit: the contract checked against the live instance.
# ------------------------------------------------------------------

@dataclass(frozen=True)
class RunnerProtocolAudit:
    """The runner contract checked against one
    live instance: the vocabulary's own integrity,
    how much schema was inspected, and every
    runner-shaped name found in it. The contract
    stands cleanly only while the sole runner
    surfaces in the instance are S-317's lawful
    registry tables (``runner_registration_tokens``
    and ``runners``, admitted by name since S-317
    landed) and no audit event carries a runner
    surface -- any other runner-named table or
    column is a surface arriving by a back door."""
    protocol_ok: bool
    tables_scanned: int
    columns_scanned: int
    events_scanned: int
    offending_tables: tuple
    offending_columns: tuple
    offending_events: tuple

    @property
    def stands_cleanly(self) -> bool:
        return (self.protocol_ok
                and not self.offending_tables
                and not self.offending_columns
                and not self.offending_events)


#: The lawful runner surface since S-317: its
#: registry tables, admitted by name. Any other
#: runner-named table or column is an offender.
_LAWFUL_RUNNER_TABLES = frozenset({
    "runner_registration_tokens", "runners"})


def audit_runner_protocol(conn: sqlite3.Connection
                          ) -> RunnerProtocolAudit:
    """Check the runner contract against the live
    instance: the vocabulary is exactly this
    module's seven kinds, three scopes and S-246's
    seven conclusions, and the only runner
    surfaces in the schema are S-317's two lawful
    registry tables and their columns -- any
    other runner-named table or column, or any
    runner audit event, would be the contract
    broken by a back door. Pure read."""
    protocol_ok = (
        len(set(MESSAGE_KINDS)) == 7
        and tuple(RUNNER_SCOPES) == ("instance", "org", "repo")
        and len(set(RUNNER_CONCLUSIONS)) == 7
        and set(STEP_CONCLUSIONS) < set(RUNNER_CONCLUSIONS))
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
    events = sorted(taxonomy.AUDIT_EVENTS)
    offending_events = [
        e for e in events if "runner" in e.lower()]
    return RunnerProtocolAudit(
        protocol_ok=protocol_ok,
        tables_scanned=len(tables),
        columns_scanned=columns_scanned,
        events_scanned=len(events),
        offending_tables=tuple(offending_tables),
        offending_columns=tuple(offending_columns),
        offending_events=tuple(offending_events))


def render_runner_protocol_page(
        audit: RunnerProtocolAudit | None = None) -> str:
    """The runner contract, rendered: the four
    movements said in words, the label, log and
    conclusion laws, and the checked proof when
    an audit rides along -- every value escaped,
    the state said in words, never colour-only."""
    parts = [
        "<h1>Runner protocol (S-316)</h1>",
        "<p>A runner speaks four movements: it"
        " <strong>registers</strong> once with its"
        " name, labels, scope and a one-time"
        " registration token; it <strong>polls for"
        " work</strong> and is answered wait or one"
        " assignment, which it accepts or declines"
        " with its reason in words; while the job"
        " runs it <strong>streams logs</strong> as"
        " numbered chunks and may send a heartbeat;"
        " and it <strong>reports conclusion</strong>"
        " -- exactly one, and terminal.</p>",
        "<h2>Labels are the address</h2>",
        "<p>One job at a time. An assignment's"
        " required labels must be among the labels"
        " the poll declared, and an assignment"
        " carries environment names only -- values"
        " and secrets never travel in it.</p>",
        "<h2>Logs are a numbered stream</h2>",
        "<p>Each chunk names its run, job and step"
        " and carries a per-step sequence from 1"
        " with no gaps: the sequence is the ordering"
        " law, and a gap is a hole in the record.</p>",
        "<h2>Conclusions agree with their steps</h2>",
        "<p>Conclusions are the check-run vocabulary"
        " -- success, failure, neutral, cancelled,"
        " skipped, timed_out, action_required -- and"
        " a report whose steps failed may not call"
        " itself success.</p>",
    ]
    if audit is not None:
        state = ("stands cleanly" if audit.stands_cleanly
                 else "does NOT stand cleanly")
        parts.append("<h2>Checked against this instance</h2>")
        parts.append(
            f"<p>The runner contract {escape_html_text(state)}: "
            f"{audit.tables_scanned} tables and "
            f"{audit.columns_scanned} columns scanned, "
            f"{audit.events_scanned} audit events scanned; "
            f"offending tables: "
            f"{escape_html_text(', '.join(audit.offending_tables) or 'none')}; "
            f"offending columns: "
            f"{escape_html_text(', '.join(audit.offending_columns) or 'none')}; "
            f"offending events: "
            f"{escape_html_text(', '.join(audit.offending_events) or 'none')}.</p>")
    return "\n".join(parts)
