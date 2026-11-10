# Notice detail follow-up — 2026-11-10 JST

## Verified scope and limitation

Already-read notices now support body, sender, attachment references and private attachment download. **Unread non-marking retrieval is not implemented**: the advertised detail action has no verified non-marking option. Unread/unknown selection is rejected before sending a detail request. No mark-read-then-restore workaround exists.

A primary university manual for the same product says selecting a notice automatically makes it read ([名桜大学 UNIPA manual, p.4](https://www.meio-u.ac.jp/student/assets/UniPa_manual_1.pdf)). This is supporting context, not a claim that another institution's manual proves CIT's implementation. CIT live checks were restricted to already-read notices; no unread detail was opened to discover whether it would be marked.

## Read-state checks

- Only the exact observed CIT command-link renderer is recognized. Normal links are read, fontBold links unread. Unsupported classes, inline styling or handlers are unknown and blocked.
- `notice_ref` hashes metadata plus the current view locator. Duplicate IDs, stale refs and contradictory displays fail closed. Callers cannot supply component IDs, URLs, arbitrary form parameters or state tokens.
- Snapshots compare metadata/read-state counters with duplicate multiplicity, not transient component IDs. Every detail/file operation takes before and after snapshots in independently restored app views.
- Repeating an already active menu can return a no-op JSF partial response without the list. That is not an empty list or evidence of a state change. Verification deliberately uses fresh app views, then disposes them while retaining SSO; a normal list request after a detail operation was also verified.
- Only if snapshots match is detail data returned or an attachment committed to disk. No UI callbacks, mark/unmark, flag, receipt, print or logout requests are executed.

This verifies the displayed state of the requested list at two points in time. It is not a server transaction enforcing a no-write condition. Read timestamps/audit logs and concurrent browser edits have not been verified. Unknown behavior is not presented as a successful unread retrieval.

## Implementation and regressions

The response contains separately named dialog forms and a lazily introduced attachment panel. Each fragment's actual form ownership and hidden state are preserved independently; hidden-field updates are scoped by element ID. Reparenting forms into an old document was incorrect and is covered by the nested-form/lazy-panel regression fixtures.

Files use a normal prepare request followed by the submit control advertised by its PrimeFaces widget. The observed callback is `!args.exceptionFlg`, including an empty callback-args object; exception/validation failures stop the download. Pure browsing-context target assignments are recognized but not executed. The returned HTML/scripts are never evaluated.

Attachments are held in memory until the independent state check passes. Files are then atomically saved under `~/.local/share/cit-campus-mcp/attachments/`, directory0700/file0600, hash-based filenames, 8MiB/file, 200MiB total. Cancellation before the atomic commit removes the temporary file. Metadata/local path are returned, not binary data, private download URLs or tokens. No private HTML, notice content or real attachments are added to Git or CI.

## Evidence

Local synthetic suite: **94 PASS / 0 FAIL**. All 15 tools have a real stdio synthetic/schema check. Additional tests cover unread/unknown detail and download refusal, unknown handlers, ambiguous/stale metadata, state drift, missing fields, network failure, private file permissions, cancellation without commit, callback preparation errors, non-file responses and per-form token isolation.

Actual installed-server command:

```bash
.venv/bin/python scripts/smoke_notice_details.py --live --download
```

| Case | Result | Evidence |
| --- | --- | --- |
| New tools initialize/list | PASS | Real stdio, 15 tools present |
| Unread detail guard | PASS (refusal) | READ_STATE_CHANGE_REQUIRED; not a successful unread-body retrieval |
| Already-read body/sender/attachment refs | PASS | Present, outputSchema valid, state check passed; 10.790 seconds in recorded MCP sample |
| Already-read attachment bytes | PASS | Local file, 0600, SHA-256 match, state check passed; 11.565 seconds in recorded MCP sample |
| Independent final list | PASS | Snapshot matches original, including unread states |
| No data in test logs | PASS (observed scope) | Script prints booleans/status/timing only; contents, filenames, refs and private paths omitted |
| Unknown/changed renderer | PASS (synthetic refusal) | No detail POST |
| State drift | PASS (synthetic refusal) | No body result or committed attachment |
| Unread body/file retrieval without marking | NOT IMPLEMENTED / NOT RUN | No verified supported path; requires university/vendor-supported non-marking access |
| Real Mac reboot and concurrent browser edits | NOT RUN | Outside this follow-up's verified scope |

These are single-run timing observations. No notice contents, filenames, record counts or actual identifiers are included in this report. Version remains 0.1.8 because this extends the same unreleased draft PR, not a published release.
