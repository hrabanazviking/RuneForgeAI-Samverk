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
