import pytest
from firebase_admin import auth as firebase_auth
from fastapi import HTTPException

from backend.firebaseDB.firebase_service import RequestUser


@pytest.mark.parametrize(
    ("claims", "expected"),
    [
        ({"firebase": {"sign_in_provider": "password"}}, True),
        ({"firebase": {"sign_in_provider": "emaillink"}}, True),
        ({"firebase": {"sign_in_provider": "email_link"}}, True),
        ({"firebase": {"sign_in_provider": "google.com"}}, False),
        ({}, False),
        ({"firebase": "bad-shape"}, False),
    ],
)
def test_is_password_sign_in_variants(app_main, claims, expected) -> None:
    assert app_main._is_password_sign_in(claims) is expected


def test_enforce_email_verification_rejects_unverified_password_signin(app_main) -> None:
    with pytest.raises(HTTPException) as ctx:
        app_main._enforce_email_verification(
            {"firebase": {"sign_in_provider": "password"}, "email_verified": False}
        )
    assert ctx.value.status_code == 403
    assert "Email verification required" in str(ctx.value.detail)


def test_enforce_email_verification_allows_non_password_or_verified(app_main) -> None:
    app_main._enforce_email_verification({"firebase": {"sign_in_provider": "google.com"}})
    app_main._enforce_email_verification(
        {"firebase": {"sign_in_provider": "password"}, "email_verified": True}
    )


def test_verify_token_success_path(app_main, mocker) -> None:
    decoded = {"uid": "user_1", "firebase": {"sign_in_provider": "google.com"}}
    mocker.patch.object(app_main, "verify_id_token", return_value=decoded)
    assert app_main._verify_token("Bearer abc") == decoded


def test_verify_token_maps_missing_token_to_401(app_main, mocker) -> None:
    mocker.patch.object(app_main, "verify_id_token", side_effect=ValueError("missing"))
    with pytest.raises(HTTPException) as ctx:
        app_main._verify_token(None)
    assert ctx.value.status_code == 401
    assert "Missing Authorization token" in str(ctx.value.detail)


def test_verify_token_maps_unconfigured_auth_to_500(app_main, mocker) -> None:
    mocker.patch.object(app_main, "verify_id_token", side_effect=RuntimeError("firebase missing"))
    with pytest.raises(HTTPException) as ctx:
        app_main._verify_token("Bearer abc")
    assert ctx.value.status_code == 500
    assert "not configured" in str(ctx.value.detail)


def test_verify_token_maps_revoked_token_to_401(app_main, mocker) -> None:
    mocker.patch.object(
        app_main,
        "verify_id_token",
        side_effect=firebase_auth.RevokedIdTokenError("revoked"),
    )
    with pytest.raises(HTTPException) as ctx:
        app_main._verify_token("Bearer abc")
    assert ctx.value.status_code == 401
    assert "revoked" in str(ctx.value.detail).lower()


def test_verify_token_maps_generic_failure_to_401(app_main, mocker) -> None:
    mocker.patch.object(app_main, "verify_id_token", side_effect=Exception("bad token"))
    with pytest.raises(HTTPException) as ctx:
        app_main._verify_token("Bearer abc")
    assert ctx.value.status_code == 401
    assert "Invalid Authorization token" in str(ctx.value.detail)


def test_require_user_maps_ensure_user_failure_to_500(app_main, mocker) -> None:
    mocker.patch.object(app_main, "_verify_token", return_value={"uid": "user_1"})
    mocker.patch.object(app_main, "ensure_user", side_effect=Exception("firestore down"))
    with pytest.raises(HTTPException) as ctx:
        app_main._require_user("Bearer abc")
    assert ctx.value.status_code == 500
    assert "synchronize user profile" in str(ctx.value.detail)


def test_require_user_returns_request_user(app_main, mocker) -> None:
    expected = RequestUser(uid="u1", app_user_id="u1", email="a@b.c", display_name="U", role="base")
    mocker.patch.object(app_main, "_verify_token", return_value={"uid": "u1"})
    mocker.patch.object(app_main, "ensure_user", return_value=expected)
    assert app_main._require_user("Bearer abc") == expected


def test_has_admin_override_disabled_in_prod(app_main, monkeypatch, mocker) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "secret")
    mocker.patch.object(app_main, "_is_prod", return_value=True)
    assert app_main._has_admin_override("Bearer secret", None) is False


def test_has_admin_override_accepts_bearer_or_header_token(app_main, monkeypatch, mocker) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "secret")
    mocker.patch.object(app_main, "_is_prod", return_value=False)
    assert app_main._has_admin_override("Bearer secret", None) is True
    assert app_main._has_admin_override(None, "secret") is True


def test_has_admin_override_respects_allow_override_flag(app_main, monkeypatch, mocker) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "secret")
    monkeypatch.setenv("SANDBOX_ALLOW_ADMIN_OVERRIDE", "false")
    mocker.patch.object(app_main, "_is_prod", return_value=False)
    assert app_main._has_admin_override("Bearer secret", "secret") is False


def test_has_admin_override_uses_debug_password_fallback(app_main, monkeypatch, mocker) -> None:
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    mocker.patch.object(app_main, "_is_prod", return_value=False)
    mocker.patch.object(app_main, "debug_enabled", return_value=True)
    mocker.patch.object(app_main, "get_debug_password", return_value="debug-secret")
    assert app_main._has_admin_override("Bearer debug-secret", None) is True


# ---------------------------------------------------------------------------
# Edge-case: verify_token swallows HTTPException(403) from enforce_email_verification
# ---------------------------------------------------------------------------
# The blanket `except Exception` in verify_token catches the HTTPException(403)
# raised by enforce_email_verification and re-raises it as HTTPException(401).
def test_verify_token_raises_403_for_unverified_email(app_main, mocker) -> None:
    # Unverified password users should receive a 403 from
    # enforce_email_verification, not a generic 401.
    decoded = {
        "uid": "user_unverified",
        "email_verified": False,
        "firebase": {"sign_in_provider": "password"},
    }
    mocker.patch.object(app_main, "verify_id_token", return_value=decoded)

    with pytest.raises(HTTPException) as ctx:
        app_main._verify_token("Bearer valid-but-unverified")
    assert ctx.value.status_code == 403


# ---------------------------------------------------------------------------
# Edge-case: has_admin_override with SANDBOX_ALLOW_ADMIN_OVERRIDE="true"
# ---------------------------------------------------------------------------
# When the flag is explicitly set to a truthy value the admin override should
# be permitted (assuming non-prod and the token matches).
def test_has_admin_override_truthy_allow_flag(app_main, monkeypatch, mocker) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "secret")
    monkeypatch.setenv("SANDBOX_ALLOW_ADMIN_OVERRIDE", "true")
    mocker.patch.object(app_main, "_is_prod", return_value=False)
    # With the flag explicitly "true", the override should succeed.
    assert app_main._has_admin_override("Bearer secret", None) is True
    # Also confirm the header-based token variant works.
    assert app_main._has_admin_override(None, "secret") is True
