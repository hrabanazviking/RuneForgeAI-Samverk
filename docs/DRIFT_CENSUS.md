# Drift census (S-343)

Roadmap S-343: **a weekly read-only job comparing mirror heads
against source heads; drift beyond the sync interval is reported
to the owner, quietly and factually.**

`samverk/drift_census.py` is that job. Part XVII gave Samverk
mirrors a schedule (S-331), an honest status (S-332), a first
verified pass (S-336), private originals (S-337), and imported
metadata (S-338). None of those looked again later. The census is
the standing look.

## The laws

- **Read-only, always.** The census compares and reports. It never
  syncs, never fetches into a mirror, and never writes a mirror
  record or touches a source. Source heads are read through
  S-014's `ls-remote` seam (`run_git_ls_remote_refs` -- a listing,
  not a fetch); mirror heads are read from the mirror's own refs
  through S-051's `RefStore`. A census run leaves every ref and
  every `repo_mirrors` row exactly as it found them, and adds no
  audit event.
- **Drift is a fact about time.** A mirror whose heads differ from
  its source's heads is *behind*. It is *drifted* only when it has
  stayed behind beyond its own sync interval (S-331's per-mirror
  interval; the 24-hour founding cadence by default), measured
  from its last successful sync (S-332's `last_success_at` -- a
  failed attempt never moves that moment). Exactly at the
  interval is still within it. Behind within the interval is the
  ordinary state between syncs and is reported as behind, not as
  drift.
- **Nothing is guessed.** A mirror with differing heads and no
  recorded successful sync is *never synced*. A source that
  cannot be read makes that mirror's entry *unreadable*, with the
  recorded detail beside the words; it never stops the census and
  never hides the other mirrors.
- **Weekly, off the request path.** `run_census` is the job entry
  point, run by an operator or a scheduler as
  `python3 -m samverk.drift_census <db-path> <repos-root>`. The
  pure `census_due` judgement names the weekly cadence
  (`CENSUS_INTERVAL_SECONDS`, seven days): a census is due when
  none has run, or when the last one is a week or more old. No
  request handler calls the census; the render page only displays
  a report a census already made.
- **Quiet and factual.** The report counts what it checked and
  states each mirror's state in plain words. It carries no alarm
  language: drift is a fact to act on at the owner's pace, stated
  once, exactly as found.

## The states

| State | Meaning |
| --- | --- |
| `in_sync` | The mirror's heads match its source's heads. |
| `behind` | The source has moved since the last successful sync, within the sync interval. |
| `drifted` | The source moved beyond the sync interval since the last successful sync. |
| `never_synced` | Heads differ and no successful sync is recorded. |
| `unreadable` | The source's heads could not be read; the detail is recorded on the entry. |

Ref comparison is S-336's `compare_ref_maps` over heads and tags:
matched, missing (advertised by the source, absent in the mirror),
extra (in the mirror, not advertised), and diverged (in both, at
different object ids) counts ride every entry, and
`entry_to_dict` / `census_to_dict` expose names, states, times,
and counts only -- no source, no secret.

## Storage and taxonomy

None. The census is a read-only job over records S-070, S-331,
and S-332 already keep, so it takes **no migration** (schema 139
stands) and claims **no new audit event** (the taxonomy stands at
138). A read-only job that wrote records to report on records
would be neither.

## Known boundary

The census reads source heads without a mirror credential: a
private source that refuses an unauthenticated listing is
reported *unreadable* with the refusal as its detail -- stated,
never hidden, and never worked around by the census itself.
Credential-aware census reads are a possible later slice, not
this one's silent behaviour.
