"""Unit tests for backend.scripts.purge_downgrade_retention."""

from __future__ import annotations

from backend.scripts import purge_downgrade_retention


def test_main_continues_after_one_user_failure(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        purge_downgrade_retention,
        "_build_parser",
        lambda: type("Parser", (), {"parse_args": staticmethod(lambda: type("Args", (), {"dry_run": False})())})(),
    )
    monkeypatch.setattr(
        purge_downgrade_retention,
        "list_users_with_expired_downgrade_retention",
        lambda: ["user-1", "user-2"],
    )

    def _delete(user_id: str) -> dict[str, list[str]]:
        if user_id == "user-1":
            raise RuntimeError("storage failure")
        return {"deletedTemplateIds": ["tpl-2"], "deletedLinkIds": ["link-2"]}

    monkeypatch.setattr(purge_downgrade_retention, "delete_user_downgrade_retention_now", _delete)

    exit_code = purge_downgrade_retention.main()
    output_lines = capsys.readouterr().out.strip().splitlines()

    assert exit_code == 1
    assert output_lines == [
        "failed user=user-1 error=storage failure",
        "purged user=user-2 templates=1 links=1",
        "completed users=2 templates=1 links=1 failed=1",
    ]


def test_main_dry_run_keeps_zero_exit_code(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        purge_downgrade_retention,
        "list_users_with_expired_downgrade_retention",
        lambda: ["user-1"],
    )
    monkeypatch.setattr(
        purge_downgrade_retention,
        "_build_parser",
        lambda: type("Parser", (), {"parse_args": staticmethod(lambda: type("Args", (), {"dry_run": True})())})(),
    )

    exit_code = purge_downgrade_retention.main()
    output_lines = capsys.readouterr().out.strip().splitlines()

    assert exit_code == 0
    assert output_lines == ["user-1", "dry-run users=1"]
