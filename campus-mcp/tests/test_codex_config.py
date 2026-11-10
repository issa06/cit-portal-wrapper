import importlib.util
from pathlib import Path

import pytest


def module():
    spec = importlib.util.spec_from_file_location(
        "configure_codex", Path(__file__).parents[1] / "scripts/configure_codex.py"
    )
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_codex_configuration_preserves_other_servers_and_roundtrips(tmp_path, capsys):
    path = tmp_path / "config.toml"
    original = '[mcp_servers.other]\ncommand="other"\n[mcp_servers.other.env]\nTOKEN="synthetic-private"\n'
    path.write_text(original)
    configure = module().configure
    launcher = tmp_path / "run.sh"
    configure(path, launcher)
    first = path.read_text()
    configure(path, launcher)
    assert path.read_text() == first
    configure(path, launcher, remove=True)
    assert path.read_text() == original
    assert "synthetic-private" not in capsys.readouterr().out


def test_codex_existing_different_server_is_preserved(tmp_path):
    path = tmp_path / "config.toml"
    original = '[mcp_servers.cit-campus]\ncommand="existing"\n'
    path.write_text(original)
    with pytest.raises(ValueError):
        module().configure(path, tmp_path / "new")
    assert path.read_text() == original
