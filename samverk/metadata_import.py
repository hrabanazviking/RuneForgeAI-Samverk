"""Metadata import (S-338).

Roadmap S-338: **metadata import -- issues, labels,
milestones, and releases imported from GitHub's API
into the mirror (where the owner's credential allows),
marked as imported with source links.**

S-336/S-337 mirrored the *code* of the originals,
ref-for-ref. This slice mirrors their *metadata* --
the issues, labels, milestones, and releases the
GitHub API serves for the source repository -- under
laws inherited whole from its predecessors:

- **The credential gate (S-337's, reused).** Metadata
  is fetched only where the owner's credential allows:
  the mirror must name an S-330 credential (an S-003
  instance-secret name, never a value), that secret
  must be loaded, and the operator-declared scope must
  be read-only, judged by S-337's own pure
  ``decide_credential``. No credential, an unloaded
  secret, or an undeclared or non-read scope refuses
  the import *before any fetch is attempted*, in plain
  words, and the refusal is recorded as a run -- never
  a silent skip.
- **Marked as imported, with source links.** Every
  item that lands is recorded in ``metadata_imports``
  (migration 139): its kind, its source key, the
  source link (the item's ``html_url`` on GitHub, or
  the canonical URL built from the source identity),
  and the local row it landed as. The import page
  names each item *imported* beside its source link;
  nothing imported is ever dressed as native.
- **Idempotent.** An item already recorded as imported
  for this mirror is counted skipped and never
  duplicated; a local row that already stands (a
  default label, a milestone of the same title) is
  linked, not recreated.
- **Honest shapes.** The GitHub issues API also serves
  pull requests; those are counted as skipped pull
  requests, never imported as issues. Malformed items
  are refused in plain words and counted, never guessed
  at. Issue numbers are preserved when the mirror's
  shared sequence (S-121) has not claimed them, and
  the counter is advanced past any preserved number so
  a later native claim can never collide.

The fetch rides one seam: ``fetch_fn(url, token)``
returning the parsed JSON list, defaulting to a
urllib read of ``api.github.com`` carrying the token
in the Authorization header only -- never in a URL,
never logged. The judgements are pure:
``parse_github_source`` reads a mirror source,
``normalise_*`` validate one API item each and write
nothing. No new audit event is claimed; the taxonomy
stands at 138. The schema moves 138 -> 139 for the
two provenance tables above, and for nothing else.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from .accounts import AccountStore
from .audit import AuditLog
from .escaping import escape_html_attr, escape_html_text
from .labels import validate_colour
from .milestones import validate_due_on
from .mirror_credentials import MirrorCredentialError, MirrorCredentialService
from .private_originals import ACTION_ALLOW, decide_credential
from .pull_mirrors import PullMirrorService
from .repositories import RepositoryStore
from .secrets import Secrets

KIND_ISSUE = "issue"
KIND_LABEL = "label"
KIND_MILESTONE = "milestone"
KIND_RELEASE = "release"
KINDS = (KIND_LABEL, KIND_MILESTONE, KIND_ISSUE, KIND_RELEASE)

STATE_IMPORTED = "imported"
STATE_REFUSED = "refused"
STATE_FAILED = "failed"

API_ROOT = "https://api.github.com"
_GITHUB_HOSTS = frozenset({"github.com", "www.github.com"})
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class MetadataImportError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def parse_github_source(source: object) -> tuple[str, str] | None:
    """Pure: the (owner, repo) a mirror source names on
    GitHub, or None when the source is not a GitHub URL
    this import can read metadata for. A trailing
    ``.git`` and a trailing slash are the same source."""
    if not isinstance(source, str):
        return None
    parsed = urlparse(source.strip())
    if parsed.scheme not in ("https", "http"):
        return None
    if (parsed.hostname or "").lower() not in _GITHUB_HOSTS:
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) != 2:
        return None
    owner, repo = parts
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not _NAME_RE.match(owner) or not _NAME_RE.match(repo):
        return None
    return owner, repo


def source_url_for(kind: str, gh_owner: str, gh_repo: str,
                   item: dict) -> str:
    """The source link for one item: its own html_url
    when the API gave one, else the canonical GitHub
    URL built from the source identity -- a link is
    never invented from anything weaker."""
    url = item.get("html_url")
    if isinstance(url, str) and url.startswith("https://"):
        return url
    base = f"https://github.com/{gh_owner}/{gh_repo}"
    if kind == KIND_ISSUE:
        return f"{base}/issues/{item.get('number')}"
    if kind == KIND_LABEL:
        return f"{base}/labels"
    if kind == KIND_MILESTONE:
        return f"{base}/milestones"
    if kind == KIND_RELEASE:
        return f"{base}/releases/tag/{item.get('tag_name')}"
    return base


@dataclass(frozen=True)
class ImportedLabel:
    name: str
    colour: str
    description: str


@dataclass(frozen=True)
class ImportedMilestone:
    title: str
    description: str
    state: str
    due_on: str | None


@dataclass(frozen=True)
class ImportedIssue:
    number: int
    title: str
    body: str
    state: str
    state_reason: str
    label_names: tuple[str, ...]
    milestone_title: str | None


@dataclass(frozen=True)
class ImportedRelease:
    tag: str
    title: str
    notes: str
    draft: bool
    prerelease: bool
    target: str


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def normalise_label(item: object) -> ImportedLabel:
    """Pure: one GitHub label judged. A label with no
    name is refused in words -- colour alone is never
    the meaning (S-124). An unreadable colour falls
    back to the neutral grey GitHub itself uses."""
    if not isinstance(item, dict):
        raise MetadataImportError("item_invalid", "A label item is not an object.")
    name = _text(item.get("name")).strip()
    if not name:
        raise MetadataImportError("item_invalid", "A label carries no name.")
    raw = _text(item.get("color")).strip()
    try:
        colour = validate_colour("#" + raw.lstrip("#"))
    except Exception:
        colour = "#ededed"
    return ImportedLabel(name=name[:50], colour=colour,
                         description=_text(item.get("description"))[:200])


def normalise_milestone(item: object) -> ImportedMilestone:
    """Pure: one GitHub milestone judged. The due date
    is the date part of the API's timestamp, judged by
    S-125's own validator; an impossible date refuses."""
    if not isinstance(item, dict):
        raise MetadataImportError("item_invalid", "A milestone item is not an object.")
    title = _text(item.get("title")).strip()
    if not title:
        raise MetadataImportError("item_invalid", "A milestone carries no title.")
    state = _text(item.get("state")) or "open"
    if state not in ("open", "closed"):
        raise MetadataImportError("item_invalid", f"A milestone state {state!r} is not open or closed.")
    due_raw = item.get("due_on")
    due_on = None
    if isinstance(due_raw, str) and due_raw:
        due_on = validate_due_on(due_raw[:10])
    return ImportedMilestone(title=title[:100], description=_text(item.get("description"))[:1000], state=state, due_on=due_on)


