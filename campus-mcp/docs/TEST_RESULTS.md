# Verification — 2026-11-10 JST

Environment: macOS 26.6.2 arm64, Python 3.12.14, MCP SDK 2.3.0, pytest 9.2.0, ruff 0.17.4. Baseline r1.7: **22 PASS**. Initial stabilization: **72 PASS**. With notice detail follow-up: **94 PASS / 0 FAIL**. GitHub CI evidence is recorded in the PR; CI never receives university credentials or data.

## Requested cases

PASS under Synthetic means a fixture/policy/protocol regression test passed. It does not claim a live university outage or grade-publication state was reproduced. Live tests used the existing account, normal authentication and read-only list navigation. Only status/timing information was printed; no academic rows, notice text, screenshots, credentials or cookie files were saved to the repository or CI.

| # | Case | Synthetic | Live | Evidence / limits |
| --- | --- | --- | --- | --- |
| 1 | Initial startup | PASS | PASS | Fresh wheel install; subprocess initialize |
| 2 | MCP initialize | PASS | PASS | Official SDK client against stdio |
| 3 | tools/list | PASS | PASS | 15 tools, descriptions and schemas |
| 4 | Each tool normal response | PASS | PASS / NOT RUN | All 15 synthetic; live Portal status + 4 datasets + full notices + already-read detail/file. Other 7 tools NOT RUN live |
| 5 | Unlogged state | PASS | NOT RUN | Missing credentials mapped to auth error; did not log the user out |
| 6 | Normal login | PASS | PASS | Real credential + TOTP + SAML/UPRX flow succeeded |
| 7 | MFA requested | PASS | PASS | Synthetic missing-seed MFA_REQUIRED; real configured MFA succeeded |
| 8 | Existing session reuse | PASS | PASS | Durable SSO fixtures; configured launcher reported restored_session=true |
| 9 | Expired session | PASS | PASS (restore) | Stale preexisting UPRX cache returned 500, then normal auth succeeded. Synthetic mid-operation expiry retried once; live mid-operation expiry NOT RUN |
| 10 | Auth failure | PASS | NOT RUN | Rejecting form stops after one credential submission; did not send bad real credentials |
| 11 | Network disconnect | PASS | NOT RUN | ConnectionError classification; no reauthentication/retry of parser operation |
| 12 | Timeout | PASS | NOT RUN | Timeout classification, cache retention, nonblocking tool loop |
| 13 | Rate limit / transient service | PASS | NOT RUN | 429/503 classification, GET-only retry policy, no forced credentials on 503 |
| 14 | HTML structure change | PASS | PASS (failure found/fixed) | Old timetable parser failed on live DOM; dedicated parser then passed |
| 15 | Empty board | PASS | NOT RUN | Explicit empty marker differs from unexpected HTML |
| 16 | Multiple board pages | PASS | NOT RUN | Synthetic paging/dedup/repeated-page regression; full-board live navigation PASS, actual multiple live page controls unconfirmed |
| 17 | Exceptional timetable data | PASS | PASS (weekly/intensive) | Multi-weekday occurrences and intensive courses preserved; live cancellation/makeup data NOT RUN |
| 18 | Missing attendance | PASS | NOT RUN | Null/unknown status, missing count, local summary distinction |
| 19 | Unpublished grades | PASS | NOT RUN | Explicit unpublished page vs changed HTML; blank evaluation not fabricated |
| 20 | Concurrent access | PASS | NOT RUN | 6 concurrent operations fetch once; bounded file-lock contention |
| 21 | Cache refresh | PASS | PASS (warm cache) | TTL and explicit refresh synthetic; live repeated MCP query retains original data and timestamp |
| 22 | Recovery after restart | PASS | PASS (process) | Private cookie save/reload; 2 fresh configured launcher processes restore SSO. Actual Mac reboot NOT RUN |
| 23 | JSON schema | PASS | PASS | jsonschema validates outputSchema on synthetic and real stdio responses |
| 24 | No secret output | PASS | PASS (observed scope) | Sentinel credentials/URLs absent from protocol errors/stderr, private repr/cache, field-limited live status. Not a formal proof of all possible server behavior |

