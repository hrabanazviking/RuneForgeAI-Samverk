"""Webhook events taxonomy (S-247).

The event store's verbs mapped to webhook payloads:
S-221's canonical store holds one event per witnessed
mutation, its verb drawn from the frozen audit taxonomy
(131 verbs stand: 33 auth / 85 repo / 13 admin), and
this slice states -- as data, documented per event in
docs/WEBHOOK_EVENTS.md -- which of those verbs a
webhook may carry, under what scope, and in what
payload. S-248 builds subscriptions against this
taxonomy, S-249 signs its payloads, S-250 delivers
them; none of them invents its own event vocabulary.

- **The webhook event name is the verb itself.**
  Samverk's payload shape is its own (the shape
  S-139 set for the issue outbox and S-221
  generalised): the payload's `event` field is the
  audit verb verbatim (`repo.issue.create`), its
  `action` the verb's final segment, and the rest
  of the envelope is S-221's `event_payload` shape
  unchanged -- delivery id (`evt-<event id>`,
  stable across redelivery so a receiver can
  dedupe), actor, target, repository, number,
  refs, the witness's safe detail carried
  unchanged, and the witnessed timestamp. This
  module builds payloads by delegating to
  `event_payload`, never by re-shaping, so the
  webhook face cannot drift from the store's.
- **Scope is the subscription's reach, stated per
  verb.** Every `repo.*` verb is repository scope
  (85 verbs): a repository hook subscribes to its
  own repository's events, and an organization
  hook to the events of the organization's
  repositories. The two `auth.organization.*`
  verbs are organization scope: an organization
  hook subscribes to them; no repository hook ever
  carries them. Routing a scoped event to the
  hooks entitled to it is S-248's delivery law;
  the scope stated here is the fact it routes by.
- **Withheld verbs are named, never silent.** The
  remaining 44 verbs are scope `none` and are
  never delivered: account and credential facts
  (signups, logins, tokens, keys, passwords,
  recovery, passkeys, follows -- the `auth.*`
  family outside the organization verbs) and
  instance administration facts (the whole
  `admin.*` family). A webhook is an exfiltration
  path by design (the taxonomy already watches
  `repo.webhook.add` for exactly that reason), so
  what it may carry is a closed list, and a
  person's credentials and an instance's
  administration are not on it. Asking this
  module for a withheld verb's payload is refused
  `webhook_event_not_deliverable`, in words.
- **Categories group the deliverable vocabulary**
  for subscribers choosing filters: repository,
  push, issues, pull_requests, labels, milestones,
  branches, checks, releases and webhooks inside
  repository scope; organization inside its own;
  account, following and administration among the
  withheld. A category is a reading aid over the
  same data, never a second vocabulary: the verb
  remains the event's name.
- **Detail fields are the taxonomy's own contract.**
  Each spec names the keys its verb's detail may
  carry, taken from docs/AUDIT_TAXONOMY.md's
  per-event contract (and, for the ten verbs the
  taxonomy states in its slice notes rather than
  its tables, from the emitting slices' own
  witness calls). The detail itself is the
  witness's safe specifics -- numbers, names,
  reasons; never titles, bodies, tokens or
  secrets (S-018's law rides unchanged).
- **Proven, not just claimed.**
  `audit_webhook_events` checks this taxonomy
  against the live code and the live document:
  every verb in `samverk.taxonomy.AUDIT_EVENTS`
  has exactly one spec and no spec names a verb
  outside it; every spec's scope obeys the scope
  law above; the payload fields stated here are
  the keys S-221's own serialiser emits; and
  docs/WEBHOOK_EVENTS.md names every verb. A
  taxonomy verb added without a webhook ruling,
  or a document that stops naming one, stops the
  audit being clean.
- **A pure read, like S-202, S-219 and S-237.**
  This module holds no store, writes no row and
  audits nothing: a taxonomy is a document the
  delivery slices build against, and reading it
  changes nothing. Synthetic test events are
  S-252's, not this slice's: every event here is
  a real store verb. No migration (schema 95
  stands), no new taxonomy event (131 stand).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .escaping import escape_html_text
from .event_store import CanonicalEvent, event_payload
from .taxonomy import AUDIT_EVENTS

__all__ = [
    "PAYLOAD_FIELDS", "SCOPES", "WEBHOOK_CATEGORIES",
    "WEBHOOK_EVENTS", "WebhookEventSpec",
    "WebhookEventsError", "WebhookTaxonomyAudit",
    "all_verbs", "audit_webhook_events",
    "deliverable_verbs", "get_webhook_event",
    "is_deliverable", "payload_json",
    "render_webhook_events_page", "verbs_for_category",
    "verbs_for_scope", "webhook_payload",
]

#: One webhook payload's fields, in envelope order:
#: exactly the keys S-221's `event_payload` emits
#: (pinned against that serialiser by the audit).
PAYLOAD_FIELDS = (
    "delivery_id", "event", "action", "actor",
    "target", "repository", "number", "refs",
    "detail", "occurred_at")

#: The scopes a verb may hold: the reach of the
#: hooks that may carry it, or `none` -- withheld.
SCOPES = ("repository", "organization", "none")

_SCOPE_WORDS = {
    "repository": "repository scope",
    "organization": "organization scope",
    "none": "never delivered",
}


class WebhookEventsError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class WebhookEventSpec:
    """One verb's webhook ruling: the verb itself
    (the webhook event name), its category, its
    scope, the detail keys its payload may carry
    (the taxonomy's per-event contract), and the
    plain-words summary the document states."""
    verb: str
    category: str
    scope: str
    detail_fields: tuple[str, ...]
    summary: str

    @property
    def event_name(self) -> str:
        return self.verb

    @property
    def action(self) -> str:
        return self.verb.rsplit(".", 1)[-1]

    @property
    def family(self) -> str:
        return self.verb.split(".", 1)[0]

    @property
    def deliverable(self) -> bool:
        return self.scope != "none"


WEBHOOK_EVENT_DATA: tuple[tuple[str, str, str, tuple[str, ...], str], ...] = (
    ('auth.signup.success', 'account', 'none', ('method',),
     'Account created'),
    ('auth.signup.denied', 'account', 'none', ('reason',),
     'Signup refused (throttle/policy)'),
    ('auth.login.success', 'account', 'none', ('method',),
     'Login succeeded'),
    ('auth.login.failure', 'account', 'none', ('attempted_user',),
     'Login failed'),
    ('auth.logout', 'account', 'none', (),
     'Session ended by its owner'),
    ('auth.password.change', 'account', 'none', (),
     'Password changed (sessions revoked)'),
    ('auth.password.reset', 'account', 'none', ('via',),
     'Password reset completed'),
    ('auth.token.create', 'account', 'none', ('token_id', 'scopes'),
     'API/access token created'),
    ('auth.token.revoke', 'account', 'none', ('token_id',),
     'Token revoked'),
    ('auth.ssh_key.add', 'account', 'none', ('fingerprint',),
     'SSH key registered'),
    ('auth.ssh_key.remove', 'account', 'none', ('fingerprint',),
     'SSH key removed'),
    ('auth.twofactor.enable', 'account', 'none', ('method',),
     '2FA enrolled'),
    ('auth.twofactor.disable', 'account', 'none', (),
     '2FA removed'),
    ('auth.twofactor.reset', 'account', 'none', (),
     '2FA reset via recovery'),
    ('auth.session.revoke', 'account', 'none', ('scope',),
     'A session (or all) revoked'),
    ('auth.email.verify', 'account', 'none', ('reason',),
     'Email verification token redeemed (S-026; outcome distinguishes success from denied)'),
    ('auth.profile.update', 'account', 'none', ('fields',),
     'Profile text or avatar changed (S-029)'),
    ('auth.recovery.generate', 'account', 'none', ('count', 'invalidated'),
     'Recovery code set generated; any old set invalidated (S-037)'),
    ('auth.recovery.use', 'account', 'none', (),
     'A recovery code was redeemed (S-037)'),
    ('auth.passkey.add', 'account', 'none', ('credential_id', 'format'),
     'Passkey enrolled (S-039)'),
    ('auth.passkey.remove', 'account', 'none', ('credential_id',),
     'Passkey removed by its owner (S-039)'),
    ('auth.passkey.login', 'account', 'none', ('credential_id',),
     'Passkey assertion verified — second factor or passwordless (S-039)'),
    ('auth.signin.notify', 'account', 'none', ('device',),
     'New-device sign-in notice fired (S-041)'),
    ('auth.username.change', 'account', 'none', ('from', 'to'),
     'Account renamed; old name tombstoned (S-042)'),
    ('auth.deletion.request', 'account', 'none', ('scheduled_at',),
     'Account deletion requested; grace begins (S-043)'),
    ('auth.deletion.cancel', 'account', 'none', (),
     'Pending deletion cancelled by its owner (S-043)'),
    ('auth.deletion.execute', 'account', 'none', ('username',),
     'Account irreversibly deleted after grace (S-043)'),
    ('auth.identity.link', 'account', 'none', ('provider',),
     'External identity linked (S-045)'),
    ('auth.identity.unlink', 'account', 'none', ('provider',),
     'External identity unlinked (S-045)'),
    ('repo.create', 'repository', 'repository', ('visibility',),
     'Repository created'),
    ('repo.delete', 'repository', 'repository', (),
     'Repository deleted'),
    ('repo.visibility.change', 'repository', 'repository', ('from', 'to'),
     'Visibility changed'),
    ('repo.transfer', 'repository', 'repository', ('from_owner', 'to_owner'),
     'Ownership transferred'),
    ('repo.push', 'push', 'repository', ('ref', 'old', 'new'),
     'Refs updated by a push'),
    ('repo.protection.change', 'repository', 'repository', ('branch', 'rule'),
     'Branch protection changed'),
    ('repo.collaborator.add', 'repository', 'repository', ('user', 'role'),
     'Collaborator added'),
    ('repo.collaborator.remove', 'repository', 'repository', ('user',),
     'Collaborator removed'),
    ('repo.collaborator.role_change', 'repository', 'repository', ('user', 'from', 'to'),
     'Collaborator role changed'),
    ('repo.release.publish', 'releases', 'repository', ('tag',),
     'Release published'),
    ('repo.webhook.add', 'webhooks', 'repository', ('host',),
     'Webhook added (an exfiltration path; watched)'),
    ('repo.webhook.remove', 'webhooks', 'repository', ('host',),
     'Webhook removed'),
    ('repo.settings.change', 'repository', 'repository', ('key', 'from', 'to'),
     'Security-relevant repo setting changed'),
    ('repo.fork', 'repository', 'repository', ('fork_of',),
     'Repository forked; upstream link recorded (S-055)'),
    ('repo.fetch', 'repository', 'repository', ('transport', 'service'),
     'Private repository content fetched/cloned/archived via a transport (S-094)'),
    ('repo.issue.create', 'issues', 'repository', ('number',),
     'Issue created in a repository (S-122)'),
    ('repo.issue.update', 'issues', 'repository', ('number', 'version'),
     'Issue title/body edited (S-122)'),
    ('repo.issue.comment', 'issues', 'repository', ('number', 'comment_id'),
     'Comment added to an issue (S-123)'),
    ('repo.issue.comment_edit', 'issues', 'repository', ('number', 'comment_id'),
     'Comment edited by its author; previous body kept in the visible edit history (S-123)'),
    ('repo.issue.comment_delete', 'issues', 'repository', ('number', 'comment_id'),
     'Comment deleted by its author or a repository admin; tombstone remains (S-123)'),
    ('repo.label.create', 'labels', 'repository', ('label',),
     'Label created in a repository (S-124)'),
    ('repo.label.update', 'labels', 'repository', ('label',),
     'Label renamed, recoloured, or redescribed (S-124)'),
    ('repo.label.delete', 'labels', 'repository', ('label',),
     'Label deleted; its issue assignments die with it (S-124)'),
    ('repo.issue.label_add', 'issues', 'repository', ('number', 'label'),
     'Label added to an issue (S-124)'),
    ('repo.issue.label_remove', 'issues', 'repository', ('number', 'label'),
     'Label removed from an issue (S-124)'),
    ('repo.milestone.create', 'milestones', 'repository', ('milestone',),
     'Milestone created in a repository (S-125)'),
    ('repo.milestone.update', 'milestones', 'repository', ('milestone',),
     'Milestone edited, closed, or reopened (S-125)'),
    ('repo.milestone.delete', 'milestones', 'repository', ('milestone',),
     'Milestone deleted; its issues are unassigned, never deleted (S-125)'),
    ('repo.issue.milestone', 'issues', 'repository', ('number', 'milestone'),
     "An issue's milestone set or cleared (S-125)"),
    ('repo.issue.assign', 'issues', 'repository', ('number', 'assignee'),
     'An account assigned to an issue (S-126)'),
    ('repo.issue.unassign', 'issues', 'repository', ('number', 'assignee'),
     'An account unassigned from an issue (S-126)'),
    ('repo.issue.reaction_add', 'issues', 'repository', ('number', 'reaction', 'comment_id'),
     'A reaction given to an issue or comment; only a real change is recorded (S-128)'),
    ('repo.issue.reaction_remove', 'issues', 'repository', ('number', 'reaction', 'comment_id'),
     'A reaction taken back by its giver (S-128)'),
    ('repo.issue_template.create', 'repository', 'repository', ('template', 'kind'),
     'An issue template (Markdown or YAML form) created in a repository (S-129)'),
    ('repo.issue_template.update', 'repository', 'repository', ('template', 'kind'),
     'An issue template edited or replaced (S-129)'),
    ('repo.issue_template.delete', 'repository', 'repository', ('template', 'kind'),
     'An issue template deleted (S-129)'),
    ('repo.issue.close', 'issues', 'repository', ('number', 'reason'),
     'An issue closed, with its reason (S-130)'),
    ('repo.issue.reopen', 'issues', 'repository', ('number',),
     'A closed issue reopened (S-130)'),
    ('repo.issue.lock', 'issues', 'repository', ('number', 'reason'),
     "An issue's conversation locked by a moderator, with its reason (S-132)"),
    ('repo.issue.unlock', 'issues', 'repository', ('number',),
     'A locked conversation unlocked by a moderator (S-132)'),
    ('repo.issue.pin', 'issues', 'repository', ('number',),
     'An issue pinned by a moderator (at most three per repository) (S-132)'),
    ('repo.issue.unpin', 'issues', 'repository', ('number',),
     'An issue unpinned by a moderator (S-132)'),
    ('repo.issue.transfer_out', 'issues', 'repository', ('number', 'to', 'to_number'),
     'An issue transferred out of this repository to another repository of the same owner (S-133)'),
    ('repo.issue.transfer_in', 'issues', 'repository', ('number', 'from', 'from_number'),
     'An issue transferred into this repository from another repository of the same owner (S-133)'),
    ('repo.issue.convert', 'issues', 'repository', ('number', 'to_number', 'branch'),
     'An issue converted to a draft pull request: a linked branch created from it (S-137)'),
    ('repo.pull_request.create', 'pull_requests', 'repository', ('number', 'base', 'head', 'draft', 'from_issue'),
     "A pull request created, claiming its shared number (S-137; Part VII's creation roads ride the same event)"),
    ('repo.pull_request.mark_ready', 'pull_requests', 'repository', ('number',),
     'A draft pull request marked ready for review by its author or a repository writer (S-143)'),
    ('repo.pull_request.convert_to_draft', 'pull_requests', 'repository', ('number',),
     'An open pull request converted back to a draft by its author or a repository writer (S-143)'),
    ('repo.pull_request.comment', 'pull_requests', 'repository', ('number', 'comment_id'),
     'Comment added to a pull request (S-144)'),
    ('repo.pull_request.comment_edit', 'pull_requests', 'repository', ('number', 'comment_id'),
     'A pull-request comment edited by its author; previous body kept in the visible edit history (S-144)'),
    ('repo.pull_request.comment_delete', 'pull_requests', 'repository', ('number', 'comment_id'),
     'A pull-request comment deleted by its author or a repository admin; tombstone remains (S-144)'),
    ('repo.pull_request.line_comment', 'pull_requests', 'repository', ('number', 'comment_id', 'file', 'side', 'line'),
     "A comment anchored to one line of a pull request's diff (S-146)"),
    ('repo.pull_request.line_comment_edit', 'pull_requests', 'repository', ('number', 'comment_id', 'file', 'side', 'line'),
     'A pull-request line comment edited by its author; previous body kept in the visible edit history (S-146)'),
    ('repo.pull_request.line_comment_delete', 'pull_requests', 'repository', ('number', 'comment_id', 'file', 'side', 'line'),
     'A pull-request line comment deleted by its author or a repository admin; tombstone remains (S-146)'),
    ('repo.pull_request.line_reply', 'pull_requests', 'repository', ('number', 'comment_id', 'reply_id'),
     "A reply added in a pull-request line comment's review thread (S-147)"),
    ('repo.pull_request.line_reply_edit', 'pull_requests', 'repository', ('number', 'comment_id', 'reply_id'),
     'A review-thread reply edited by its author; previous body kept in the visible edit history (S-147)'),
    ('repo.pull_request.line_reply_delete', 'pull_requests', 'repository', ('number', 'comment_id', 'reply_id'),
     'A review-thread reply deleted by its author or a repository admin; tombstone remains (S-147)'),
    ('repo.pull_request.thread_resolve', 'pull_requests', 'repository', ('number', 'comment_id'),
     "A review thread marked resolved by the comment's author, the pull request's author, or a repository writer (S-147)"),
    ('repo.pull_request.thread_unresolve', 'pull_requests', 'repository', ('number', 'comment_id'),
     "A resolved review thread marked unresolved again by the comment's author, the pull request's author, or a repository writer (S-147)"),
    ('repo.pull_request.review_submit', 'pull_requests', 'repository', ('number', 'review_id', 'verdict'),
     'A review submitted on a pull request with one verdict — approved, commented, or changes requested (S-148)'),
    ('repo.pull_request.suggestion_propose', 'pull_requests', 'repository', ('number', 'suggestion_id', 'file', 'start_line', 'end_line'),
     'A committable suggested change proposed on a pull request, anchored to a range of new-side lines in one file of its diff (S-150)'),
    ('repo.pull_request.suggestion_apply', 'pull_requests', 'repository', ('number', 'suggestion_ids', 'commit', 'count'),
     "One suggested change or a batch of them applied by the pull request's author (or an allowed maintainer) as exactly one signed-off commit on the head branch (S-150)"),
    ('repo.pull_request.codeowners_request', 'pull_requests', 'repository', ('number', 'owner_refs'),
     'Reviewers auto-requested on a pull request from the CODEOWNERS file on its base branch (S-151)'),
    ('repo.pull_request.review_request', 'pull_requests', 'repository', ('number', 'owner_refs'),
     'Reviewers manually requested on a pull request by its author or a base-repository writer (S-152)'),
    ('repo.pull_request.review_rerequest', 'pull_requests', 'repository', ('number', 'owner_refs'),
     'A dismissed review request re-requested on a pull request, reactivating its record (S-152)'),
    ('repo.pull_request.review_dismiss', 'pull_requests', 'repository', ('number', 'owner_refs'),
     'An active review request dismissed on a pull request; the record stays, stamped with who dismissed it and when (S-152)'),
    ('repo.pull_request.merge', 'pull_requests', 'repository', ('number', 'commit', 'base', 'head', 'closed'),
     "A pull request landed on its base branch as a merge commit — the message the pull request's title/body by default or as edited by the merger, the two parents, and the issues its closing keywords closed on landing (S-153)"),
    ('repo.pull_request.squash_merge', 'pull_requests', 'repository', ('number', 'strategy', 'commit', 'base', 'head', 'author', 'closed_numbers'),
     'A pull request squash-merged onto its base branch as one commit, its author preserved and its closing keywords executed on landing (S-154)'),
    ('repo.pull_request.rebase', 'pull_requests', 'repository', ('number', 'replayed', 'base_before', 'base_after'),
     'A pull request landed by rebase: its head commits replayed onto its base branch, the base ref moved to the replayed tip (S-155)'),
    ('repo.branch.delete_on_merge', 'branches', 'repository', ('number', 'branch', 'head_repo', 'oid', 'merge'),
     "Head branch deleted when its pull request merged, under the repository's delete_branch_on_merge opt-in; the deletion is tombstoned for restore (S-159)"),
    ('repo.branch.restore', 'branches', 'repository', ('branch', 'oid', 'deleted_branch_id'),
     'A deleted branch restored from its tombstone at the recorded head oid (S-159)'),
    ('repo.pull_request.revert', 'pull_requests', 'repository', ('number', 'revert_number', 'commit', 'branch', 'merged_commit'),
     'A merged pull request reverted by opening a revert pull request linked both ways to it (S-160)'),
    ('repo.issue.comment_hide', 'issues', 'repository', ('number', 'comment_id', 'reason'),
     'A comment hidden by a moderator, with its reason (S-138)'),
    ('repo.issue.comment_unhide', 'issues', 'repository', ('number', 'comment_id'),
     'A hidden comment restored by a moderator (S-138)'),
    ('repo.issue.comment_remove', 'issues', 'repository', ('number', 'comment_id', 'reason'),
     "A comment removed by a moderator (the S-123 tombstone, struck as a moderation act distinct from an author's own delete), with its reason (S-138)"),
    ('repo.watch', 'repository', 'repository', ('mode', 'previous'),
     'A watch set or its mode changed -- only a real change is recorded (S-222)'),
    ('repo.unwatch', 'repository', 'repository', ('previous',),
     'A watch removed entirely, any mode (S-222)'),
    ('repo.star', 'repository', 'repository', (),
     'A repository starred -- only a real change is recorded (S-222)'),
    ('repo.unstar', 'repository', 'repository', (),
     'A star taken back by its own giver (S-222)'),
    ('admin.user.create', 'administration', 'none', (),
     'Admin created a user'),
    ('admin.user.disable', 'administration', 'none', ('reason',),
     'User disabled'),
    ('admin.user.delete', 'administration', 'none', (),
     'User deleted'),
    ('admin.user.role_change', 'administration', 'none', ('from', 'to'),
     'Instance role changed'),
    ('admin.settings.change', 'administration', 'none', ('key', 'from', 'to'),
     'Instance setting changed'),
    ('admin.plaintext_http_override', 'administration', 'none', ('scope',),
     'Plaintext-HTTP override armed (S-015)'),
    ('admin.audit.ip_disclosure', 'administration', 'none', ('scope', 'enabled'),
     'Audit IP display enabled/disabled for a scope'),
    ('admin.audit.export', 'administration', 'none', ('scope', 'entries'),
     'Audit log exported'),
    ('admin.key.rotate', 'administration', 'none', ('key',),
     'Instance key rotated (S-020)'),
    ('admin.user.approve', 'administration', 'none', ('from_status',),
     'Operator approved a pending account (S-026, the no-SMTP road)'),
    ('admin.user.suspend', 'administration', 'none', ('reason',),
     'Admin suspended an account, with reason (S-044)'),
    ('admin.user.unsuspend', 'administration', 'none', ('reason',),
     'Admin lifted a suspension (S-044)'),
    ('admin.index.rebuild', 'administration', 'none', ('kinds', 'generations', 'jobs'),
     'Admin triggered a search-index rebuild for a repository (S-215)'),
    ('auth.organization.create', 'organization', 'organization', ('org',),
     'Organization created (S-185)'),
    ('auth.organization.update', 'organization', 'organization', ('fields',),
     'Organization profile, membership, team, permission or settings changed (S-185)'),
    ('auth.follow', 'following', 'none', ('followed',),
     'An account followed another account (S-232)'),
    ('auth.unfollow', 'following', 'none', ('followed',),
     'An account took its follow back (S-232)'),
    ('repo.protection.bypass', 'repository', 'repository', ('branch', 'patterns', 'rule_ids', 'bypass_entry', 'gate', 'actor'),
     'A branch-protection bypass was used by an actor it named (S-179)'),
    ('repo.push_protection.bypass', 'push', 'repository', ('repository', 'actor', 'role', 'role_source', 'reason', 'findings', 'refs'),
     'A push-protection refusal was bypassed by a permitted role with a stated reason; the bypass stands as an alert visible to owners (S-293)'),
    ('repo.pull_request.auto_merge_arm', 'pull_requests', 'repository', ('number', 'strategy', 'checks', 'head'),
     'Auto-merge armed on a pull request (S-158)'),
    ('repo.pull_request.auto_merge_cancel', 'pull_requests', 'repository', ('number',),
     'Auto-merge cancelled on a pull request (S-158)'),
    ('repo.pull_request.auto_merge_fire', 'pull_requests', 'repository', ('number', 'strategy', 'commit', 'error'),
     'Auto-merge fired on a pull request, merged or failed (S-158)'),
    ('repo.status.post', 'checks', 'repository', ('poster', 'credential', 'token_id', 'oid', 'context', 'state'),
     'A commit status posted through the API by a scoped poster (S-246)'),
    ('repo.check_run.post', 'checks', 'repository', ('poster', 'credential', 'token_id', 'oid', 'name', 'status', 'conclusion'),
     'A check run posted through the API by a scoped poster (S-246)'),
    ('repo.artifact.upload', 'checks', 'repository', ('poster', 'credential', 'token_id', 'oid', 'check_run', 'name', 'size', 'retention_days'),
     'A CI artifact uploaded through the API by a scoped poster (S-266)'),
    ('repo.artifact.delete', 'checks', 'repository', ('poster', 'credential', 'token_id', 'oid', 'check_run', 'name'),
     'A CI artifact deleted through the API by a scoped poster (S-266)'),
    ('repo.code_scanning.upload', 'checks', 'repository', ('poster', 'credential', 'token_id', 'oid', 'ref', 'runs', 'results'),
     'A SARIF document uploaded through the code-scanning API by a scoped poster (S-302)'),
)

WEBHOOK_EVENTS: tuple[WebhookEventSpec, ...] = tuple(
    WebhookEventSpec(
        verb=verb, category=category, scope=scope,
        detail_fields=detail_fields, summary=summary)
    for verb, category, scope, detail_fields, summary
    in WEBHOOK_EVENT_DATA)

_BY_VERB = {spec.verb: spec for spec in WEBHOOK_EVENTS}

#: Every category named by the data, in the order
#: the data first names it.
WEBHOOK_CATEGORIES: tuple[str, ...] = tuple(
    dict.fromkeys(spec.category for spec in WEBHOOK_EVENTS))


def all_verbs() -> tuple[str, ...]:
    """Every verb the taxonomy rules on, in
    document order."""
    return tuple(spec.verb for spec in WEBHOOK_EVENTS)


def get_webhook_event(verb: object) -> WebhookEventSpec:
    """One verb's webhook ruling. A verb the event
    store does not hold is refused
    `webhook_event_unknown` -- the taxonomy does
    not invent an event to answer with."""
    if isinstance(verb, str) and verb in _BY_VERB:
        return _BY_VERB[verb]
    raise WebhookEventsError(
        "webhook_event_unknown",
        "No such event-store verb is mapped.")


def is_deliverable(verb: object) -> bool:
    """Whether a webhook may carry this verb at
    all. An unknown verb is not deliverable."""
    return (isinstance(verb, str) and verb in _BY_VERB
            and _BY_VERB[verb].deliverable)


def deliverable_verbs(scope: str | None = None
                      ) -> tuple[str, ...]:
    """The verbs a webhook may carry, in document
    order -- all of them, or only one scope's."""
    if scope is not None:
        return tuple(
            spec.verb for spec in WEBHOOK_EVENTS
            if spec.deliverable and spec.scope == scope)
    return tuple(
        spec.verb for spec in WEBHOOK_EVENTS if spec.deliverable)


def verbs_for_scope(scope: object) -> tuple[str, ...]:
    """Every verb holding one scope (withheld verbs
    included, under `none`). An unknown scope is
    refused `webhook_scope_unknown`."""
    if scope not in SCOPES:
        raise WebhookEventsError(
            "webhook_scope_unknown", "No such webhook scope.")
    return tuple(
        spec.verb for spec in WEBHOOK_EVENTS if spec.scope == scope)


def verbs_for_category(category: object) -> tuple[str, ...]:
    """Every verb in one category. An unknown
    category is refused `webhook_category_unknown`."""
    if category not in WEBHOOK_CATEGORIES:
        raise WebhookEventsError(
            "webhook_category_unknown",
            "No such webhook category.")
    return tuple(
        spec.verb for spec in WEBHOOK_EVENTS
        if spec.category == category)


def webhook_payload(event: CanonicalEvent) -> dict:
    """One canonical event as a webhook payload:
    S-221's own shape, delegated to unchanged, so
    the webhook face cannot drift from the store's.
    A withheld verb is refused
    `webhook_event_not_deliverable`; a verb outside
    the taxonomy is `webhook_event_unknown`."""
    spec = get_webhook_event(event.verb)
    if not spec.deliverable:
        raise WebhookEventsError(
            "webhook_event_not_deliverable",
            "This event is never delivered as a webhook.")
    return event_payload(event)


def payload_json(event: CanonicalEvent) -> str:
    """The webhook payload as canonical JSON
    (sorted keys, tight separators) -- the bytes
    S-249's signing road will sign."""
    return json.dumps(webhook_payload(event), sort_keys=True,
                      separators=(",", ":"))


@dataclass(frozen=True)
class WebhookTaxonomyAudit:
    """The taxonomy checked against the live code
    and the live document: coverage of the frozen
    audit taxonomy, the scope law, the payload
    shape read from S-221's own serialiser, and
    per-event documentation. Ratified only when
    every check holds."""
    verbs_checked: int
    deliverable: int
    repository_scope: int
    organization_scope: int
    withheld: int
    problems: tuple[str, ...]

    @property
    def ratified(self) -> bool:
        return not self.problems


def _expected_scope(verb: str) -> str:
    if verb.startswith("repo."):
        return "repository"
    if verb.startswith("auth.organization."):
        return "organization"
    return "none"


def audit_webhook_events() -> WebhookTaxonomyAudit:
    """Check this taxonomy against the live code
    and document. Pure read: imports,
    introspection and one file read only."""
    problems: list[str] = []
    seen: set[str] = set()
    for spec in WEBHOOK_EVENTS:
        if spec.verb in seen:
            problems.append(f"duplicate:{spec.verb}")
        seen.add(spec.verb)
        if spec.scope not in SCOPES:
            problems.append(f"scope-value:{spec.verb}")
        elif spec.scope != _expected_scope(spec.verb):
            problems.append(f"scope:{spec.verb}")
        if not spec.summary:
            problems.append(f"summary:{spec.verb}")
        if not spec.category:
            problems.append(f"category:{spec.verb}")
        for key in spec.detail_fields:
            if not key.isidentifier():
                problems.append(f"detail:{spec.verb}:{key}")
    for verb in sorted(set(AUDIT_EVENTS) - seen):
        problems.append(f"missing:{verb}")
    for verb in sorted(seen - set(AUDIT_EVENTS)):
        problems.append(f"extra:{verb}")
    probe = CanonicalEvent(
        id=1, audit_seq=1, actor_kind="user", actor_id=1,
        actor="probe", verb="repo.issue.create",
        target_kind="repo", target_id="probe/probe#1",
        refs=("repo:probe/probe", "number:1"), detail={},
        outcome="success", created_at=0)
    if tuple(event_payload(probe).keys()) != PAYLOAD_FIELDS:
        problems.append("payload-fields")
    if tuple(webhook_payload(probe).keys()) != PAYLOAD_FIELDS:
        problems.append("webhook-payload-fields")
    doc_path = (Path(__file__).resolve().parent.parent
                / "docs" / "WEBHOOK_EVENTS.md")
    try:
        doc_text = doc_path.read_text(encoding="utf-8")
    except OSError:
        doc_text = ""
        problems.append("docs:missing")
    if doc_text:
        for spec in WEBHOOK_EVENTS:
            if f"`{spec.verb}`" not in doc_text:
                problems.append(f"docs:{spec.verb}")
    return WebhookTaxonomyAudit(
        verbs_checked=len(WEBHOOK_EVENTS),
        deliverable=len(deliverable_verbs()),
        repository_scope=len(verbs_for_scope("repository")),
        organization_scope=len(
            verbs_for_scope("organization")),
        withheld=len(verbs_for_scope("none")),
        problems=tuple(problems))


def render_webhook_events_page(
        audit: WebhookTaxonomyAudit | None = None) -> str:
    """The taxonomy, rendered where integrators
    find it: the payload envelope in plain words,
    the scope law, and every verb with its ruling,
    grouped by category. Every value escaped
    through S-010; scope and standing are said in
    words, never colour-only."""
    parts = [
        "<h1>Webhook events</h1>",
        "<p>Every webhook Samverk sends carries one "
        "event from the canonical event store "
        "(S-221). The event's name is its audit verb; "
        "its payload is Samverk's own shape: "
        + escape_html_text(", ".join(PAYLOAD_FIELDS))
        + ". The detail keys a payload may carry are "
        "the taxonomy's per-event contract, stated "
        "below and in docs/WEBHOOK_EVENTS.md. "
        "Subscriptions are S-248's, signing S-249's, "
        "delivery S-250's.</p>",
        "<p>Repository-scope events go to repository "
        "hooks and to the hooks of the organization "
        "that owns the repository. Organization-scope "
        "events go to organization hooks only. "
        "Account, credential and administration "
        "events are never delivered.</p>",
    ]
    for category in WEBHOOK_CATEGORIES:
        parts.append(
            f"<h2>{escape_html_text(category)}</h2>")
        parts.append("<ul>")
        for spec in WEBHOOK_EVENTS:
            if spec.category != category:
                continue
            detail = (
                ", ".join(spec.detail_fields)
                if spec.detail_fields else "no detail keys")
            parts.append(
                "<li>"
                f"<strong>{escape_html_text(spec.verb)}</strong> "
                f"({escape_html_text(_SCOPE_WORDS[spec.scope])}): "
                f"{escape_html_text(spec.summary)} "
                "Detail: "
                f"{escape_html_text(detail)}."
                "</li>")
        parts.append("</ul>")
    if audit is not None:
        if audit.ratified:
            parts.append(
                "<p>Checked, not just claimed: this "
                "taxonomy was compared with the live "
                f"code -- {audit.verbs_checked} verbs "
                "are ruled on, "
                f"{audit.deliverable} of them "
                "deliverable ("
                f"{audit.repository_scope} repository "
                "scope, "
                f"{audit.organization_scope} "
                "organization scope) and "
                f"{audit.withheld} withheld -- the "
                "payload shape matches S-221's own "
                "serialiser, and every verb is "
                "documented per event.</p>")
        else:
            problems = ", ".join(audit.problems)
            parts.append(
                "<p>Checked, and no longer exact: "
                "this taxonomy disagrees with the "
                "live code or its document -- "
                f"{escape_html_text(problems)} "
                "-- and that is a defect against "
                "S-247, to be fixed where it lies.</p>")
    parts.append(
        "<p>The same taxonomy lives in "
        "docs/WEBHOOK_EVENTS.md for a reader who "
        "never opens this page. The audit "
        "vocabulary behind every verb is "
        "docs/AUDIT_TAXONOMY.md.</p>")
    return "\n".join(parts)