def is_pull_request(item: object) -> bool:
    """Pure: the GitHub issues API serves pull requests
    in the same list; the marker key is the tell."""
    return isinstance(item, dict) and "pull_request" in item


def normalise_issue(item: object) -> ImportedIssue:
    """Pure: one GitHub issue judged. Number and title
    are the identity; a missing either refuses."""
    if not isinstance(item, dict):
        raise MetadataImportError("item_invalid", "An issue item is not an object.")
    number = item.get("number")
    if not isinstance(number, int) or number < 1:
        raise MetadataImportError("item_invalid", "An issue carries no valid number.")
    title = _text(item.get("title")).strip()
    if not title:
        raise MetadataImportError("item_invalid", f"Issue #{number} carries no title.")
    state = _text(item.get("state")) or "open"
    if state not in ("open", "closed"):
        raise MetadataImportError("item_invalid", f"Issue #{number} state {state!r} is not open or closed.")
    reason = _text(item.get("state_reason"))
    state_reason = reason if state == "closed" and reason in ("completed", "not_planned") else ("completed" if state == "closed" else "")
    names: list[str] = []
    for lab in item.get("labels") or []:
        if isinstance(lab, dict) and _text(lab.get("name")).strip():
            names.append(_text(lab["name"]).strip())
        elif isinstance(lab, str) and lab.strip():
            names.append(lab.strip())
    milestone = item.get("milestone")
    ms_title = _text(milestone.get("title")).strip() if isinstance(milestone, dict) else None
    return ImportedIssue(number=number, title=title[:256], body=_text(item.get("body"))[:65536], state=state, state_reason=state_reason, label_names=tuple(names), milestone_title=ms_title or None)


