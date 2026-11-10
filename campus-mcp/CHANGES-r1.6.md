# r1.6

- Changed Portal restart recovery from UPRX-only cookie replay to a two-stage strategy:
  1. direct UPRX cookie probe;
  2. cached Keycloak SSO resume through Shibboleth without sending password or TOTP.
- Removes stale Keycloak transaction cookies (`AUTH_SESSION_ID`, `KC_AUTH_SESSION_HASH`, etc.) before SSO resume while preserving identity/session cookies.
- Enables Keycloak `rememberMe=on` when the login form exposes the `rememberMe` checkbox, so future process restarts can reuse the SSO login.
- `Session restored: True` now also means the UPRX application was rebuilt from an existing SSO session without password/TOTP.
- Added sanitized SSO-resume trace events.
- Added tests for remember-me field detection and transient-cookie filtering.
