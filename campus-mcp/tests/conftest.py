import pytest


@pytest.fixture(autouse=True)
def isolated_session_dir(tmp_path, monkeypatch):
    # Unit tests never touch the user's real session cache or Keychain.
    monkeypatch.setenv("CIT_SESSION_DIR", str(tmp_path / "session-cache"))
