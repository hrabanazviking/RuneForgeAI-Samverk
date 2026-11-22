# Agent parity (S-364) — the Astrid law

Samtal's agent principals hold Samverk accounts with keys
and tokens exactly as humans do (`samverk/agent_parity.py`),
under the frozen S-361 contract and standing on S-362's link.

## Equal seats

- Provisioning (`AgentParityService.provision_agent`) seats
  an agent through the standing `AccountStore.register`
  door — same username law, password law, reserved names,
  and registration gates a human faces. No agent-only
  account type, flag, or rank exists in the account record.
- The agent then holds SSH keys through the standing
  `SshKeyStore` and access tokens through the standing
  `AccessTokenStore` — same scopes, same expiry law, same
  revocation. The battery proves key and token parity
  side-by-side with a human account, including revocation.

## Provenance shown, never rank

- Provenance lives on the S-045 identity link (provider
  `samtal`, the principal id) and is shown wherever the
  seat is presented (`render_seat_page`): "Agent — Samtal
  principal …" for an agent, "Human" otherwise.
- Provenance is never a rank, score, tier, ordering, or
  permission input; the seat page deliberately carries no
  such field (battery-checked).

## Guards

- The seam must be enabled (`seam_disabled`); a principal
  already linked is refused (`principal_already_linked`)
  rather than silently re-seated; parity reads are pure.
