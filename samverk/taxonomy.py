"""Audit event taxonomy v1 (S-008).

The frozen vocabulary of audit event names. Emitters may only use
names from this set — `AuditLog.append` refuses anything else — so
the log stays searchable and meaningful for the life of the instance
(study 35 §2/§4).

Rules of the taxonomy:
- Names are `family.subject.verb` in lowercase, dot-separated.
- v1 names are never renamed or removed. A name that stops being
  emitted is marked *deprecated* in docs/AUDIT_TAXONOMY.md and stays
  in this set forever (old log rows must remain interpretable).
- Additions append new names and bump the taxonomy's minor note in
  the doc; they never change existing meanings.
"""

from __future__ import annotations

TAXONOMY_VERSION = 1

AUTH_EVENTS = frozenset({
    "auth.signup.success",
    "auth.signup.denied",
    "auth.login.success",
    "auth.login.failure",
    "auth.logout",
    "auth.password.change",
    "auth.password.reset",
    "auth.token.create",
    "auth.token.revoke",
    "auth.ssh_key.add",
    "auth.ssh_key.remove",
    "auth.twofactor.enable",
    "auth.twofactor.disable",
    "auth.twofactor.reset",
    "auth.session.revoke",
    # S-026 addition (append-only, per the taxonomy rules):
    "auth.email.verify",
    # S-029 addition (append-only, per the taxonomy rules):
    "auth.profile.update",
    # S-037 additions (append-only, per the taxonomy rules):
    "auth.recovery.generate",
    "auth.recovery.use",
    # S-039 additions (append-only, per the taxonomy rules):
    "auth.passkey.add",
    "auth.passkey.remove",
    "auth.passkey.login",
    # S-041 addition (append-only, per the taxonomy rules):
    "auth.signin.notify",
    # S-042 addition (append-only, per the taxonomy rules):
    "auth.username.change",
    # S-043 additions (append-only, per the taxonomy rules):
    "auth.deletion.request",
    "auth.deletion.cancel",
    "auth.deletion.execute",
    # S-045 additions (append-only, per the taxonomy rules):
    "auth.identity.link",
    "auth.identity.unlink",
})

REPO_EVENTS = frozenset({
    "repo.create",
    "repo.delete",
    "repo.visibility.change",
    "repo.transfer",
    "repo.push",
    "repo.protection.change",
    "repo.collaborator.add",
    "repo.collaborator.remove",
    "repo.collaborator.role_change",
    "repo.release.publish",
    "repo.webhook.add",
    "repo.webhook.remove",
    "repo.settings.change",
    # S-055 addition (append-only, per the taxonomy rules):
    "repo.fork",
    # S-094 addition (append-only, per the taxonomy rules):
    "repo.fetch",
    # S-122 additions (append-only, per the taxonomy rules):
    "repo.issue.create",
    "repo.issue.update",
    # S-123 additions (append-only, per the taxonomy rules):
    "repo.issue.comment",
    "repo.issue.comment_edit",
    "repo.issue.comment_delete",
    # S-124 additions (append-only, per the taxonomy rules):
    "repo.label.create",
    "repo.label.update",
    "repo.label.delete",
    "repo.issue.label_add",
    "repo.issue.label_remove",
    # S-125 additions (append-only, per the taxonomy rules):
    "repo.milestone.create",
    "repo.milestone.update",
    "repo.milestone.delete",
    "repo.issue.milestone",
    # S-126 additions (append-only, per the taxonomy rules):
    "repo.issue.assign",
    "repo.issue.unassign",
    # S-128 additions (append-only, per the taxonomy rules):
    "repo.issue.reaction_add",
    "repo.issue.reaction_remove",
    # S-129 additions (append-only, per the taxonomy rules):
    "repo.issue_template.create",
    "repo.issue_template.update",
    "repo.issue_template.delete",
    # S-130 additions (append-only, per the taxonomy rules):
    "repo.issue.close",
    "repo.issue.reopen",
    # S-132 additions (append-only, per the taxonomy rules):
    "repo.issue.lock",
    "repo.issue.unlock",
    "repo.issue.pin",
    "repo.issue.unpin",
    # S-133 additions (append-only, per the taxonomy rules):
    "repo.issue.transfer_out",
    "repo.issue.transfer_in",
    # S-137 additions (append-only, per the taxonomy rules):
    "repo.issue.convert",
    "repo.pull_request.create",
    # S-138 additions (append-only, per the taxonomy rules):
    "repo.issue.comment_hide",
    "repo.issue.comment_unhide",
    "repo.issue.comment_remove",
    # S-143 additions (append-only, per the taxonomy rules):
    "repo.pull_request.mark_ready",
    "repo.pull_request.convert_to_draft",
})

ADMIN_EVENTS = frozenset({
    "admin.user.create",
    "admin.user.disable",
    "admin.user.delete",
    "admin.user.role_change",
    "admin.settings.change",
    "admin.plaintext_http_override",
    "admin.audit.ip_disclosure",
    "admin.audit.export",
    "admin.key.rotate",
    # S-026 addition (append-only, per the taxonomy rules):
    "admin.user.approve",
    # S-044 additions (append-only, per the taxonomy rules):
    "admin.user.suspend",
    "admin.user.unsuspend",
})

AUDIT_EVENTS = AUTH_EVENTS | REPO_EVENTS | ADMIN_EVENTS


def is_known_event(action: str) -> bool:
    return action in AUDIT_EVENTS
