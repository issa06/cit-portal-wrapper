# CIT Campus MCP r1.7

Read-only MCP server for:

- CIT Portal (`portal.chibatech.ac.jp` entry + UPRX application)
- CIT manaba (`cit.manaba.jp`)
- CIT Student Documents (`kmsk.is.it-chiba.ac.jp/portal/`)

The Portal parser is based on the structure of `issa06/cit-portal-wrapper`, with authentication separated from scraping and MFA/TOTP support added.

## Safety / behavior

- Read-only tools only. No course registration, assignment submission, survey submission, or profile modification.
- Portal password and TOTP secret are not written to this project.
- macOS Keychain is used directly through `/usr/bin/security` by default.
- Session cache files contain cookies only and are stored under `~/.config/cit-campus-mcp/` with restrictive permissions where supported.
- `portal_get_student_info` intentionally excludes the face-photo Base64 field.

## 1. Install on macOS

```bash
cd cit-campus-mcp-r1.7
./scripts/bootstrap_macos.sh
```

Manual equivalent:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

Python 3.10+ is required.

## 2. Store credentials

```bash
.venv/bin/cit-campus-keyring
```

It stores:

- `portal.user_id`
- `portal.password`
- `portal.totp_secret`
- optionally `manaba.user_id`
- optionally `manaba.password`

under the keyring service `cit-campus-mcp`.

For temporary testing, environment variables are also supported:

```bash
export CIT_PORTAL_USER_ID='...'
export CIT_PORTAL_PASSWORD='...'
export CIT_PORTAL_TOTP_SECRET='BASE32...'
```

Do not commit those values.

## 3. Test Portal authentication first

```bash
.venv/bin/cit-campus-login-test portal --force --trace
```

Expected shape:

```text
Portal login OK: https://.../uprx/...
Session restored: False
```

Run it again without `--force` to test cookie restoration:

```bash
.venv/bin/cit-campus-login-test portal
```

The current CIT Keycloak page can expose multiple TOTP credentials. r1.7 selects the credential labelled `Python` by default. If yours has another label, set `CIT_PORTAL_TOTP_CREDENTIAL_LABEL` before running the test.

If the University's SSO field names differ from the auto-detector, set the optional overrides from `.env.example` in the shell, for example:

```bash
export CIT_PORTAL_USER_FIELD='username'
export CIT_PORTAL_PASSWORD_FIELD='password'
export CIT_PORTAL_OTP_FIELD='otp'
```

A sanitized state trace can be printed with `--trace`. A debugging HTML dump can also be generated locally:

```bash
.venv/bin/cit-campus-login-test portal --force --trace --debug-html debug-portal.html
```

**The debug HTML may contain personal information. Do not upload it publicly.**

## 4. Test manaba

```bash
.venv/bin/cit-campus-login-test manaba --force
```

The r1 manaba parser intentionally uses broad, read-only link discovery so that it can be refined after seeing the authenticated CIT DOM.

## 5. Run offline tests

```bash
.venv/bin/python -m pytest
```

## 6. Run MCP over stdio

```bash
.venv/bin/cit-campus-mcp
```

The process waits for an MCP host on stdin/stdout; no normal prompt appears.

Current tools:

### Portal

- `portal_status`
- `portal_get_notices`
- `portal_get_grades`
- `portal_get_attendance`
- `portal_get_timetable`
- `portal_get_student_info`

### manaba

- `manaba_list_courses`
- `manaba_list_action_items`
- `manaba_get_page_text`

### Student Documents

- `docs_list_links`
- `docs_search`
- `docs_get_text`

## MCP host config example

Use the absolute path on your Mac:

```json
{
  "mcpServers": {
    "cit-campus": {
      "command": "/ABSOLUTE/PATH/cit-campus-mcp-r1.7/.venv/bin/cit-campus-mcp"
    }
  }
}
```

## What to send back after the first run

If Portal login succeeds but a parser fails, send only:

1. the command you ran,
2. the traceback,
3. which tool failed.

Avoid sending passwords, TOTP secrets, session cookie JSON, or a full student-info/debug HTML dump unless it has been sanitized.


## Session restore behavior (r1.4)

CIT Portal may return the authenticated UPRX bridge page on a cached session and require one hidden-only `loginForm` postback before `menuForm` appears. r1.4 replays that bridge postback during session restore without resending the password or TOTP.

If you deliberately run `--force` twice inside the same 30-second TOTP window, Keycloak may reject the second use of the same one-time code. Normally this is avoided by using the cached Portal session instead of forcing a new MFA login.


## Session restore behavior (r1.5)

The authenticated UPRX application home is `/uprx/up/bs/bsa001/Bsa00101.xhtml`. r1.5 probes this page first when restoring saved cookies. `Pky00102.xhtml` is retained only as a compatibility fallback for the post-SAML bridge.

With `--trace`, restoration now reports sanitized cookie metadata (name/domain/path/expiry, never values) and each restore probe before a fresh SSO/MFA login begins.

## r1.6 session behavior

UPRX's application `JSESSIONID` may not be reusable after the MCP/client process exits. r1.6 therefore treats the upstream Keycloak SSO session as the durable session layer:

1. Try the cached UPRX cookies directly.
2. If UPRX rejects them, keep `KEYCLOAK_IDENTITY` / `KEYCLOAK_SESSION`, remove stale authentication-transaction cookies, and re-enter through Shibboleth.
3. If Keycloak accepts the cached SSO login, rebuild UPRX without sending the password or TOTP and report `Session restored: True`.
4. If Keycloak requests credentials, perform the normal login and submit `rememberMe=on` when supported so the next restart can use SSO resume.

A cache created by r1.5 or earlier may require one normal MFA login under r1.6 before SSO resume becomes persistent.

## r1.7 TOTP timing behavior

r1.7 makes the Portal MFA step time-aware instead of blindly generating a code from the Mac clock:

1. Read the Keycloak response HTTP `Date` header when it is available.
2. Estimate the SSO server clock offset from the local clock and generate TOTP against that corrected time.
3. Calculate the remaining validity in the current 30-second TOTP window.
4. If fewer than `CIT_PORTAL_TOTP_MIN_VALIDITY_SECONDS` remain, wait for the next window plus a small guard before submitting.
5. If Keycloak returns the OTP form again, retry at most once by default and force the retry into a newer TOTP counter window so the same code is never replayed.

`--trace` reports only sanitized timing metadata such as clock source, server offset, remaining validity, wait duration, and attempt number. It never prints the TOTP secret or generated code.

Defaults:

```text
CIT_PORTAL_TOTP_MIN_VALIDITY_SECONDS=5
CIT_PORTAL_TOTP_ROLLOVER_GUARD_SECONDS=0.25
CIT_PORTAL_TOTP_MAX_ATTEMPTS=2
```

Set `CIT_PORTAL_TOTP_MAX_ATTEMPTS=1` if you want to disable the automatic second-window retry.
