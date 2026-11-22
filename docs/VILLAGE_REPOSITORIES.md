# Village repositories (S-365)

A Samtal hall may own repositories in Samverk. The hall stands as an
organization (S-185); hall membership is org membership (owner /
member). What hall members may do in a hall repo comes from one
owner-defined mapping — hall role to repo role on the S-189 ladder
(read / triage / write / maintain / admin, or none).

The mapping is **shown before saving**: `preview_mapping` renders its
exact effect in plain words and returns a token over the canonical
mapping; `save_mapping` refuses any mapping not previewed under that
token (`mapping_not_previewed`). Saving applies the mapping through
the standing team machinery — two hall teams (members, owners) linked
to the repo and graded via TeamPermissionStore — and membership is
synced into those teams (`sync_hall` after membership changes), so
roles resolve through the S-190 permission engine alone. There is no
second permission law for halls.

Guards: seam disabled refuses (`seam_disabled`); only a hall owner
may preview/save/sync (`not_hall_owner`); unknown hall roles, repo
roles, halls, and repos are refused by name. No migration and no new
taxonomy event — the saved mapping rides the settings table.
