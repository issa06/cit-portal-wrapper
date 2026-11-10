# Source note

The Portal DOM/navigation logic in this prototype was derived from the user's fork:

- `issa06/cit-portal-wrapper`
- originally forked from `kairi003/cit-portal-wrapper`

The prototype restructures that logic into a read-only MCP server, fixes the `couese_name` typo in returned data, removes automatic JSON/photo file writes, and adds a separate requests-based SSO/MFA authentication layer.

The repository's MIT license and upstream/fork attribution are preserved. The subproject includes a copy of that LICENSE for packaged distribution. The separate r1.7 source and its change records were retained before stabilization.
