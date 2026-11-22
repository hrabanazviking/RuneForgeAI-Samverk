# Layout shell (S-382)

One navigation skeleton for all surfaces: `samverk/layout_shell.py`
holds the surface registry, the primary navigation order and the
link graph between surfaces. A surface outside the registry does
not exist for navigation; a registered surface unreachable from
home fails `audit_shell`.

## Findability — the release gate

`tools/findability_check.py` walks three timed tasks through the
graph from home and must pass for every release:

| Task | Path | Steps | Time |
| --- | --- | --- | --- |
| Mint a token | home > settings > tokens | 2 | 8s |
| Create a repo | home > new_repository | 1 | 4s |
| Add a mirror | home > repositories > mirrors > new_mirror | 3 | 12s |

Budgets: at most 4 steps and 30 seconds per task (one page
decision = 4s). The script exits non-zero and names the failing
task when any task breaks. Rendering marks the current surface
in text (`aria-current`), never by colour alone.
