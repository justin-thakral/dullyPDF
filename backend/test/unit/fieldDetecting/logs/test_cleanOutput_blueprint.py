from pathlib import Path

import pytest

from backend.fieldDetecting.logs import cleanOutput as cleanup


def test_main_requires_all_flag(capsys) -> None:
    rc = cleanup.main([])
    captured = capsys.readouterr()

    assert rc == 2
    assert "--all" in captured.err


def test_main_dry_run_keeps_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    keep_file = tmp_path / "README.md"
    keep_file.write_text("keep", encoding="utf-8")
    removed_file = tmp_path / "temp.log"
    removed_file.write_text("x", encoding="utf-8")

    monkeypatch.setattr(cleanup, "BASE_DIR", tmp_path)
    monkeypatch.setattr(cleanup, "KEEP_NAMES", {"README.md", "cleanOutput.py"})

    rc = cleanup.main(["--all", "--dry-run"])
    captured = capsys.readouterr()

    assert rc == 0
    assert removed_file.exists()
    assert "dry-run: remove" in captured.out


def test_main_full_cleanup_removes_non_keep_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "README.md").write_text("keep", encoding="utf-8")
    (tmp_path / "cleanOutput.py").write_text("keep", encoding="utf-8")
    (tmp_path / "delete.me").write_text("x", encoding="utf-8")
    nested = tmp_path / "artifacts"
    nested.mkdir()
    (nested / "a.txt").write_text("x", encoding="utf-8")

    monkeypatch.setattr(cleanup, "BASE_DIR", tmp_path)
    monkeypatch.setattr(cleanup, "KEEP_NAMES", {"README.md", "cleanOutput.py"})

    rc = cleanup.main(["--all"])

    assert rc == 0
    assert (tmp_path / "README.md").exists()
    assert (tmp_path / "cleanOutput.py").exists()
    assert not (tmp_path / "delete.me").exists()
    assert not nested.exists()


def test_remove_path_rejects_deletes_outside_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    outside = tmp_path.parent / "outside.log"
    outside.write_text("x", encoding="utf-8")

    monkeypatch.setattr(cleanup, "BASE_DIR", tmp_path)

    with pytest.raises(RuntimeError):
        cleanup._remove_path(outside, dry_run=False)


def test_main_propagates_cleanup_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cleanup, "_clear_all", lambda _dry: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        cleanup.main(["--all"])
