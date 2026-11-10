# Samverk Webhook Events Taxonomy

*Slice S-247. The event store's verbs (S-221, over the frozen
audit taxonomy of docs/AUDIT_TAXONOMY.md) mapped to webhook
payloads. Enforced in code by `samverk/webhook_events.py`:
every audit verb has exactly one ruling there, and the audit
in that module refuses a taxonomy that drifts from this
document, from the taxonomy, or from S-221's serialiser.*

## The payload

The payload shape is Samverk's own (the shape S-139 set for
the issue outbox, generalised by S-221). Every delivered
webhook carries exactly these fields, in this envelope:

`delivery_id`, `event`, `action`, `actor`, `target`, `repository`, `number`, `refs`, `detail`, `occurred_at`

- `event` is the audit verb itself (`repo.issue.create`);
  `action` is its final segment. There is no second,
  coarser webhook vocabulary to translate between.
- `delivery_id` is `evt-<event id>`, stable across
  redelivery so a receiver can dedupe (delivery itself
  is S-250).
- `detail` is the witness's safe detail, carried
  unchanged: the keys it may hold are stated per event
  below, from the audit taxonomy's per-event contract.
  It never carries titles, bodies, tokens or secrets.
- `occurred_at` is the witnessed timestamp -- the moment
  the mutation landed, never a second clock.

## Scope law

- **Repository scope (85 verbs):** every `repo.*` verb.
  A repository hook subscribes to its own repository's
  events; an organization hook subscribes to the events
  of the organization's repositories.
- **Organization scope (2 verbs):** `auth.organization.create`
  and `auth.organization.update`. Organization hooks only;
  no repository hook ever carries them.
- **Never delivered (44 verbs):** the rest of `auth.*`
  (accounts, credentials, follows) and the whole of
  `admin.*` (instance administration). A webhook is an
  exfiltration path by design; what it may carry is a
  closed list, and these are not on it.

Subscriptions are S-248's, signing (over exactly the
canonical JSON of this payload) is S-249's, delivery is
S-250's, and synthetic test events are S-252's -- every
event named here is a real event-store verb.

## Events, per event


### account (29)

| Event | Scope | Meaning | detail may carry |
|---|---|---|---|
| `auth.signup.success` | none | Account created | `method` |
| `auth.signup.denied` | none | Signup refused (throttle/policy) | `reason` |
| `auth.login.success` | none | Login succeeded | `method` |
| `auth.login.failure` | none | Login failed | `attempted_user` |
| `auth.logout` | none | Session ended by its owner | -- |
| `auth.password.change` | none | Password changed (sessions revoked) | -- |
| `auth.password.reset` | none | Password reset completed | `via` |
| `auth.token.create` | none | API/access token created | `token_id`, `scopes` |
| `auth.token.revoke` | none | Token revoked | `token_id` |
| `auth.ssh_key.add` | none | SSH key registered | `fingerprint` |
| `auth.ssh_key.remove` | none | SSH key removed | `fingerprint` |
| `auth.twofactor.enable` | none | 2FA enrolled | `method` |
| `auth.twofactor.disable` | none | 2FA removed | -- |
| `auth.twofactor.reset` | none | 2FA reset via recovery | -- |
| `auth.session.revoke` | none | A session (or all) revoked | `scope` |
| `auth.email.verify` | none | Email verification token redeemed (S-026; outcome distinguishes success from denied) | `reason` |
| `auth.profile.update` | none | Profile text or avatar changed (S-029) | `fields` |
| `auth.recovery.generate` | none | Recovery code set generated; any old set invalidated (S-037) | `count`, `invalidated` |
| `auth.recovery.use` | none | A recovery code was redeemed (S-037) | -- |
| `auth.passkey.add` | none | Passkey enrolled (S-039) | `credential_id`, `format` |
| `auth.passkey.remove` | none | Passkey removed by its owner (S-039) | `credential_id` |
| `auth.passkey.login` | none | Passkey assertion verified — second factor or passwordless (S-039) | `credential_id` |
| `auth.signin.notify` | none | New-device sign-in notice fired (S-041) | `device` |
| `auth.username.change` | none | Account renamed; old name tombstoned (S-042) | `from`, `to` |
| `auth.deletion.request` | none | Account deletion requested; grace begins (S-043) | `scheduled_at` |
| `auth.deletion.cancel` | none | Pending deletion cancelled by its owner (S-043) | -- |
| `auth.deletion.execute` | none | Account irreversibly deleted after grace (S-043) | `username` |
| `auth.identity.link` | none | External identity linked (S-045) | `provider` |
| `auth.identity.unlink` | none | External identity unlinked (S-045) | `provider` |

### repository (19)

