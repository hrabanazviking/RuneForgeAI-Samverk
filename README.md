# RuneForgeAI-Samverk

Samverk is the together-work, your own forge that stands alone yet can nestle inside Samtel. It speaks the old Git tongue, opens its doors to your hand, and lets your village's talk become work—soft, yours to reshape, whether it lives by itself or beside the longhouse fire.

# Samverk — the together-work, in founding

**Samverk** (Old Norse *samverk*: work done together, joint labour) is a
**clean-room, open-source version-control application**: an extremely robust,
highly secure forge with the feature-set GitHub's users know — repositories,
issues, pull requests, code review, organizations, search, releases, and the
rest — studied from GitHub's *public behaviour and documentation* and built
from scratch as our own work. It copies **no** GitHub code, **no** assets,
**no** proprietary design. What GitHub *does* is public fact; how Samverk
does it is Samverk's own engineering.

Named by the Skald of Mythic Engineering and chosen by Volmarr, 2026-10-29 —
*Samtal* is the together-talk, *Samkoma* is the together-gathering, and
*Samverk* is the together-work: the place where the village's talk becomes
the village's work.

---

![https://github.com/hrabanazviking/RuneForgeAI-Samverk/blob/main/Lets_Build_Our_Own_App_1.png](https://github.com/hrabanazviking/RuneForgeAI-Samverk/blob/main/Lets_Build_Our_Own_App_1.png)

---

## Why it exists

Volmarr tried the self-hosted forges on offer and was fought at every door —
a forge whose own admin could not find the control to mint a token is a
forge that has failed its founding duty. Samverk's founding virtues are the
answer to that failure:

1. **User-friendliness is law.** Every everyday control must be findable by
   its owner without a manual, a forum post, or a prayer. If Volmarr cannot
   find it, it does not exist — however clever the code beneath it.
2. **Security is the spine, not a coat of paint.** The threat model is
   written before the features; credentials are stored so a database leak is
   not a credential leak; every security claim is proven by a test or
   honestly marked **NOT PROVEN**.
3. **Sovereignty.** Samverk runs on its owner's own machines, natively —
   **no Docker, ever** — under a systemd unit, with its data in the owner's
   own directories. No account on anyone else's computer, no landlord.
4. **Standard git, standard habits.** An unmodified git client clones,
   pushes, and pulls against Samverk (SSH and smart HTTP). Workflows shaped
   like the ones GitHub taught the world carry over, so nobody relearns
   their craft to come home.
5. **Standalone first, Samtal-hearted.** Samverk is a complete application
   on its own. It can *also* be woven into **Samtal** (Volmarr's sovereign
   village chat) as the village's code-and-file-sharing heart — but the seam
   is a seam: Samverk never requires Samtal, and Samtal never swallows it.
6. **Cross-platform, completely.** Samverk works on all operating systems
   and all kinds of hardware: the server runs on Linux, Windows, and
   macOS, on x86-64 and ARM down to a Raspberry Pi — and the web face is
   reachable from any modern browser on any device. Portability is a
   founding law, proven platform by platform, never assumed.

Samverk's face is designed under Volmarr's Cyber-Viking Visual Design
Lawbook — *really nice* is a founding requirement, not a garnish.

Samverk also inherits a standing duty: **the backup of Volmarr's own work.**
It mirrors his original repositories from GitHub onto his own machines and
keeps them current, so his creations never live only under a landlord's roof.

## Status

**Founding phase (2026-10-29).** This repository currently holds:

- the AGPL-3.0 `LICENSE` (placed by Volmarr at the founding),
- `research/` — the clean-room research corpus: 46 study areas, each an
  empty file awaiting its study, with `research/INDEX.md` naming the
  question each must answer,
- `docs/SAMVERK_MASSIVE_ROADMAP.md` — the massive slice roadmap for the
  whole build,
- `PROJECT_MEMORY_MAP.md` — the living map of this project, per the Forge
  Protocol,
- the `samverk/` package and its counted test batteries — Part I of the
  roadmap (the security spine, S-001 onward) is built and proven slice
  by slice; see the project map for the current position,
- `docs/CLAIMS_REGISTER.md` — every security claim in this README,
  mapped to the battery that proves it or honestly marked NOT PROVEN
  with the roadmap part that owns its proof.

What is proven will be counted; what is not proven will be named
NOT PROVEN, in this README and everywhere else.

## Licence

**GNU Affero General Public License v3.0** (AGPL-3.0) — see `LICENSE`.
Samverk is free software: run it, study it, reshape it; if you offer your
reshaped version to others over a network, offer them the same freedom in
return. That reciprocity is why the AGPL was chosen: the together-work
stays together.
