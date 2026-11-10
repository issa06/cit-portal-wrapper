# Changelog

## 0.1.8 — 2026-11-10

- Preserve r1.7 Keychain, server-time-aware TOTP, SAML bridge and durable SSO restore.
- Serialize JSF operations/authentication across threads/processes; reuse latest forms and HTTP sessions.
- Recover failed UPRX restore probes through passwordless SSO before fresh credentials; retain caches on outages.
- Atomic unique 0600 cookie writes; reject unsafe/corrupt/symlink caches and avoid partially loaded cookies.
- Enforce HTTPS and configured hosts on redirects. Bounded GET-only status retries, no POST connect retries; 8MiB cap.
- Allowlisted MCP/CLI errors and state diagnostics; no remote URLs, forms, error text, cookie metadata or credential repr.
- Decode HTML and JSF CDATA/ViewState; normalize/deduplicate notices; bound full-list pagination and detect loops.
- Parse observed weekly timetable grids and intensive-course tables separately from attendance.
- Normalize attendance states and label local counts; preserve missing values.
- Match dynamic grade IDs, preserve blank evaluation/GPA markers and distinguish unpublished pages.
- Keep 12 tool names; add portal_query with bounded paging, filters, original fetched_at and source.
- 128KiB response limit, event-loop-safe sync I/O, timeout/cancellation, separate 30-second memory data cache.
- Lazy PDF import, locked dependencies, ruff, regression/protocol/live tests, Codex installer/rollback and synthetic CI.
- Preserve old wrapper and its dirty worktree in a separate local checkout; import only r1.7 code/synthetic tests/docs.
- Validate on macOS arm64, Python 3.12.14, MCP 2.3.0. See docs/TEST_RESULTS.md for evidence and limitations.
- No tag/release publication, merge, force push, public server or tunnel deployment.

Compatibility: timetable now returns weekly/intensive records rather than attendance-shaped data. Missing values can be null. Unknown/unpublished pages fail explicitly. Large legacy lists return a size error; use portal_query. Keychain names and safe v2 cookie caches are unchanged.

## 0.1.7 — preserved baseline

Downloads r1.7 package; 22 synthetic tests passed before changes. See CHANGES-r1.7.md and earlier files. The separately reported r1.8 artifact was not found; it is not claimed recovered or compared.
