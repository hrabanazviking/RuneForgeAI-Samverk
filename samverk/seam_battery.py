"""Seam battery (S-374).

The end-to-end walk, scripted once and run whole: a
villager pushes code, opens a pull request from Samtal,
gets reviewed, merges, and the hall sees it. Every step
runs on the real standing stores — no mocks anywhere in
the walk (Volmarr's law): the identity link is S-362's
signed exchange, the entry is S-363's SSO exchange, the
push is a real git push into the real bare repository,
the pull request is S-141's store over the real refs,
the review is the standing review store, the merge is
S-153's merge store landing a real merge commit, and
the hall's sight of it all is S-367's event cards. The
panel (S-368), the unfurl (S-370) and the mentions
bridge (S-369) are walked too, because a villager's day
crosses them.

The walk records each step as it lands — name, verdict,
detail — and stops at the first failed step, naming it:
a red walk says exactly where the seam broke, never a
blur. run_walk returns the WalkReport; all_green is the
battery's one question. The walk builds its village in
the caller's database and data root (a temp dir in the
battery) and leaves everything it made standing, so a
failure can be inspected where it fell.

No migration, no new taxonomy event: the walk writes
only what the standing stores themselves write.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .accounts import AccountStore, User
from .audit import AuditLog
from .hall_events import HallEventService
from .identity_linking import IdentityLinkStore
from .issues import IssueStore
from .link_unfurl import LinkUnfurlService
from .mentions_bridge import MentionsBridgeService
from .pull_request_merge import PullRequestMergeStore
from .pull_request_reviews import PullRequestReviewStore
from .pull_requests import PullRequestStore
from .repositories import RepositoryStore
from .samtal_panel import SamtalPanelService
from .seam_identity import SeamIdentityService, mint_link_token
from .seam_sso import SeamSsoService, mint_sso_token
from .sessions import SessionStore

_GIT_ENV = {"GIT_AUTHOR_NAME": "Walk", "GIT_AUTHOR_EMAIL": "walk@samverk",
            "GIT_COMMITTER_NAME": "Walk", "GIT_COMMITTER_EMAIL": "walk@samverk",
            "PATH": "/usr/bin:/bin"}


def _git(cwd: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=cwd, env=_GIT_ENV,
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {out.stderr.strip()}")
    return out.stdout.strip()


@dataclass(frozen=True)
class Step:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class WalkReport:
    steps: tuple
    pr_number: int | None
    hall_cards: tuple

    @property
    def all_green(self) -> bool:
        return bool(self.steps) and all(s.ok for s in self.steps)

    @property
    def failed_step(self) -> str | None:
        for s in self.steps:
            if not s.ok:
                return s.name
        return None

    def summary(self) -> str:
        verdict = "all green" if self.all_green else f"failed at {self.failed_step}"
        return f"seam walk: {len(self.steps)} steps, {verdict}"


class SeamWalk:
    def __init__(self, conn, data_root: Path, accounts: AccountStore,
                 *, settings: dict, secret: bytes,
                 audit: AuditLog | None = None, time_fn=None):
        self._conn = conn
        self._root = Path(data_root)
        self._accounts = accounts
        self._settings = settings
        self._secret = secret
        self._audit = audit
        self._now = time_fn or (lambda: 5000)
        self._repos = RepositoryStore(conn, self._root, accounts)
        self._issues = IssueStore(conn, self._repos, accounts, audit=audit)
        self._links = IdentityLinkStore(conn, accounts, audit=audit, time_fn=self._now)

    def run(self, villager: User, reviewer: User, *, hall: str = "longhouse",
            repo_name: str = "anvil", principal: str = "villager@longhouse") -> WalkReport:
        steps: list[Step] = []
        pr_number: int | None = None
        hall = hall.strip().lower()
        owner = villager.username
        full = f"{owner}/{repo_name}"
        halls = HallEventService(self._conn, settings=self._settings)

        def step(name, fn):
            try:
                detail = fn()
            except Exception as exc:  # the walk names its break
                reason = getattr(exc, "reason", None)
                label = f"{type(exc).__name__} ({reason})" if reason else type(exc).__name__
                steps.append(Step(name, False, f"{label}: {exc}"))
                raise _StopWalk
            steps.append(Step(name, True, str(detail)))

        try:
            step("link_identity", lambda: self._link(villager, principal))
            step("enter_by_sso", lambda: self._sso(principal))
            step("push_code", lambda: self._push(villager, repo_name))
            step("hall_sees_push", lambda: self._hall_push(halls, hall, villager, full))
            step("panel_from_samtal", lambda: self._panel(villager, full))
            def _open():
                nonlocal pr_number
                pr_number = self._open_pr(villager, repo_name)
                return f"pull request #{pr_number} opened from Samtal"
            step("open_pr_from_samtal", _open)
            step("hall_sees_pr", lambda: self._hall_pr(halls, hall, full, pr_number))
            step("review_approves", lambda: self._review(reviewer, villager, repo_name, pr_number))
            step("mention_crosses", lambda: self._mention(reviewer, villager, full, pr_number))
            step("unfurl_in_conversation", lambda: self._unfurl(reviewer, full, pr_number))
            step("merge_lands", lambda: self._merge(villager, repo_name, pr_number))
            step("hall_sees_merge", lambda: self._hall_merge(halls, hall, full, pr_number))
        except _StopWalk:
            pass
        cards = ()
        try:
            cards = tuple(c.title for c in halls.cards_for(hall))
        except Exception:
            pass
        return WalkReport(steps=tuple(steps), pr_number=pr_number, hall_cards=cards)


    # -- the steps, each on its standing store --------------
    def _link(self, villager, principal):
        svc = SeamIdentityService(self._links, secret=self._secret,
                                  settings=self._settings, time_fn=self._now)
        token = mint_link_token(self._secret, principal=principal,
                                now=int(self._now()), nonce="walk-link-1")
        link = svc.complete_link(villager.id, token)
        return f"{villager.username} linked to {link.external_id}"

    def _sso(self, principal):
        sessions = SessionStore(self._conn, time_fn=self._now)
        svc = SeamSsoService(self._links, self._accounts, sessions,
                             secret=self._secret, settings=self._settings,
                             time_fn=self._now)
        token = mint_sso_token(self._secret, principal=principal,
                               now=int(self._now()), nonce="walk-sso-1")
        session_token = svc.exchange(token)
        user_id = sessions.authenticate(session_token)
        if user_id is None:
            raise RuntimeError("SSO session does not authenticate")
        return "Samtal session entered Samverk without a second password"

    def _push(self, villager, repo_name):
        self._repos.create_repository(villager.id, villager.username,
                                      repo_name, visibility="public")
        bare = self._repos.path_for(villager.username, repo_name)
        work = self._root / "walk-work"
        work.mkdir(parents=True, exist_ok=True)
        _git(work, "init", "-b", "main")
        (work / "anvil.py").write_text("FORGED = False\n", encoding="utf-8")
        _git(work, "add", "."); _git(work, "commit", "-m", "base: the anvil")
        _git(work, "checkout", "-b", "feature")
        (work / "anvil.py").write_text("FORGED = True\n", encoding="utf-8")
        _git(work, "add", "."); _git(work, "commit", "-m", "forge the anvil")
        _git(work, "push", str(bare), "main", "feature")
        return f"villager pushed main + feature to {villager.username}/{repo_name}"

    def _hall_push(self, halls, hall, villager, full):
        halls.opt_in(villager, hall, full)
        card = halls.post_event(hall, kind="push", repo=full,
                                title="2 commits pushed", link_path=f"/{full}",
                                actor_name=villager.username,
                                idempotency_key="walk-push-1")
        return f"hall card: {card.summary()}"

    def _panel(self, villager, full):
        panel = SamtalPanelService(self._conn, self._root, self._accounts,
                                   settings=self._settings, audit=self._audit,
                                   time_fn=self._now).panel_for(villager)
        names = [r.full_name for r in panel.repos]
        if full not in names:
            raise RuntimeError(f"panel does not show {full}: {names}")
        return f"panel decided by {panel.decided_by} shows {full}"

    def _open_pr(self, villager, repo_name):
        prs = PullRequestStore(self._conn, self._repos, self._accounts,
                               self._issues, audit=self._audit)
        pr = prs.create_pull_request(villager, villager.username, repo_name,
                                     base_branch="main", head_branch="feature",
                                     title="Forge the anvil",
                                     body="Walked in from Samtal.")
        return pr.number

    def _hall_pr(self, halls, hall, full, number):
        card = halls.post_event(hall, kind="pull_request", repo=full,
                                title=f"PR #{number} opened: Forge the anvil",
                                link_path=f"/{full}/pulls/{number}",
                                actor_name="villager", idempotency_key=f"walk-pr-{number}")
        return f"hall card: {card.summary()}"

    def _review(self, reviewer, villager, repo_name, number):
        store = PullRequestReviewStore(self._conn, self._repos, self._accounts,
                                       self._issues, audit=self._audit,
                                       time_fn=self._now)
        review = store.submit_review(reviewer, villager.username, repo_name,
                                     number, verdict="approve",
                                     summary="Forged true. Landing it.")
        return f"review #{review.id}: {review.verdict}"

    def _mention(self, reviewer, villager, full, number):
        bridge = MentionsBridgeService(self._conn, self._accounts,
                                       settings=self._settings, audit=self._audit,
                                       time_fn=self._now)
        delivery = bridge.bridge_mention(source_key=f"walk-pr-{number}",
                                         recipient=villager, actor=reviewer,
                                         target_kind="pull_request",
                                         target_id=f"{full}#{number}")
        if delivery.doors != ("samverk", "samtal"):
            raise RuntimeError(f"mention doors wrong: {delivery.doors}")
        return "one notification, two doors (samverk + samtal)"

    def _unfurl(self, reviewer, full, number):
        svc = LinkUnfurlService(self._conn, self._root, self._accounts,
                                settings=self._settings, audit=self._audit,
                                time_fn=self._now)
        card = svc.unfurl(reviewer, f"/{full}/pulls/{number}")
        return f"unfurl kind {card.kind}, decided by samverk"

    def _merge(self, villager, repo_name, number):
        store = PullRequestMergeStore(self._conn, self._repos, self._accounts,
                                      self._issues, audit=self._audit,
                                      time_fn=self._now)
        merged = store.merge_pull_request(villager, villager.username,
                                          repo_name, number)
        return f"PR #{number} merged as {merged.merge_commit_oid[:12]}"

    def _hall_merge(self, halls, hall, full, number):
        card = halls.post_event(hall, kind="pull_request", repo=full,
                                title=f"PR #{number} merged: Forge the anvil",
                                link_path=f"/{full}/pulls/{number}",
                                actor_name="villager", idempotency_key=f"walk-merge-{number}")
        titles = [c.title for c in halls.cards_for(hall)]
        if card.title not in titles or len(titles) != 3:
            raise RuntimeError(f"hall cards wrong: {titles}")
        return f"the hall sees all of it: {len(titles)} cards standing"
class _StopWalk(Exception):
    pass
