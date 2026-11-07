"""Billing-shaped hole, honestly empty (S-202).

Samverk is free software on your own machines; no
seat/billing concepts exist, and the docs say why.

- **The hole is shaped like billing on purpose.**
  People arriving from hosted forges look for billing
  where they were trained to look: an organization's
  settings, and the instance's. So the surface exists
  exactly there — S-185's settings map gains a
  ``billing`` area (built by this slice, available,
  never a link to nowhere) and ``render_billing_page``
  renders it — and what it says, in plain words, is
  that there is nothing in it: no seats, no plans, no
  tiers, no invoices, no charges, no payment methods,
  not a free tier and not a trial. Empty, and honest
  about why it is empty.
- **Why it is empty.** Samverk is free software
  under the AGPL-3.0 (the licence in pyproject): use,
  study, sharing and change are granted for no fee,
  to everyone, forever. It runs on machines its
  people already own — the computer, the disk and
  the electricity are theirs — so there is no hosted
  service to meter and no host to pay. There is no
  vendor account and no payment rail: Samverk never
  asks for a card, and no code in it can take one.
  And people are not seats: membership of an
  organization is a relationship recorded by S-186,
  not a unit sold back to the organization. The
  member count on the page is stated only to say it
  is never metered — the first member and the
  ten-thousandth cost the same: nothing.
- **Proven, not just claimed.** ``BillingHole.
  audit_surface`` inspects the live instance: every
  table and column in the database schema and every
  event in S-008's audit taxonomy is checked against
  ``FORBIDDEN_TERMS``, and the audit is honest only
  when the offenders lists are all empty. The
  battery plants a billing-shaped table and proves
  the audit catches it, so the emptiness is a
  checked fact about this code, not a promise. One
  term is deliberately *not* forbidden: ``quota``.
  S-0xx's ``repo_quotas`` is a disk budget on a
  machine its owner owns — a capacity guard that
  refuses to fill your own disk, never a charge —
  and naming the distinction is part of the honesty.
- **There is no billing act.** Every billing-shaped
  request — subscribe, add seats, change plan, pay
  an invoice, update a payment method, anything —
  is refused by the pure ``decide_billing_request``
  (``no_billing``; a shapeless action is
  ``billing_action_invalid``), and ``BillingHole``
  raises it as ``OrganizationError`` before anything
  is touched. Refusals write nothing and audit
  nothing: there is no billing event to write, and
  inventing one would put a billing concept in the
  taxonomy to record that there is none.
- **A pure read, like S-201.** This module holds no
  ``AuditLog``, writes no row and grants nothing. It
  reads organizations and memberships where S-185 /
  S-186 put them, the schema where the migrations
  put it, and the taxonomy where S-008 froze it.
- **No storage, no event.** The hole claims no
  migration of its own (schema stays 78) and no
  taxonomy event (122 stand: 31 auth / 79 repo /
  12 admin): a billing table for recording that
  there is no billing would be the concept arriving
  by the back door. The why also lives in
  ``docs/BILLING.md``, where a person who never
  opens the settings can read it.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from . import taxonomy
from .accounts import AccountStore
from .escaping import escape_html_text
from .organizations import Organization, OrganizationError

__all__ = [
    "BILLING_ACTIONS", "FORBIDDEN_TERMS", "LICENSE_NAME",
    "WHY_FREE", "BillingAudit", "BillingHole",
    "BillingStatement", "decide_billing_request",
    "forbidden_terms_in", "render_billing_page",
]

LICENSE_NAME = "AGPL-3.0"

# Billing-shaped words that must never name a table,
# a column or an audit event in Samverk. ``quota`` is
# absent on purpose: a disk budget on your own
# machine is a capacity guard, not a charge.
FORBIDDEN_TERMS = (
    "billing", "seat", "invoice", "subscription",
    "payment", "charge", "price", "plan", "tier",
    "customer", "checkout",
)

# The billing acts a hosted forge offers. Every one
# of them is refused here; the list exists so the
# refusal can name what was asked for.
BILLING_ACTIONS = (
    "subscribe", "add_seats", "remove_seats",
    "change_plan", "pay_invoice", "update_payment_method",
    "add_payment_method", "start_trial", "buy_seats",
)

WHY_FREE = (
    "Samverk is free software under the AGPL-3.0: the "
    "licence grants use, study, sharing and change for "
    "no fee, to everyone, forever.",
    "It runs on your own machines: the computer, the "
    "disk and the electricity are already yours, so "
    "there is no hosted service to meter and no host "
    "to pay.",
    "There is no vendor account and no payment rail: "
    "Samverk never asks for a card, and no code in it "
    "can take one.",
    "People are not seats: membership is a relationship "
    "in your own organization, not a unit sold back "
    "to you.",
)


def forbidden_terms_in(name: object) -> tuple[str, ...]:
    """The forbidden billing terms found in one schema
    or event name, in ``FORBIDDEN_TERMS`` order. A
    non-string names nothing and matches nothing."""
    if not isinstance(name, str):
        return ()
    lowered = name.lower()
    return tuple(t for t in FORBIDDEN_TERMS if t in lowered)


def decide_billing_request(action: object) -> str:
    """Pure billing judgement: the refusal reason for
    any billing-shaped request. A recognisable act —
    and, honestly, any worded act at all, since there
    is no billing here for an unlisted act to reach —
    is refused ``no_billing``; a shapeless action (not
    text, or no text) is ``billing_action_invalid``."""
    if not isinstance(action, str) or not action.strip():
        return "billing_action_invalid"
    return "no_billing"


@dataclass(frozen=True)
class BillingStatement:
    """The honest billing state of one scope: an
    organization (named, with its member count —
    stated only to say it is never metered) or the
    whole instance. Every billing concept reads as
    absent; the licence and the reasons ride along so
    the page and the docs can say why from one source."""
    scope: str                    # "organization" | "instance"
    subject: str                  # display name / "This instance"
    subject_lower: str
    license_name: str
    member_count: int | None      # organizations only
    reasons: tuple[str, ...]

    @property
    def has_billing(self) -> bool:
        return False

    @property
    def has_seats(self) -> bool:
        return False

    @property
    def has_plans(self) -> bool:
        return False

    @property
    def has_charges(self) -> bool:
        return False


@dataclass(frozen=True)
class BillingAudit:
    """The checked emptiness of one instance: how much
    schema and vocabulary was inspected, and every
    billing-shaped name found in it. Honest only when
    every offender list is empty."""
    tables_scanned: int
    columns_scanned: int
    events_scanned: int
    offending_tables: tuple[str, ...]
    offending_columns: tuple[str, ...]
    offending_events: tuple[str, ...]

    @property
    def honestly_empty(self) -> bool:
        return not (self.offending_tables
                    or self.offending_columns
                    or self.offending_events)


class BillingHole:
    """The billing surface itself: statements for an
    organization or the instance, the surface audit
    that proves the statements, and the one refusal
    every billing act meets. Reads only — this class
    holds no AuditLog and writes nothing."""

    def __init__(
        self, conn: sqlite3.Connection, accounts: AccountStore,
    ):
        self._conn = conn
        self._accounts = accounts

    # -- lookups --------------------------------------
    def _resolve_org(self, org: object) -> Organization:
        from .organizations import OrganizationStore
        store = OrganizationStore(
            self._conn, self._accounts, audit=None)
        found: Organization | None = None
        if isinstance(org, Organization):
            found = store.get_by_id(org.id)
        elif isinstance(org, int):
            found = store.get_by_id(org)
        elif isinstance(org, str):
            found = store.get_by_name(org)
        if found is None:
            raise OrganizationError(
                "org_not_found", "No such organization.")
        return found

    def _member_count(self, org_id: int) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM organization_members"
            " WHERE org_id = ?", (org_id,)).fetchone()
        return int(row["c"])

    # -- statements ------------------------------------
    def statement_for_organization(
        self, org: object,
    ) -> BillingStatement:
        """The billing statement of one organization,
        named by Organization, id or name. An unknown
        organization is ``org_not_found`` — the hole
        does not invent an organization to be empty
        for."""
        found = self._resolve_org(org)
        return BillingStatement(
            scope="organization", subject=found.name,
            subject_lower=found.name_lower,
            license_name=LICENSE_NAME,
            member_count=self._member_count(found.id),
            reasons=WHY_FREE)

    def instance_statement(self) -> BillingStatement:
        """The billing statement of the whole instance:
        the same emptiness, unscoped."""
        return BillingStatement(
            scope="instance", subject="This instance",
            subject_lower="", license_name=LICENSE_NAME,
            member_count=None, reasons=WHY_FREE)

    # -- the proof --------------------------------------
    def audit_surface(self) -> BillingAudit:
        """Check the live schema and the frozen
        taxonomy for any billing concept: every table
        name, every column name and every audit event,
        judged by ``forbidden_terms_in``. Pure read."""
        tables = [r["name"] for r in self._conn.execute(
            "SELECT name FROM sqlite_master"
            " WHERE type = 'table' ORDER BY name").fetchall()]
        offending_tables: list[str] = []
        offending_columns: list[str] = []
        columns_scanned = 0
        for table in tables:
            if forbidden_terms_in(table):
                offending_tables.append(table)
            safe = table.replace('"', '""')
            for row in self._conn.execute(
                    f'PRAGMA table_info("{safe}")').fetchall():
                columns_scanned += 1
                column = f"{table}.{row[1]}"
                if forbidden_terms_in(row[1]):
                    offending_columns.append(column)
        events = sorted(taxonomy.AUDIT_EVENTS)
        offending_events = [
            e for e in events if forbidden_terms_in(e)]
        return BillingAudit(
            tables_scanned=len(tables),
            columns_scanned=columns_scanned,
            events_scanned=len(events),
            offending_tables=tuple(offending_tables),
            offending_columns=tuple(offending_columns),
            offending_events=tuple(offending_events))

    # -- the one refusal ---------------------------------
    def attempt_billing_action(self, action: object) -> None:
        """Refuse a billing-shaped act, always: there
        is no billing to act on. Raises
        ``OrganizationError`` carrying the pure
        decision's reason; writes nothing, audits
        nothing (there is no billing event to write)."""
        reason = decide_billing_request(action)
        if reason == "billing_action_invalid":
            raise OrganizationError(
                reason, "That billing action is not valid.")
        raise OrganizationError(
            reason,
            "Samverk has no billing: it is free software "
            "on your own machines, with no seats, no "
            "plans and no charges, so there is nothing "
            "to subscribe to, buy or pay.")

    # -- pages -------------------------------------------
    def organization_page(self, org: object) -> str:
        """One organization's billing page: its
        statement, rendered with the surface audit."""
        return render_billing_page(
            self.statement_for_organization(org),
            self.audit_surface())

    def instance_page(self) -> str:
        """The instance billing page: its statement,
        rendered with the surface audit."""
        return render_billing_page(
            self.instance_statement(), self.audit_surface())


def render_billing_page(
    statement: BillingStatement,
    audit: BillingAudit | None = None,
) -> str:
    """The billing-shaped hole, rendered: the plain
    statement that there is no billing, what is absent
    named item by item, the member count said to be
    unmetered (organizations), why it is empty, the
    checked proof when an audit rides along, and where
    to go instead — every value escaped through S-010,
    the state said in words, never colour-only."""
    subject = escape_html_text(statement.subject)
    if statement.scope == "organization":
        title = f"Billing — {subject} — Samverk"
        heading = f"Billing — {subject}"
        opening = (
            f"There is no billing for {statement.subject}.")
    else:
        title = "Billing — Samverk"
        heading = "Billing"
        opening = "There is no billing on this instance."
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{title}</title></head>",
        "<body>",
        f"<h1>{heading}</h1>",
        f"<p>{escape_html_text(opening)}</p>",
        "<p>Samverk is free software on your own machines. "
        "There are no seats, no plans, no tiers, no "
        "invoices and no charges — not a free tier, not "
        "a trial, and no payment method is kept or asked "
        "for. Nothing here is metered and nobody is "
        "owed.</p>",
    ]
    if statement.member_count is not None:
        noun = ("member" if statement.member_count == 1
                else "members")
        parts.append(
            f"<p>{escape_html_text(statement.subject)} has "
            f"{statement.member_count} {noun}. Members are "
            "never counted for billing: the first member "
            "and the ten-thousandth cost the same — "
            "nothing — because there is no meter. To add "
            "people, add members; no seat is needed, "
            "because there are no seats.</p>")
    parts.append("<h2>Why there is no billing</h2>")
    parts.append("<ul>")
    for reason in statement.reasons:
        parts.append(f"<li>{escape_html_text(reason)}</li>")
    parts.append("</ul>")
    if audit is not None:
        if audit.honestly_empty:
            parts.append(
                "<p>Checked, not just claimed: this "
                "instance was inspected for billing "
                f"concepts — {audit.tables_scanned} tables, "
                f"{audit.columns_scanned} columns and "
                f"{audit.events_scanned} audit events — "
                "and none was found: no billing table, no "
                "seat or plan column, no billing event "
                "exists here.</p>")
        else:
            found = ", ".join(
                audit.offending_tables + audit.offending_columns
                + audit.offending_events)
            parts.append(
                "<p>Checked, and not empty: billing-shaped "
                "names were found — "
                f"{escape_html_text(found)} — and that is a "
                "defect against S-202, not a feature.</p>")
    parts.append(
        "<p>If you arrived looking for a plan to change, "
        "a seat to buy or a card to update: those "
        "controls do not exist anywhere in Samverk, in "
        "any menu, for anyone — this page is the whole "
        "of billing, and it is honestly empty. The "
        f"licence is {escape_html_text(statement.license_name)} "
        "and the full reasoning lives in docs/BILLING.md.</p>")
    parts.append("</body></html>")
    return "\n".join(parts)
