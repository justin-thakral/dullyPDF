"""Security-focused regression tests for `backend.services.fill_links_service`."""

from __future__ import annotations

from backend.services import fill_links_service as fls


def test_dev_fill_link_secret_fallback_is_ephemeral_and_not_the_old_shared_literal(mocker, monkeypatch) -> None:
    monkeypatch.delenv("FILL_LINK_TOKEN_SECRET", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    mocker.patch.object(fls, "_DEV_FILL_LINK_TOKEN_SECRET", "dev-ephemeral-secret")
    mocker.patch.object(fls, "_WARNED_DEV_FILL_LINK_TOKEN_SECRET", False)

    first = fls._resolve_fill_link_token_secret()
    second = fls._resolve_fill_link_token_secret()

    assert first == "dev-ephemeral-secret"
    assert second == "dev-ephemeral-secret"
    assert first != "dullypdf-fill-link-dev-secret"


def test_prod_fill_link_secret_rejects_missing_or_weak_values(monkeypatch) -> None:
    monkeypatch.setenv("ENV", "production")

    monkeypatch.delenv("FILL_LINK_TOKEN_SECRET", raising=False)
    try:
        fls._resolve_fill_link_token_secret()
    except RuntimeError as exc:
        assert "must be unique and at least 32 characters" in str(exc)
    else:  # pragma: no cover - defensive branch
        raise AssertionError("Expected production fill link secret validation to fail when unset.")

    monkeypatch.setenv("FILL_LINK_TOKEN_SECRET", "change_me_prod_fill_link_token_secret")
    try:
        fls._resolve_fill_link_token_secret()
    except RuntimeError as exc:
        assert "must be unique and at least 32 characters" in str(exc)
    else:  # pragma: no cover - defensive branch
        raise AssertionError("Expected production fill link secret validation to fail for weak placeholder values.")
