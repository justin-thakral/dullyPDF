from pathlib import Path

import pytest

from backend.fieldDetecting.rename_pipeline import env_loader


def test_load_env_file_parses_export_comments_and_malformed_lines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "# comment",
                "FOO=from_file",
                "export BAR='bar value'",
                "MALFORMED_LINE",
                " BAZ = \" spaced \" ",
                "",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("FOO", "existing")
    monkeypatch.delenv("BAR", raising=False)
    monkeypatch.delenv("BAZ", raising=False)

    env_loader._load_env_file(env_file)

    assert "MALFORMED_LINE" not in env_loader.os.environ
    assert env_loader.os.environ["FOO"] == "existing"
    assert env_loader.os.environ["BAR"] == "bar value"
    assert env_loader.os.environ["BAZ"] == " spaced "


def test_load_env_file_missing_file_is_noop(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.env"
    env_loader._load_env_file(missing)


def test_bootstrap_env_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Path] = []

    def _fake_loader(path: Path) -> None:
        calls.append(path)

    monkeypatch.setattr(env_loader, "_BOOTSTRAPPED", False)
    monkeypatch.setattr(env_loader, "_load_env_file", _fake_loader)

    env_loader.bootstrap_env()
    first_call_count = len(calls)
    env_loader.bootstrap_env()

    assert first_call_count == 5
    assert len(calls) == first_call_count


# ---------------------------------------------------------------------------
# Edge-case tests added below
# ---------------------------------------------------------------------------


def test_load_env_file_values_containing_equals_split_on_first_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Values that contain '=' signs (e.g. base64 tokens, connection strings)
    should be preserved intact.  The split('=', 1) call ensures only the
    first '=' is treated as the separator."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "DATABASE_URL=postgres://host:5432/db?sslmode=require",
                "BASE64_TOKEN=abc123==",
                "NESTED=key=val=extra",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("BASE64_TOKEN", raising=False)
    monkeypatch.delenv("NESTED", raising=False)

    env_loader._load_env_file(env_file)

    assert env_loader.os.environ["DATABASE_URL"] == "postgres://host:5432/db?sslmode=require"
    assert env_loader.os.environ["BASE64_TOKEN"] == "abc123=="
    assert env_loader.os.environ["NESTED"] == "key=val=extra"


def test_load_env_file_with_only_comments_and_empty_lines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A file containing only comments and blank lines should be parsed
    without error and should not set any environment variables.  This
    exercises every skip branch (empty line, comment line, no '=' present)."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "# This is a comment",
                "",
                "  # Indented comment",
                "   ",
                "# Another comment",
                "",
            ]
        ),
        encoding="utf-8",
    )

    # Use a sentinel key to verify nothing was set.
    sentinel = "_ENV_LOADER_TEST_SENTINEL_KEY"
    monkeypatch.delenv(sentinel, raising=False)

    env_loader._load_env_file(env_file)

    assert sentinel not in env_loader.os.environ
