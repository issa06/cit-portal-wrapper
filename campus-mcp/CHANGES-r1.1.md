# r1.1 changes

- Prefer the UPRX `ShibbolethAuthServlet` student/staff SSO link over the legacy local login form.
- Detect the current CIT Keycloak username/password form (`username`, `password`).
- Detect Keycloak OTP credential tiles and select the credential labelled `Python` by default.
- Submit `selectedCredentialId` together with the TOTP code so the TOTP secret matches the selected Keycloak credential.
- Stop after one rejected password or OTP submission instead of repeatedly retrying and risking an account lockout.
- Change the default UPRX application host to `https://portal.chibatech.ac.jp`.
- Suppress BeautifulSoup's misleading XHTML-as-HTML warning for UPRX pages.
- Add tests matching the current CIT Portal landing page and Keycloak OTP structure.
