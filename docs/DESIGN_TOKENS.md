# Design tokens (S-381)

The Lawbook's numbers as code. `samverk/design_tokens.py` is
the one registry every surface draws from; pages take the
numbers only through `render_css_variables`.

| Law | Number | Registry |
| --- | --- | --- |
| Corner cuts | 6-12 px | 6 / 9 / 12 (soft, standard, deep) |
| Frame strengths | at most 3 | 1 / 2 / 3 px |
| Accent budget | 5-12% of a surface | judged per page by `check_accent_budget` |
| Dark surfaces | at least 4 values | 5-step darkness ladder |
| Body text | 14-18 px | body 16, small 14 (the floor), heading 18 |

`validate_registry` re-judges the standing registry itself:
an edit that breaks the law fails the battery instead of
shipping quietly. No store, no audit event, no migration --
schema 140 / taxonomy 142 stand.
