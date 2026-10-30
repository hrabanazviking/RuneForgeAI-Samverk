"""Empty-repository state (S-065).

A brand-new repository has no commits, and what it shows
instead of a file browser decides whether a new user ever
gets code into it: correct, copyable first-push instructions,
generated **per transport** from the instance's own
configured addresses.

The law:

- **Generated, never templated by hand.** Every command is
  built from the repository's real owner, name, and default
  branch and the instance's configured transport bases, so
  the instructions cannot drift from the truth the way a
  static help page does.
- **Copyable means copyable.** Command blocks carry no shell
  prompts, no leading `$`, no commentary inside the block —
  a user can select the whole block and paste it.
- **Honest about transports.** A transport the instance has
  not configured produces no instructions at all (named in
  `unavailable_transports`), never a guessed address. Both
  transports configured → both sets; neither → an empty set
  with the state itself still reported.
- **Only for empty repositories.** Once a first commit
  exists the state ends: `instructions_for` refuses with
  `repo_not_empty` so surfaces route to the normal
  repository view. Emptiness is read from git itself
  (no refs, no HEAD object), never from a flag.
- **Permission first.** S-054's `can_read` gates the state,
  as everywhere: a private repo's emptiness is as private
  as its content.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .accounts import User
from .permissions import can_read
from .refs import RefStore
from .repositories import RepositoryStore


class EmptyStateError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class TransportInstructions:
    transport: str                    # 'https' | 'ssh'
    clone_url: str
    new_repository_commands: tuple[str, ...]
    existing_repository_commands: tuple[str, ...]


@dataclass(frozen=True)
class EmptyRepoInstructions:
    full_name: str
    default_branch: str
    transports: tuple[TransportInstructions, ...]
    unavailable_transports: tuple[str, ...]


class EmptyStateService:
    def __init__(self, repositories: RepositoryStore, *,
                 http_base: str | None = None,
                 ssh_host: str | None = None,
                 ssh_user: str = "git"):
        self._repos = repositories
        self._http_base = self._clean_http_base(http_base)
        self._ssh_host = self._clean_ssh_host(ssh_host)
        if not ssh_user or any(c in ssh_user for c in " @/:"):
            raise EmptyStateError("ssh_user_invalid", "Bad SSH user.")
        self._ssh_user = ssh_user

    # -- state ------------------------------------------------------
    def is_empty(self, owner: object, repo: object) -> bool:
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise EmptyStateError("repo_not_found", "No such repository.")
        refs = RefStore(self._repos.path_for(current.owner, current.name))
        return refs.head_oid() is None and not refs.list_refs()

    # -- instructions -------------------------------------------------
    def instructions_for(self, viewer: User | None,
                         owner: object, repo: object) -> EmptyRepoInstructions:
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise EmptyStateError("repo_not_found", "No such repository.")
        if not self.is_empty(current.owner, current.name):
            raise EmptyStateError(
                "repo_not_empty",
                "This repository already has commits; the empty state is over.")
        branch = current.default_branch
        transports: list[TransportInstructions] = []
        unavailable: list[str] = []
        if self._http_base:
            url = f"{self._http_base}/{current.owner}/{current.name}.git"
            transports.append(self._build("https", url, current.name, branch))
        else:
            unavailable.append("https")
        if self._ssh_host:
            url = (f"ssh://{self._ssh_user}@{self._ssh_host}/"
                   f"{current.owner}/{current.name}.git")
            transports.append(self._build("ssh", url, current.name, branch))
        else:
            unavailable.append("ssh")
        return EmptyRepoInstructions(
            full_name=current.full_name, default_branch=branch,
            transports=tuple(transports),
            unavailable_transports=tuple(unavailable))

    @staticmethod
    def _build(transport: str, url: str, repo_name: str,
               branch: str) -> TransportInstructions:
        new_commands = (
            f'echo "# {repo_name}" >> README.md',
            "git init",
            "git add README.md",
            'git commit -m "first commit"',
            f"git branch -M {branch}",
            f"git remote add origin {url}",
            f"git push -u origin {branch}",
        )
        existing_commands = (
            f"git remote add origin {url}",
            f"git branch -M {branch}",
            f"git push -u origin {branch}",
        )
        return TransportInstructions(
            transport=transport, clone_url=url,
            new_repository_commands=new_commands,
            existing_repository_commands=existing_commands)

    # -- configuration hygiene -----------------------------------------
    @staticmethod
    def _clean_http_base(value: str | None) -> str | None:
        if value is None:
            return None
        text = str(value).strip().rstrip("/")
        if not (text.startswith("https://") or text.startswith("http://")) \
                or any(c in text for c in " \t\r\n"):
            raise EmptyStateError(
                "http_base_invalid", "The HTTP base must be an http(s) URL.")
        authority = text.split("://", 1)[1].split("/", 1)[0]
        if "@" in authority:
            raise EmptyStateError(
                "http_base_invalid",
                "The HTTP base must not carry credentials.")
        return text

    @staticmethod
    def _clean_ssh_host(value: str | None) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text or any(c in text for c in " \t\r\n/@"):
            raise EmptyStateError(
                "ssh_host_invalid", "The SSH host must be a host[:port].")
        return text


def render_text(instructions: EmptyRepoInstructions) -> str:
    """The plain-text empty-state page: headings plus the raw
    command blocks, nothing inside a block but commands."""
    lines = [
        f"{instructions.full_name} is empty.",
        "",
        "Create the first commit and push it:",
    ]
    for t in instructions.transports:
        lines += [
            "",
            f"Clone address ({t.transport}): {t.clone_url}",
            "",
            "…from a new local repository:",
            *t.new_repository_commands,
            "",
            "…from an existing local repository:",
            *t.existing_repository_commands,
        ]
    for name in instructions.unavailable_transports:
        lines += ["", f"The {name} transport is not configured on this instance."]
    return "\n".join(lines) + "\n"
