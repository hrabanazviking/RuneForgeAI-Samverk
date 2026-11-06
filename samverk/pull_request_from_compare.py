"""Pull request from compare (S-167).

The compare view (S-105) offers "open pull request"
with the context intact: the pair the reader is already
looking at, its ahead/behind counts, its commit list
and diff totals, and the title that list suggests —
carried into S-141's creation road without retyping.

- **The offer is the compare, plus a verdict.**
  `offer` runs S-105's compare unchanged (the same
  counts, commits and diff totals the compare page
  shows) and adds only what creation needs: whether
  the compared refs are two branches, whether an
  open pull request already exists for that pair,
  whether the viewer may open one, and the title the
  preview would suggest. The verdict is said in
  words (`blockers`); `can_open` is empty blockers.
- **Only a branch pair opens.** A pull request is a
  branch pair (S-141), so a comparison against a tag
  or a bare commit id is a true comparison that
  simply cannot open — the offer says so in words
  (`not_branches` on the open road) instead of
  pretending a tag is a branch. A branch named with
  slashes (`feature/x`) is still one branch: the
  creation link carries it whole.
- **Context rides the link and the open call.** The
  rendered compare page carries an `Open pull
  request` link to the creation page for the exact
  pair (`/owner/repo/pulls/new/base...head`, the
  compare URL's shape) and names the context beside
  it — ahead/behind, files changed, additions and
  deletions, and the suggested title. `open_from_compare`
  opens through S-141's `create_pull_request` whole:
  its validation, its shared number, its recorded
  oids as compared at opening, its draft road, and
  its audit — so the pull request is born from the
  same pair and the same compare the offer showed.
- **Permissions ride S-141, read rides S-105.** A
  stranger to a private repository gets S-105's
  uniform `repo_not_found` before any question; a
  mere reader of a public repository sees the
  comparison and the offer's words, but the open
  road refuses `permission_denied` exactly as
  S-141's creation does.
- **No migration, no taxonomy event.** The offer is
  a read over S-105 plus S-141's existing preview;
  opening writes only the rows and the one
  `repo.pull_request.create` audit row S-141 already
  writes (schema stays 64, taxonomy stands at 119
  events), and its battery proves both.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote

from .accounts import AccountStore, User
from .audit import AuditLog
from .compare_view import CompareService, CompareView, render_compare_page
from .escaping import escape_html_text
from .issue_conversion import PullRequest
from .issues import IssueStore
from .permissions import can_write
from .pull_requests import PullRequestError, PullRequestStore
from .refs import RefStore
from .repositories import RepositoryStore

__all__ = [
    "ComparePrOffer", "PullRequestFromCompareStore",
    "render_compare_offer", "render_compare_page_with_offer",
]


def _branch_name(refs: RefStore, ref_text: str, oid: str) -> str | None:
    """The branch short name when *ref_text* names a branch
    at *oid* — else None (tag, bare id, full branch ref
    spelling included)."""
    name = ref_text
    if name.startswith("refs/heads/"):
        name = name[len("refs/heads/"):]
    for ref in refs.list_branches():
        if ref.short == name and ref.oid == oid:
            return ref.short
    return None


@dataclass(frozen=True)
class ComparePrOffer:
    full_name: str
    owner: str
    repo: str
    compare: CompareView
    base_branch: str | None    # branch short names — None
    head_branch: str | None    # when the ref is not a branch
    existing_open_number: int  # 0 when the pair has no open PR
    viewer_can_write: bool

    @property
    def blockers(self) -> tuple:
        """Why this comparison cannot be opened as a pull
        request, in words — empty when it can."""
        out = []
        if self.base_branch is None or self.head_branch is None:
            out.append(
                "Only a comparison between two branches can "
                "be opened as a pull request; "
                f"{self.compare.base_ref} … "
                f"{self.compare.head_ref} is not a pair of "
                "branch names.")
        if self.compare.ahead == 0:
            out.append(
                "There are no commits on the head branch that "
                "the base branch does not already have.")
        if self.existing_open_number:
            out.append(
                f"Pull request #{self.existing_open_number} is "
                "already open for this pair of branches.")
        if not self.viewer_can_write:
            out.append(
                "Only a repository writer can open a pull "
                "request from a branch in this repository.")
        return tuple(out)

    @property
    def can_open(self) -> bool:
        return not self.blockers

    @property
    def suggested_title(self) -> str:
        if self.compare.commits:
            return self.compare.commits[0].subject
        if self.head_branch is not None:
            return self.head_branch
        return self.compare.head_ref

    @property
    def context_words(self) -> str:
        """The compare's totals, in words — the context the
        offer carries into creation."""
        view = self.compare
        return (f"{view.ahead} ahead · {view.behind} behind · "
                f"{view.files_changed} files changed · "
                f"+{view.diff.additions} −{view.diff.deletions}")

    @property
    def creation_url(self) -> str | None:
        """The creation page's address for this exact pair,
        in the compare URL's shape — None when the pair
        is not two branches, because there is no creation
        page for any other pair."""
        if self.base_branch is None or self.head_branch is None:
            return None
        return (
            f"/{quote(self.owner, safe='-._~')}"
            f"/{quote(self.repo, safe='-._~')}/pulls/new/"
            f"{quote(self.base_branch, safe='-._~/')}..."
            f"{quote(self.head_branch, safe='-._~/')}")

    @property
    def existing_url(self) -> str | None:
        if not self.existing_open_number:
            return None
        return (
            f"/{quote(self.owner, safe='-._~')}"
            f"/{quote(self.repo, safe='-._~')}"
            f"/pulls/{self.existing_open_number}")


class PullRequestFromCompareStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        issues: IssueStore,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._issues = issues
        self._audit = audit
        self._now = time_fn
        self._compare = CompareService(repositories)
        self._prs = PullRequestStore(
            conn, repositories, accounts, issues, audit=audit,
            time_fn=time_fn)

    def offer(self, viewer: User | None, owner: object,
              repo: object, base_ref: object, head_ref: object,
              *, ignore_whitespace: bool = False) -> ComparePrOffer:
        """S-105's compare for this pair plus the creation
        verdict: branch pair, existing open pull request,
        and writer standing, all read fresh. Refusals of
        the compare itself (unknown repository for this
        viewer, unknown ref) are S-105's CompareError."""
        view = self._compare.compare(
            viewer, owner, repo, base_ref, head_ref,
            ignore_whitespace=ignore_whitespace)
        current = self._repos.get_repository(owner, repo)
        assert current is not None  # the compare required read
        path = self._repos.path_for(current.owner, current.name)
        refs = RefStore(path)
        base_branch = _branch_name(refs, view.base_ref, view.base_oid)
        head_branch = _branch_name(refs, view.head_ref, view.head_oid)
        existing = 0
        if base_branch is not None and head_branch is not None \
                and base_branch != head_branch:
            existing = self._prs._existing_open_number(
                current.id, base_branch, head_branch)
        return ComparePrOffer(
            full_name=current.full_name, owner=current.owner,
            repo=current.name, compare=view,
            base_branch=base_branch, head_branch=head_branch,
            existing_open_number=existing,
            viewer_can_write=can_write(viewer, current))

    def open_from_compare(
            self, actor: User, owner: object, repo: object,
            base_ref: object, head_ref: object, *,
            title: object = None, body: object = "",
            draft: bool = False,
            source_ip: str | None = None) -> PullRequest:
        """Open the pull request this comparison proposes.
        The offer is recomputed whole, so a comparison the
        repository has outgrown (pair no longer branches,
        commits already proposed, already open) is refused
        by name before S-141 claims any number; a pair that
        still stands opens through S-141 unchanged, with
        the compare's pair, and S-141's default title — the
        compared head's first commit subject — when the
        author gives none."""
        offer = self.offer(actor, owner, repo, base_ref, head_ref)
        if not offer.can_open:
            if offer.base_branch is None or offer.head_branch is None:
                reason = "not_branches"
            elif offer.compare.ahead == 0:
                reason = "no_commits"
            elif offer.existing_open_number:
                reason = "already_exists"
            else:
                reason = "permission_denied"
            raise PullRequestError(reason, offer.blockers[0])
        return self._prs.create_pull_request(
            actor, owner, repo, base_branch=offer.base_branch,
            head_branch=offer.head_branch, title=title, body=body,
            draft=draft, source_ip=source_ip)


