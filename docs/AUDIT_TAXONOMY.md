# Samverk Audit Event Taxonomy — v1

*Slice S-008. The frozen vocabulary of the audit log (study 35).
Enforced in code by `samverk/taxonomy.py`: `AuditLog.append` refuses
any name not in this document's set.*

## Rules

- Names are `family.subject.verb`, lowercase, dot-separated.
- **v1 names are never renamed or removed.** A name that stops being
  emitted is marked *(deprecated)* here and stays valid forever — old
  rows must remain interpretable for the life of the instance.
- Additions append new names (and are recorded in
  `PROJECT_MEMORY_MAP.md` when they land); they never change an
  existing name's meaning.
- Every event carries the standard fields of study 35 §2 (seq, ts,
  actor_kind, actor_id, target_kind, target_id, source_ip, outcome).
  The `detail` column holds only the safe specifics listed per event
  — never secrets, tokens, passwords, or request bodies (S-018).

## auth — authentication and credentials

| Event | Meaning | detail carries |
|---|---|---|
| `auth.signup.success` | Account created | `{"method": "invite"\|"open"}` |
| `auth.signup.denied` | Signup refused (throttle/policy) | `{"reason": ...}` |
| `auth.login.success` | Login succeeded | `{"method": "password"}` |
| `auth.login.failure` | Login failed | `{"attempted_user": ...}` (see study 35 §4 caveat) |
| `auth.logout` | Session ended by its owner | — |
| `auth.password.change` | Password changed (sessions revoked) | — |
| `auth.password.reset` | Password reset completed | `{"via": "email"\|"operator"}` |
| `auth.token.create` | API/access token created | `{"token_id": ..., "scopes": [...]}` — never the token |
| `auth.token.revoke` | Token revoked | `{"token_id": ...}` |
| `auth.ssh_key.add` | SSH key registered | `{"fingerprint": ...}` |
| `auth.ssh_key.remove` | SSH key removed | `{"fingerprint": ...}` |
| `auth.twofactor.enable` | 2FA enrolled | `{"method": "totp"\|"webauthn"}` |
| `auth.twofactor.disable` | 2FA removed | — |
| `auth.twofactor.reset` | 2FA reset via recovery | — |
| `auth.session.revoke` | A session (or all) revoked | `{"scope": "one"\|"all"}` |
| `auth.email.verify` | Email verification token redeemed (S-026; outcome distinguishes success from denied) | `{"reason": ...}` on denial only |
| `auth.profile.update` | Profile text or avatar changed (S-029) | `{"fields": "text"\|"avatar"}` |
| `auth.recovery.generate` | Recovery code set generated; any old set invalidated (S-037) | `{"count": ..., "invalidated": ...}` — never the codes |
| `auth.recovery.use` | A recovery code was redeemed (S-037) | — |
| `auth.passkey.add` | Passkey enrolled (S-039) | `{"credential_id": ..., "format": ...}` — the id is a public identifier, never key material beyond the stored public key |
| `auth.passkey.remove` | Passkey removed by its owner (S-039) | `{"credential_id": ...}` |
| `auth.passkey.login` | Passkey assertion verified — second factor or passwordless (S-039) | `{"credential_id": ...}` |
| `auth.signin.notify` | New-device sign-in notice fired (S-041) | `{"device": ...}` — the label only, never a fingerprint |
| `auth.username.change` | Account renamed; old name tombstoned (S-042) | `{"from": ..., "to": ...}` — usernames are public identifiers |
| `auth.deletion.request` | Account deletion requested; grace begins (S-043) | `{"scheduled_at": ...}` |
| `auth.deletion.cancel` | Pending deletion cancelled by its owner (S-043) | — |
| `auth.deletion.execute` | Account irreversibly deleted after grace (S-043) | `{"username": ...}` — the name only, no content |
| `auth.identity.link` | External identity linked (S-045) | `{"provider": ...}` — never the external secret, there is none stored beyond the public principal id |
| `auth.identity.unlink` | External identity unlinked (S-045) | `{"provider": ...}` |

## repo — repositories and their security surface

