# Phase 6 — Retire local-dev worktree (deferred)

**Status: not executed.** Keep the local-dev worktree and DEV-only paths until you explicitly approve cleanup after Phase 5 success.

When approved later:

1. Confirm staging Releases + restore are the source of truth
2. Copy any remaining valuables off the worktree
3. Remove the worktree (`git worktree remove …`)
4. Optionally delete DEV-only scripts/paths and stale `cursor/*` branches (separate approval)

Do not run those steps from automation without a fresh human go-ahead.
