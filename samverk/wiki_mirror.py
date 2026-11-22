"""Wiki mirror (S-339).

Roadmap S-339: **a source repo's wiki (S-273 form)
mirrors alongside its code repo.**

S-273 made each repository's wiki its own bare git
repository, ``<repo>.wiki``, standing beside the code
repository. S-070/S-329 made a repository a mirror of
a source, and S-336/S-337 verified those mirrors
ref-for-ref. But the code mirror carried no wiki: a
mirrored original arrived without the wiki its source
keeps beside its code. This slice closes that gap,
under laws inherited whole from its predecessors:

- **The wiki source is derived, never stored.** A
  mirror record names one source (S-070). The wiki's
  source is that same source in S-273 form, derived by
  the pure ``wiki_source_for``: a local source
  ``<name>.git`` derives ``<name>.wiki`` (a source
  without the suffix derives ``<name>.wiki`` beside
  it), and a remote source ``<name>.git`` derives
  ``<name>.wiki.git`` -- the form the source host
  serves its wiki under. No second source is recorded
  anywhere, so the wiki can never drift to a different
  origin than the code it stands beside.
- **No wiki is an honest answer, not a failure dressed
  as health.** A source that has no wiki -- the derived
  local path does not stand, a remote wiki listing
  fails or advertises no refs, or the wiki repository
  stands empty -- records a run in the standing run log
  (``first_pass_mirror_runs``, phase ``wiki``) with
  state ``no_wiki`` and plain words saying exactly
  that. It creates no local wiki, fetches nothing, and
  never reports ``verified``.
- **The same cadence, the same credential gate.** A
  wiki sync resolves the mirror's credential through
  S-330 exactly as the code sync does: a named but
  unloaded secret refuses before any fetch, the token
  travels only through the S-014 fetch seam's askpass
  environment, and recorded detail is scrubbed of it.
  ``sync_alongside_code`` runs the code sync (S-330's
  road) and then the wiki sync as one act, so a wiki
  follows its repository's own mirror cadence rather
  than inventing a second schedule.
- **Verified ref-for-ref, like the code.** A synced
  wiki is judged exactly as S-336 judges a code mirror:
  the refs the wiki source advertises (S-014 ls-remote
  seam, scoped to heads and tags) must stand in the
  local ``<repo>.wiki`` at the same object ids, with
  nothing missing, extra, or diverged. A fetch that
  completes but does not verify is a failed run.
- **Failures never look healthy.** A drifted local
  wiki path (standing, but not a bare git repository),
  a failed fetch, an unreadable source, and a refused
  credential each record a ``failed`` run with the
  reason in plain words; the standing wiki content, if
  any, is left untouched and readable.

The judgements are pure. ``wiki_source_for`` derives
one source from another and writes nothing;
``decide_wiki_sync`` states what a probe of the wiki
source means and writes nothing; ``state_from_run``
reads a recorded run's state as a standing wiki state
and writes nothing. The service acts on the judgements
and records every outcome. No migration and no new
audit event: the schema stands at 138 and the taxonomy
stands at 138 -- the run log, the credential seam, and
the wiki form are all reused on purpose.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from .accounts import AccountStore
from .audit import AuditLog
from .escaping import escape_html_text
from .first_pass_mirroring import compare_ref_maps, parse_ls_remote
from .mirror_credentials import MirrorCredentialError, MirrorCredentialService
from .mirrors import MirrorService
from .platform_seam import ensure_dir
from .proc import (
    ProcRefused, run_git, run_git_fetch_from, run_git_in,
    run_git_ls_remote_refs)
from .refs import RefStore
from .repositories import RepositoryStore
from .secrets import Secrets
from .wiki_storage import wiki_path_for

PHASE_WIKI = "wiki"

VERIFIED = "verified"
FAILED = "failed"
NO_WIKI = "no_wiki"

STATE_NOT_A_MIRROR = "not_a_mirror"
STATE_NEVER_SYNCED = "never_synced"
STATE_SYNCED = "synced"
STATE_NO_WIKI = "no_wiki"
STATE_FAILED = "failed"

ACTION_SYNC = "sync"
ACTION_NO_WIKI = "no_wiki"
ACTION_REFUSE = "refuse"

PROBE_PRESENT = "present"
PROBE_ABSENT = "absent"
PROBE_UNREADABLE = "unreadable"

__all__ = [
    "ACTION_NO_WIKI", "ACTION_REFUSE", "ACTION_SYNC", "FAILED",
    "NO_WIKI", "PHASE_WIKI", "PROBE_ABSENT", "PROBE_PRESENT",
    "PROBE_UNREADABLE", "STATE_FAILED", "STATE_NEVER_SYNCED",
    "STATE_NOT_A_MIRROR", "STATE_NO_WIKI", "STATE_SYNCED",
    "VERIFIED", "WikiMirrorDecision", "WikiMirrorError",
    "WikiMirrorReport", "WikiMirrorRun", "WikiMirrorService",
    "WikiMirrorStatus", "decide_wiki_sync", "render_wiki_mirror_page",
    "state_from_run", "wiki_source_for",
]


class WikiMirrorError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def wiki_source_for(source: object, source_kind: object):
    """Derive the wiki source from a mirror's code
    source. Pure. Local: ``<name>.git`` -> ``<name>.wiki``
    and ``<name>`` -> ``<name>.wiki``, as a Path. Remote:
    ``<name>.git`` -> ``<name>.wiki.git`` and ``<name>``
    -> ``<name>.wiki.git``, as a string. A source already
    in wiki form, an unknown kind, or a remote source
    naming no repository is refused in plain words -- a
    derivation never guesses."""
    if source_kind == "local":
        path = source if isinstance(source, Path) else Path(str(source))
        if path.suffix == ".wiki":
            raise WikiMirrorError(
                "source_invalid",
                "That source is already a wiki repository; a wiki "
                "mirrors alongside a code repository, not a wiki.")
        if path.suffix == ".git":
            return path.with_suffix(".wiki")
        return path.with_name(path.name + ".wiki")
    if source_kind == "url":
        if not isinstance(source, str) or not source:
            raise WikiMirrorError(
                "source_invalid", "A remote mirror source is a URL.")
        parsed = urlparse(source)
        name = parsed.path.rstrip("/").rsplit("/", 1)[-1]
        if not name:
            raise WikiMirrorError(
                "source_invalid",
                "The mirror source names no repository, so it "
                "names no wiki either.")
        if name.endswith(".wiki.git") or name.endswith(".wiki"):
            raise WikiMirrorError(
                "source_invalid",
                "That source is already a wiki repository; a wiki "
                "mirrors alongside a code repository, not a wiki.")
        if name.endswith(".git"):
            wiki_name = name[: -len(".git")] + ".wiki.git"
        else:
            wiki_name = name + ".wiki.git"
        new_path = parsed.path.rstrip("/").rsplit("/", 1)[0] + "/" + wiki_name
        return urlunparse((parsed.scheme, parsed.netloc, new_path,
                           "", parsed.query, ""))
    raise WikiMirrorError(
        "source_invalid",
        f"A mirror source kind is 'url' or 'local', not {source_kind!r}.")


@dataclass(frozen=True)
class WikiMirrorDecision:
    action: str                # ACTION_SYNC | ACTION_NO_WIKI | ACTION_REFUSE
    reason: str


def decide_wiki_sync(is_mirror: bool, probe: object) -> WikiMirrorDecision:
    """State what a probe of the derived wiki source
    means. Pure. Only a mirror with a present wiki
    source syncs; an absent wiki source is the honest
    ``no_wiki`` answer; an unreadable one refuses, so a
    broken source never reads as an absent wiki."""
    if not is_mirror:
        return WikiMirrorDecision(
            action=ACTION_REFUSE,
            reason=("that repository is not a mirror; only a mirror "
                    "carries its source's wiki alongside its code"))
    if probe == PROBE_PRESENT:
        return WikiMirrorDecision(
            action=ACTION_SYNC,
            reason="the source has a wiki; it mirrors alongside the code")
    if probe == PROBE_ABSENT:
        return WikiMirrorDecision(
            action=ACTION_NO_WIKI,
            reason=("the source has no wiki; there is nothing to "
                    "mirror alongside its code"))
    return WikiMirrorDecision(
        action=ACTION_REFUSE,
        reason=("the source's wiki could not be read, so its "
                "presence cannot be judged honestly"))


def state_from_run(run_state: object) -> str:
    """Read a recorded wiki run's state as the standing
    wiki state. Pure. No run yet is ``never_synced`` --
    a mirror whose wiki was never attempted does not
    claim any wiki state beyond that."""
    if run_state == VERIFIED:
        return STATE_SYNCED
    if run_state == NO_WIKI:
        return STATE_NO_WIKI
    if run_state == FAILED:
        return STATE_FAILED
    return STATE_NEVER_SYNCED


@dataclass(frozen=True)
class WikiMirrorRun:
    full_name: str
    state: str                 # VERIFIED | FAILED | NO_WIKI
    refs_matched: int
    refs_missing: int
    refs_extra: int
    refs_diverged: int
    detail: str
    run_at: int

    @property
    def headline(self) -> str:
        return f"{self.full_name} wiki: {self.state} -- {self.detail}"


@dataclass(frozen=True)
class WikiMirrorStatus:
    full_name: str
    is_mirror: bool
    wiki_source: str | None
    state: str                 # STATE_* word
    detail: str
    last_run_at: int | None

    @property
    def headline(self) -> str:
        if not self.is_mirror:
            return (f"{self.full_name} is not a mirror; it has no "
                    f"mirrored wiki.")
        return (f"{self.full_name} wiki mirror of "
                f"{self.wiki_source}: {self.state} -- {self.detail}")


@dataclass
class WikiMirrorReport:
    runs: list[WikiMirrorRun] = field(default_factory=list)
    note: str = ""

    @property
    def verified_count(self) -> int:
        return sum(1 for r in self.runs if r.state == VERIFIED)

    @property
    def no_wiki_count(self) -> int:
        return sum(1 for r in self.runs if r.state == NO_WIKI)

    @property
    def failed(self) -> list[WikiMirrorRun]:
        return [r for r in self.runs if r.state == FAILED]

    @property
    def headline(self) -> str:
        return (f"wiki mirrors: {self.verified_count} verified, "
                f"{self.no_wiki_count} with no source wiki, "
                f"{len(self.failed)} failed")


class WikiMirrorService:
    """Wiki mirroring over S-070's mirror records: the
    derived wiki source probed, fetched, and verified
    into the S-273 wiki standing beside the mirror's
    code, behind S-330's credential gate, with every
    outcome recorded in the standing run log."""

    def __init__(self, conn: sqlite3.Connection, data_root: Path,
                 accounts: AccountStore, repositories: RepositoryStore,
                 audit: AuditLog | None = None,
                 time_fn: Callable[[], float] = time.time,
                 ls_remote_fn: Callable[..., object] = run_git_ls_remote_refs,
                 fetch_fn: Callable[..., object] = run_git_fetch_from):
        self._conn = conn
        self._data_root = Path(data_root)
        self._accounts = accounts
        self._repos = repositories
        self._audit = audit
        self._now = time_fn
        self._ls_remote = ls_remote_fn
        self._fetch = fetch_fn
        self._mirrors = MirrorService(
            conn, data_root, accounts, repositories,
            audit=audit, time_fn=time_fn)
        self._credentials = MirrorCredentialService(
            conn, data_root, accounts, repositories,
            audit=audit, time_fn=time_fn)

    # -- records ---------------------------------------------------
    def _store(self, record: WikiMirrorRun, repo_id: int) -> WikiMirrorRun:
        with self._conn:
            self._conn.execute(
                "INSERT INTO first_pass_mirror_runs (full_name, repo_id,"
                " phase, state, refs_matched, refs_missing, refs_extra,"
                " refs_diverged, detail, run_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (record.full_name, repo_id, PHASE_WIKI, record.state,
                 record.refs_matched, record.refs_missing,
                 record.refs_extra, record.refs_diverged,
                 record.detail, record.run_at))
        return record

    def _record(self, full_name: str, repo_id: int, state: str,
                detail: str, run_at: int, *,
                matched: int = 0, missing: int = 0, extra: int = 0,
                diverged: int = 0) -> WikiMirrorRun:
        return self._store(WikiMirrorRun(
            full_name=full_name, state=state, refs_matched=matched,
            refs_missing=missing, refs_extra=extra,
            refs_diverged=diverged, detail=detail, run_at=run_at), repo_id)

    def runs_for(self, full_name: str) -> list[WikiMirrorRun]:
        rows = self._conn.execute(
            "SELECT * FROM first_pass_mirror_runs WHERE full_name = ?"
            " AND phase = ? ORDER BY run_at, id",
            (full_name, PHASE_WIKI)).fetchall()
        return [WikiMirrorRun(
            full_name=row["full_name"], state=row["state"],
            refs_matched=row["refs_matched"],
            refs_missing=row["refs_missing"], refs_extra=row["refs_extra"],
            refs_diverged=row["refs_diverged"], detail=row["detail"],
            run_at=row["run_at"]) for row in rows]

    def latest_run(self, full_name: str) -> WikiMirrorRun | None:
        runs = self.runs_for(full_name)
        return runs[-1] if runs else None

    # -- standing facts ----------------------------------------------
    def wiki_path(self, owner, repo) -> Path:
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise WikiMirrorError("no_such_repo", "No such repository.")
        return wiki_path_for(self._repos, current)

    @staticmethod
    def _is_bare(path: Path) -> bool:
        if not path.is_dir():
            return False
        probe = run_git_in(
            path, ["rev-parse", "--is-bare-repository"], timeout=15.0)
        return (probe.returncode == 0
                and probe.stdout.decode("utf-8", "replace").strip() == "true")

    def status_for(self, owner, repo) -> WikiMirrorStatus:
        """The standing wiki-mirror facts for one
        repository: not a mirror, or the derived wiki
        source beside the latest recorded run's honest
        state. Reads only; syncs nothing, creates
        nothing."""
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise WikiMirrorError("no_such_repo", "No such repository.")
        mirror = self._mirrors.mirror_for(owner, repo)
        if mirror is None:
            return WikiMirrorStatus(
                full_name=current.full_name, is_mirror=False,
                wiki_source=None, state=STATE_NOT_A_MIRROR,
                detail="that repository is not a mirror",
                last_run_at=None)
        wiki_source = wiki_source_for(mirror.source, mirror.source_kind)
        latest = self.latest_run(current.full_name)
        return WikiMirrorStatus(
            full_name=current.full_name, is_mirror=True,
            wiki_source=str(wiki_source),
            state=state_from_run(latest.state if latest else None),
            detail=(latest.detail if latest else
                    "the wiki has never been synced"),
            last_run_at=latest.run_at if latest else None)

    # -- probing ------------------------------------------------------
    def _probe_local(self, wiki_source: Path) -> str:
        if not wiki_source.exists():
            return PROBE_ABSENT
        if not self._is_bare(wiki_source):
            return PROBE_UNREADABLE
        return PROBE_PRESENT

    def _source_refs(self, wiki_source, token: str | None) -> dict[str, str]:
        try:
            result = self._ls_remote(wiki_source, timeout=120.0, token=token)
        except TypeError:
            result = self._ls_remote(wiki_source, timeout=120.0)
        except ProcRefused as exc:
            raise WikiMirrorError("source_refs_unreadable", str(exc)) from exc
        if result.returncode != 0:
            detail = result.stderr.decode(
                "utf-8", "replace").strip()[:200] or "ls-remote failed"
            raise WikiMirrorError("source_refs_unreadable", detail)
        return parse_ls_remote(result.stdout.decode("utf-8", "replace"))

    def _wiki_refs(self, wiki_path: Path) -> dict[str, str]:
        return {ref.name: ref.oid for ref in RefStore(wiki_path).list_refs()
                if ref.name.startswith("refs/heads/")
                or ref.name.startswith("refs/tags/")}

    def _ensure_wiki(self, owner, repo, wiki_path: Path) -> None:
        current = self._repos.get_repository(owner, repo)
        ensure_dir(wiki_path.parent)
        result = run_git(
            ["init", "--bare",
             f"--initial-branch={current.default_branch}", str(wiki_path)],
            timeout=30.0)
        if result.returncode != 0:
            raise WikiMirrorError(
                "wiki_init_failed",
                "git could not create the mirror's wiki repository: "
                + result.stderr.decode("utf-8", "replace").strip()[:200])

    @staticmethod
    def _scrub(text: str, token: str | None) -> str:
        return text.replace(token, "[REDACTED]") if token else text

    # -- the sync -------------------------------------------------------
    def sync_wiki(self, owner, repo, *,
                  secrets: Secrets | None = None) -> WikiMirrorRun:
        """Sync one mirror's wiki from its derived source,
        behind the mirror's own S-330 credential gate,
        verified ref-for-ref. Every outcome -- verified,
        no-wiki, or failed -- is recorded; a refusal at
        the gate fetches nothing. A repository that is
        not a mirror raises ``not_a_mirror``: there is no
        source to derive a wiki from."""
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise WikiMirrorError("no_such_repo", "No such repository.")
        mirror = self._mirrors.mirror_for(owner, repo)
        if mirror is None:
            raise WikiMirrorError(
                "not_a_mirror",
                f"{current.full_name} is not a mirror; only a mirror "
                "carries its source's wiki alongside its code.")
        run_at = int(self._now())
        wiki_source = wiki_source_for(mirror.source, mirror.source_kind)
        try:
            token = self._credentials.resolve_token(owner, repo, secrets)
        except MirrorCredentialError as exc:
            return self._record(
                current.full_name, current.id, FAILED,
                f"credential gate refused: {exc}", run_at)
        if mirror.source_kind == "local":
            probe = self._probe_local(Path(wiki_source))
            decision = decide_wiki_sync(True, probe)
            if decision.action == ACTION_NO_WIKI:
                return self._record(
                    current.full_name, current.id, NO_WIKI,
                    "the source has no wiki: no wiki repository "
                    f"stands at {wiki_source}", run_at)
            if decision.action == ACTION_REFUSE:
                return self._record(
                    current.full_name, current.id, FAILED,
                    f"the source's wiki at {wiki_source} is not a "
                    "readable bare git repository", run_at)
            try:
                source_refs = self._source_refs(wiki_source, token)
            except Exception as exc:  # stated, never hidden
                return self._record(
                    current.full_name, current.id, FAILED,
                    self._scrub(
                        f"the source's wiki refs could not be read: {exc}",
                        token), run_at)
        else:
            try:
                source_refs = self._source_refs(wiki_source, token)
            except Exception:
                # A remote wiki that cannot be listed is how a
                # source with no wiki answers; state it as such,
                # never as a verified or healthy wiki.
                return self._record(
                    current.full_name, current.id, NO_WIKI,
                    "the source has no wiki: its wiki source "
                    f"{wiki_source} could not be listed", run_at)
        if not source_refs:
            return self._record(
                current.full_name, current.id, NO_WIKI,
                "the source has no wiki: its wiki repository "
                "advertises no pages (no refs)", run_at)
        wiki_path = wiki_path_for(self._repos, current)
        if wiki_path.exists() and not self._is_bare(wiki_path):
            return self._record(
                current.full_name, current.id, FAILED,
                "a directory already exists at the mirror's wiki "
                "path and is not a bare git repository; refusing "
                "to adopt it silently", run_at)
        if not wiki_path.exists():
            try:
                self._ensure_wiki(owner, repo, wiki_path)
            except Exception as exc:  # stated, never hidden
                return self._record(
                    current.full_name, current.id, FAILED,
                    f"the mirror's wiki could not be created: {exc}",
                    run_at)
        try:
            result = self._fetch(
                wiki_path, wiki_source, timeout=120.0, token=token)
        except TypeError:
            result = self._fetch(wiki_path, wiki_source, timeout=120.0)
        except Exception as exc:  # recorded, never hidden
            return self._record(
                current.full_name, current.id, FAILED,
                self._scrub(f"wiki fetch failed: {exc}", token), run_at)
        if result.returncode != 0:
            detail = result.stderr.decode(
                "utf-8", "replace").strip()[:200] or "fetch failed"
            return self._record(
                current.full_name, current.id, FAILED,
                self._scrub(f"wiki sync failed: {detail}", token), run_at)
        comparison = compare_ref_maps(source_refs, self._wiki_refs(wiki_path))
        return self._record(
            current.full_name, current.id,
            VERIFIED if comparison.verified else FAILED,
            comparison.headline.replace("verified ref-for-ref",
                                        "wiki verified ref-for-ref"),
            run_at, matched=comparison.matched,
            missing=len(comparison.missing), extra=len(comparison.extra),
            diverged=len(comparison.diverged))

    def sync_alongside_code(self, owner, repo, *,
                            secrets: Secrets | None = None) -> WikiMirrorRun:
        """The cadence act: sync the code mirror through
        S-330's credential road, then sync its wiki as
        part of the same act. The code outcome stands in
        the mirror's own S-070 record, the wiki outcome
        in the run log -- the two halves of one cadence,
        each recorded on its own standing record."""
        self._credentials.sync_mirror(owner, repo, secrets=secrets)
        return self.sync_wiki(owner, repo, secrets=secrets)

    def sync_owner_wikis(self, owner, *,
                         secrets: Secrets | None = None) -> WikiMirrorReport:
        """Sync the wiki of every mirror one owner holds,
        in repository name order. One mirror's outcome
        never hides another's; repositories that are not
        mirrors are not mirrors' wikis and are skipped."""
        report = WikiMirrorReport()
        mirrors = []
        for repo in self._repos.list_for_owner(owner):
            if self._mirrors.mirror_for(repo.owner, repo.name) is not None:
                mirrors.append(repo)
        if not mirrors:
            report.note = ("no mirrors are defined for this owner; "
                           "no wikis were mirrored")
            return report
        for repo in mirrors:
            report.runs.append(
                self.sync_wiki(repo.owner, repo.name, secrets=secrets))
        return report


def render_wiki_mirror_page(statuses: list[WikiMirrorStatus]) -> str:
    """The wiki-mirror page: every repository named with
    its wiki state in words -- synced, no source wiki,
    failed, or never synced -- never colour-only. All
    text escaped."""
    parts = ["<h1>Wiki mirrors</h1>"]
    if not statuses:
        parts.append("<p>No repositories to report.</p>")
        return "\n".join(parts)
    parts.append("<ul>")
    for status in statuses:
        parts.append(f"<li>{escape_html_text(status.headline)}</li>")
    parts.append("</ul>")
    return "\n".join(parts)
