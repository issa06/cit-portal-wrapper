# r1.7

- Added server-time-aware TOTP generation for CIT Portal Keycloak MFA.
- Reads the HTTPS response `Date` header and estimates SSO server/local clock skew before generating the OTP.
- Calculates the current TOTP window's remaining validity and avoids submitting codes near rollover.
- Defaults to a 5-second minimum remaining lifetime and a 0.25-second rollover guard.
- If Keycloak returns the OTP form after the first submission, retries at most once by default and waits for a strictly newer TOTP counter window so the same code is never resent.
- Added `CIT_PORTAL_TOTP_MIN_VALIDITY_SECONDS`, `CIT_PORTAL_TOTP_ROLLOVER_GUARD_SECONDS`, and `CIT_PORTAL_TOTP_MAX_ATTEMPTS`.
- `--trace` now includes sanitized timing diagnostics (`totp_clock_source`, clock offset, remaining seconds, wait time, attempt number) without exposing the TOTP code or secret.
- Added unit tests for server clock skew correction, near-expiry rollover waiting, next-window retry behavior, and no-wait behavior when enough validity remains.
