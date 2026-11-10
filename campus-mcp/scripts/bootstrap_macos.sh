#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
"${CIT_MCP_BOOTSTRAP_PYTHON:-python3.12}" -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
# A normal install avoids macOS hidden .pth flags breaking editable imports.
python -m pip install '.[dev]'
echo
echo 'Installed.'
echo '1) .venv/bin/cit-campus-keyring'
echo '2) .venv/bin/cit-campus-login-test portal --force'
echo '3) .venv/bin/cit-campus-login-test manaba --force   # optional'
echo '4) .venv/bin/python -m pytest'
echo '5) .venv/bin/cit-campus-mcp'
