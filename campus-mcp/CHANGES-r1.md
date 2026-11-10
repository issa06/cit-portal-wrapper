# r1 implementation summary

## Portal

- Split authentication from Portal scraping.
- Added requests-based multi-step SSO form handling.
- Added RFC 6238 TOTP generation using only Python standard-library cryptography primitives.
- Added automatic password/MFA form field detection plus environment overrides.
- Added hidden-field preservation for CSRF/ViewState/SAML-style forms.
- Added hidden-form auto-post and basic client-side redirect following for SSO flows.
- Added cookie-session persistence under `~/.config/cit-campus-mcp/`.
- Added macOS Keychain storage through `/usr/bin/security`.
- Retained read-only notice, grade, attendance, timetable, and student-info parsing from the existing wrapper structure.
- Fixed returned `couese_name` typo to `course_name`.
- Removed automatic JSON/photo writes from parser calls.
- Face-photo data is excluded from the MCP student-info tool.

## manaba

- Added read-only form login with session-cookie persistence.
- Added course-link discovery.
- Added task/action-link discovery for report/quiz/survey/submission-like entries.
- Added same-host page text extraction.
- No submission/write endpoints are implemented.

## Student Documents

- Added bounded same-host crawler.
- Added HTML/PDF text search.
- Added direct HTML/PDF text extraction.
- Added default 0.2 second request spacing.

## MCP

- Uses MCP Python SDK v2 (`MCPServer`).
- stdio transport by default.
- 12 read-only tools.

## Validation performed in the build environment

- Python compile check: passed.
- Offline unit tests: 6 passed.
- Live CIT authentication: not run in the build environment because the runtime has no outbound DNS/network access and no user credentials.
