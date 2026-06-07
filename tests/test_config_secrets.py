"""Settings secret resolution from `*_FILE` paths (Docker/K8s/systemd secrets)."""

from __future__ import annotations

from pathlib import Path

import pytest

from northbound.config import Settings


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear secret env vars other test modules set at import.

    pydantic ``Settings()`` reads ``os.environ``; without this the inline env
    value would win over the file under test (and mask the file path entirely).
    """
    for var in ("NB_MASTER_KEY", "NB_SECRET_KEY", "NB_MASTER_KEY_FILE", "NB_SECRET_KEY_FILE"):
        monkeypatch.delenv(var, raising=False)


def test_master_key_loaded_from_file(tmp_path: Path) -> None:
    f = tmp_path / "mk"
    f.write_text("file-master-key", encoding="utf-8")
    assert Settings(master_key_file=str(f)).master_key == "file-master-key"


def test_secret_key_loaded_from_file(tmp_path: Path) -> None:
    f = tmp_path / "sk"
    f.write_text("file-jwt-secret", encoding="utf-8")
    assert Settings(secret_key_file=str(f)).secret_key == "file-jwt-secret"


def test_trailing_newline_is_stripped(tmp_path: Path) -> None:
    f = tmp_path / "mk"
    f.write_text("key-with-newline\n", encoding="utf-8")  # secret files often have one
    assert Settings(master_key_file=str(f)).master_key == "key-with-newline"


def test_inline_value_wins_over_file(tmp_path: Path) -> None:
    f = tmp_path / "mk"
    f.write_text("from-file", encoding="utf-8")
    assert Settings(master_key="inline", master_key_file=str(f)).master_key == "inline"


def test_no_file_no_inline_leaves_none() -> None:
    s = Settings()
    assert s.master_key is None
    assert s.secret_key is None


def test_missing_file_is_a_hard_error(tmp_path: Path) -> None:
    # A configured-but-unreadable secret source must fail loudly, never degrade.
    with pytest.raises(ValueError, match="could not be read"):
        Settings(secret_key_file=str(tmp_path / "nope"))


def test_empty_file_is_a_hard_error(tmp_path: Path) -> None:
    f = tmp_path / "blank"
    f.write_text("   \n", encoding="utf-8")
    with pytest.raises(ValueError, match="is empty"):
        Settings(master_key_file=str(f))