## Commands and coverage

```bash
uv sync --locked --extra dev --no-editable --python 3.12
.venv/bin/python -m pytest -q
.venv/bin/ruff check src tests scripts
.venv/bin/ruff format --check src tests scripts
.venv/bin/python scripts/smoke_mcp.py
.venv/bin/python scripts/smoke_mcp.py --live
```

Regression files: test_auth_failures, test_session_restore, test_totp_timing, test_stability, test_timetable, test_mcp_stdio, test_codex_config, and preserved r1.7 parser/form/document tests. test_mcp_stdio starts separate real subprocesses with synthetic providers; it covers every tool, schema validation, machine-readable failures and cancellation followed by a responsive ping.

Static secret scan uses detect-secrets 1.5.0 with virtual environments, build outputs and dependency hashes excluded. Reviewed findings are synthetic credentials, RFC test vectors and historical documentation placeholders; production code contains no scanner findings. No real credentials were added, and no credential-rotation incident was identified in the files inspected. This does not audit the user's unrelated files or historical repositories for all secrets.

## Live feature status

- Notices: summary/full lists PASS. Already-read body/sender/attachment references and private file download PASS, with independent before/after snapshots matching. Unread/unknown selection is blocked before a detail request; unread non-marking retrieval is NOT IMPLEMENTED. See NOTICE_DETAILS.md. Current record counts, filenames and contents are intentionally omitted.
- Timetable: weekly grids and intensive tables PASS. Explicit 前期/後期 labels observed. A date query is a weekday pattern, not a claim that a class occurs on a holiday or cancellation date. Automatic current-semester selection is not implemented.
- Attendance: live records PASS; official aggregation equivalence NOT RUN. Missing/unknown-status behavior is tested synthetically.
- Grades: live records PASS; unpublished behavior synthetic only. No GPA/earned-credit calculation or finality inference.
- manaba/documents/student-info: synthetic responses/guards PASS; live NOT RUN.

## Measured performance

Single-run observations from the initial stabilization phase, before the notice-detail follow-up. These are development measurements, not a controlled before/after benchmark of untouched r1.7 or a measurement of the new detail/download pipeline; network and filesystem cache conditions vary. Detail/download timings are recorded separately in NOTICE_DETAILS.md.

| Measurement | Before connection/PDF-import fix | After |
| --- | ---: | ---: |
| initialize + tools/list | 1999.86 ms | 575.15 ms |
| Notices after status | 5162.75 ms | 1464.30 ms |
| Timetable | 4908.25 ms | 1004.56 ms |
| Attendance | 5052.88 ms | 1139.23 ms |
| Grades | 4643.09 ms | 1025.37 ms |
| Full notices | 6840.10 ms | 2920.37 ms |
| Repeated notices query | 5157.83 ms | 2.77 ms |
| Child peak RSS (macOS getrusage) | 168.42 MiB | 121.19 MiB |

Cause: unnecessary home probes were invalidating memory data caches and entering SSO. Reusing the current menu form avoids those probes; confirmed expiry still takes the bounded reauthentication path. PDF parsing imports are deferred until PDF use. Direct service warm-cache measurement was 0.3 ms; 2.77 ms includes MCP serialization/stdio roundtrip. Both values are single samples.

## Remaining checks

- Desktop UI/model tool selection after a new chat/app restart; the active chat's initial tool inventory cannot be hot-reloaded by this script.
- Mac reboot, Intel hardware, other macOS/Python versions and real outage/rate-limit scenarios.
- Real multi-page notice controls, an officially supported non-marking route for unread notice details, server read timestamps/audit semantics, cancellation/makeup information, and official GPA rules.
- Locate the reported earlier r1.8 artifact if available, compare its source before adopting any additional changes.
- ChatGPT remote transport/authentication remains a separate future task; no tunnel or public deployment was performed.
