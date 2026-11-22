# Keyboard completeness (S-388)

Every action is reachable by keyboard and focus is visible
everywhere: `samverk/keyboard_completeness.py` holds the per-surface
tab orders, the action-to-control keyboard routes, and the declared
focus outline (>= 2px, standing at 3px) for every focusable.
`audit_keyboard` names surfaces without an order, keyboard traps
(an order not ending at the exit stop back to the S-382 nav),
S-386 targets the keyboard cannot reach, invisible focus, and
unreachable actions. The battery walks S-382's three findability
tasks keyboard-only, stop by stop. Nav targets are global chrome:
the audit judges them reachable when any surface's order carries
them, which is how the shell actually renders.
