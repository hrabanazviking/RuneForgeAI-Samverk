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
