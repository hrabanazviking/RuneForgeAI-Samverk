# Alt-text law (S-390)

Every image in the UI and docs carries real alt text.
`samverk/alt_text_law.py` states the law once: `judge_alt` refuses
missing, generic ("image", "photo", "diagram"), and bare-filename
alt, and requires diagrams to be described in at least five words;
`decide_alt` honours a user-supplied alt that passes (the avatar
rule profiles have carried since S-185) and falls back to the
authored alt when the user's fails; `audit_rendered` and
`audit_docs` sweep rendered HTML and the docs tree under the same
judge. The docs tree audits clean.

## In-slice fix (bug law)

The audit caught the markdown pipeline rendering author images
with `alt=""` or `alt="image"` when the author wrote no real alt.
The pipeline now takes the law's floor — `fallback_alt` names the
image file (media_view's standing pattern) — so a content image
never renders alt-less or generically labelled, while a real
author alt is preserved exactly.