| Event | Scope | Meaning | detail may carry |
|---|---|---|---|
| `repo.create` | repository | Repository created | `visibility` |
| `repo.delete` | repository | Repository deleted | -- |
| `repo.visibility.change` | repository | Visibility changed | `from`, `to` |
| `repo.transfer` | repository | Ownership transferred | `from_owner`, `to_owner` |
| `repo.protection.change` | repository | Branch protection changed | `branch`, `rule` |
| `repo.collaborator.add` | repository | Collaborator added | `user`, `role` |
| `repo.collaborator.remove` | repository | Collaborator removed | `user` |
| `repo.collaborator.role_change` | repository | Collaborator role changed | `user`, `from`, `to` |
| `repo.settings.change` | repository | Security-relevant repo setting changed | `key`, `from`, `to` |
| `repo.fork` | repository | Repository forked; upstream link recorded (S-055) | `fork_of` |
| `repo.fetch` | repository | Private repository content fetched/cloned/archived via a transport (S-094) | `transport`, `service` |
| `repo.issue_template.create` | repository | An issue template (Markdown or YAML form) created in a repository (S-129) | `template`, `kind` |
| `repo.issue_template.update` | repository | An issue template edited or replaced (S-129) | `template`, `kind` |
| `repo.issue_template.delete` | repository | An issue template deleted (S-129) | `template`, `kind` |
| `repo.watch` | repository | A watch set or its mode changed -- only a real change is recorded (S-222) | `mode`, `previous` |
| `repo.unwatch` | repository | A watch removed entirely, any mode (S-222) | `previous` |
| `repo.star` | repository | A repository starred -- only a real change is recorded (S-222) | -- |
| `repo.unstar` | repository | A star taken back by its own giver (S-222) | -- |
| `repo.protection.bypass` | repository | A branch-protection bypass was used by an actor it named (S-179) | `branch`, `patterns`, `rule_ids`, `bypass_entry`, `gate`, `actor` |

### push (1)

| Event | Scope | Meaning | detail may carry |
|---|---|---|---|
| `repo.push` | repository | Refs updated by a push | `ref`, `old`, `new` |

### releases (1)

| Event | Scope | Meaning | detail may carry |
|---|---|---|---|
| `repo.release.publish` | repository | Release published | `tag` |

### webhooks (2)

| Event | Scope | Meaning | detail may carry |
|---|---|---|---|
| `repo.webhook.add` | repository | Webhook added (an exfiltration path; watched) | `host` |
| `repo.webhook.remove` | repository | Webhook removed | `host` |

### issues (24)

