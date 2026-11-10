# r1.2 changes

- Fix the post-SAML UPRX `Pky00102.xhtml` loop observed after successful password + TOTP authentication.
- Treat `Pky00102.xhtml` as a dedicated UPRX authentication bridge instead of a generic hidden-form auto-post page.
- Probe the normal Portal top page after SAML before posting any JSF bridge form.
- If required, submit only `form#loginForm` once; never auto-submit `infoForm` or `errForm`.
- Fail closed after one bridge postback instead of repeatedly posting forms.
- Add sanitized trace action names so future failures show which transition was taken.
- Add tests for the multi-form UPRX bridge structure.
