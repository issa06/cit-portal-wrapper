"""Append/remove exactly one credential-free block; never print/copy other settings."""

import argparse
import os
import tempfile
from pathlib import Path

import tomllib

MARKER = "# CIT Campus MCP managed block"


def configure(path: Path, launcher: Path, remove: bool = False) -> str:
    original = path.read_text() if path.exists() else ""
    parsed = tomllib.loads(original)
    expected = {"command": str(launcher), "startup_timeout_sec": 20, "tool_timeout_sec": 65}
    current = parsed.get("mcp_servers", {}).get("cit-campus")
    import json

    block = (
        f"\n{MARKER}\n[mcp_servers.cit-campus]\ncommand = {json.dumps(str(launcher))}\n"
        "startup_timeout_sec = 20\ntool_timeout_sec = 65\n# End CIT Campus MCP managed block\n"
    )
    if remove:
        if block not in original or current != expected:
            raise ValueError("Managed block differs; existing settings were preserved.")
        updated = original.replace(block, "", 1)
    else:
        if current is not None:
            if current == expected:
                return "CIT Campus MCP already configured; no changes."
            raise ValueError("cit-campus already exists with different settings; preserved.")
        updated = original + block
    # Validate semantics before atomic replacement, including every unrelated setting.
    after = tomllib.loads(updated)
    before_without = {
        **parsed,
        "mcp_servers": {k: v for k, v in parsed.get("mcp_servers", {}).items() if k != "cit-campus"},
    }
    after_without = {
        **after,
        "mcp_servers": {k: v for k, v in after.get("mcp_servers", {}).items() if k != "cit-campus"},
    }
    if before_without != after_without:
        raise ValueError("Unrelated configuration would change; stopped.")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".codex-config-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as output:
            output.write(updated)
            output.flush()
            os.fsync(output.fileno())
        if (path.read_text() if path.exists() else "") != original:
            raise ValueError("Configuration changed concurrently; stopped.")
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
    return (
        "Removed CIT Campus MCP only."
        if remove
        else "Added CIT Campus MCP; all other settings preserved. Rollback: configure_codex.py --remove"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args()
    launcher = Path(__file__).resolve().with_name("run_mcp.sh")
    try:
        print(configure(Path.home() / ".codex/config.toml", launcher, args.remove))
    except Exception:
        print("Configuration update stopped; inspect locally. No existing server was overwritten.")
        raise SystemExit(1) from None