| Event | Scope | Meaning | detail may carry |
|---|---|---|---|
| `repo.issue.create` | repository | Issue created in a repository (S-122) | `number` |
| `repo.issue.update` | repository | Issue title/body edited (S-122) | `number`, `version` |
| `repo.issue.comment` | repository | Comment added to an issue (S-123) | `number`, `comment_id` |
| `repo.issue.comment_edit` | repository | Comment edited by its author; previous body kept in the visible edit history (S-123) | `number`, `comment_id` |
| `repo.issue.comment_delete` | repository | Comment deleted by its author or a repository admin; tombstone remains (S-123) | `number`, `comment_id` |
| `repo.issue.label_add` | repository | Label added to an issue (S-124) | `number`, `label` |
| `repo.issue.label_remove` | repository | Label removed from an issue (S-124) | `number`, `label` |
| `repo.issue.milestone` | repository | An issue's milestone set or cleared (S-125) | `number`, `milestone` |
| `repo.issue.assign` | repository | An account assigned to an issue (S-126) | `number`, `assignee` |
| `repo.issue.unassign` | repository | An account unassigned from an issue (S-126) | `number`, `assignee` |
| `repo.issue.reaction_add` | repository | A reaction given to an issue or comment; only a real change is recorded (S-128) | `number`, `reaction`, `comment_id` |
| `repo.issue.reaction_remove` | repository | A reaction taken back by its giver (S-128) | `number`, `reaction`, `comment_id` |
| `repo.issue.close` | repository | An issue closed, with its reason (S-130) | `number`, `reason` |
| `repo.issue.reopen` | repository | A closed issue reopened (S-130) | `number` |
| `repo.issue.lock` | repository | An issue's conversation locked by a moderator, with its reason (S-132) | `number`, `reason` |
| `repo.issue.unlock` | repository | A locked conversation unlocked by a moderator (S-132) | `number` |
| `repo.issue.pin` | repository | An issue pinned by a moderator (at most three per repository) (S-132) | `number` |
| `repo.issue.unpin` | repository | An issue unpinned by a moderator (S-132) | `number` |
| `repo.issue.transfer_out` | repository | An issue transferred out of this repository to another repository of the same owner (S-133) | `number`, `to`, `to_number` |
| `repo.issue.transfer_in` | repository | An issue transferred into this repository from another repository of the same owner (S-133) | `number`, `from`, `from_number` |
| `repo.issue.convert` | repository | An issue converted to a draft pull request: a linked branch created from it (S-137) | `number`, `to_number`, `branch` |
| `repo.issue.comment_hide` | repository | A comment hidden by a moderator, with its reason (S-138) | `number`, `comment_id`, `reason` |
| `repo.issue.comment_unhide` | repository | A hidden comment restored by a moderator (S-138) | `number`, `comment_id` |
| `repo.issue.comment_remove` | repository | A comment removed by a moderator (the S-123 tombstone, struck as a moderation act distinct from an author's own delete), with its reason (S-138) | `number`, `comment_id`, `reason` |

### labels (3)

| Event | Scope | Meaning | detail may carry |
|---|---|---|---|
| `repo.label.create` | repository | Label created in a repository (S-124) | `label` |
| `repo.label.update` | repository | Label renamed, recoloured, or redescribed (S-124) | `label` |
| `repo.label.delete` | repository | Label deleted; its issue assignments die with it (S-124) | `label` |

### milestones (3)

| Event | Scope | Meaning | detail may carry |
|---|---|---|---|
| `repo.milestone.create` | repository | Milestone created in a repository (S-125) | `milestone` |
| `repo.milestone.update` | repository | Milestone edited, closed, or reopened (S-125) | `milestone` |
| `repo.milestone.delete` | repository | Milestone deleted; its issues are unassigned, never deleted (S-125) | `milestone` |

### pull_requests (28)

| Event | Scope | Meaning | detail may carry |
|---|---|---|---|
| `repo.pull_request.create` | repository | A pull request created, claiming its shared number (S-137; Part VII's creation roads ride the same event) | `number`, `base`, `head`, `draft`, `from_issue` |
| `repo.pull_request.mark_ready` | repository | A draft pull request marked ready for review by its author or a repository writer (S-143) | `number` |
| `repo.pull_request.convert_to_draft` | repository | An open pull request converted back to a draft by its author or a repository writer (S-143) | `number` |
| `repo.pull_request.comment` | repository | Comment added to a pull request (S-144) | `number`, `comment_id` |
| `repo.pull_request.comment_edit` | repository | A pull-request comment edited by its author; previous body kept in the visible edit history (S-144) | `number`, `comment_id` |
| `repo.pull_request.comment_delete` | repository | A pull-request comment deleted by its author or a repository admin; tombstone remains (S-144) | `number`, `comment_id` |
| `repo.pull_request.line_comment` | repository | A comment anchored to one line of a pull request's diff (S-146) | `number`, `comment_id`, `file`, `side`, `line` |
| `repo.pull_request.line_comment_edit` | repository | A pull-request line comment edited by its author; previous body kept in the visible edit history (S-146) | `number`, `comment_id`, `file`, `side`, `line` |
| `repo.pull_request.line_comment_delete` | repository | A pull-request line comment deleted by its author or a repository admin; tombstone remains (S-146) | `number`, `comment_id`, `file`, `side`, `line` |
| `repo.pull_request.line_reply` | repository | A reply added in a pull-request line comment's review thread (S-147) | `number`, `comment_id`, `reply_id` |
| `repo.pull_request.line_reply_edit` | repository | A review-thread reply edited by its author; previous body kept in the visible edit history (S-147) | `number`, `comment_id`, `reply_id` |
| `repo.pull_request.line_reply_delete` | repository | A review-thread reply deleted by its author or a repository admin; tombstone remains (S-147) | `number`, `comment_id`, `reply_id` |
| `repo.pull_request.thread_resolve` | repository | A review thread marked resolved by the comment's author, the pull request's author, or a repository writer (S-147) | `number`, `comment_id` |
| `repo.pull_request.thread_unresolve` | repository | A resolved review thread marked unresolved again by the comment's author, the pull request's author, or a repository writer (S-147) | `number`, `comment_id` |
| `repo.pull_request.review_submit` | repository | A review submitted on a pull request with one verdict — approved, commented, or changes requested (S-148) | `number`, `review_id`, `verdict` |
| `repo.pull_request.suggestion_propose` | repository | A committable suggested change proposed on a pull request, anchored to a range of new-side lines in one file of its diff (S-150) | `number`, `suggestion_id`, `file`, `start_line`, `end_line` |
| `repo.pull_request.suggestion_apply` | repository | One suggested change or a batch of them applied by the pull request's author (or an allowed maintainer) as exactly one signed-off commit on the head branch (S-150) | `number`, `suggestion_ids`, `commit`, `count` |
| `repo.pull_request.codeowners_request` | repository | Reviewers auto-requested on a pull request from the CODEOWNERS file on its base branch (S-151) | `number`, `owner_refs` |
| `repo.pull_request.review_request` | repository | Reviewers manually requested on a pull request by its author or a base-repository writer (S-152) | `number`, `owner_refs` |
| `repo.pull_request.review_rerequest` | repository | A dismissed review request re-requested on a pull request, reactivating its record (S-152) | `number`, `owner_refs` |
| `repo.pull_request.review_dismiss` | repository | An active review request dismissed on a pull request; the record stays, stamped with who dismissed it and when (S-152) | `number`, `owner_refs` |
| `repo.pull_request.merge` | repository | A pull request landed on its base branch as a merge commit — the message the pull request's title/body by default or as edited by the merger, the two parents, and the issues its closing keywords closed on landing (S-153) | `number`, `commit`, `base`, `head`, `closed` |
| `repo.pull_request.squash_merge` | repository | A pull request squash-merged onto its base branch as one commit, its author preserved and its closing keywords executed on landing (S-154) | `number`, `strategy`, `commit`, `base`, `head`, `author`, `closed_numbers` |
| `repo.pull_request.rebase` | repository | A pull request landed by rebase: its head commits replayed onto its base branch, the base ref moved to the replayed tip (S-155) | `number`, `replayed`, `base_before`, `base_after` |
| `repo.pull_request.revert` | repository | A merged pull request reverted by opening a revert pull request linked both ways to it (S-160) | `number`, `revert_number`, `commit`, `branch`, `merged_commit` |
| `repo.pull_request.auto_merge_arm` | repository | Auto-merge armed on a pull request (S-158) | `number`, `strategy`, `checks`, `head` |
| `repo.pull_request.auto_merge_cancel` | repository | Auto-merge cancelled on a pull request (S-158) | `number` |
| `repo.pull_request.auto_merge_fire` | repository | Auto-merge fired on a pull request, merged or failed (S-158) | `number`, `strategy`, `commit`, `error` |

### branches (2)

| Event | Scope | Meaning | detail may carry |
|---|---|---|---|
| `repo.branch.delete_on_merge` | repository | Head branch deleted when its pull request merged, under the repository's delete_branch_on_merge opt-in; the deletion is tombstoned for restore (S-159) | `number`, `branch`, `head_repo`, `oid`, `merge` |
| `repo.branch.restore` | repository | A deleted branch restored from its tombstone at the recorded head oid (S-159) | `branch`, `oid`, `deleted_branch_id` |

### administration (13)

| Event | Scope | Meaning | detail may carry |
|---|---|---|---|
| `admin.user.create` | none | Admin created a user | -- |
| `admin.user.disable` | none | User disabled | `reason` |
| `admin.user.delete` | none | User deleted | -- |
| `admin.user.role_change` | none | Instance role changed | `from`, `to` |
| `admin.settings.change` | none | Instance setting changed | `key`, `from`, `to` |
| `admin.plaintext_http_override` | none | Plaintext-HTTP override armed (S-015) | `scope` |
| `admin.audit.ip_disclosure` | none | Audit IP display enabled/disabled for a scope | `scope`, `enabled` |
| `admin.audit.export` | none | Audit log exported | `scope`, `entries` |
| `admin.key.rotate` | none | Instance key rotated (S-020) | `key` |
| `admin.user.approve` | none | Operator approved a pending account (S-026, the no-SMTP road) | `from_status` |
| `admin.user.suspend` | none | Admin suspended an account, with reason (S-044) | `reason` |
| `admin.user.unsuspend` | none | Admin lifted a suspension (S-044) | `reason` |
| `admin.index.rebuild` | none | Admin triggered a search-index rebuild for a repository (S-215) | `kinds`, `generations`, `jobs` |

### organization (2)

| Event | Scope | Meaning | detail may carry |
|---|---|---|---|
| `auth.organization.create` | organization | Organization created (S-185) | `org` |
| `auth.organization.update` | organization | Organization profile, membership, team, permission or settings changed (S-185) | `fields` |

### following (2)

| Event | Scope | Meaning | detail may carry |
|---|---|---|---|
| `auth.follow` | none | An account followed another account (S-232) | `followed` |
| `auth.unfollow` | none | An account took its follow back (S-232) | `followed` |

### checks (2)

| Event | Scope | Meaning | detail may carry |
|---|---|---|---|
| `repo.status.post` | repository | A commit status posted through the API by a scoped poster (S-246) | `poster`, `credential`, `token_id`, `oid`, `context`, `state` |
| `repo.check_run.post` | repository | A check run posted through the API by a scoped poster (S-246) | `poster`, `credential`, `token_id`, `oid`, `name`, `status`, `conclusion` |