def render_compare_offer(offer: ComparePrOffer) -> str:
    """The offer as it appears on the compare page: the
    `Open pull request` link to the creation page for the
    exact pair with its context named beside it when the
    pair can open; every reason it cannot, in words and
    with the already-open pull request linked, when it
    cannot. Text always — never a colour alone."""
    if offer.can_open:
        href = escape_html_text(offer.creation_url or "")
        return (
            '<p class="compare-pr-offer">'
            '<a class="open-pull-request" href="' + href + '">'
            "Open pull request</a> — "
            + escape_html_text(offer.head_branch or "") + " into "
            + escape_html_text(offer.base_branch or "") + " · "
            + escape_html_text(offer.context_words) + " · "
            + "title starts as “"
            + escape_html_text(offer.suggested_title) + "”</p>")
    parts = ['<div class="compare-pr-offer">']
    for blocker in offer.blockers:
        parts.append(
            '<p class="blocker">' + escape_html_text(blocker) + "</p>")
    if offer.existing_url is not None:
        href = escape_html_text(offer.existing_url)
        parts.append(
            '<p class="existing"><a href="' + href + '">'
            + f"View pull request #{offer.existing_open_number}"
            + "</a></p>")
    parts.append("</div>")
    return "\n".join(parts)


def render_compare_page_with_offer(view: CompareView,
                                   offer: ComparePrOffer) -> str:
    """S-105's compare page, whole and unchanged, with the
    S-167 offer laid over it — the view *view* rendered,
    the offer *offer* (computed from that same pair)
    inserted before the page closes."""
    page = render_compare_page(view)
    offer_html = render_compare_offer(offer)
    marker = "</body></html>"
    if marker in page:
        return page.replace(marker, offer_html + "\n" + marker, 1)
    return page + "\n" + offer_html
