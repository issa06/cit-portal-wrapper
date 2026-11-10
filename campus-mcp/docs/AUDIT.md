# Audit — 2026-11-10 JST

## Phase 1: confirmed

- macOS 26.6.2, arm64; Codex CLI 0.167.0; default Python 3.15.2.
- Validation uses an isolated Python 3.12.14 environment; Python 3.15 is not claimed supported.
- Authoritative remote: `https://github.com/issa06/cit-portal-wrapper` (existing public fork).
- Remote main: `122be56f3543dd41b834f361a534e5886928fd92`; branches main and feature-syllabus; no tags, issues or PRs at audit time (authenticated API).
- Existing local wrapper main: `a7af3bd`, behind remote by one commit, with staged/unstaged work and a feature-syllabus worktree. Left untouched. No unpublished branch commits found in that repository.
- Separate Downloads r1.7: package `cit-campus-mcp==0.1.7`, no Git metadata. MFA/TOTP timing, SAML bridge, cookie/SSO restoration, 12 MCP tools. Imported only source, synthetic tests, scripts and documentation into `campus-mcp/`. No private HTML, credentials, session caches or environment files imported.
- r1.8 not found by directory/name search in the user home and Spotlight. Reported 15/39 notice parsing results are not treated as reproduced evidence.
- Baseline: 22 synthetic tests PASS with MCP SDK 2.3.0. Fresh install needed a separate subproject because the legacy setup.py imports the legacy package during build.
- Keychain entries and existing cookie cache present; values were not printed. Existing Codex config contains one other MCP server and no CIT server.

## Findings to address

- Every Portal tool starts authentication again; no operation lock around mutable JSF state.
- menu_post parses HTML as XML; partial-response CDATA not decoded reliably.
- Authentication logs/errors may contain URLs, form metadata or remote error text.
- Session cache temporary file permissions are applied after writing; fixed temporary filename races.
- Empty/changed/unpublished pages are inconsistently classified; grade blank evaluation is invented as 履修中.
- Timetable currently reuses attendance parser and cannot substantiate a weekly timetable.
- MCP success types exist but no bounded pagination or stable error classification.

Later phases and remaining unverified behavior are recorded in TEST_RESULTS.md and CHANGELOG.md.
