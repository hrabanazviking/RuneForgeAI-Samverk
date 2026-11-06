# S-153–S-168: merge engine, atomicity and release gates

**Immediate next roadmap task:** S-153 merge commits, then S-154 squash and S-155 rebase. **Not yet implemented at the 2026-11-06 snapshot.**

## The merge transaction

1. Resolve PR and base/head repositories with role/access check. Refuse draft/closed PRs.
2. Snapshot exact base OID and head OID; fetch review freshness, required checks, branch policies and CODEOWNERS gates at those OIDs.
3. Determine mergeability off-path. No ref move while evaluating or building a commit.
4. Build result using verified Git algorithms/plumbing; isolate conflicts and do not modify current refs yet.
5. Recheck policy and expected old base ref; atomically publish with compare-and-swap. If base moved, abort and require fresh mergeability calculation.
6. Commit immutable merge outcome and closing actions to SQLite with recoverable outbox. If state commit fails after Git succeeds, reconcile on startup rather than lie.
7. Notify users only after durable state, using idempotent event identifiers.

## Three distinct semantics

| Mode | Graph | Metadata expectations | Special risk |
|---|---|---|---|
| Merge commit S-153 | preserve side branch ancestry with two parents | default subject/body editable, merge actor recorded | race and duplicate merge |
| Squash S-154 | one new base commit represents combined diff | record original PR/head and contributors | author attribution, lost internal commit lineage |
| Rebase S-155 | replay head commits onto updated base | retain source/result OID mapping | conflicts and changed commit identity |

Use Git's built-in merge algorithms (e.g., `merge-tree` and merge/rebase plumbing where appropriate) instead of inventing content-level merge rules. Do not infer conflict-free from empty `git diff` alone.

## Branch protection ordering

Visibility/authorization → draft state → rule preconditions → review freshness and code-owner approval → check run status bound to current SHA → conflict calculation → final ref CAS → durable audit/close. Show missing requirement plainly. A privileged merge bypass must be explicit and audited.

## Difficult cases

- Head branch deleted, force-pushed or moved between preview and merge.
- Base branch moves concurrently; two operators press Merge.
- Cross-fork PR with no maintainer edits; canonical merge still targets base repository.
- Existing merge commit in head, rename conflicts, binary conflict, CRLF normalization.
- Required checks green for old SHA but pending for new head.
- Closing-keyword event committed to SQLite, but webhook worker crashes.
- Commit constructed successfully, then ref update fails; unreachable result objects may be garbage-collected later.

## Acceptance gate matrix

```text
for method in [merge_commit, squash, rebase]:
  for origin in [same_repo, fork]:
    for actor in [owner, writer, unauthorized]:
      for base_state in [unchanged, concurrent_move]:
        assert graph_or_refusal_is_correct
        assert only_authorized_actor_moves_base
        assert no_double_merge_on_retry
        assert audit + issue closing correspond to actual result
```

Add conflict fixtures, stale reviews and missing checks. Verify Git graph with `git log --graph --all`, exact parent/OID structure and ref contents. Then test through live HTTP and keyboard-accessible UI, not merely direct `PullRequestStore` calls.

## References

- https://git-scm.com/docs/git-merge-tree
- https://git-scm.com/docs/git-merge
- https://git-scm.com/docs/git-rebase
- https://git-scm.com/docs/git-update-ref