def normalise_release(item: object) -> ImportedRelease:
    """Pure: one GitHub release judged. The tag is the
    identity; a release with no tag refuses."""
    if not isinstance(item, dict):
        raise MetadataImportError("item_invalid", "A release item is not an object.")
    tag = _text(item.get("tag_name")).strip()
    if not tag:
        raise MetadataImportError("item_invalid", "A release carries no tag.")
    return ImportedRelease(tag=tag, title=(_text(item.get("name")).strip() or tag)[:256], notes=_text(item.get("body"))[:65536], draft=bool(item.get("draft")), prerelease=bool(item.get("prerelease")), target=_text(item.get("target_commitish")))


@dataclass(frozen=True)
class MetadataImportRecord:
    full_name: str
    kind: str
    source_key: str
    source_url: str
    local_id: int
    imported_at: int

    @property
    def headline(self) -> str:
        return (f"{self.kind} {self.source_key} imported into "
                f"{self.full_name} from {self.source_url}")


@dataclass
class MetadataImportReport:
    full_name: str = ""
    state: str = STATE_IMPORTED
    labels_imported: int = 0
    labels_skipped: int = 0
    milestones_imported: int = 0
    milestones_skipped: int = 0
    issues_imported: int = 0
    issues_skipped: int = 0
    pull_requests_skipped: int = 0
    releases_imported: int = 0
    releases_skipped: int = 0
    invalid_items: int = 0
    detail: str = ""
    run_at: int = 0
    records: list[MetadataImportRecord] = field(default_factory=list)

    @property
    def imported_total(self) -> int:
        return (self.labels_imported + self.milestones_imported
                + self.issues_imported + self.releases_imported)

    @property
    def headline(self) -> str:
        if self.state == STATE_REFUSED:
            return f"metadata import for {self.full_name} refused: {self.detail}"
        if self.state == STATE_FAILED:
            return f"metadata import for {self.full_name} failed: {self.detail}"
        return (f"metadata import for {self.full_name}: "
                f"{self.labels_imported} labels, {self.milestones_imported} milestones, "
                f"{self.issues_imported} issues, {self.releases_imported} releases imported; "
                f"{self.labels_skipped + self.milestones_skipped + self.issues_skipped + self.releases_skipped} already imported skipped, "
                f"{self.pull_requests_skipped} pull requests skipped, "
                f"{self.invalid_items} invalid items refused")


def fetch_github_json(url: str, token: str | None) -> object:
    """The live fetch seam: one GitHub API page as parsed
    JSON. The token rides the Authorization header only."""
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "samverk-metadata-import"})
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


