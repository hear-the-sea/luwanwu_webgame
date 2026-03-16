# ADR-002: Fail-open vs fail-closed policies

## Status: Accepted
## Date: 2026-03

## Context

The application relies on a cache layer (Redis / LocMem) in front of the database
for performance.  When that cache becomes unavailable, each subsystem must decide
whether to deny service (fail-closed) or degrade gracefully (fail-open).  A blanket
policy in either direction is inappropriate: authentication shortcuts could let
attackers hijack sessions, while blocking the entire UI over a transient cache
hiccup harms all players unnecessarily.

## Decision

### Fail-closed paths (security-critical)

`SingleSessionMiddleware` always falls back to the database when the cache is
unreachable.  If `cache.get` raises, the middleware queries `UserActiveSession`
directly.  If `cache.add` for the verification marker fails, the middleware forces
a DB check (`_should_verify_matching_session` returns `True`) rather than trusting
a potentially stale cached session key.  Session mismatches result in `logout()` --
never silently allowed.

### Fail-open paths (display / stats / chat)

- **Context processor (`gameplay.context_processors`):** `_safe_cache_get` /
  `_safe_cache_set` swallow exceptions and fall back to a process-local LRU cache,
  then to the database.  If every tier fails, counters default to `0` via
  `_build_default_context()`.  The page renders normally with placeholder stats.
- **World chat (`WorldChatConsumer`):** History retrieval catches `RedisError` and
  returns an empty list with `_history_degraded=True`, signalling the client.
  Display-name resolution falls back to `"未知玩家"` on DB errors.  Message
  *sending* is fail-closed (rejects and optionally refunds the trumpet item) so
  that messages are never silently lost.

## Consequences

- Infrastructure outages may temporarily show stale or zero counts for online users,
  unread messages, and sidebar stats, but the game remains navigable.
- Authentication and session enforcement are never relaxed; a cache failure may add
  latency (extra DB round-trip) but cannot bypass the single-session constraint.
- Chat history may appear empty during a Redis outage, but the client receives an
  explicit degraded-status flag to display an appropriate notice.
