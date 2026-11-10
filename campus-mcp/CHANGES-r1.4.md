# r1.4 changes

- Fixed cached Portal session validation on `Pky00102.xhtml`.
- Session restore now replays the hidden-only UPRX `loginForm` postback once before declaring cookies invalid.
- No password or TOTP is resent during a successful cached-session restore.
- Added regression coverage for the real `Pky00102 -> loginForm POST -> menuForm` restore flow.
- Documented Keycloak TOTP replay rejection when `--force` is used repeatedly within one TOTP interval.
