# CIT Campus MCP r1.3

- Fix cached Portal session restoration after successful SAML/MFA login.
- Persist the last authenticated Portal URL with the cookie jar.
- Probe `Pky00102.xhtml` first for r1.2 session files that lack metadata.
- Preserve cookie `secure`, `expires`, and rest attributes when restoring.
- Upgrade older session JSON to the v2 session format after a successful restore.
- No changes to credentials, TOTP secrets, or write permissions.
