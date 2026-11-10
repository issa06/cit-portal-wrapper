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

## Phase 2: stabilization

Normal MFA/SAML login succeeded using existing Keychain entries without displaying values. An old cached UPRX probe returned HTTP 500 while the public entry was healthy. A bounded passwordless SSO rebuild distinguishes an expired app session from a service outage; it requests credentials only when the normal SSO flow explicitly does. Restarts subsequently restored SSO without password/TOTP submission. Session and complete JSF operations now have process/thread locks and private atomic cache writes.

## Phase 3: feature work

Live list-only navigation confirmed notices, grades and attendance. The existing attendance-shaped timetable parser failed against the actual grid. Structural diagnostics excluded academic values; the replacement weekly/intensive parser passed. Normal and full notice lists passed. No notice detail or state-changing operation was opened. Missing and unpublished data use explicit null/status/error classifications.

## Phase 4: MCP and Codex

MCP 2.3.0 real stdio initialize/list plus 13 synthetic tool responses passed. Live status, four Portal data queries and full notices passed with schema checks. Codex config gained one credential-free launcher block, preserving the existing server; rollback has a byte-roundtrip regression test. Two fresh subprocesses started from the actual configured launcher and returned authenticated/restored status. Desktop model-driven tool selection remains unverified until a new chat/app refresh.

## Phase 5: quality

Regression suite, ruff, locked dependencies, bounded outputs/retries/downloads, nonblocking cancellation and memory cache checks are recorded in TEST_RESULTS.md. The current-form reuse fix removed repeated SSO entry; PDF imports are lazy. Only synthetic fixtures are used in CI. Secret scanning findings were reviewed as test vectors/placeholders, with no production secret findings.

## Phase 6: delivery

New package 0.1.8 follows the verified 0.1.7 baseline because no earlier r1.8 source/tag was located. The new code is isolated under campus-mcp; the legacy package, original dirty checkout and feature-syllabus worktree remain preserved. Commits, pushed branch, scoped CI and the draft PR form the GitHub record. No merge, release publication, force push, remote server or tunnel is part of this delivery.

The repository has Issues disabled. Issue creation was therefore unavailable; progress, test evidence and remaining work are consolidated in the draft PR instead of changing repository settings.
