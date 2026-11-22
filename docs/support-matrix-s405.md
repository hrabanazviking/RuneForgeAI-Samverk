# Support matrix -- S-405

The cross-platform promise ratified as a matrix,
judged at 401/416 against the tree as it stands
(S-402, the founder walk, still open in roadmap
order; this slice banks after S-402..S-404).
The full matrix ships at `docs/SUPPORT_MATRIX.md`
and lives in research file 45
(`research/45-cross-platform-architecture.md`);
this is its counted log.

Matrix cells judged: 12

- os_cpu: 4
- filesystem: 2
- deployment: 2
- service: 3
- reach: 1

| Cell | Status | Flips at |
|---|---|---|
| linux-x86-64 | NOT PROVEN | S-416 |
| linux-arm64-pi5 | NOT PROVEN | S-415 |
| windows-x86-64 | NOT PROVEN | S-416 |
| macos-arm64 | NOT PROVEN | S-416 |
| fs-case-sensitive | NOT PROVEN | S-408 |
| fs-case-insensitive | NOT PROVEN | S-408 |
| deploy-real-sshd | NOT PROVEN | Part XXII (S-415/S-416 cells) |
| deploy-real-http | NOT PROVEN | Part XXII (S-415/S-416 cells) |
| service-systemd | NOT PROVEN | S-412 |
| service-windows | NOT PROVEN | S-410 |
| service-launchd | NOT PROVEN | S-411 |
| browser-device-reach | NOT PROVEN | S-414 |

Verdict: **RATIFIED -- every cell NOT PROVEN**