class MetadataImportService:
    def __init__(self, conn: sqlite3.Connection, data_root: Path,
                 accounts: AccountStore, repositories: RepositoryStore,
                 audit: AuditLog | None = None,
                 time_fn: Callable[[], float] = time.time,
                 fetch_fn: Callable[..., object] = fetch_github_json):
        self._conn = conn
        self._accounts = accounts
        self._repos = repositories
        self._audit = audit
        self._now = time_fn
        self._fetch = fetch_fn
        self._credentials = MirrorCredentialService(conn, data_root, accounts, repositories, audit=audit, time_fn=time_fn)
        self._pull = PullMirrorService(conn, data_root, accounts, repositories, audit=audit, time_fn=time_fn)

    # -- records -------------------------------------------------
    def imports_for(self, owner, name: str) -> list[MetadataImportRecord]:
        repo = self._repos.get_repository(owner, name)
        if repo is None:
            return []
        rows = self._conn.execute("SELECT * FROM metadata_imports WHERE repo_id = ? ORDER BY kind, source_key", (repo.id,)).fetchall()
        return [MetadataImportRecord(full_name=r["full_name"], kind=r["kind"], source_key=r["source_key"], source_url=r["source_url"], local_id=r["local_id"], imported_at=r["imported_at"]) for r in rows]

    def runs_for(self, full_name: str) -> list[MetadataImportReport]:
        rows = self._conn.execute("SELECT * FROM metadata_import_runs WHERE full_name = ? ORDER BY run_at, id", (full_name,)).fetchall()
        out = []
        for r in rows:
            out.append(MetadataImportReport(full_name=r["full_name"], state=r["state"], labels_imported=r["labels_imported"], labels_skipped=r["labels_skipped"], milestones_imported=r["milestones_imported"], milestones_skipped=r["milestones_skipped"], issues_imported=r["issues_imported"], issues_skipped=r["issues_skipped"], releases_imported=r["releases_imported"], releases_skipped=r["releases_skipped"], detail=r["detail"], run_at=r["run_at"]))
        return out

    def _record_run(self, report: MetadataImportReport, repo_id: int) -> None:
        with self._conn:
            self._conn.execute("INSERT INTO metadata_import_runs (full_name, repo_id, state, labels_imported, labels_skipped, milestones_imported, milestones_skipped, issues_imported, issues_skipped, releases_imported, releases_skipped, detail, run_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (report.full_name, repo_id, report.state, report.labels_imported, report.labels_skipped, report.milestones_imported, report.milestones_skipped, report.issues_imported, report.issues_skipped, report.releases_imported, report.releases_skipped, report.detail, report.run_at))

    def _already(self, repo_id: int, kind: str, key: str) -> bool:
        return self._conn.execute("SELECT 1 FROM metadata_imports WHERE repo_id = ? AND kind = ? AND source_key = ?", (repo_id, kind, key)).fetchone() is not None

    def _mark(self, report: MetadataImportReport, repo_id: int, kind: str, key: str, url: str, local_id: int, run_at: int) -> None:
        with self._conn:
            self._conn.execute("INSERT INTO metadata_imports (repo_id, full_name, kind, source_key, source_url, local_id, imported_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (repo_id, report.full_name, kind, key, url, local_id, run_at))
        report.records.append(MetadataImportRecord(full_name=report.full_name, kind=kind, source_key=key, source_url=url, local_id=local_id, imported_at=run_at))

    # -- landing ---------------------------------------------------
    def _land_label(self, repo_id: int, item: ImportedLabel, now: int) -> int:
        row = self._conn.execute("SELECT id FROM labels WHERE repo_id = ? AND name_lower = ?", (repo_id, item.name.lower())).fetchone()
        if row is not None:
            return int(row["id"])
        with self._conn:
            cur = self._conn.execute("INSERT INTO labels (repo_id, name, name_lower, colour, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (repo_id, item.name, item.name.lower(), item.colour, item.description, now, now))
        return int(cur.lastrowid)

    def _land_milestone(self, repo_id: int, item: ImportedMilestone, now: int) -> int:
        row = self._conn.execute("SELECT id FROM milestones WHERE repo_id = ? AND title_lower = ?", (repo_id, item.title.lower())).fetchone()
        if row is not None:
            return int(row["id"])
        with self._conn:
            cur = self._conn.execute("INSERT INTO milestones (repo_id, title, title_lower, description, due_on, state, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (repo_id, item.title, item.title.lower(), item.description, item.due_on, item.state, now, now))
        return int(cur.lastrowid)

    def _claim_number(self, repo_id: int, wanted: int) -> int:
        taken = self._conn.execute("SELECT 1 FROM issues WHERE repo_id = ? AND number = ?", (repo_id, wanted)).fetchone()
        with self._conn:
            if taken is None:
                self._conn.execute("INSERT INTO repo_counters (repo_id, last_number) VALUES (?, ?) ON CONFLICT (repo_id) DO UPDATE SET last_number = MAX(last_number, excluded.last_number)", (repo_id, wanted))
                return wanted
            row = self._conn.execute("INSERT INTO repo_counters (repo_id, last_number) VALUES (?, 1) ON CONFLICT (repo_id) DO UPDATE SET last_number = last_number + 1 RETURNING last_number", (repo_id,)).fetchone()
            return int(row["last_number"])

    def _land_issue(self, repo_id: int, author_id: int, item: ImportedIssue, now: int) -> int:
        number = self._claim_number(repo_id, item.number)
        milestone_id = None
        if item.milestone_title:
            mrow = self._conn.execute("SELECT id FROM milestones WHERE repo_id = ? AND title_lower = ?", (repo_id, item.milestone_title.lower())).fetchone()
            milestone_id = int(mrow["id"]) if mrow else None
        with self._conn:
            cur = self._conn.execute("INSERT INTO issues (repo_id, number, kind, author_id, title, body, state, state_reason, milestone_id, version, created_at, updated_at) VALUES (?, ?, 'issue', ?, ?, ?, ?, ?, ?, 1, ?, ?)", (repo_id, number, author_id, item.title, item.body, item.state, item.state_reason, milestone_id, now, now))
            issue_id = int(cur.lastrowid)
            for name in item.label_names:
                lrow = self._conn.execute("SELECT id FROM labels WHERE repo_id = ? AND name_lower = ?", (repo_id, name.lower())).fetchone()
                if lrow is not None:
                    self._conn.execute("INSERT OR IGNORE INTO issue_labels (issue_id, label_id, created_at) VALUES (?, ?, ?)", (issue_id, int(lrow["id"]), now))
        return issue_id

    def _land_release(self, repo_id: int, author_id: int, item: ImportedRelease, now: int) -> int:
        row = self._conn.execute("SELECT id FROM releases WHERE repo_id = ? AND tag = ?", (repo_id, item.tag)).fetchone()
        if row is not None:
            return int(row["id"])
        with self._conn:
            cur = self._conn.execute("INSERT INTO releases (repo_id, tag, title, notes, target_oid, author_id, source, draft, prerelease, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'api', ?, ?, ?, ?)", (repo_id, item.tag, item.title, item.notes, item.target, author_id, 1 if item.draft else 0, 1 if item.prerelease else 0, now, now))
        return int(cur.lastrowid)

    # -- fetching ----------------------------------------------------
    def _fetch_list(self, gh_owner: str, gh_repo: str, endpoint: str, token: str | None) -> list:
        url = f"{API_ROOT}/repos/{gh_owner}/{gh_repo}/{endpoint}?per_page=100&state=all"
        try:
            result = self._fetch(url, token)
        except TypeError:
            result = self._fetch(url)
        if not isinstance(result, list):
            raise MetadataImportError("api_shape_invalid", f"GitHub's {endpoint} answer for {gh_owner}/{gh_repo} is not a list.")
        return result

    # -- the run -------------------------------------------------------
    def import_metadata(self, owner, name: str, *, secrets: Secrets | None, declared_scope: object) -> MetadataImportReport:
        """Import one mirror's metadata from GitHub's API,
        behind the S-337 credential gate. Every outcome --
        imported, refused, failed -- is recorded as a run."""
        mirror = self._pull.pull_mirror_for(owner, name)
        if mirror is None:
            raise MetadataImportError("not_a_mirror", f"{owner}/{name} is not a defined pull mirror.")
        repo = self._repos.get_repository(owner, name)
        run_at = int(self._now())
        report = MetadataImportReport(full_name=mirror.full_name, run_at=run_at)
        cred = self._credentials.credential_for(owner, name)
        gate = decide_credential(bool(cred and cred.has_credential), declared_scope)
        if gate.action != ACTION_ALLOW:
            report.state = STATE_REFUSED
            report.detail = f"credential gate refused: {gate.reason}"
            self._record_run(report, mirror.repo_id)
            return report
        try:
            token = self._credentials.resolve_token(owner, name, secrets)
        except MirrorCredentialError as exc:
            report.state = STATE_REFUSED
            report.detail = f"credential gate refused: {exc}"
            self._record_run(report, mirror.repo_id)
            return report
        source = parse_github_source(mirror.source)
        if source is None:
            report.state = STATE_FAILED
            report.detail = ("the mirror's source is not a GitHub repository "
                             "URL; metadata import reads GitHub's API only")
            self._record_run(report, mirror.repo_id)
            return report
        gh_owner, gh_repo = source
        author = self._accounts.get_by_username(repo.owner)
        if author is None:
            report.state = STATE_FAILED
            report.detail = f"the owner of {mirror.full_name} cannot be found"
            self._record_run(report, mirror.repo_id)
            return report
        try:
            labels_raw = self._fetch_list(gh_owner, gh_repo, "labels", token)
            milestones_raw = self._fetch_list(gh_owner, gh_repo, "milestones", token)
            issues_raw = self._fetch_list(gh_owner, gh_repo, "issues", token)
            releases_raw = self._fetch_list(gh_owner, gh_repo, "releases", token)
        except Exception as exc:
            report.state = STATE_FAILED
            report.detail = f"the GitHub API fetch failed: {exc}"[:400]
            self._record_run(report, mirror.repo_id)
            return report
        for raw in labels_raw:
            try:
                item = normalise_label(raw)
            except Exception:
                report.invalid_items += 1
                continue
            if self._already(repo.id, KIND_LABEL, item.name):
                report.labels_skipped += 1
                continue
            local_id = self._land_label(repo.id, item, run_at)
            self._mark(report, repo.id, KIND_LABEL, item.name, source_url_for(KIND_LABEL, gh_owner, gh_repo, raw), local_id, run_at)
            report.labels_imported += 1
        for raw in milestones_raw:
            try:
                item = normalise_milestone(raw)
            except Exception:
                report.invalid_items += 1
                continue
            if self._already(repo.id, KIND_MILESTONE, item.title):
                report.milestones_skipped += 1
                continue
            local_id = self._land_milestone(repo.id, item, run_at)
            self._mark(report, repo.id, KIND_MILESTONE, item.title, source_url_for(KIND_MILESTONE, gh_owner, gh_repo, raw), local_id, run_at)
            report.milestones_imported += 1
        for raw in issues_raw:
            if is_pull_request(raw):
                report.pull_requests_skipped += 1
                continue
            try:
                item = normalise_issue(raw)
            except Exception:
                report.invalid_items += 1
                continue
            if self._already(repo.id, KIND_ISSUE, str(item.number)):
                report.issues_skipped += 1
                continue
            local_id = self._land_issue(repo.id, author.id, item, run_at)
            self._mark(report, repo.id, KIND_ISSUE, str(item.number), source_url_for(KIND_ISSUE, gh_owner, gh_repo, raw), local_id, run_at)
            report.issues_imported += 1
        for raw in releases_raw:
            try:
                item = normalise_release(raw)
            except Exception:
                report.invalid_items += 1
                continue
            if self._already(repo.id, KIND_RELEASE, item.tag):
                report.releases_skipped += 1
                continue
            local_id = self._land_release(repo.id, author.id, item, run_at)
            self._mark(report, repo.id, KIND_RELEASE, item.tag, source_url_for(KIND_RELEASE, gh_owner, gh_repo, raw), local_id, run_at)
            report.releases_imported += 1
        report.detail = report.headline
        self._record_run(report, mirror.repo_id)
        return report


def render_metadata_import_page(report: MetadataImportReport, records: list[MetadataImportRecord] | None = None) -> str:
    """The metadata-import page: the run's verdict in
    words, then every imported item named as imported
    beside its source link. All text escaped."""
    parts = ["<h1>Metadata import</h1>", f"<p>{escape_html_text(report.headline)}.</p>"]
    items = records if records is not None else report.records
    if items:
        parts.append("<ul>")
        for record in items:
            parts.append(f'<li>{escape_html_text(record.kind)} {escape_html_text(record.source_key)} -- imported from <a href="{escape_html_attr(record.source_url)}">{escape_html_text(record.source_url)}</a></li>')
        parts.append("</ul>")
    return "\n".join(parts)
