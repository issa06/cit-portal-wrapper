# r1.5 changes

- Session restoration now probes the real authenticated UPRX home page first: `/uprx/up/bs/bsa001/Bsa00101.xhtml`.
- `Pky00102.xhtml` is treated as a post-SAML bridge/fallback rather than the canonical home page.
- Added sanitized restore diagnostics to `--trace` (cookie names/scopes only; never cookie values).
- Preserves compatibility with r1.2-r1.4 session files.
- Added `CIT_PORTAL_HOME_PATH` override.
