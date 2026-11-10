# CI artifacts (S-266)

Build artifacts are the files a check run produces -- the built
archive, the test report, the coverage page -- kept tied to the
commit and the check run that made them, under a stated retention
policy. The face is `samverk/ci_artifacts.py` (`CIArtifactsAPI`);
the rows live in migration 105 (`ci_artifacts` and
`ci_artifact_upload_sessions`, schema 104 to 105).

## The tie

An artifact names a commit (`oid`) and a check run by its S-246
name. Opening an upload resolves the standing `check_runs` row for
(repository, commit, name); no standing run, no artifact
(`check_run_not_found`). The row keeps the run's id, so the run page
(S-323) and the expiry job (S-267) read the same tie.

## The door

Every call resolves through S-238's API door and S-190's permission
engine, exactly as S-246's status and checks face does. Uploading
and deleting are writes (credential required, write rung, token
scope as ceiling); listing and downloading are reads. A missing or
unreadable repository is the one uniform `repo_not_found`. Chunk
calls must come from the session's own uploader. A completed upload
is witnessed as `repo.artifact.upload` and a deletion as
`repo.artifact.delete`, each naming the poster, credential kind and
token id; refused acts store and audit nothing.

## Upload, download, retention

Upload is chunked under S-012's law (S-259's wire): open, send
chunks strictly in order (at most 1 MiB each), complete. Promotion
stores the content type the bytes prove; a disguised declared type
is refused. Each artifact is at most 256 MiB; a check run carries
at most 100 artifacts; one name per run (`artifact_taken`).
Downloads serve the sniffed type and count on the row.

Retention is chosen at upload from 7, 30, 90, 180 or 365 days, or 0
(keep forever); the default is 90. The row stores the choice and
its computed `expires_at` (NULL when forever). Listings state the
expiry and mark expired artifacts; an expired artifact refuses
download (`artifact_expired`) and is never counted. Removing
expired bytes from disk is S-267's off-path sweep; storage
accounting joins S-268.