| Event | Meaning | detail carries |
|---|---|---|
| `repo.create` | Repository created | `{"visibility": ...}` |
| `repo.delete` | Repository deleted | — |
| `repo.visibility.change` | Visibility changed | `{"from": ..., "to": ...}` |
| `repo.transfer` | Ownership transferred | `{"from_owner": ..., "to_owner": ...}` |
| `repo.push` | Refs updated by a push | `{"ref": ..., "old": ..., "new": ...}` (oid prefixes) |
| `repo.protection.change` | Branch protection changed | `{"branch": ..., "rule": ...}` |
| `repo.collaborator.add` | Collaborator added | `{"user": ..., "role": ...}` |
| `repo.collaborator.remove` | Collaborator removed | `{"user": ...}` |
| `repo.collaborator.role_change` | Collaborator role changed | `{"user": ..., "from": ..., "to": ...}` |
| `repo.release.publish` | Release published | `{"tag": ...}` |
| `repo.webhook.add` | Webhook added (an exfiltration path; watched) | `{"host": ...}` — never the secret |
| `repo.webhook.remove` | Webhook removed | `{"host": ...}` |
| `repo.settings.change` | Security-relevant repo setting changed | `{"key": ..., "from": ..., "to": ...}` |
| `repo.fork` | Repository forked; upstream link recorded (S-055) | `{"fork_of": ...}` |
| `repo.fetch` | Private repository content fetched/cloned/archived via a transport (S-094) | `{"transport": ..., "service": ...}` — never pack or file contents; public reads are not recorded |
| `repo.issue.create` | Issue created in a repository (S-122) | `{"number": ...}` — never the title or body |
| `repo.issue.update` | Issue title/body edited (S-122) | `{"number": ..., "version": ...}` — never the title or body |
| `repo.issue.comment` | Comment added to an issue (S-123) | `{"number": ..., "comment_id": ...}` — never the body |
| `repo.issue.comment_edit` | Comment edited by its author; previous body kept in the visible edit history (S-123) | `{"number": ..., "comment_id": ...}` — never the body |
| `repo.issue.comment_delete` | Comment deleted by its author or a repository admin; tombstone remains (S-123) | `{"number": ..., "comment_id": ...}` — never the body |
| `repo.label.create` | Label created in a repository (S-124) | `{"label": ...}` — the name (text is the meaning, never colour alone) |
| `repo.label.update` | Label renamed, recoloured, or redescribed (S-124) | `{"label": ...}` |
| `repo.label.delete` | Label deleted; its issue assignments die with it (S-124) | `{"label": ...}` |
| `repo.issue.label_add` | Label added to an issue (S-124) | `{"number": ..., "label": ...}` |
| `repo.issue.label_remove` | Label removed from an issue (S-124) | `{"number": ..., "label": ...}` |
| `repo.milestone.create` | Milestone created in a repository (S-125) | `{"milestone": ...}` |
| `repo.milestone.update` | Milestone edited, closed, or reopened (S-125) | `{"milestone": ...}` |
| `repo.milestone.delete` | Milestone deleted; its issues are unassigned, never deleted (S-125) | `{"milestone": ...}` |
| `repo.issue.milestone` | An issue's milestone set or cleared (S-125) | `{"number": ..., "milestone": ...}` — milestone is null when cleared |
| `repo.issue.assign` | An account assigned to an issue (S-126) | `{"number": ..., "assignee": ...}` |
| `repo.issue.unassign` | An account unassigned from an issue (S-126) | `{"number": ..., "assignee": ...}` |
| `repo.issue.reaction_add` | A reaction given to an issue or comment; only a real change is recorded (S-128) | `{"number": ..., "reaction": ...}` — the reaction's stored name, plus `"comment_id"` when the target is a comment |
| `repo.issue.reaction_remove` | A reaction taken back by its giver (S-128) | `{"number": ..., "reaction": ...}`, plus `"comment_id"` when the target is a comment |
| `repo.issue_template.create` | An issue template (Markdown or YAML form) created in a repository (S-129) | `{"template": ..., "kind": ...}` |
| `repo.issue_template.update` | An issue template edited or replaced (S-129) | `{"template": ..., "kind": ...}` |
| `repo.issue_template.delete` | An issue template deleted (S-129) | `{"template": ..., "kind": ...}` |
| `repo.issue.close` | An issue closed, with its reason (S-130) | `{"number": ..., "reason": ...}` — `completed` or `not_planned` |
| `repo.issue.reopen` | A closed issue reopened (S-130) | `{"number": ...}` |
| `repo.issue.lock` | An issue's conversation locked by a moderator, with its reason (S-132) | `{"number": ..., "reason": ...}` — the lock vocabulary |
| `repo.issue.unlock` | A locked conversation unlocked by a moderator (S-132) | `{"number": ...}` |
| `repo.issue.pin` | An issue pinned by a moderator (at most three per repository) (S-132) | `{"number": ...}` |
| `repo.issue.unpin` | An issue unpinned by a moderator (S-132) | `{"number": ...}` |
| `repo.issue.transfer_out` | An issue transferred out of this repository to another repository of the same owner (S-133) | `{"number": ..., "to": ..., "to_number": ...}` |
| `repo.issue.transfer_in` | An issue transferred into this repository from another repository of the same owner (S-133) | `{"number": ..., "from": ..., "from_number": ...}` |
| `repo.issue.convert` | An issue converted to a draft pull request: a linked branch created from it (S-137) | `{"number": ..., "to_number": ..., "branch": ...}` |
| `repo.pull_request.create` | A pull request created, claiming its shared number (S-137; Part VII's creation roads ride the same event) | `{"number": ..., "base": ..., "head": ..., "draft": true}` plus `"from_issue"` when born from an issue |
| `repo.pull_request.mark_ready` | A draft pull request marked ready for review by its author or a repository writer (S-143) | `{"number": ...}` |
| `repo.pull_request.convert_to_draft` | An open pull request converted back to a draft by its author or a repository writer (S-143) | `{"number": ...}` |
| `repo.pull_request.comment` | Comment added to a pull request (S-144) | `{"number": ..., "comment_id": ...}` — never the body |
| `repo.pull_request.comment_edit` | A pull-request comment edited by its author; previous body kept in the visible edit history (S-144) | `{"number": ..., "comment_id": ...}` — never the body |
| `repo.pull_request.comment_delete` | A pull-request comment deleted by its author or a repository admin; tombstone remains (S-144) | `{"number": ..., "comment_id": ...}` — never the body |
| `repo.pull_request.line_comment` | A comment anchored to one line of a pull request's diff (S-146) | `{"number": ..., "comment_id": ..., "file": ..., "side": ..., "line": ...}` — never the body |
| `repo.pull_request.line_comment_edit` | A pull-request line comment edited by its author; previous body kept in the visible edit history (S-146) | `{"number": ..., "comment_id": ..., "file": ..., "side": ..., "line": ...}` — never the body |
| `repo.pull_request.line_comment_delete` | A pull-request line comment deleted by its author or a repository admin; tombstone remains (S-146) | `{"number": ..., "comment_id": ..., "file": ..., "side": ..., "line": ...}` — never the body |
| `repo.pull_request.line_reply` | A reply added in a pull-request line comment's review thread (S-147) | `{"number": ..., "comment_id": ..., "reply_id": ...}` — never the body |
| `repo.pull_request.line_reply_edit` | A review-thread reply edited by its author; previous body kept in the visible edit history (S-147) | `{"number": ..., "comment_id": ..., "reply_id": ...}` — never the body |
| `repo.pull_request.line_reply_delete` | A review-thread reply deleted by its author or a repository admin; tombstone remains (S-147) | `{"number": ..., "comment_id": ..., "reply_id": ...}` — never the body |
| `repo.pull_request.thread_resolve` | A review thread marked resolved by the comment's author, the pull request's author, or a repository writer (S-147) | `{"number": ..., "comment_id": ...}` |
| `repo.pull_request.thread_unresolve` | A resolved review thread marked unresolved again by the comment's author, the pull request's author, or a repository writer (S-147) | `{"number": ..., "comment_id": ...}` |
| `repo.pull_request.review_submit` | A review submitted on a pull request with one verdict — approved, commented, or changes requested (S-148) | `{"number": ..., "review_id": ..., "verdict": ...}` — never the summary |
| `repo.pull_request.suggestion_propose` | A committable suggested change proposed on a pull request, anchored to a range of new-side lines in one file of its diff (S-150) | `{"number": ..., "suggestion_id": ..., "file": ..., "start_line": ..., "end_line": ...}` — never the replacement |
| `repo.pull_request.suggestion_apply` | One suggested change or a batch of them applied by the pull request's author (or an allowed maintainer) as exactly one signed-off commit on the head branch (S-150) | `{"number": ..., "suggestion_ids": [...], "commit": ..., "count": ...}` |
| `repo.pull_request.codeowners_request` | Reviewers auto-requested on a pull request from the CODEOWNERS file on its base branch (S-151) | `{"number": ..., "owner_refs": [...]}` — never file contents |
| `repo.pull_request.review_request` | Reviewers manually requested on a pull request by its author or a base-repository writer (S-152) | `{"number": ..., "owner_refs": [...]}` — never bodies |
| `repo.pull_request.review_rerequest` | A dismissed review request re-requested on a pull request, reactivating its record (S-152) | `{"number": ..., "owner_refs": [...]}` — never bodies |
| `repo.pull_request.review_dismiss` | An active review request dismissed on a pull request; the record stays, stamped with who dismissed it and when (S-152) | `{"number": ..., "owner_refs": [...]}` — never bodies |
| `repo.pull_request.merge` | A pull request landed on its base branch as a merge commit — the message the pull request's title/body by default or as edited by the merger, the two parents, and the issues its closing keywords closed on landing (S-153) | `{"number": ..., "commit": ..., "base": ..., "head": ..., "closed": [...]}` — never the message |
| `repo.pull_request.squash_merge` | A pull request squash-merged onto its base branch as one commit, its author preserved and its closing keywords executed on landing (S-154) | `{"number": ..., "strategy": "squash", "commit": ..., "base": ..., "head": ..., "author": ..., "closed_numbers": [...]}` — never the message |
| `repo.pull_request.rebase` | A pull request landed by rebase: its head commits replayed onto its base branch, the base ref moved to the replayed tip (S-155) | `{"number": ..., "replayed": ..., "base_before": ..., "base_after": ...}` — never bodies |
| `repo.branch.delete_on_merge` | Head branch deleted when its pull request merged, under the repository's delete_branch_on_merge opt-in; the deletion is tombstoned for restore (S-159) | `{"number": ..., "branch": ..., "head_repo": ..., "oid": ..., "merge": ...}` — never bodies |
| `repo.branch.restore` | A deleted branch restored from its tombstone at the recorded head oid (S-159) | `{"branch": ..., "oid": ..., "deleted_branch_id": ...}` — never bodies |
| `repo.pull_request.revert` | A merged pull request reverted by opening a revert pull request linked both ways to it (S-160) | `{"number": ..., "revert_number": ..., "commit": ..., "branch": ..., "merged_commit": ...}` — never the title or body |
| `repo.issue.comment_hide` | A comment hidden by a moderator, with its reason (S-138) | `{"number": ..., "comment_id": ..., "reason": ...}` — never the body |
| `repo.issue.comment_unhide` | A hidden comment restored by a moderator (S-138) | `{"number": ..., "comment_id": ...}` |
| `repo.issue.comment_remove` | A comment removed by a moderator (the S-123 tombstone, struck as a moderation act distinct from an author's own delete), with its reason (S-138) | `{"number": ..., "comment_id": ..., "reason": ...}` — never the body |
| `repo.watch` | A watch set or its mode changed -- only a real change is recorded (S-222) | `{"mode": ..., "previous": ...}` -- the new mode (`all` / `releases_only` / `ignore`) and the mode it replaced, or null |
| `repo.unwatch` | A watch removed entirely, any mode (S-222) | `{"previous": ...}` -- the mode the removed row held |
| `repo.star` | A repository starred -- only a real change is recorded (S-222) | -- |
| `repo.unstar` | A star taken back by its own giver (S-222) | -- |

## admin — instance administration

| Event | Meaning | detail carries |
|---|---|---|
| `admin.user.create` | Admin created a user | — |
| `admin.user.disable` | User disabled | `{"reason": ...}` |
| `admin.user.delete` | User deleted | — |
| `admin.user.role_change` | Instance role changed | `{"from": ..., "to": ...}` |
| `admin.settings.change` | Instance setting changed | `{"key": ..., "from": ..., "to": ...}` |
| `admin.plaintext_http_override` | Plaintext-HTTP override armed (S-015) | `{"scope": ...}` |
| `admin.audit.ip_disclosure` | Audit IP display enabled/disabled for a scope | `{"scope": ..., "enabled": true\|false}` |
| `admin.audit.export` | Audit log exported | `{"scope": ..., "entries": ...}` |
| `admin.key.rotate` | Instance key rotated (S-020) | `{"key": ...}` — the key's name, never its value |
| `admin.user.approve` | Operator approved a pending account (S-026, the no-SMTP road) | `{"from_status": ...}` |
| `admin.user.suspend` | Admin suspended an account, with reason (S-044) | `{"reason": ...}` |
| `admin.user.unsuspend` | Admin lifted a suspension (S-044) | `{"reason": ...}` on the record, if given |
| `admin.index.rebuild` | Admin triggered a search-index rebuild for a repository (S-215) | `{"kinds": [...], "generations": [...], "jobs": [...]}` |

## Version note

Taxonomy v1, frozen 2026-10-29 with S-008. 37 events: 15 auth,
13 repo, 9 admin. The machine-readable set lives in
`samverk/taxonomy.py`; a battery test asserts this document and the
code name exactly the same set.

Additions (append-only, meanings of existing names unchanged):
S-026 (2026-10-30) added `auth.email.verify` and
`admin.user.approve` — 39 events: 16 auth, 13 repo, 10 admin.
S-029 (2026-10-30) added `auth.profile.update` — 40 events:
17 auth, 13 repo, 10 admin.
S-037 (2026-10-30) added `auth.recovery.generate` and
`auth.recovery.use` — 42 events: 19 auth, 13 repo, 10 admin.
S-039 (2026-10-30) added `auth.passkey.add`,
`auth.passkey.remove` and `auth.passkey.login` — 45 events:
22 auth, 13 repo, 10 admin.
S-041 (2026-10-30) added `auth.signin.notify` — 46 events:
23 auth, 13 repo, 10 admin.
S-042 (2026-10-30) added `auth.username.change` — 47 events:
24 auth, 13 repo, 10 admin.
S-043 (2026-10-30) added `auth.deletion.request`,
`auth.deletion.cancel` and `auth.deletion.execute`;
S-044 added `admin.user.suspend` and `admin.user.unsuspend`;
S-045 added `auth.identity.link` and `auth.identity.unlink`
— 54 events: 29 auth, 13 repo, 12 admin.
S-055 (2026-10-30) added `repo.fork` — 55 events.
S-094 (2026-10-30) added `repo.fetch` — 56 events:
29 auth, 15 repo, 12 admin.
S-122 (2026-10-30) added `repo.issue.create` and
`repo.issue.update` — 58 events: 29 auth, 17 repo, 12 admin.
S-123 (2026-10-30) added `repo.issue.comment`,
`repo.issue.comment_edit` and `repo.issue.comment_delete`
— 61 events: 29 auth, 20 repo, 12 admin.
S-124 (2026-10-30) added `repo.label.create`,
`repo.label.update`, `repo.label.delete`,
`repo.issue.label_add` and `repo.issue.label_remove`
— 66 events: 29 auth, 25 repo, 12 admin.
S-125 (2026-10-30) added `repo.milestone.create`,
`repo.milestone.update`, `repo.milestone.delete` and
`repo.issue.milestone` — 70 events: 29 auth, 29 repo,
12 admin.
S-126 (2026-10-30) added `repo.issue.assign` and
`repo.issue.unassign` — 72 events: 29 auth, 31 repo,
12 admin.
S-128 (2026-10-30) added `repo.issue.reaction_add` and
`repo.issue.reaction_remove` — 74 events: 29 auth,
33 repo, 12 admin. (S-127's cross-references are derived
data recomputed from already-audited prose, so they add
no event of their own.)
S-129 (2026-10-30) added `repo.issue_template.create`,
`repo.issue_template.update` and
`repo.issue_template.delete` — 77 events: 29 auth,
36 repo, 12 admin. (The blank-issue toggle rides the
frozen `repo.settings.change` with its key named, per
the S-066 settings pattern.)
S-130 (2026-10-30) added `repo.issue.close` and
`repo.issue.reopen` — 79 events: 29 auth, 38 repo,
12 admin. (S-131's timeline is derived data read from
already-audited records, so it adds no event of its own.)
S-132 (2026-10-30) added `repo.issue.lock`,
`repo.issue.unlock`, `repo.issue.pin` and
`repo.issue.unpin` — 83 events: 29 auth, 42 repo,
12 admin.
S-133 (2026-10-30) added `repo.issue.transfer_out`
and `repo.issue.transfer_in` — 85 events: 29 auth,
44 repo, 12 admin.
S-137 (2026-10-30) added `repo.issue.convert` and
`repo.pull_request.create` — 87 events: 29 auth,
46 repo, 12 admin.
S-138 (2026-10-30) added `repo.issue.comment_hide`,
`repo.issue.comment_unhide` and
`repo.issue.comment_remove` — 90 events: 29 auth,
49 repo, 12 admin.
S-143 (2026-10-30) added `repo.pull_request.mark_ready`
and `repo.pull_request.convert_to_draft` — 92 events:
29 auth, 51 repo, 12 admin.
S-144 (2026-10-30) added `repo.pull_request.comment`,
`repo.pull_request.comment_edit` and
`repo.pull_request.comment_delete` — 95 events:
29 auth, 54 repo, 12 admin.
S-146 (2026-10-30) added `repo.pull_request.line_comment`,
`repo.pull_request.line_comment_edit` and
`repo.pull_request.line_comment_delete` — 98 events:
29 auth, 57 repo, 12 admin.
S-147 (2026-10-30) added `repo.pull_request.line_reply`,
`repo.pull_request.line_reply_edit`,
`repo.pull_request.line_reply_delete`,
`repo.pull_request.thread_resolve` and
`repo.pull_request.thread_unresolve` — 103 events:
29 auth, 62 repo, 12 admin.
S-148 (2026-10-30) added `repo.pull_request.review_submit`
— 104 events: 29 auth, 63 repo, 12 admin.
S-150 (2026-10-31) added
`repo.pull_request.suggestion_propose` and
`repo.pull_request.suggestion_apply` — 106 events:
29 auth, 65 repo, 12 admin.
S-151 (2026-11-02) added
`repo.pull_request.codeowners_request` — 107 events:
29 auth, 66 repo, 12 admin.
S-152 (2026-11-02) added
`repo.pull_request.review_request`,
`repo.pull_request.review_rerequest` and
`repo.pull_request.review_dismiss` — 110 events:
29 auth, 69 repo, 12 admin.
S-153 (2026-11-06) added
`repo.pull_request.merge`, S-154 (2026-11-06)
added `repo.pull_request.squash_merge` and
S-155 (2026-11-06) added
`repo.pull_request.rebase` — 113 events:
29 auth, 72 repo, 12 admin.
S-158 (2026-11-06) added
`repo.pull_request.auto_merge_arm`,
`repo.pull_request.auto_merge_cancel` and
`repo.pull_request.auto_merge_fire` — 116 events:
29 auth, 75 repo, 12 admin.
S-159 (2026-11-06) added
`repo.branch.delete_on_merge` and
`repo.branch.restore` — 118 events:
29 auth, 77 repo, 12 admin. (The
delete_branch_on_merge toggle itself rides
the frozen `repo.settings.change` with its
key named, per the S-149 settings pattern;
the fork sync hint is a read and adds no
event of its own.)
S-160 (2026-11-06) added
`repo.pull_request.revert` — 119 events:
29 auth, 78 repo, 12 admin. (Claimed as
111 on the team branch; renumbered at
banking, and its migration went 60 → 63
for the same reason.)
S-165 (2026-11-06) added no event of its own —
119 events stand: 29 auth, 78 repo, 12 admin.
(Its review notifications are derived data
materialised from the already-audited review
acts — S-148's `repo.pull_request.review_submit`
and S-151/S-152's request family — on the
S-139 pattern, each notification carrying its
S-223 reason on its own row, migration 64.)
S-169 (2026-11-06) added no event of its own —
119 events stand: 29 auth, 78 repo, 12 admin.
(Its protection rule model writes under the
frozen `repo.protection.change` named above,
with detail {"branch": <pattern>, "rule":
"create"|"update"|"delete", "rule_id": ...},
migration 65.)
S-170 (2026-11-06) added no event of its own —
119 events stand: 29 auth, 78 repo, 12 admin.
(Its pull-request requirement is a pure read over
S-169 rules, enforced at S-089 protection stage;
refusals write nothing and audit nothing, and rule
changes ride the frozen repo.protection.change,
no migration.)
S-171 (2026-11-06) added no event of its own —
119 events stand: 29 auth, 78 repo, 12 admin.
(Its required-approvals gate is a pure read over
S-169 rules and S-164 review state; refusals write
nothing and audit nothing, and rule changes ride
the frozen repo.protection.change. Migration 66
adds the last-pusher approval toggle to
protection_rules.)
S-172 (2026-11-06) added no event of its own —
119 events stand: 29 auth, 78 repo, 12 admin.
(Its stale-review dismissal is a pure read over
S-169 rules and S-149 freshness; judgments write
nothing and audit nothing, and rule changes ride
the frozen repo.protection.change, no migration.)
S-173 (2026-11-06) added no event of its own —
119 events stand: 29 auth, 78 repo, 12 admin.
(Its code-owner gate is a pure read over
S-169 rules and S-164 review state; judgments write
nothing and audit nothing, and rule changes ride
the frozen repo.protection.change, no migration.)
S-174 (2026-11-06) added no event of its own —
119 events stand: 29 auth, 78 repo, 12 admin.
(Its required-status-checks gate is a pure read over
S-169 rules, S-157 check rows, and the counted
branch position; judgments write nothing and audit
nothing, and rule changes ride the frozen
repo.protection.change, no migration.)
S-175 (2026-11-06) added no event of its own —
119 events stand: 29 auth, 78 repo, 12 admin.
(Its signed-commits gate is a pure read over
S-169 rules and the signature headers of the
commits a push or merge carries; judgments write
nothing and audit nothing, and rule changes ride
the frozen repo.protection.change, no migration.)
S-176 (2026-11-06) added no event of its own —
119 events stand: 29 auth, 78 repo, 12 admin.
(Its linear-history gate is a pure read over
S-169 rules and the parent headers of the
commits a push or merge carries; judgments write
nothing and audit nothing, and rule changes ride
the frozen repo.protection.change, no migration.)
S-177 (2026-11-06) added no event of its own —
119 events stand: 29 auth, 78 repo, 12 admin.
(Its force-push and branch-deletion gate is a pure
read over S-169 rules and git ancestry; judgments
write nothing and audit nothing, and rule changes
ride the frozen repo.protection.change, no migration.)
S-178 (2026-11-06) added no event of its own —
119 events stand: 29 auth, 78 repo, 12 admin.
(Its push-actor gate is a pure read over
S-169 rules; judgments write nothing and audit
nothing, and rule changes ride the frozen
repo.protection.change, no migration.)
S-179 (2026-11-06) added
`repo.protection.bypass` — 120 events:
29 auth, 79 repo, 12 admin. (Its bypass gate is
the one audited road over S-169 rules: a named
bypasser's *use* of a bypass appends this event
with detail {"branch": ..., "patterns": [...],
"rule_ids": [...], "bypass_entry": ...,
"gate": ..., "actor": ...} before the bypass is
answered yes; the check itself is a pure read,
no other door exempts a bypass name, and a store
without an audit log refuses every use. No
migration — schema stays 66; the bypass list
already lives in migration 65.)
S-180 (2026-11-06) added no event of its own —
120 events stand: 29 auth, 79 repo, 12 admin.
(Its enforce-for-admins judgment is a pure read
over S-169 rules and S-054 roles, wired into
S-170's direct-push check in this slice;
judgments write nothing and audit nothing, and
rule changes ride the frozen
repo.protection.change, no migration.)
S-181 (2026-11-06) added no event of its own —
120 events stand: 29 auth, 79 repo, 12 admin.
(Its rulesets are instance policy stored by
migration 67 in protection_rulesets — schema
moves 66 to 67 — and ruleset changes ride the
frozen repo.protection.change with detail
{"ruleset": ..., "ruleset_id": ..., "name": ...,
"target": ...}; layered evaluation is a pure
read over S-169 rules and the rulesets, writes
nothing, and audits nothing.)
S-182 (2026-11-06) added no event of its own —
120 events stand: 29 auth, 79 repo, 12 admin.
(Its tag-protection judgment is a pure read
over S-181 rulesets targeting tags plus the
release-tag strongest default; judgments write
nothing and audit nothing, and ruleset changes
ride the frozen repo.protection.change, no
migration — schema stays 67.)
S-183 (2026-11-06) added no event of its own —
120 events stand: 29 auth, 79 repo, 12 admin.
(Its rule-insights page is a pure read over
this log: rows targeting a repository whose
outcome is denied or failure, explained in
plain words from the recorded action, reason
and detail; reads write nothing and audit
nothing, no migration — schema stays 67.)
S-185 (2026-11-07) added
`auth.organization.create` and
`auth.organization.update` — 122 events:
31 auth, 79 repo, 12 admin. (Creation of an
organization appends the create event with detail
{"org": ...}; profile and avatar changes append
the update event with detail {"fields": "text"}
or {"fields": "avatar"}. Organizations are stored
by migration 68 in organizations — schema moves
67 to 68.)
S-186 (2026-11-07) added no event of its own —
122 events stand: 31 auth, 79 repo, 12 admin.
(Its organization membership changes ride the
existing `auth.organization.update` event with
detail {"fields": "members", "action": "add" /
"remove" / "leave" / "role_change", "target": ...,
"role": ...}; membership is stored by migration
69 in organization_members — schema moves 68
to 69. Refused membership changes write nothing
and audit nothing, and the last-owner invariant
— the last owner cannot leave or be removed —
is enforced in samverk/organization_members.py.)
S-187 (2026-11-07) added no event of its own —
122 events stand: 31 auth, 79 repo, 12 admin.
(Its team changes ride the existing
`auth.organization.update` event with
detail {"fields": "teams", "action": "create" /
"update" / "add_member" / "remove_member" /
"link_repo" / "unlink_repo", "team": ...};
teams are stored by migration 70 in teams,
team_members and team_repositories — schema
moves 69 to 70. Refused team changes write
nothing and audit nothing, secret teams answer
the uniform team_not_found to non-members, and
the model is enforced in samverk/teams.py.)

S-188 (2026-11-07) added no event of its own —
122 events stand: 31 auth, 79 repo, 12 admin.
(Its nested-team changes ride the existing
`auth.organization.update` event with
detail {"fields": "teams", "action": "set_parent" /
"clear_parent", "team": ..., "parent": ...};
the parent is stored by migration 71 in
teams.parent_team_id — schema moves 70 to 71.
Refused parent changes and previews write nothing
and audit nothing, and the model is enforced in
samverk/team_nesting.py. This note was appended
by S-189's banking, which found it missing.)

S-189 (2026-11-07) added no event of its own —
122 events stand: 31 auth, 79 repo, 12 admin.
(Its team permission changes ride the existing
`auth.organization.update` event with
detail {"fields": "teams", "action":
"set_permission", "team": ..., "repo": ...,
"permission": ...}; the ladder — read / triage /
write / maintain / admin, applied per repo per
team — is stored by migration 72 in
team_repositories.permission — schema moves 71
to 72. Refused changes and same-role no-op sets
write nothing and audit nothing, and the ladder
is enforced in samverk/team_permissions.py.)

S-190 (2026-11-07) added no event of its own —
122 events stand: 31 auth, 79 repo, 12 admin.
(The permission resolution engine is a pure
read: it resolves one person's role in one
repository from ownership, site administration,
organization ownership, team grants with nesting
(S-187/S-188/S-189), caller-supplied collaborator
grants (stored grants land in S-191) and
visibility, in samverk/permission_engine.py.
It writes nothing and audits nothing, and
claims no migration — schema stays 72.
Organization membership alone grants no role
until S-192's default repository permission.)

S-191 (2026-11-07) added no event of its own —
122 events stand: 31 auth, 79 repo, 12 admin.
(Its outside collaborator changes ride the
long-standing `repo.collaborator.add`,
`repo.collaborator.remove` and
`repo.collaborator.role_change` events with the
detail shapes this document has always promised
for them ({"user": ..., "role": ...} on add,
{"user": ...} on remove, {"user": ..., "from":
..., "to": ...} on role change), targeted at the
repository; the grants — per-repo ladder roles
for non-members, listed in one auditable place
per repository and per owner, revocable in one
call — are stored by migration 73 in
outside_collaborators — schema moves 72 to 73.
Refused grants, changes and revocations write
nothing and audit nothing, a same-role set is a
no-op that audits nothing, and the model is
enforced in samverk/outside_collaborators.py.
S-190's permission engine reads the store when
no explicit collaborator role is passed.)

S-192 (2026-11-07) added no event of its own —
122 events stand: 31 auth, 79 repo, 12 admin.
(Its default-permission changes ride the existing
`auth.organization.update` event with detail
{"fields": "default_permission", "action":
"set_default", "from": ..., "to": ...}, targeted
at the organization; the default — one org-wide
base ladder role, or none, for members, settable
by an organization owner or a site admin, shown
in effect on S-190's matrix page with the source
Organization default — is stored by migration 74
in org_default_permissions — schema moves 73 to
74. Refused sets write nothing and audit nothing,
a same-value set is a no-op that audits nothing,
and the model is enforced in
samverk/default_permissions.py. S-190's permission
engine reads the stored default for plain members
of the owning organization.)

S-193 (2026-11-07) added no event of its own —
122 events stand: 31 auth, 79 repo, 12 admin.
(Its invitation acts ride the existing
`auth.organization.update` event: inviting and
rescinding write one event targeted at the
organization with detail {"fields": "invitations",
"action": "invite" / "rescind", "target": ...},
and acceptance writes two — one targeted at the
organization with detail {"fields": "invitations",
"action": "accept", "target": <invitee>} and one
targeted at the user with detail {"fields":
"invitations", "action": "accept", "org": <org>},
both acted by the accepting user; the invitations
— by username or email, expiring after seven
days, rescindable by an organization owner or a
site admin, their acceptance creating the
membership with the invited role — are stored by
migration 75 in org_invitations — schema moves 74
to 75. Refused invitations, rescinds and
acceptances write nothing and audit nothing, and
the model is enforced in samverk/invitations.py.)

S-194 (2026-11-07) added no event of its own —
122 events stand: 31 auth, 79 repo, 12 admin.
(Its member removal cascade is a pure preview in
samverk/member_removal_cascade.py:
CascadeStore.preview_removal computes — before
confirming, and writing and auditing nothing —
the whole effect of removing one member from one
organization: their role and the last-owner
refusal judged by S-186's decide_removal,
direct and S-188-inherited team memberships and
their teams' repository links, S-126 assignments,
S-151/S-152 review requests, S-148 submitted and
pending reviews, S-191 outside-collaborator
grants held in organization repositories, the
S-192 default permission floor, pending S-193
invitations they sent, the organization's and
their own repositories, and open authored work.
Removal itself stays S-186's act through the
existing membership doors. No migration — schema
stays 75. The preview raises only org_not_found
and no_such_user; a non-member and the last owner
are reported in the preview, never raised.)

S-195 (2026-11-07) added no event of its own —
122 events stand: 31 auth, 79 repo, 12 admin.
(Its team mentions — `@org/team` in issue and
pull request bodies and comments, and standing
`@org/team` review requests in the S-151/S-152
record — are materialised as addressed
notifications in samverk/team_mentions.py:
TeamMentionStore syncs each source whole, so the
record follows the text; a token notifies only
when the organization and team provably exist,
a secret team named in prose resolves only for
an author who may see it, and the recipients are
the team's S-188 effective members minus the
author and minus anyone who cannot read the
repository. Prose mentions store reason `mention`;
team review requests store `review-requested` —
the expansion S-165 expressly left to this slice,
its own store untouched. Storage is migration 76
in team_mention_notifications — schema moves 75
to 76. Syncs write no audit row; unknown
repositories and items raise the uniform
repo_not_found / issue_not_found.)

S-196 (2026-11-07) added no event of its own —
122 events stand: 31 auth, 79 repo, 12 admin.
(Its org repository creation policies — who may
create (owners / members / none; owners by
default) and the allowed visibilities (a
non-empty subset of public / private; both by
default), judged purely by decide_creation in
samverk/org_repositories.py — are set under the
existing auth.organization.update event with
detail fields=repositories, and repositories
created through the policy door audit the
existing repo.create event. The org repo list
filters by visibility and by a name/description
query, and the viewer list keeps only
repositories S-190's engine lets the viewer
read, so a private repository never appears,
not even as a count. Storage is migration 77
in org_repo_policies — schema moves 76 to 77.
Refusals and no-op policy sets write nothing
and audit nothing.)

S-198 (2026-11-07) added no event of its own —
122 events stand: 31 auth, 79 repo, 12 admin.
(Its org audit log is a pure read in
samverk/org_audit_log.py: OrgAuditLogStore
reads S-007's audit_log and returns, in
sequence order, the rows that belong to one
organization — rows targeted at the organization
itself, and rows targeted at a repository under
the organization's own first path segment, so
org `crew` never claims `crew2/repo`. Each row
is sorted purely by classify_event into
membership, permission, repository or
organization, and carried with a plain-words
summary from event_summary. Only an
organization owner or a site admin may read;
a plain member or a stranger is refused
not_org_owner, an unknown organization is
org_not_found, an unknown viewer is
no_such_user, and an unknown category filter
is category_invalid. No migration — schema
stays 77. Reading writes nothing and audits
nothing.)

S-199 (2026-11-07) added no event of its own --
122 events stand: 31 auth, 79 repo, 12 admin.
(Its org deletion acts ride the existing
`auth.organization.update` event with detail
{"fields": "danger", "action": "request_deletion" /
"cancel_deletion" / "execute_deletion"}, targeted
at the organization; the deletion -- owner-only,
under the sudo gate, with a typed confirmation,
an inventory shown first, and a seven-day grace
as S-043 -- is stored by migration 78 in
org_deletions -- schema moves 77 to 78. While
the organization still owns repositories a
request is refused repos_remaining: repositories
must be transferred or deleted explicitly first,
and a repository arriving during grace blocks
execution. Refused requests write nothing and
audit nothing, and the model is enforced in
samverk/org_deletion.py.)

S-200 (2026-11-07) added no event of its own --
122 events stand: 31 auth, 79 repo, 12 admin.
(Its role change guardrails refuse before any
event could be written: demoting or revoking the
last grant-admin of a repository -- the last
person holding admin through a collaborator
grant (S-191), a team grant (S-189 over S-188),
or the org default at admin (S-192) -- is refused
`last_admin` in samverk/role_change_guardrails.py,
judged by the pure decide_last_admin over the
holder sets before and after the change as it
would land, and wired into
OutsideCollaboratorStore.set_role / revoke and
TeamPermissionStore.set_permission. Intrinsic
admin -- the personal owner, org owners (already
guarded by S-186's last_owner), site admins -- is
not counted, because no role change can demote
it. Refusals write nothing and audit nothing,
successful changes keep riding their doors'
existing events, and no migration was needed --
schema stays 78.)

S-201 (2026-11-07) added no event of its own --
122 events stand: 31 auth, 79 repo, 12 admin.
(Its permission preview is a pure read with no
event at all, deliberately: a site admin views
the instance exactly as a chosen member sees it
by resolving that member in every repository
through S-190's engine, in
samverk/permission_preview.py. Only a site admin
may preview (not_site_admin otherwise; an org
owner is not enough), an unknown actor or target
is no_such_user, repositories the target holds
no role in are counted and never named, and the
preview writes nothing, grants nothing and
audits nothing -- an audit entry in the target's
name would be impersonation leakage. No
migration was needed -- schema stays 78.)

S-202 (2026-11-07) added no event of its own --
122 events stand: 31 auth, 79 repo, 12 admin.
(Its billing-shaped hole is honestly empty, in
samverk/billing_hole.py: Samverk is free
software (AGPL-3.0) on your own machines, so no
seat/billing concepts exist -- no seats, no
plans, no invoices, no charges -- and the
billing surface that organizations find in
their settings says exactly that, in plain
words, with the emptiness proven by an audit of
the live schema and of this taxonomy against
the forbidden billing terms. Every billing
act is refused `no_billing` before anything is
touched, and refusals write nothing and audit
nothing: an entry recording that there is no
billing would put a billing concept in this
vocabulary to say there is none. The why also
lives in docs/BILLING.md. No migration was
needed -- schema stays 78.)

S-203 (2026-11-07) added no event of its own --
122 events stand: 31 auth, 79 repo, 12 admin.
(Its instance-wide group acts ride the existing
`admin.settings.change` event -- the instance-
settings door the two-factor policy already uses:
creating, updating, adding and removing members,
linking and unlinking repositories, setting a
linked repository's ladder permission and setting
or clearing a parent each write one event targeted
at the instance with the group's slug as target and
detail {"fields": "instance_groups", "action": ...}
plus the act's own names (target username, repo
full name, role, parent slug); a permission set to
the rung already held is a no-op that audits
nothing, and refusals write nothing and audit
nothing. The groups -- site-level groups sharing
the team machinery of S-187/S-188/S-189, managed
by site admins alone, their membership and grants
asked by Part XVIII's admin policy through the
seam's three answers (is_effective_member,
effective_groups_for_user, group_role_for_user) --
are stored by migration 79 in instance_groups,
instance_group_members and
instance_group_repositories -- schema moves 78
to 79, and the model is enforced in
samverk/instance_groups.py.)

S-205 (2026-11-07) added no event of its own --
122 events stand: 31 auth, 79 repo, 12 admin.
(Its index architecture is derived bookkeeping
over acts already on the record -- the accepted
push's S-090 event and each mutation's own audit
-- so enqueueing, claiming, completing, failing
and rebuilding write no audit row, in
samverk/index_architecture.py: the closed catalog
of what is indexed (issues, pull requests,
commits, code), the pure trigger law (commits and
code on push, issues and pull requests on
mutation), the coverage law for code (size budget,
binary / oversized / submodule / ignored / empty
skipped for named reasons, LFS pointers indexed
as pointers), the coalescing background queue
with retry-to-dead, the per-(repository, kind)
state with its high-water mark, and rebuilds by
generation, where the served generation flips
only when a rebuild completes. The admin-facing,
audited rebuild door is S-215's, not this slice's.
Storage is migration 80's index_jobs, index_state
and index_documents -- schema moves 79 to 80.)

S-206 (2026-11-07) added no event of its own --
122 events stand: 31 auth, 79 repo, 12 admin.
(Its issue/PR search backend is a read over an
index derived from acts already on the record --
searching mutates nothing, and indexing writes
only derived data (the FTS rows and S-205's
document registry), rebuildable from the owning
tables at any time, in samverk/issue_pr_search.py:
the unified qualifier language of S-135/S-161
plus research 19's repo:, no:, created:/updated:,
sort: and negation, executed over SQLite FTS5
text plus structured fields, with unknown
qualifiers refused query_invalid. Permission
rides S-054's can_read resolved before any index
row is read; S-209 owns the leakage hardening.
Storage is migration 81's issue_pr_fts -- schema
moves 80 to 81.)

S-207 (2026-11-07) added no event of its own --
122 events stand: 31 auth, 79 repo, 12 admin.
(Its code indexing is derived data over the
push's own S-090 record -- indexing writes only
the FTS rows and S-205's document registry,
rebuildable from the bare repository at any
time, in samverk/code_indexing.py: on push, the
default branch's tip snapshot is diffed against
the previously indexed snapshot and exactly the
changed blobs are extracted, judged by S-205's
decide_code_disposition within the 1 MiB budget
(binary / oversized / submodule / ignored / empty
skipped for named reasons), and LFS pointers are
indexed as pointers -- their own text, target oid
and size recorded as what they are, the pointee's
bytes never fetched or indexed in their place.
Deletions leave the index in the same run, and a
rebuild replaces a repository's rows whole so it
converges with no stale rows. Querying the index
is S-208's slice; permission filtering is
S-209's. Storage is migration 82's code_fts --
schema moves 81 to 82.)

S-209 (2026-11-07) added no event of its own --
122 events stand: 31 auth, 79 repo, 12 admin.
(Its permission-filtered results are a read over
reads, in samverk/search_permissions.py: the one
global resolution, visible_repositories over
S-054's can_read, resolved before any index row
is read, to which the S-206 backend and S-208
code search now both delegate. Counts are tallied
from the filtered hits only -- the counted faces
search_counted on both executors, totals computed
before any result cap -- so an unreadable
repository contributes no title, no snippet, and
no count; a search scoped to it answers the
uniform repo_not_found, worded identically to a
repository that does not exist. The leakage
battery proves the equivalence: a stranger's hits
and counts over a world containing a planted
private repository equal the same search over a
world where it was never created. No migration
-- schema stays 82.)

S-210 (2026-11-07) added no event of its own --
122 events stand: 31 auth, 79 repo, 12 admin.
(Its repository search is a read over the
repository rows and S-066's topics, in
samverk/repository_search.py: free-text terms
matched case-insensitively as substrings
against name, description, topics, and owner,
composed by AND, with owner:, topic:, and
visibility: qualifiers (is: as the visibility
alias), -negation of one qualifier, and sort:
orderings; unknown qualifiers are refused
query_invalid, naming the qualifier. Permission
rides S-209's one resolution --
visible_repositories over S-054's can_read,
resolved before any topic is read, and topics
are loaded only for repositories that survive
it -- and the counted faces tally their totals
from the filtered hits only, before any result
cap, so an unreadable repository contributes
no name, no description, no topic, and no
count. The instance directory page is the same
law with an empty query. No migration --
schema stays 82.)

S-211 (2026-11-07) added no event of its own --
122 events stand: 31 auth, 79 repo, 12 admin.
(Its user and org search is a read over the
account, profile, and organization rows, in
samverk/user_org_search.py: free-text terms
matched case-insensitively as substrings
against the handle (username or organization
name), the display name, and the bio, composed
by AND, with type: kind qualifiers, -negation
of one type qualifier, and sort: orderings;
unknown qualifiers are refused query_invalid,
naming the qualifier. An email is never a
search field and never appears on a card.
Visibility is filtered before any profile fact
is read, the S-209 law applied to people:
organizations are public directory facts,
while a person contributes a card and a count
only while their account is active -- pending
and suspended accounts are visible in search
solely to the account holder and to site
admins, and the counted faces tally their
totals from the filtered subjects only, before
any result cap. Team rows are never read, so
secret teams cannot leak through a profile
card. The people directory page is the same
law with an empty query. No migration --
schema stays 82.)

S-213 (2026-11-08) added no event of its own --
122 events stand: 31 auth, 79 repo, 12 admin.
(Its global search UI, in samverk/global_search.py,
is a fan-out over the banked group executors --
S-210 repositories, S-211 people, S-212 commits,
S-208 code, S-206 issues and pull requests -- each
of which filters through S-209's one resolution
before reading anything private, and each group
keeps its own counted total; no combined count is
ever formed across groups. The one write is the
searcher's own recent searches (migration 83,
schema 82 to 83): a personal reading preference
in the S-136 pattern, which mutates no shared
record and so is not a witnessed act.)

S-214 (2026-11-08) added no event of its own --
122 events stand: 31 auth, 79 repo, 12 admin.
(Its saved searches, in samverk/saved_searches.py,
persist a user's own named global queries
(migration 84, schema 83 to 84) beyond S-136's
per-repo filters: any S-213 query saved under a
name and re-runnable. Saving is a personal reading
preference in the S-136 pattern, which mutates no
shared record and so is not a witnessed act; only
the query text is stored, never results, and
re-running executes live through S-213's
GlobalSearch, whose groups filter through S-209
before reading anything private, so a saved search
grants no access.)

S-215 (2026-11-08) added `admin.index.rebuild` --
123 events stand: 31 auth, 79 repo, 13 admin.
(Its index health, in samverk/index_health.py, is
Part X's operations door over S-205's architecture:
site admins only, every face checked before any
index row is read. A repository's health is S-205's
own four states and the queue snapshot, computed at
read time and stored nowhere; lag is the age of the
oldest waiting job -- per repository and for the
instance -- rendered on every page, including when
it is 0, and a kind that never ran says never, never
current. Each repository folds to its worst status
(failed, then stale, indexing, queued, never,
current), and the instance counts the fully current
and the behind by name. The rebuild trigger is
S-205's own request_rebuild behind the admin gate,
witnessed by the one new event (target the
repository; detail naming the kinds, the generation
each rebuild carries, and its jobs), and a store
without an audit log refuses audit_required before
anything is enqueued -- an unaudited rebuild must
not happen. Health reads audit nothing. No
migration -- schema stays 84.)

S-217 (2026-11-08) added no event of its own --
123 events stand: 31 auth, 79 repo, 13 admin.
(Its performance budget, in samverk/search_budgets.py,
measures S-208's permission-filtered code search
over a reference corpus defined in code -- six
mirror-shaped repositories, 300 files, 9,000 lines,
with a common needle in every file and a rare
needle in exactly one. Budgets are stated per
hardware class (S-073's classes) as p95 latencies
and judged by the pure judge law over real timed
samples; a report marks every class it did not
measure as unmeasured, and the Pi-class budget
stays NOT PROVEN until S-395 re-measures it there
and S-413 restates it. Measuring a read is a read
and audits nothing. No migration -- schema
stays 84.)

S-219 (2026-11-08) added no event of its own --
123 events stand: 31 auth, 79 repo, 13 admin.
(Its honest limits document, in
samverk/search_limits.py and docs/SEARCH_LIMITS.md,
states what Samverk search does NOT do: no meaning
search, no relevance ranking, regex cost caps that
are caps on size and never on time (no timeout
exists in S-208's executor), the pattern / result /
snippet caps, the index coverage and freshness
edges, the language census limits, the global and
API caps, S-212's 5000-commit scan cap, and the
per-hardware-class budgets with Pi-class NOT
PROVEN. The limits are data, rendered on a page
the global search page links to, and an audit
compares the documented caps with the live
engines' own constants and hit shapes on every
run. A document about reads is a read: it writes
nothing and audits nothing. No migration -- schema
stays 84.)

S-221 (2026-11-08) added no event of its own --
123 events stand: 31 auth, 79 repo, 13 admin.
(Its event store completion, in
samverk/event_store.py, is Part XI's canonical
store: one record per witnessed mutation -- actor
(kind, id, and the account's name resolved at read
time), verb (the audit action itself), target
(kind and id, carried unchanged), refs (derived
purely: `repo:<owner>/<name>`, `number:<n>`, and a
push's moved refs by name), the safe detail and
outcome carried unchanged, and the witness's own
timestamp. Every mutation in Parts III-X already
writes exactly one row in S-007's log, so the
store materialises those rows -- one canonical
event per audit seq under a UNIQUE constraint,
inserted with OR IGNORE -- which makes syncing
exactly-once, keeps refused and rolled-back
mutations (never witnessed) out entirely, and
turns any unaudited mutation into a visible gap
between the two records. S-090's push store and
S-139's issue outbox remain the family stores;
this is the one canonical store over all of them.
Reads sync first, so an answer is never stale,
and respect permission by construction: a
repository's events ride S-054's read gate (a
stranger to a private repository gets the uniform
repo_not_found, and its events are invisible in
the actor and public faces too), an actor feed
filters event by event, non-repository events are
visible only to the actor themself and site
admins (organization events excepted, as public
directory facts), and the public feed carries
only public repositories. Materialising is a read
of the witness and audits nothing. One migration
-- schema 84 to 85, the `events` table.)

S-222 (2026-11-08) added `repo.watch`,
`repo.unwatch`, `repo.star` and `repo.unstar` --
127 events stand: 31 auth, 83 repo, 13 admin.
(Its watch and star, in samverk/watch_star.py,
wires S-119: a watch is a stored row with a mode
-- `all`, `releases_only`, or `ignore`, the last
an explicit opt-out that is stored but never
counted as watching -- and a star is a stored
row, a bookmark and a public signal in one. The
counts the repository header shows are counted
live from those rows at read time, never cached
and never faked, and the store's counters feed
the header's seam unchanged. Only real changes
are witnessed: re-setting the held mode,
re-starring, un-starring what was never starred
and clearing no watch are quiet no-ops, so
S-221's canonical store sees exactly the real
mutations. Watching and starring are reader
acts under S-054: a stranger to a private
repository gets the uniform repo_not_found for
reads and writes alike, a refusal stores nothing
and emits nothing, and mutations need a
signed-in account. One migration -- schema 85
to 86, the `repo_watches` and `repo_stars`
tables.)

S-223 (2026-11-08) added no event of its own --
127 events stand: 31 auth, 83 repo, 13 admin.
(Its notification reasons, in
samverk/notification_reasons.py, are Part XI's
canonical reason vocabulary: exactly seven
reasons -- `mention`, `assign`,
`review-requested`, `author`, `comment`,
`state-change`, `subscribed` -- each stored on
its notification row at creation and shown, in
plain words, with every notification wherever it
is rendered. `validate_reason` is the only door:
anything outside the seven (S-165's
family-internal `review-dismissed` included) is
refused with `reason_invalid` naming the honest
set, and a refusal stores nothing. The store is
the general notification record the family
stores feed: S-165's review store already stores
`review-requested` and `author` on its own rows
in this slice's words, and S-224's inbox and
S-228's per-reason preferences read this
vocabulary. An inbox belongs to its recipient --
listing, counting and marking read take the
recipient themself, and marking read is
owner-scoped in the query itself. Creating a
notification is the delivery of a mutation
already witnessed under its own verb, so --
like S-165's store and S-221's store -- it
records no verb of its own and audits nothing.
One migration -- schema 86 to 87, the
`notifications` table.)

S-224 (2026-11-08) added no event of its own --
127 events stand: 31 auth, 83 repo, 13 admin.
(Its inbox, in samverk/inbox.py, is Part XI's
working surface over S-223's store: the
recipient's own list, newest first, filtered by
one reason -- judged through S-223's
`validate_reason`, an unknown reason refused
`reason_invalid` -- and by one repository, the
`owner/name` derived purely from the stored
target (`detail["repo"]` when the delivery
recorded one, else the target id's first two
segments), a filter naming anything else refused
`repo_invalid`. Done and saved are distinct
states on one `inbox_triage` row per
notification: done is the only exit and moves
S-223's `read_at` with it, reopening restores
the row unread as it was, and saved is an
orthogonal flag that never touches read or
done. Keyboard triage is a frozen registry in
S-111's shape whose transitions are the pure
`apply_triage`, and the empty state teaches the
whole model in one screen -- the seven reasons,
the two filters, done versus saved, and the
triage keys -- rendered from the lessons, the
vocabulary, and the registry themselves. Triage
is a personal reading state, like S-214's saved
searches: it mutates no shared record, so it is
not a witnessed act and audits nothing. One
migration -- schema 87 to 88, the `inbox_triage`
table.)
S-225 (2026-11-08) added no event of its own --
127 events stand: 31 auth, 83 repo, 13 admin.
(Its thread subscriptions, in
samverk/thread_subscriptions.py, are Part XI's
per-thread layer over S-222's repository watch:
one stored override per (account, repository,
thread kind, thread number) -- `subscribed` or
`muted` -- with the absence of a row as the
third standing, inherit. A thread is named
whole: the repository as `owner/name`, a kind
from S-121's shared numbering (`issue` or
`pull_request`, judged at the door with
`thread_kind_invalid`), and a positive number
(`thread_number_invalid`); existence is read
through S-121's `IssueStore.resolve_number`, so
a number naming no thread, or a thread of the
other kind, answers the uniform
`thread_not_found` -- the same answer a missing
repository and a repository the caller cannot
read under S-054 give, and a refusal stores
nothing. The pure `decide_notify` is the whole
override law: muted beats repository watch
`all`; subscribed beats `ignore`,
`releases_only`, and no watch at all, and
notifies under S-223's reason `subscribed`;
with no override the repository watch decides
as S-222 left it, and only `all` notifies
thread activity. The override is honest and
visible: every view carries the stored
override, the repository watch underneath it,
the effective decision, and the explanation
said in plain words by the pure
`explain_effective` -- an override that agrees
with the watch is said to confirm it, never to
override it -- and the renderers say the
explanation outright through S-010. A
subscription belongs to its holder: every face
is owner-scoped in the query itself, and an
anonymous caller is refused
`authentication_required`, S-223/S-224's name.
A thread subscription is a personal
notification state, like S-224's inbox triage:
it mutates no shared record, so it is not a
witnessed act and audits nothing. One
migration -- schema 88 to 89, the
`thread_overrides` table.)

S-226 (2026-11-08) added no event of its own --
127 events stand: 31 auth, 83 repo, 13 admin.
(Its mention routing, in
samverk/mention_routing.py, is Part XI's router:
`@user` and `@org/team` mentions in primary prose
-- an issue or pull request body, or one live
comment -- create S-223 notifications under the
reason `mention`, exactly once per (source,
recipient). However many paths in one source
reach the same person -- named directly, reached
through one mentioned team, reached through two
-- they receive one notification, its delivery
ledger row recording every path in its `via`;
re-syncing a source keeps standing deliveries
and their read state, an edit that removes a
mention withdraws its delivery whole, and a
tombstoned comment's mentions die with its body.
Cross-reference echoes never notify: only
primary prose is a source, S-127's
cross-reference record and the back-references
derived from it are never read by the router, so
an echo can neither create nor duplicate a
delivery, and routing the target thread of a
mentioning text creates nothing there. Only
proven mentions route -- the account must exist,
the team must resolve through S-195's own
resolution (secret-team visibility included),
the recipient must be able to read the
repository under S-054, the author is never
notified of their own act, code spans and fences
never parse, and a recipient who muted the
thread under S-225 receives no delivery until
the mute is cleared and the source re-syncs.
Routing is the delivery of acts already
witnessed under their own verbs -- the prose's
creation and edits, judged exactly as S-195's
and S-223's stores judged theirs -- so it is not
a witnessed act and audits nothing. One
migration -- schema 89 to 90, the
`mention_deliveries` table.)

S-227 (2026-11-08) added no event of its own --
127 events stand: 31 auth, 83 repo, 13 admin.
(Its email notifications, in
samverk/email_notifications.py, are Part XI's
second door: S-223 notifications also leave the
instance as email via the instance SMTP when it
is configured -- per-event or queued and sent as
one digest per recipient on flush -- and never
at all when SMTP is absent, the delivery decision
recorded honestly as skipped while the in-app
inbox works exactly as before. The SMTP is named
whole by an SmtpConfig judged by the pure
smtp_config_from: absent settings mean no SMTP,
a half-named SMTP is refused fail-closed, and the
transport is a mailer seam in S-026's shape with
smtp_mailer building the real smtplib transport.
The pure decide_email is the whole law -- SMTP
absent, no address on the account, or an
unsubscribe covering the reason each skip with
their ground stored on the row -- and migration
91's email_deliveries is UNIQUE on the
notification, so a notification is emailed
exactly once and a transport failure is recorded
as failed, never raised into the mutation that
created the in-app notification. Every letter
carries signed unsubscribe links: HMAC-SHA256
tokens over user and scope (`all`, or one of
S-223's seven reasons) under the instance signing
key, redeemed generically -- one refusal for
forged, tampered and shapeless tokens alike --
into migration 91's email_optouts, consulted at
decision time and again at digest-flush time, so
an unsubscribe recorded after queueing still
stops that mail. Delivering a notification is
the delivery of a mutation already witnessed
under its own verb, and an opt-out is a personal
notification state like S-224's triage and
S-225's overrides, so neither is a witnessed act
and the audit log does not move. One migration
-- schema 90 to 91, the email_deliveries and
email_optouts tables.)

S-228 (2026-11-08) added no event of its own --
127 events stand: 31 auth, 83 repo, 13 admin.
(Its notification preferences, in
samverk/notification_preferences.py, are Part
XI's one findable page: email on or off for
each of S-223's seven reasons, the digest
cadence, and every watched repository managed
in one list, the three sections named in order
by PREFERENCE_SECTIONS and rendered from one
aggregated view. The page writes no second
record of anything: email on/off is migration
91's email_optouts itself -- the record S-227's
signed unsubscribe links write and its delivery
law consults -- with S-227's `all` scope carried
as the master choice above the seven per-reason
choices, the pure decide_email_enabled composing
the two honestly (a reason held off by the
master switch says so, and flipping one reason
never lifts the master); watched repositories
are migration 86's repo_watches, listed live in
name order with every stored mode, `ignore`
included as a managed choice, filtered through
S-054's can_read so an unreadable repository is
never named, and changed only through S-222's
own store, so its repo.watch / repo.unwatch
verbs remain the only witness. The one new
record is the digest cadence -- immediate,
daily, or weekly, judged at the door, no row
meaning the immediate default -- in migration
92's notification_preferences, composed with
the email standing by the pure decide_user_email
into the per-person delivery law (skip, send
now, or queue for the named digest); S-227's
store keeps its instance law. A preference is
a personal notification state like S-224's
triage, S-225's overrides and S-227's opt-outs,
so it is not a witnessed act and the audit log
does not move for it. One migration -- schema
91 to 92, the notification_preferences table.)

S-229 (2026-11-08) added no event of its own --
127 events stand: 31 auth, 83 repo, 13 admin.
(Its activity feeds, in
samverk/activity_feeds.py, are Part XI's three
read faces over S-221's canonical event store:
a person's feed (their own actions), a
repository's feed, and the instance's
public-activity feed. Every read syncs through
S-221's EventStore first, so a feed is never
stale, and every repository event is filtered
through S-190's PermissionEngine -- the one
function that also speaks S-197's internal
visibility, team grants, and collaborator
grants -- so S-209's law holds by construction:
a feed never reveals an action on a repository
the reader cannot read, in rows, targets, or
counts, and an unreadable repository's feed
answers the uniform repo_not_found. The public
feed is judged by visibility alone: it carries
an event exactly when its repository is public,
so private and internal actions never appear
there -- not even for site administrators, who
receive the same public-only feed as an
anonymous visitor -- and its page says so in
plain words. Non-repository events follow
S-221's standing law (organisation events are
public directory facts; the rest are their
actor's and site administrators'). No
migration -- schema 92 stands; a feed is a
read model over the witness, not a witnessed
act, so the audit log does not move for it.)

S-230 (2026-11-08) added no event of its own --
127 events stand: 31 auth, 83 repo, 13 admin.
(Its profile activity, in
samverk/profile_activity.py, is the profile face
of S-229's feeds: a read model over S-221's
canonical event store, gathered through S-229's
own store. A profile is a public surface, so
visibility is judged by the resource, never by
who is asking: an action appears exactly when it
is genuinely public -- it names a public
repository (S-229's in_public_feed judgement), or
it is an organisation event, a public directory
fact. Actions in private and internal
repositories never appear, not even for the
subject themself or a site administrator, and the
page says so in plain words. No migration --
schema 92 stands; a profile is a read model over
the witness, not a witnessed act, so the audit
log does not move for it.)

S-231 (2026-11-08) added no event of its own --
127 events stand: 31 auth, 83 repo, 13 admin.
(Its events API, in
samverk/events_api.py, is the feed as a Part XII
resource: S-229's three feeds and S-221's single
event answered as JSON-safe data, in the shape
S-216 set for API faces. The API owns no
visibility law of its own -- it builds S-229's
feed store and judges every event through that
store's own per-event filter (S-190's engine over
S-209's law), so permission filtering is
identical by construction: an unreadable
repository contributes no row, no target, and no
count, the repository face answers the uniform
repo_not_found, and the public face is public
repositories only for every reader, site
administrators included. Each feed payload
carries the filtered total tallied before the
cap, the returned count, and a complete flag --
there is deliberately no paging cursor, which is
S-239's work -- and refusals carry the stores'
own reasons verbatim (no_such_user,
repo_not_found, event_not_found) beside the
contract's limit_invalid and filter_invalid,
rendered by error_to_dict in this contract's
shape, not S-240's future unified problem
format. No migration -- schema 92 stands; an API
read is a read model over the witness, not a
witnessed act, so the audit log does not move
for it.)

S-232 (2026-11-08) added two events of its own --
129 events stand: 33 auth, 83 repo, 13 admin.
(`auth.follow` and `auth.unfollow`, append-only in
the AUTH family beside the other account acts.)
(Its following, in samverk/following.py, is
Part XI's people layer over S-222's stored-act
law: a follow is one stored row per (follower,
followed) pair (migration 93's user_follows;
schema 92 to 93), counts are counted live from
those rows, and only real changes are witnessed
-- re-following a held follow and unfollowing a
non-follow are quiet no-ops, exactly as
watch/star judge their retries. Follower and
following lists are public profile facts in the
order the follows began. The following feed is
a read model over S-221's canonical event
store, gathered through S-229's feed store and
judged event by event through S-230's
is_profile_public -- reused, never re-derived --
so it carries a followed person's actions
exactly when they are genuinely public:
actions in private and internal repositories
never appear, for anyone. Its order is the
witness's own, newest first: there is no
algorithmic ranking, no score, and nothing
reorders chronological truth.)

S-233 (2026-11-08) added no event of its own --
129 events stand: 33 auth, 83 repo, 13 admin.
(Its star lists, in samverk/star_lists.py, are
a read model over S-222's repo_stars rows and
S-050's repository record: browsing a list is
not a witnessed act, so the audit log does not
move for it -- the star itself was witnessed
by `repo.star` when it was made, and its
removal by `repo.unstar`. No migration --
schema 93 stands. Each entry is judged
through S-054's can_read before any fact
about it is read, so a star on a private
repository is as invisible as the repository
itself: filtered rows contribute no entry, no
name, and no count, and the list's total is
the visible total, never the stored one.
Every page and every entry labels the star a
public signal in plain words: anyone who can
read a repository can see who starred it.)

S-234 (2026-11-08) added no event of its own --
129 events stand: 33 auth, 83 repo, 13 admin.
(Its push feed for owners, in
samverk/push_feed.py, is a read model over
S-090's push_events rows, gathered by repository
ownership at read time: a push surfaces in a
person's feed exactly when it landed on a
repository that person owns, whoever pushed it,
and pushes to other people's repositories are
never gathered, in rows or in counts. Reading
the feed is not a witnessed act, so the audit
log does not move for it -- the push itself was
witnessed by `repo.push` when it landed. No
migration -- schema 93 stands. Each moved ref is
summarised live from the repository itself: its
kind, the true commit count of its range, and
up to five commit subjects with the remainder
counted; a range whose commits cannot be read
surfaces with its summary marked unavailable in
words, never with an invented count. The feed is
personal and signed-in only, because it gathers
pushes to private repositories too.)

S-237 (2026-11-09) added no event of its own --
129 events stand: 33 auth, 83 repo, 13 admin.
(Its API contract document, in
samverk/api_contract.py and docs/API_CONTRACT.md,
ratifies Samverk's own /api/v1 before the code:
26 resources and 42 routes held as data, nine
cross-cutting rules, the two landed faces
(S-216 search, S-231 events) checked mechanically
against their own serialisers and refusals, and
every other resource a named promise for its
Part XII builder (S-242..S-248). The contract is
a document, not an act: reading it changes
nothing, so the audit log does not move for it.
No migration -- schema 94 stands.)

S-238 (2026-11-09) added no event of its own --
129 events stand: 33 auth, 83 repo, 13 admin.
(Its API authentication, in
samverk/api_auth.py, is the one door that
turns an `Authorization` header into an API
caller: a Bearer personal access token
resolved by S-032's or S-033's own store, or
session-free HTTP Basic for scripts with the
account password or a token in the password
slot, judged through S-081's git
authenticator. No session is consulted,
created, or extended, and authentication and
authorisation write no row and audit nothing
of their own -- the only write a call can
cause is the token stores' own last-used
stamp. Every authorisation resolves through
S-190's permission engine alone: a missing
repository and an unreadable one are the one
uniform `repo_not_found` refusal, and a token's
scopes are a ceiling over its owner's resolved
role, never a widening of it. Refusals carry
S-237's current two fields through
`error_to_dict`. No migration -- schema 94
stands.)

S-239 (2026-11-09) added no event of its own --
129 events stand: 33 auth, 83 repo, 13 admin.
(Its pagination and conditional requests, in
samverk/api_pagination.py, land the paging law
S-237 contracted: keyset cursors over each
face's permission-filtered list -- a cursor is
a position in one list, never a credential,
and contexts never cross -- page size bounded
(default 30, at most 100), Link headers
walking first / prev / next / last, and strong
ETags over canonical JSON whose If-None-Match
match answers 304 with no body. S-231's events
face crawls through it; paging and
conditioning are reads that witness nothing,
so the audit log does not move for them. No
migration -- schema 94 stands.)

S-240 (2026-11-09) added no event of its own --
129 events stand: 33 auth, 83 repo, 13 admin.
(Its error shape, in samverk/error_shape.py,
lands the one problem format S-237 contracted:
type, title, status, detail, error id, shaped
in one registry every refusal surface derives
from -- the four API faces' error_to_dict
(S-216, S-231, S-238, S-239), the server's
S-019 body, and S-113's web error states, whose
titles and messages are now the format's
canonical public words. A missing repository
and an unreadable one remain the one
repo_not_found problem in every field but the
error id each refusal mints, and successful
responses are untouched. Shaping a refusal is
not a witnessed act, so the audit log does not
move for it. No migration -- schema 94 stands.)

S-241 (2026-11-09) added no event of its own --
129 events stand: 33 auth, 83 repo, 13 admin.
(Its API rate limiting, in
samverk/api_rate_limit.py, judges every API
call at S-238's door against a per-token bucket
-- a token's own bucket, an account's bucket
for a password call, and the one tighter
anonymous bucket for a caller with no
credential -- answering every judgement with
the limit headers (X-RateLimit-Limit,
X-RateLimit-Remaining, X-RateLimit-Reset) and
refusing in S-240's one problem format as
rate_limited (429) with an honest Retry-After
computed from the bucket's own state; a
refusal charges nothing. The limits are
instance-configurable in the settings table
under api_rate_limit.* keys, and changing them
is audited admin.settings.change with the keys
named -- the existing event, as S-038 rides it
-- while judging a call writes no row and
audits nothing. No migration -- schema 94
stands.)

S-242 (2026-11-09) added no event of its own --
129 events stand: 33 auth, 83 repo, 13 admin.
(Its repositories API, in
samverk/api_repositories.py, is the programmatic
face of capabilities the web already has, and
every act it performs is witnessed by the web's
own stores on their existing events, exactly as
the same act on the web is witnessed: creation
on repo.create, metadata and rename and the
deletion request on repo.settings.change, a
visibility change on repo.visibility.change, a
fork on repo.fork, and a deletion's execution --
when its grace expires, by the web's own process
-- on repo.delete. Reads (the root, the
collection, one repository, branches, contents,
forks) write no row and audit nothing. No
migration -- schema 94 stands.)

S-243 (2026-11-09) added no event of its own --
129 events stand: 33 auth, 83 repo, 13 admin.
(Its issues and PRs API, in
samverk/api_issues_pulls.py, is the programmatic
face of capabilities the web already has, and
every act it performs is witnessed by the web's
own stores on their existing events, exactly as
the same act on the web is witnessed: issue
creation, edit, close and reopen on
repo.issue.create, repo.issue.update,
repo.issue.close and repo.issue.reopen; comments
on repo.issue.comment and
repo.pull_request.comment; labels, assignees and
milestone on repo.issue.label_add,
repo.issue.label_remove, repo.issue.assign,
repo.issue.unassign and repo.issue.milestone;
pull creation and draft conversions on
repo.pull_request.create,
repo.pull_request.mark_ready and
repo.pull_request.convert_to_draft; reviews on
repo.pull_request.review_submit; and the merge
on repo.pull_request.merge. Reads (both
collections, one issue, one pull, comments,
reviews) write no row and audit nothing. No
migration -- schema 94 stands.)

S-244 (2026-11-09) added no event of its own --
129 events stand: 33 auth, 83 repo, 13 admin.
(Its users, orgs and teams API, in
samverk/api_orgs.py, is the programmatic face of
capabilities the web already has, and every act
it performs is witnessed by the web's own stores
on their existing events, exactly as the same
act on the web is witnessed: organization
creation and profile changes on
auth.organization.create and
auth.organization.update; membership, team,
team-permission and default-permission changes
on auth.organization.update, with the changed
field named in the detail; and outside
collaborator grants, role changes and
revocations on repo.collaborator.add,
repo.collaborator.role_change and
repo.collaborator.remove. Reads (one user, the
organizations and their members, teams and
their members, team permissions, the default
permission, collaborator lists) write no row
and audit nothing. No migration -- schema 94
stands.)

S-245 (2026-11-09) added no event of its own --
129 events stand: 33 auth, 83 repo, 13 admin.
(Its search API, in samverk/api_search.py, is
S-216's search face ratified as the public
contract: the whole search delegates to S-216's
face over S-213's engine and the paged group
calls delegate to the five banked group
executors, every call resolved through S-238's
door and permission-filtered per S-209 exactly
as the web search is. Searching is a read: it
records no recent searches, writes no row and
audits nothing. No migration -- schema 94
stands.)

S-246 (2026-11-09) added two events of its own --
131 events stand: 33 auth, 85 repo, 13 admin.
(Its status and checks API, in
samverk/api_checks.py, is the seam S-157 named:
external CI posts a commit status on
`repo.status.post` and a check run on
`repo.check_run.post`, each entry carrying the
poster's scoped identity in its detail -- the
username, the credential kind and the token id
-- beside the commit, the context or run name
and the state posted. A status lands on S-157's
one commit_checks record (migration 95 adds the
poster column the row carries); a check run is
kept in its own check_runs table in the run
vocabulary and folded onto that same record
under its name, so the checks panel and the
S-174 gate read what was posted with no second
store to drift. Posting is judged through
S-238's door and S-190 at the write rung, with
the token scope as a ceiling; reads at the read
rung audit nothing, and refused posts store
nothing and audit nothing. Migration 95;
schema 94 -> 95.)

S-247 (2026-11-09) added no event of its own --
131 events stand: 33 auth, 85 repo, 13 admin.
(Its webhook events taxonomy, in
samverk/webhook_events.py and documented per
event in docs/WEBHOOK_EVENTS.md, maps every
verb in this taxonomy to its webhook ruling:
the webhook event name is the verb itself and
the payload is S-221's own event shape, with
the detail keys this document contracts per
event. Every repo.* verb is repository scope
(deliverable to repository hooks, and to the
hooks of the organization that owns the
repository); auth.organization.create and
auth.organization.update are organization scope
(organization hooks only); the remaining 44
verbs -- the rest of auth.* and the whole of
admin.* -- are never delivered, because a
webhook is an exfiltration path and account,
credential and instance-administration facts
are not on its closed list. The taxonomy is a
pure read: it holds no store, writes no row
and audits nothing. No migration -- schema 95
stands.)

S-248 (2026-11-09) added no event of its own --
131 events stand: 33 auth, 85 repo, 13 admin.
(Its webhook subscriptions, in
samverk/webhook_subscriptions.py, are witnessed
by the verbs that already stand: a repository
subscription's creation appends
`repo.webhook.add` and its deletion
`repo.webhook.remove`, the detail carrying the
target host only -- never the secret, which is
stored only as its SHA-256 digest and shown by
no face -- and a real update rides
`repo.settings.change` with the key
`webhook.update` named, as S-031's deploy keys
ride it. Organization subscriptions ride the
existing `auth.organization.update` event with
detail {"fields": "webhooks", "action": ...,
"host": ...}, the road S-186's membership and
S-192's defaults already travel. Filters are
S-247's taxonomy judged at the door; repository
access is S-190's admin rung, organization
access the owners'. Migration 96; schema
95 -> 96.)

S-249 (2026-11-09) added no event of its own --
131 events stand: 33 auth, 85 repo, 13 admin.
(Its webhook signing, in
samverk/webhook_signing.py, is a pure road like
S-247's taxonomy: HMAC-SHA256 over the raw
delivered bytes, header
X-Samverk-Signature-256 with a sha256= value,
keyed by the secret's SHA-256 digest -- the
only form S-248 stores -- so the sender signs
from the stored digest and the receiver
derives the same key from the raw secret.
Signing writes no row and audits nothing; a
subscription with no secret is unsigned and
carries no header. No migration -- schema 96
stands.)

S-250 (2026-11-09) added no event of its own --
131 events stand: 33 auth, 85 repo, 13 admin.
(Its webhook delivery worker, in
samverk/webhook_delivery.py, is bookkeeping over
acts already witnessed, like S-221's store and
S-235's digest job: enqueueing and attempting a
delivery witness no mutation, so the worker
audits nothing. Deliveries queue in migration
97's webhook_deliveries outbox (schema 96 -> 97),
routed by S-248's subscriptions_for_event and
signed at attempt time through S-249's
delivery_headers road; attempts are recorded
redacted in webhook_delivery_attempts for
S-251's delivery log.)

S-251 (2026-11-09) added no event of its own --
131 events stand: 33 auth, 85 repo, 13 admin.
(Its delivery log and redelivery, in
samverk/webhook_delivery_log.py, read S-250's
attempt history under S-248's own gate -- admin
on the repository, an owner of the organization,
or a site admin -- and inspections write and
audit nothing. A redelivery is a manager's act
and is witnessed on the standing verbs, as
S-248's subscription changes are: a repository
redelivery rides `repo.settings.change` with the
key `webhook.redeliver` named, an organization
redelivery rides `auth.organization.update` with
`fields` `webhooks` and action `redeliver`; the
detail carries the host and the original
delivery's key, never the payload and never a
secret. Redelivery queues a fresh outbox row
carrying the original's frozen payload and
naming it in `redelivery_of`; migration 98 adds
that lineage to `webhook_deliveries` (schema
97 -> 98) and widens the exactly-once index to
(subscription, event, redelivery number), the
original enqueue standing at number 0.)

S-252 (2026-11-10) added no event of its own --
131 events stand: 33 auth, 85 repo, 13 admin.
(Its ping and test events, in
samverk/webhook_ping.py, are synthetic sends,
not events: a ping rides the event name `ping`,
which no verb claims, and a test event rides one
real verb's name with a sample detail shaped by
that verb's stated detail fields, marked
synthetic in the payload itself. Nothing is
written to the event store; each send queues one
fresh row on S-250's outbox under a negative
event number and is ledgered in `webhook_pings`
(migration 99, schema 98 -> 99). A send is
witnessed on the standing verbs: a repository
send rides `repo.settings.change` with the key
`webhook.ping` or `webhook.test` named, an
organization send rides
`auth.organization.update` with `fields`
`webhooks` and action `ping` or `test`; the
detail carries the host and the delivery key
(and, for a test event, the verb), never the
payload and never a secret.)

S-253 (2026-11-10) added no event of its own --
131 events stand: 33 auth, 85 repo, 13 admin.
(Its GraphQL verdict, in
samverk/graphql_verdict.py, is a pure read like
S-202's billing hole and S-237's contract: the
study in research file 24 concludes DEFER, with
reasons, the three named clients judged one by
one, and the invariants a future GraphQL layer
must not break recorded in the REST contract
itself (rule graphql-deferred). There is no
GraphQL endpoint, schema or event to witness;
a request to execute GraphQL is refused
graphql_deferred and writes and audits nothing.
No migration -- schema 99 stands.)

S-254 (2026-11-10) added no event of its own --
131 events stand: 33 auth, 85 repo, 13 admin.
(Its API versioning policy, in
samverk/api_versioning.py, is a pure read like
S-202's billing hole, S-237's contract and
S-253's verdict: v1 changes additively only --
seven kinds of change are allowed inside v1 and
eight are breaking and require a v2 -- a v2
would be introduced alongside v1 under /api/v2,
never in its place, and deprecation is announced
in the Deprecation, Sunset and Link headers with
at least 180 days between deprecation and
sunset, as the contract's versioned-base rule
now records. There is no v2 endpoint, no
deprecation in force and no act to witness; the
policy writes and audits nothing. No migration
-- schema 99 stands.)

S-255 (2026-11-10) added no event of its own --
131 events stand: 33 auth, 85 repo, 13 admin.
(Its API abuse defences, in
samverk/api_abuse.py, stand beside S-241's rate
buckets at the API door: every resource of the
contract's route table is catalogued with the
size class of the body it may carry and a price
in cost units, payload size caps are judged
before a body is read for meaning
(payload_too_large at 413), every admitted call
is accounted to its caller at its endpoint's
price, and per-token concurrency limits are held
in leases (concurrency_limit_exceeded at 429).
Judging, accounting and holding a slot write no
row and audit nothing -- the ledger and the
slots are memory, as S-241's buckets are; only
changing the defences themselves is witnessed,
on the standing admin.settings.change event with
the api_abuse.* keys named. No migration --
schema 99 stands.)
