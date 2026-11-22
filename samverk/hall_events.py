"""Repo events into halls (S-367).

Pushes, pull requests, issues, and releases post into a
chosen Samtal hall as concise cards with links — under
the frozen S-361 event-bridge section: per-hall opt-in
and mute, idempotency-keyed delivery, exactly-once at
the seam (S-226's rule), and payloads privacy-filtered
so a private repo's events never reach a hall whose
members lack rights.

Opt-in is per hall and per repo: a hall hears nothing
about a repo until it opts in, and may name the event
kinds it wants (default: all four frozen kinds). Mute
is the per-hall off-switch — by repo, or by repo and
kind — and wins over opt-in until unmuted. Delivery is
exactly-once: the hall's delivered-key ledger rides
the settings table, and re-posting an envelope whose
idempotency key already landed returns the standing
card (already_delivered) instead of a second card.

Every envelope is judged by S-361's own
validate_event_envelope before any local law runs, so
an unknown kind, a missing idempotency key, and a
private repo aimed at an open hall are refused with
the contract's own reasons. No migration, no new
taxonomy event: subscriptions, mutes, cards, and the
delivery ledger all ride the settings table.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from .accounts import User
from .escaping import escape_html_attr, escape_html_text
from .seam_contract import (EVENT_KINDS, SeamContractError, seam_enabled,
                            validate_event_envelope)


class HallEventError(ValueError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class HallCard:
    hall_id: str
    kind: str
    repo: str
    title: str
    link_path: str
    actor_name: str
    idempotency_key: str
    already_delivered: bool = False

    def summary(self) -> str:
        return f"{self.kind}: {self.repo} — {self.title}"


class HallEventService:
    def __init__(self, conn, *, settings: dict | None = None):
        self._conn = conn
        self._settings = settings

    # -- storage helpers (settings table) -------------------
    def _load(self, key: str, default):
        row = self._conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return default if row is None else json.loads(row["value"])

    def _save(self, key: str, value) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, json.dumps(value, sort_keys=True)))

    def _subs_key(self, hall: str) -> str:
        return f"seam.hall.{hall}.subscriptions"

    def _mute_key(self, hall: str) -> str:
        return f"seam.hall.{hall}.muted"

    def _cards_key(self, hall: str) -> str:
        return f"seam.hall.{hall}.cards"

    def _ledger_key(self, hall: str) -> str:
        return f"seam.hall.{hall}.delivered"

    # -- guards ---------------------------------------------
    def _require_seam(self) -> None:
        if not seam_enabled(self._settings):
            raise HallEventError(
                "seam_disabled", "The Samtal seam is not enabled.")

    @staticmethod
    def _clean(value: object, reason: str, message: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise HallEventError(reason, message)
        return value.strip()

    # -- opt-in and mute --------------------------------------
    def opt_in(self, actor: User | None, hall_id: object, repo: object,
               kinds=None) -> dict:
        """Opt a hall in to a repo's events (named kinds, or all)."""
        self._require_seam()
        if actor is None:
            raise HallEventError(
                "actor_required", "Opting a hall in needs a signed-in actor.")
        hall = self._clean(hall_id, "hall_required", "A hall is required.")
        repo_name = self._clean(repo, "repo_required", "A repo is required.")
        wanted = list(EVENT_KINDS) if kinds is None else list(kinds)
        for kind in wanted:
            if kind not in EVENT_KINDS:
                raise HallEventError(
                    "event_kind_unknown", f"Unknown event kind: {kind!r}.")
        subs = self._load(self._subs_key(hall), {})
        subs[repo_name] = sorted(set(wanted))
        self._save(self._subs_key(hall), subs)
        return dict(subs)

    def opt_out(self, actor: User | None, hall_id: object, repo: object) -> dict:
        self._require_seam()
        if actor is None:
            raise HallEventError(
                "actor_required", "Opting a hall out needs a signed-in actor.")
        hall = self._clean(hall_id, "hall_required", "A hall is required.")
        repo_name = self._clean(repo, "repo_required", "A repo is required.")
        subs = self._load(self._subs_key(hall), {})
        subs.pop(repo_name, None)
        self._save(self._subs_key(hall), subs)
        return dict(subs)

    def mute(self, actor: User | None, hall_id: object, repo: object,
             kind: object = None) -> list:
        """Mute a repo in a hall (all kinds, or one named kind)."""
        self._require_seam()
        if actor is None:
            raise HallEventError(
                "actor_required", "Muting needs a signed-in actor.")
        hall = self._clean(hall_id, "hall_required", "A hall is required.")
        repo_name = self._clean(repo, "repo_required", "A repo is required.")
        entry = repo_name if kind is None else f"{repo_name}:{kind}"
        if kind is not None and kind not in EVENT_KINDS:
            raise HallEventError(
                "event_kind_unknown", f"Unknown event kind: {kind!r}.")
        muted = self._load(self._mute_key(hall), [])
        if entry not in muted:
            muted.append(entry)
        self._save(self._mute_key(hall), muted)
        return list(muted)

    def unmute(self, actor: User | None, hall_id: object, repo: object,
               kind: object = None) -> list:
        self._require_seam()
        if actor is None:
            raise HallEventError(
                "actor_required", "Unmuting needs a signed-in actor.")
        hall = self._clean(hall_id, "hall_required", "A hall is required.")
        repo_name = self._clean(repo, "repo_required", "A repo is required.")
        entry = repo_name if kind is None else f"{repo_name}:{kind}"
        muted = [m for m in self._load(self._mute_key(hall), []) if m != entry]
        self._save(self._mute_key(hall), muted)
        return list(muted)

    def is_muted(self, hall_id: str, repo: str, kind: str) -> bool:
        muted = self._load(self._mute_key(hall_id), [])
        return repo in muted or f"{repo}:{kind}" in muted

    # -- delivery ---------------------------------------------
    def post_event(self, hall_id: object, *, kind: object, repo: object,
                   title: object, link_path: object, actor_name: str = "",
                   repo_private: bool = False, hall_restricted: bool = False,
                   idempotency_key: object = "") -> HallCard:
        """Post one repo event into a hall as a concise card.

        Judged by the S-361 envelope law first, then the
        hall's own opt-in and mute; delivery is exactly-once
        under the envelope's idempotency key.
        """
        self._require_seam()
        hall = self._clean(hall_id, "hall_required", "A hall is required.")
        try:
            validate_event_envelope({
                "kind": kind, "idempotency_key": idempotency_key,
                "repo_private": repo_private, "hall_restricted": hall_restricted})
        except SeamContractError as exc:
            raise HallEventError(exc.reason, str(exc)) from exc
        repo_name = self._clean(repo, "repo_required", "A repo is required.")
        title_text = self._clean(title, "title_required", "A card needs a title.")
        link = self._clean(link_path, "link_required", "A card needs a link.")
        key = str(idempotency_key)
        ledger = self._load(self._ledger_key(hall), [])
        if key in ledger:
            for card in self.cards_for(hall):
                if card.idempotency_key == key:
                    return HallCard(**{**card.__dict__,
                                       "already_delivered": True})
            raise HallEventError(
                "delivery_ledger_broken", "Key delivered but its card is gone.")
        subs = self._load(self._subs_key(hall), {})
        if kind not in subs.get(repo_name, []):
            raise HallEventError(
                "not_opted_in", "This hall has not opted in to that repo event.")
        if self.is_muted(hall, repo_name, str(kind)):
            raise HallEventError(
                "hall_muted", "This hall has muted that repo event.")
        card = HallCard(hall_id=hall, kind=str(kind), repo=repo_name,
                        title=title_text, link_path=link,
                        actor_name=str(actor_name), idempotency_key=key)
        cards = self._load(self._cards_key(hall), [])
        cards.append({"hall_id": card.hall_id, "kind": card.kind,
                      "repo": card.repo, "title": card.title,
                      "link_path": card.link_path,
                      "actor_name": card.actor_name,
                      "idempotency_key": card.idempotency_key})
        self._save(self._cards_key(hall), cards)
        ledger.append(key)
        self._save(self._ledger_key(hall), ledger)
        return card

    def cards_for(self, hall_id: str) -> list[HallCard]:
        """The cards a hall has received, in delivery order."""
        return [HallCard(**row)
                for row in self._load(self._cards_key(hall_id), [])]


def render_card(card: HallCard) -> str:
    """The concise hall card for one repo event, with its link."""
    who = (f" by {escape_html_text(card.actor_name)}"
           if card.actor_name else "")
    return (
        f'<article class="hall-card" data-kind="{escape_html_attr(card.kind)}">'
        f'<a href="{escape_html_attr(card.link_path)}">'
        f"{escape_html_text(card.summary())}</a>"
        f"<span>{escape_html_text(card.kind)} in "
        f"{escape_html_text(card.repo)}{who}</span></article>\n")
