from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backend.firebaseDB.user_database import UserDowngradeRetentionRecord
from backend.services import downgrade_retention_service as service
from backend.test.unit.firebase._fakes import FakeFirestoreClient


def _template(template_id: str, created_at: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=template_id,
        name=f"Template {template_id}",
        created_at=created_at,
        updated_at=created_at,
    )


def _group(group_id: str, template_ids: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        id=group_id,
        name=f"Group {group_id}",
        template_ids=template_ids,
    )


def _link(
    link_id: str,
    *,
    template_ids: list[str],
    status: str = "active",
    scope_type: str = "template",
    template_id: str | None = None,
    closed_reason: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=link_id,
        user_id="user-1",
        scope_type=scope_type,
        template_id=template_id,
        template_ids=template_ids,
        template_name=template_id,
        group_id=None,
        group_name=None,
        title=f"Link {link_id}",
        status=status,
        closed_reason=closed_reason,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


def _patch_eligible_base_user(
    mocker,
    *,
    role: str = "base",
    subscription_id: str | None = None,
    subscription_status: str | None = None,
) -> None:
    mocker.patch(
        "backend.services.downgrade_retention_service.get_user_profile",
        return_value=SimpleNamespace(role=role),
    )
    mocker.patch(
        "backend.services.downgrade_retention_service.get_user_billing_record",
        return_value=SimpleNamespace(
            subscription_id=subscription_id,
            subscription_status=subscription_status,
        ) if subscription_id is not None or subscription_status is not None else None,
    )


def test_apply_user_downgrade_retention_keeps_oldest_templates_and_closes_excess_links(mocker) -> None:
    _patch_eligible_base_user(mocker)
    mocker.patch(
        "backend.services.downgrade_retention_service.list_templates",
        return_value=[
            _template("tpl-1", "2026-01-01T00:00:00+00:00"),
            _template("tpl-2", "2026-01-02T00:00:00+00:00"),
            _template("tpl-3", "2026-01-03T00:00:00+00:00"),
            _template("tpl-4", "2026-01-04T00:00:00+00:00"),
        ],
    )
    mocker.patch(
        "backend.services.downgrade_retention_service.list_groups",
        return_value=[_group("group-1", ["tpl-3", "tpl-4"])],
    )
    mocker.patch(
        "backend.services.downgrade_retention_service.list_fill_links",
        return_value=[
            _link("link-1", template_ids=["tpl-1"], template_id="tpl-1"),
            _link("link-2", template_ids=["tpl-4"], template_id="tpl-4"),
            _link("link-3", template_ids=["tpl-2"], template_id="tpl-2"),
        ],
    )
    mocker.patch("backend.services.downgrade_retention_service.resolve_saved_forms_limit", return_value=3)
    mocker.patch("backend.services.downgrade_retention_service.resolve_fill_links_active_limit", return_value=1)
    mocker.patch("backend.services.downgrade_retention_service.get_user_downgrade_retention", return_value=None)
    mocker.patch("backend.services.downgrade_retention_service.now_iso", return_value="2026-03-10T00:00:00+00:00")
    set_retention_mock = mocker.patch("backend.services.downgrade_retention_service.set_user_downgrade_retention", return_value=None)
    close_fill_link_mock = mocker.patch("backend.services.downgrade_retention_service.close_fill_link", return_value=None)

    summary = service.apply_user_downgrade_retention("user-1")

    assert summary is not None
    assert summary["keptTemplateIds"] == ["tpl-1", "tpl-2", "tpl-3"]
    assert summary["pendingDeleteTemplateIds"] == ["tpl-4"]
    assert summary["pendingDeleteLinkIds"] == ["link-2"]
    assert summary["links"][0]["status"] == "closed"
    assert summary["counts"]["closedLinks"] == 1
    set_retention_mock.assert_called_once()
    assert set_retention_mock.call_args.kwargs["pending_delete_template_ids"] == ["tpl-4"]
    assert set_retention_mock.call_args.kwargs["pending_delete_link_ids"] == ["link-2"]
    close_fill_link_mock.assert_any_call("link-2", "user-1", closed_reason="downgrade_retention")
    close_fill_link_mock.assert_any_call("link-3", "user-1", closed_reason="downgrade_link_limit")


def test_apply_user_downgrade_retention_can_override_stale_active_subscription_state(mocker) -> None:
    _patch_eligible_base_user(mocker, subscription_id="sub_123", subscription_status="active")
    mocker.patch(
        "backend.services.downgrade_retention_service.list_templates",
        return_value=[
            _template("tpl-1", "2026-01-01T00:00:00+00:00"),
            _template("tpl-2", "2026-01-02T00:00:00+00:00"),
            _template("tpl-3", "2026-01-03T00:00:00+00:00"),
            _template("tpl-4", "2026-01-04T00:00:00+00:00"),
        ],
    )
    mocker.patch("backend.services.downgrade_retention_service.list_groups", return_value=[])
    mocker.patch(
        "backend.services.downgrade_retention_service.list_fill_links",
        return_value=[_link("link-4", template_ids=["tpl-4"], template_id="tpl-4")],
    )
    mocker.patch("backend.services.downgrade_retention_service.resolve_saved_forms_limit", return_value=3)
    mocker.patch("backend.services.downgrade_retention_service.resolve_fill_links_active_limit", return_value=1)
    mocker.patch("backend.services.downgrade_retention_service.get_user_downgrade_retention", return_value=None)
    set_retention_mock = mocker.patch("backend.services.downgrade_retention_service.set_user_downgrade_retention", return_value=None)
    close_fill_link_mock = mocker.patch("backend.services.downgrade_retention_service.close_fill_link", return_value=None)
    close_fill_link_mock = mocker.patch("backend.services.downgrade_retention_service.close_fill_link", return_value=None)

    summary = service.apply_user_downgrade_retention(
        "user-1",
        eligibility_override=service.DowngradeRetentionEligibility(
            should_apply=True,
            role="base",
            has_active_subscription=False,
        ),
    )

    assert summary is not None
    assert summary["pendingDeleteTemplateIds"] == ["tpl-4"]
    set_retention_mock.assert_called_once()
    close_fill_link_mock.assert_called_once_with("link-4", "user-1", closed_reason="downgrade_retention")


def test_apply_user_downgrade_retention_marks_deferred_billing_sync_when_requested(mocker) -> None:
    _patch_eligible_base_user(mocker, subscription_id="sub_123", subscription_status="active")
    mocker.patch(
        "backend.services.downgrade_retention_service.list_templates",
        return_value=[
            _template("tpl-1", "2026-01-01T00:00:00+00:00"),
            _template("tpl-2", "2026-01-02T00:00:00+00:00"),
            _template("tpl-3", "2026-01-03T00:00:00+00:00"),
            _template("tpl-4", "2026-01-04T00:00:00+00:00"),
        ],
    )
    mocker.patch("backend.services.downgrade_retention_service.list_groups", return_value=[])
    mocker.patch(
        "backend.services.downgrade_retention_service.list_fill_links",
        return_value=[_link("link-4", template_ids=["tpl-4"], template_id="tpl-4")],
    )
    mocker.patch("backend.services.downgrade_retention_service.resolve_saved_forms_limit", return_value=3)
    mocker.patch("backend.services.downgrade_retention_service.resolve_fill_links_active_limit", return_value=1)
    mocker.patch("backend.services.downgrade_retention_service.get_user_downgrade_retention", return_value=None)
    set_retention_mock = mocker.patch("backend.services.downgrade_retention_service.set_user_downgrade_retention", return_value=None)
    close_fill_link_mock = mocker.patch("backend.services.downgrade_retention_service.close_fill_link", return_value=None)

    summary = service.apply_user_downgrade_retention(
        "user-1",
        eligibility_override=service.DowngradeRetentionEligibility(
            should_apply=True,
            role="base",
            has_active_subscription=False,
        ),
        billing_state_deferred=True,
    )

    assert summary is not None
    assert set_retention_mock.call_args.kwargs["billing_state_deferred"] is True
    close_fill_link_mock.assert_called_once_with("link-4", "user-1", closed_reason="downgrade_retention")
    close_fill_link_mock.assert_called_once_with("link-4", "user-1", closed_reason="downgrade_retention")


def test_select_user_retained_templates_recomputes_keep_set(mocker) -> None:
    _patch_eligible_base_user(mocker)
    existing = UserDowngradeRetentionRecord(
        status="grace_period",
        policy_version=1,
        downgraded_at="2026-03-01T00:00:00+00:00",
        grace_ends_at="2026-03-31T00:00:00+00:00",
        saved_forms_limit=3,
        fill_links_active_limit=1,
        kept_template_ids=["tpl-1", "tpl-2", "tpl-3"],
        pending_delete_template_ids=["tpl-4"],
        pending_delete_link_ids=["link-4"],
    )
    mocker.patch("backend.services.downgrade_retention_service.get_user_downgrade_retention", return_value=existing)
    mocker.patch(
        "backend.services.downgrade_retention_service.list_templates",
        return_value=[
            _template("tpl-1", "2026-01-01T00:00:00+00:00"),
            _template("tpl-2", "2026-01-02T00:00:00+00:00"),
            _template("tpl-3", "2026-01-03T00:00:00+00:00"),
            _template("tpl-4", "2026-01-04T00:00:00+00:00"),
        ],
    )
    mocker.patch("backend.services.downgrade_retention_service.list_groups", return_value=[])
    mocker.patch(
        "backend.services.downgrade_retention_service.list_fill_links",
        return_value=[
            _link("link-1", template_ids=["tpl-1"], template_id="tpl-1"),
            _link("link-4", template_ids=["tpl-4"], template_id="tpl-4"),
        ],
    )
    set_retention_mock = mocker.patch("backend.services.downgrade_retention_service.set_user_downgrade_retention", return_value=None)
    close_fill_link_mock = mocker.patch("backend.services.downgrade_retention_service.close_fill_link", return_value=None)

    summary = service.select_user_retained_templates("user-1", ["tpl-2", "tpl-3", "tpl-4"])

    assert summary["keptTemplateIds"] == ["tpl-2", "tpl-3", "tpl-4"]
    assert summary["pendingDeleteTemplateIds"] == ["tpl-1"]
    assert summary["pendingDeleteLinkIds"] == ["link-1"]
    assert set_retention_mock.call_args.kwargs["kept_template_ids"] == ["tpl-2", "tpl-3", "tpl-4"]
    close_fill_link_mock.assert_called_once_with("link-1", "user-1", closed_reason="downgrade_retention")


def test_select_user_retained_templates_rejects_stale_plan_when_account_is_no_longer_eligible(mocker) -> None:
    _patch_eligible_base_user(mocker, subscription_id="sub_live", subscription_status="active")
    existing = UserDowngradeRetentionRecord(
        status="grace_period",
        policy_version=1,
        downgraded_at="2026-03-01T00:00:00+00:00",
        grace_ends_at="2026-03-31T00:00:00+00:00",
        saved_forms_limit=3,
        fill_links_active_limit=1,
        kept_template_ids=["tpl-1", "tpl-2", "tpl-3"],
        pending_delete_template_ids=["tpl-4"],
        pending_delete_link_ids=["link-4"],
    )
    mocker.patch("backend.services.downgrade_retention_service.get_user_downgrade_retention", return_value=existing)
    clear_mock = mocker.patch("backend.services.downgrade_retention_service.clear_user_downgrade_retention", return_value=None)
    set_retention_mock = mocker.patch("backend.services.downgrade_retention_service.set_user_downgrade_retention")

    try:
        service.select_user_retained_templates("user-1", ["tpl-2", "tpl-3", "tpl-4"])
        raise AssertionError("Expected DowngradeRetentionInactiveError")
    except service.DowngradeRetentionInactiveError as exc:
        assert "no longer active" in str(exc)

    clear_mock.assert_called_once_with("user-1")
    set_retention_mock.assert_not_called()


def test_select_user_retained_templates_reclassifies_previously_queued_link_when_template_becomes_kept(mocker) -> None:
    _patch_eligible_base_user(mocker)
    existing = UserDowngradeRetentionRecord(
        status="grace_period",
        policy_version=1,
        downgraded_at="2026-03-01T00:00:00+00:00",
        grace_ends_at="2026-03-31T00:00:00+00:00",
        saved_forms_limit=3,
        fill_links_active_limit=1,
        kept_template_ids=["tpl-1", "tpl-2", "tpl-3"],
        pending_delete_template_ids=["tpl-4"],
        pending_delete_link_ids=["link-delta"],
    )
    mocker.patch("backend.services.downgrade_retention_service.get_user_downgrade_retention", return_value=existing)
    mocker.patch(
        "backend.services.downgrade_retention_service.list_templates",
        return_value=[
            _template("tpl-1", "2026-01-01T00:00:00+00:00"),
            _template("tpl-2", "2026-01-02T00:00:00+00:00"),
            _template("tpl-3", "2026-01-03T00:00:00+00:00"),
            _template("tpl-4", "2026-01-04T00:00:00+00:00"),
        ],
    )
    mocker.patch("backend.services.downgrade_retention_service.list_groups", return_value=[])
    mocker.patch(
        "backend.services.downgrade_retention_service.list_fill_links",
        return_value=[
            _link("link-alpha", template_ids=["tpl-1"], template_id="tpl-1"),
            _link("link-beta", template_ids=["tpl-2"], template_id="tpl-2"),
            _link(
                "link-delta",
                template_ids=["tpl-4"],
                template_id="tpl-4",
                status="closed",
                closed_reason="downgrade_retention",
            ),
        ],
    )
    set_retention_mock = mocker.patch("backend.services.downgrade_retention_service.set_user_downgrade_retention", return_value=None)
    close_fill_link_mock = mocker.patch("backend.services.downgrade_retention_service.close_fill_link", return_value=None)
    update_fill_link_mock = mocker.patch("backend.services.downgrade_retention_service.update_fill_link", return_value=None)

    summary = service.select_user_retained_templates("user-1", ["tpl-1", "tpl-2", "tpl-4"])

    assert summary["keptTemplateIds"] == ["tpl-1", "tpl-2", "tpl-4"]
    assert summary["pendingDeleteTemplateIds"] == ["tpl-3"]
    assert summary["pendingDeleteLinkIds"] == []
    assert set_retention_mock.call_args.kwargs["pending_delete_link_ids"] == []
    close_fill_link_mock.assert_any_call("link-beta", "user-1", closed_reason="downgrade_link_limit")
    close_fill_link_mock.assert_any_call("link-delta", "user-1", closed_reason="downgrade_link_limit")
    update_fill_link_mock.assert_not_called()


def test_delete_user_downgrade_retention_now_purges_pending_templates_and_links(mocker) -> None:
    _patch_eligible_base_user(mocker)
    computation = service.DowngradeRetentionComputation(
        state=UserDowngradeRetentionRecord(
            status="grace_period",
            policy_version=1,
            downgraded_at="2026-03-01T00:00:00+00:00",
            grace_ends_at="2026-03-31T00:00:00+00:00",
            saved_forms_limit=3,
            fill_links_active_limit=1,
            kept_template_ids=["tpl-1", "tpl-2", "tpl-3"],
            pending_delete_template_ids=["tpl-4"],
            pending_delete_link_ids=["link-4"],
        ),
        templates=[],
        groups=[],
        links=[],
        pending_link_reasons={"link-4": "template_pending_delete"},
        active_limit_close_link_ids=[],
    )
    mocker.patch(
        "backend.services.downgrade_retention_service.get_user_downgrade_retention",
        return_value=computation.state,
    )
    mocker.patch(
        "backend.services.downgrade_retention_service._compute_retention",
        return_value=computation,
    )
    delete_template_mock = mocker.patch(
        "backend.services.downgrade_retention_service.delete_saved_form_assets",
        return_value=True,
    )
    delete_link_mock = mocker.patch("backend.services.downgrade_retention_service.delete_fill_link", return_value=True)
    sync_mock = mocker.patch("backend.services.downgrade_retention_service.sync_user_downgrade_retention", return_value=None)

    result = service.delete_user_downgrade_retention_now("user-1")

    assert result == {"deletedTemplateIds": ["tpl-4"], "deletedLinkIds": ["link-4"]}
    delete_template_mock.assert_called_once_with("tpl-4", "user-1", hard_delete_link_records=True)
    delete_link_mock.assert_called_once_with("link-4", "user-1")
    sync_mock.assert_called_once_with("user-1", create_if_missing=False)


def test_sync_user_downgrade_retention_can_create_missing_plan_for_base_user(mocker) -> None:
    _patch_eligible_base_user(mocker)
    mocker.patch("backend.services.downgrade_retention_service.get_user_downgrade_retention", return_value=None)
    mocker.patch(
        "backend.services.downgrade_retention_service.list_templates",
        return_value=[
            _template("tpl-1", "2026-01-01T00:00:00+00:00"),
            _template("tpl-2", "2026-01-02T00:00:00+00:00"),
            _template("tpl-3", "2026-01-03T00:00:00+00:00"),
            _template("tpl-4", "2026-01-04T00:00:00+00:00"),
        ],
    )
    mocker.patch("backend.services.downgrade_retention_service.list_groups", return_value=[])
    mocker.patch(
        "backend.services.downgrade_retention_service.list_fill_links",
        return_value=[_link("link-4", template_ids=["tpl-4"], template_id="tpl-4")],
    )
    mocker.patch("backend.services.downgrade_retention_service.resolve_saved_forms_limit", return_value=3)
    mocker.patch("backend.services.downgrade_retention_service.resolve_fill_links_active_limit", return_value=1)
    set_retention_mock = mocker.patch("backend.services.downgrade_retention_service.set_user_downgrade_retention", return_value=None)
    close_fill_link_mock = mocker.patch("backend.services.downgrade_retention_service.close_fill_link", return_value=None)
    close_fill_link_mock = mocker.patch("backend.services.downgrade_retention_service.close_fill_link", return_value=None)

    summary = service.sync_user_downgrade_retention("user-1", create_if_missing=True)

    assert summary is not None
    assert summary["pendingDeleteTemplateIds"] == ["tpl-4"]
    set_retention_mock.assert_called_once()
    close_fill_link_mock.assert_called_once_with("link-4", "user-1", closed_reason="downgrade_retention")
    close_fill_link_mock.assert_called_once_with("link-4", "user-1", closed_reason="downgrade_retention")


def test_sync_user_downgrade_retention_does_not_trust_active_status_without_subscription_id(mocker) -> None:
    _patch_eligible_base_user(mocker, subscription_status="active")
    mocker.patch("backend.services.downgrade_retention_service.get_user_downgrade_retention", return_value=None)
    mocker.patch(
        "backend.services.downgrade_retention_service.list_templates",
        return_value=[
            _template("tpl-1", "2026-01-01T00:00:00+00:00"),
            _template("tpl-2", "2026-01-02T00:00:00+00:00"),
            _template("tpl-3", "2026-01-03T00:00:00+00:00"),
            _template("tpl-4", "2026-01-04T00:00:00+00:00"),
        ],
    )
    mocker.patch("backend.services.downgrade_retention_service.list_groups", return_value=[])
    mocker.patch(
        "backend.services.downgrade_retention_service.list_fill_links",
        return_value=[_link("link-4", template_ids=["tpl-4"], template_id="tpl-4")],
    )
    mocker.patch("backend.services.downgrade_retention_service.resolve_saved_forms_limit", return_value=3)
    mocker.patch("backend.services.downgrade_retention_service.resolve_fill_links_active_limit", return_value=1)
    set_retention_mock = mocker.patch("backend.services.downgrade_retention_service.set_user_downgrade_retention", return_value=None)
    close_fill_link_mock = mocker.patch("backend.services.downgrade_retention_service.close_fill_link", return_value=None)

    summary = service.sync_user_downgrade_retention("user-1", create_if_missing=True)

    assert summary is not None
    assert summary["pendingDeleteTemplateIds"] == ["tpl-4"]
    set_retention_mock.assert_called_once()
    close_fill_link_mock.assert_called_once_with("link-4", "user-1", closed_reason="downgrade_retention")


def test_sync_user_downgrade_retention_preserves_deferred_plan_during_stale_active_billing_sync(mocker) -> None:
    _patch_eligible_base_user(mocker, subscription_id="sub_123", subscription_status="active")
    existing = UserDowngradeRetentionRecord(
        status="grace_period",
        policy_version=1,
        downgraded_at="2026-03-01T00:00:00+00:00",
        grace_ends_at="2026-03-31T00:00:00+00:00",
        saved_forms_limit=3,
        fill_links_active_limit=1,
        kept_template_ids=["tpl-1", "tpl-2", "tpl-3"],
        pending_delete_template_ids=["tpl-4"],
        pending_delete_link_ids=["link-4"],
        billing_state_deferred=True,
    )
    mocker.patch("backend.services.downgrade_retention_service.get_user_downgrade_retention", return_value=existing)
    mocker.patch(
        "backend.services.downgrade_retention_service.list_templates",
        return_value=[
            _template("tpl-1", "2026-01-01T00:00:00+00:00"),
            _template("tpl-2", "2026-01-02T00:00:00+00:00"),
            _template("tpl-3", "2026-01-03T00:00:00+00:00"),
            _template("tpl-4", "2026-01-04T00:00:00+00:00"),
        ],
    )
    mocker.patch("backend.services.downgrade_retention_service.list_groups", return_value=[])
    mocker.patch(
        "backend.services.downgrade_retention_service.list_fill_links",
        return_value=[_link("link-4", template_ids=["tpl-4"], template_id="tpl-4")],
    )
    set_retention_mock = mocker.patch("backend.services.downgrade_retention_service.set_user_downgrade_retention", return_value=None)
    close_fill_link_mock = mocker.patch("backend.services.downgrade_retention_service.close_fill_link", return_value=None)
    clear_mock = mocker.patch("backend.services.downgrade_retention_service.clear_user_downgrade_retention", return_value=None)
    close_fill_link_mock = mocker.patch("backend.services.downgrade_retention_service.close_fill_link", return_value=None)

    summary = service.sync_user_downgrade_retention("user-1")

    assert summary is not None
    assert summary["pendingDeleteTemplateIds"] == ["tpl-4"]
    assert set_retention_mock.call_args.kwargs["billing_state_deferred"] is True
    close_fill_link_mock.assert_called_once_with("link-4", "user-1", closed_reason="downgrade_retention")
    clear_mock.assert_not_called()
    close_fill_link_mock.assert_called_once_with("link-4", "user-1", closed_reason="downgrade_retention")


def test_sync_user_downgrade_retention_clears_existing_plan_when_subscription_is_confirmed_active(mocker) -> None:
    _patch_eligible_base_user(mocker, subscription_id="sub_123", subscription_status="active")
    existing = UserDowngradeRetentionRecord(
        status="grace_period",
        policy_version=1,
        downgraded_at="2026-03-01T00:00:00+00:00",
        grace_ends_at="2026-03-31T00:00:00+00:00",
        saved_forms_limit=3,
        fill_links_active_limit=1,
        kept_template_ids=["tpl-1", "tpl-2", "tpl-3"],
        pending_delete_template_ids=["tpl-4"],
        pending_delete_link_ids=["link-4"],
    )
    mocker.patch("backend.services.downgrade_retention_service.get_user_downgrade_retention", return_value=existing)
    set_retention_mock = mocker.patch("backend.services.downgrade_retention_service.set_user_downgrade_retention", return_value=None)
    clear_mock = mocker.patch("backend.services.downgrade_retention_service.clear_user_downgrade_retention", return_value=None)

    summary = service.sync_user_downgrade_retention("user-1")

    assert summary is None
    set_retention_mock.assert_not_called()
    clear_mock.assert_called_once_with("user-1")


def test_sync_user_downgrade_retention_migrates_existing_plan_to_current_policy_limits(mocker) -> None:
    _patch_eligible_base_user(mocker)
    existing = UserDowngradeRetentionRecord(
        status="grace_period",
        policy_version=1,
        downgraded_at="2026-03-01T00:00:00+00:00",
        grace_ends_at="2026-03-31T00:00:00+00:00",
        saved_forms_limit=4,
        fill_links_active_limit=2,
        kept_template_ids=["tpl-1", "tpl-2", "tpl-3", "tpl-4"],
        pending_delete_template_ids=[],
        pending_delete_link_ids=[],
    )
    mocker.patch.object(service, "DOWNGRADE_RETENTION_POLICY_VERSION", 2)
    mocker.patch("backend.services.downgrade_retention_service.get_user_downgrade_retention", return_value=existing)
    mocker.patch(
        "backend.services.downgrade_retention_service.list_templates",
        return_value=[
            _template("tpl-1", "2026-01-01T00:00:00+00:00"),
            _template("tpl-2", "2026-01-02T00:00:00+00:00"),
            _template("tpl-3", "2026-01-03T00:00:00+00:00"),
            _template("tpl-4", "2026-01-04T00:00:00+00:00"),
        ],
    )
    mocker.patch("backend.services.downgrade_retention_service.list_groups", return_value=[])
    mocker.patch(
        "backend.services.downgrade_retention_service.list_fill_links",
        return_value=[_link("link-4", template_ids=["tpl-4"], template_id="tpl-4")],
    )
    mocker.patch("backend.services.downgrade_retention_service.resolve_saved_forms_limit", return_value=2)
    mocker.patch("backend.services.downgrade_retention_service.resolve_fill_links_active_limit", return_value=1)
    set_retention_mock = mocker.patch("backend.services.downgrade_retention_service.set_user_downgrade_retention", return_value=None)
    close_fill_link_mock = mocker.patch("backend.services.downgrade_retention_service.close_fill_link", return_value=None)
    close_fill_link_mock = mocker.patch("backend.services.downgrade_retention_service.close_fill_link", return_value=None)

    summary = service.sync_user_downgrade_retention("user-1")

    assert summary is not None
    assert summary["policyVersion"] == 2
    assert summary["savedFormsLimit"] == 2
    assert summary["fillLinksActiveLimit"] == 1
    assert summary["keptTemplateIds"] == ["tpl-1", "tpl-2"]
    assert summary["pendingDeleteTemplateIds"] == ["tpl-3", "tpl-4"]
    assert summary["pendingDeleteLinkIds"] == ["link-4"]
    assert set_retention_mock.call_args.kwargs["policy_version"] == 2
    assert set_retention_mock.call_args.kwargs["saved_forms_limit"] == 2
    assert set_retention_mock.call_args.kwargs["fill_links_active_limit"] == 1
    close_fill_link_mock.assert_called_once_with("link-4", "user-1", closed_reason="downgrade_retention")
    close_fill_link_mock.assert_called_once_with("link-4", "user-1", closed_reason="downgrade_retention")


def test_apply_user_downgrade_retention_rolls_back_link_updates_when_state_persist_fails(mocker) -> None:
    _patch_eligible_base_user(mocker)
    mocker.patch(
        "backend.services.downgrade_retention_service.list_templates",
        return_value=[
            _template("tpl-1", "2026-01-01T00:00:00+00:00"),
            _template("tpl-2", "2026-01-02T00:00:00+00:00"),
            _template("tpl-3", "2026-01-03T00:00:00+00:00"),
            _template("tpl-4", "2026-01-04T00:00:00+00:00"),
        ],
    )
    mocker.patch("backend.services.downgrade_retention_service.list_groups", return_value=[])
    mocker.patch(
        "backend.services.downgrade_retention_service.list_fill_links",
        return_value=[_link("link-4", template_ids=["tpl-4"], template_id="tpl-4")],
    )
    mocker.patch("backend.services.downgrade_retention_service.resolve_saved_forms_limit", return_value=3)
    mocker.patch("backend.services.downgrade_retention_service.resolve_fill_links_active_limit", return_value=1)
    mocker.patch("backend.services.downgrade_retention_service.get_user_downgrade_retention", return_value=None)
    mocker.patch(
        "backend.services.downgrade_retention_service.set_user_downgrade_retention",
        side_effect=RuntimeError("persist failed"),
    )
    close_fill_link_mock = mocker.patch("backend.services.downgrade_retention_service.close_fill_link", return_value=None)
    update_fill_link_mock = mocker.patch("backend.services.downgrade_retention_service.update_fill_link", return_value=None)

    try:
        service.apply_user_downgrade_retention("user-1")
        raise AssertionError("Expected RuntimeError")
    except RuntimeError as exc:
        assert "persist failed" in str(exc)

    close_fill_link_mock.assert_called_once_with("link-4", "user-1", closed_reason="downgrade_retention")
    update_fill_link_mock.assert_called_once_with("link-4", "user-1", status="active", closed_reason=None)


def test_commit_retention_state_rolls_back_applied_link_changes_when_later_mutation_fails(mocker) -> None:
    computation = service.DowngradeRetentionComputation(
        state=UserDowngradeRetentionRecord(
            status="grace_period",
            policy_version=1,
            downgraded_at="2026-03-01T00:00:00+00:00",
            grace_ends_at="2026-03-31T00:00:00+00:00",
            saved_forms_limit=3,
            fill_links_active_limit=1,
            kept_template_ids=["tpl-1", "tpl-2", "tpl-3"],
            pending_delete_template_ids=["tpl-4"],
            pending_delete_link_ids=["link-4"],
        ),
        templates=[],
        groups=[],
        links=[],
        pending_link_reasons={},
        active_limit_close_link_ids=["link-3"],
    )
    mutations = [
        service._RetentionLinkMutation(
            link_id="link-3",
            user_id="user-1",
            desired_status="closed",
            desired_closed_reason="downgrade_link_limit",
            original_status="active",
            original_closed_reason=None,
        ),
        service._RetentionLinkMutation(
            link_id="link-4",
            user_id="user-1",
            desired_status="closed",
            desired_closed_reason="downgrade_retention",
            original_status="active",
            original_closed_reason=None,
        ),
    ]
    mocker.patch(
        "backend.services.downgrade_retention_service._plan_retention_link_mutations",
        return_value=mutations,
    )
    apply_link_mutation_mock = mocker.patch(
        "backend.services.downgrade_retention_service._apply_link_mutation",
        side_effect=[None, RuntimeError("sync failed")],
    )
    rollback_mock = mocker.patch(
        "backend.services.downgrade_retention_service._rollback_retention_link_mutations",
        return_value=None,
    )
    persist_retention_mock = mocker.patch(
        "backend.services.downgrade_retention_service._persist_retention_state",
        return_value=None,
    )

    try:
        service._commit_retention_state("user-1", computation)
        raise AssertionError("Expected RuntimeError")
    except RuntimeError as exc:
        assert "sync failed" in str(exc)

    apply_link_mutation_mock.assert_any_call(mutations[0])
    apply_link_mutation_mock.assert_any_call(mutations[1])
    rollback_mock.assert_called_once_with([mutations[0]])
    persist_retention_mock.assert_not_called()


def test_select_user_retained_templates_uses_current_policy_keep_count(mocker) -> None:
    _patch_eligible_base_user(mocker)
    existing = UserDowngradeRetentionRecord(
        status="grace_period",
        policy_version=1,
        downgraded_at="2026-03-01T00:00:00+00:00",
        grace_ends_at="2026-03-31T00:00:00+00:00",
        saved_forms_limit=4,
        fill_links_active_limit=1,
        kept_template_ids=["tpl-1", "tpl-2", "tpl-3", "tpl-4"],
        pending_delete_template_ids=[],
        pending_delete_link_ids=[],
    )
    mocker.patch("backend.services.downgrade_retention_service.get_user_downgrade_retention", return_value=existing)
    mocker.patch("backend.services.downgrade_retention_service.resolve_saved_forms_limit", return_value=3)
    mocker.patch(
        "backend.services.downgrade_retention_service.list_templates",
        return_value=[
            _template("tpl-1", "2026-01-01T00:00:00+00:00"),
            _template("tpl-2", "2026-01-02T00:00:00+00:00"),
            _template("tpl-3", "2026-01-03T00:00:00+00:00"),
            _template("tpl-4", "2026-01-04T00:00:00+00:00"),
        ],
    )

    try:
        service.select_user_retained_templates("user-1", ["tpl-1", "tpl-2", "tpl-3", "tpl-4"])
        raise AssertionError("Expected ValueError")
    except ValueError as exc:
        assert "Select exactly 3 saved forms to keep." in str(exc)


def test_delete_user_downgrade_retention_now_clears_stale_retention_for_pro_account(mocker) -> None:
    _patch_eligible_base_user(mocker, role="pro")
    existing = UserDowngradeRetentionRecord(
        status="grace_period",
        policy_version=1,
        downgraded_at="2026-03-01T00:00:00+00:00",
        grace_ends_at="2026-03-31T00:00:00+00:00",
        saved_forms_limit=3,
        fill_links_active_limit=1,
        kept_template_ids=["tpl-1", "tpl-2", "tpl-3"],
        pending_delete_template_ids=["tpl-4"],
        pending_delete_link_ids=["link-4"],
    )
    mocker.patch("backend.services.downgrade_retention_service.get_user_downgrade_retention", return_value=existing)
    clear_mock = mocker.patch("backend.services.downgrade_retention_service.clear_user_downgrade_retention", return_value=None)
    delete_template_mock = mocker.patch("backend.services.downgrade_retention_service.delete_saved_form_assets")
    delete_link_mock = mocker.patch("backend.services.downgrade_retention_service.delete_fill_link")

    result = service.delete_user_downgrade_retention_now("user-1")

    assert result == {"deletedTemplateIds": [], "deletedLinkIds": []}
    clear_mock.assert_called_once_with("user-1")
    delete_template_mock.assert_not_called()
    delete_link_mock.assert_not_called()


def test_delete_user_downgrade_retention_now_clears_stale_retention_for_base_account_with_active_subscription(mocker) -> None:
    _patch_eligible_base_user(mocker, role="base", subscription_id="sub_live", subscription_status="active")
    existing = UserDowngradeRetentionRecord(
        status="grace_period",
        policy_version=1,
        downgraded_at="2026-03-01T00:00:00+00:00",
        grace_ends_at="2026-03-31T00:00:00+00:00",
        saved_forms_limit=3,
        fill_links_active_limit=1,
        kept_template_ids=["tpl-1", "tpl-2", "tpl-3"],
        pending_delete_template_ids=["tpl-4"],
        pending_delete_link_ids=["link-4"],
    )
    mocker.patch("backend.services.downgrade_retention_service.get_user_downgrade_retention", return_value=existing)
    clear_mock = mocker.patch("backend.services.downgrade_retention_service.clear_user_downgrade_retention", return_value=None)
    delete_template_mock = mocker.patch("backend.services.downgrade_retention_service.delete_saved_form_assets")
    delete_link_mock = mocker.patch("backend.services.downgrade_retention_service.delete_fill_link")

    result = service.delete_user_downgrade_retention_now("user-1")

    assert result == {"deletedTemplateIds": [], "deletedLinkIds": []}
    clear_mock.assert_called_once_with("user-1")
    delete_template_mock.assert_not_called()
    delete_link_mock.assert_not_called()


def test_delete_user_downgrade_retention_now_reports_links_deleted_by_template_cascade(mocker) -> None:
    _patch_eligible_base_user(mocker)
    existing = UserDowngradeRetentionRecord(
        status="grace_period",
        policy_version=1,
        downgraded_at="2026-03-01T00:00:00+00:00",
        grace_ends_at="2026-03-31T00:00:00+00:00",
        saved_forms_limit=3,
        fill_links_active_limit=1,
        kept_template_ids=["tpl-1", "tpl-2", "tpl-3"],
        pending_delete_template_ids=["tpl-4"],
        pending_delete_link_ids=["link-template", "link-group"],
    )
    computation = service.DowngradeRetentionComputation(
        state=existing,
        templates=[
            _template("tpl-1", "2026-01-01T00:00:00+00:00"),
            _template("tpl-2", "2026-01-02T00:00:00+00:00"),
            _template("tpl-3", "2026-01-03T00:00:00+00:00"),
            _template("tpl-4", "2026-01-04T00:00:00+00:00"),
        ],
        groups=[],
        links=[
            _link("link-template", template_ids=["tpl-4"], template_id="tpl-4"),
            _link("link-group", template_ids=["tpl-3", "tpl-4"], scope_type="group"),
        ],
        active_limit_close_link_ids=[],
        pending_link_reasons={"link-template": "template_pending_delete", "link-group": "template_pending_delete"},
    )
    mocker.patch("backend.services.downgrade_retention_service.get_user_downgrade_retention", return_value=existing)
    mocker.patch("backend.services.downgrade_retention_service._compute_retention", return_value=computation)
    delete_template_mock = mocker.patch("backend.services.downgrade_retention_service.delete_saved_form_assets", return_value=True)
    delete_link_mock = mocker.patch("backend.services.downgrade_retention_service.delete_fill_link", return_value=False)
    sync_mock = mocker.patch("backend.services.downgrade_retention_service.sync_user_downgrade_retention", return_value=None)

    result = service.delete_user_downgrade_retention_now("user-1")

    assert result == {"deletedTemplateIds": ["tpl-4"], "deletedLinkIds": ["link-template", "link-group"]}
    delete_template_mock.assert_called_once_with("tpl-4", "user-1", hard_delete_link_records=True)
    delete_link_mock.assert_any_call("link-template", "user-1")
    delete_link_mock.assert_any_call("link-group", "user-1")
    sync_mock.assert_called_once_with("user-1", create_if_missing=False)


def test_list_users_with_expired_downgrade_retention_filters_deadline(mocker) -> None:
    client = FakeFirestoreClient()
    now_dt = datetime(2026, 3, 10, tzinfo=timezone.utc)
    client.collection("app_users").document("expired-user").seed(
        {
            "role": "base",
            "downgrade_retention": {
                "status": "grace_period",
                "grace_ends_at": (now_dt - timedelta(days=1)).isoformat(),
            }
        }
    )
    client.collection("app_users").document("active-user").seed(
        {
            "role": "base",
            "downgrade_retention": {
                "status": "grace_period",
                "grace_ends_at": (now_dt + timedelta(days=5)).isoformat(),
            }
        }
    )
    mocker.patch("backend.services.downgrade_retention_service.get_firestore_client", return_value=client)

    expired_users = service.list_users_with_expired_downgrade_retention(as_of=now_dt)

    assert expired_users == ["expired-user"]


def test_list_users_with_expired_downgrade_retention_skips_active_subscription(mocker) -> None:
    client = FakeFirestoreClient()
    now_dt = datetime(2026, 3, 10, tzinfo=timezone.utc)
    client.collection("app_users").document("expired-user").seed(
        {
            "role": "base",
            "stripe_subscription_id": "sub_123",
            "stripe_subscription_status": "active",
            "downgrade_retention": {
                "status": "grace_period",
                "grace_ends_at": (now_dt - timedelta(days=1)).isoformat(),
            },
        }
    )
    mocker.patch("backend.services.downgrade_retention_service.get_firestore_client", return_value=client)

    expired_users = service.list_users_with_expired_downgrade_retention(as_of=now_dt)

    assert expired_users == []


def test_list_users_with_expired_downgrade_retention_does_not_trust_status_without_subscription_id(mocker) -> None:
    client = FakeFirestoreClient()
    now_dt = datetime(2026, 3, 10, tzinfo=timezone.utc)
    client.collection("app_users").document("expired-user").seed(
        {
            "role": "base",
            "stripe_subscription_status": "active",
            "downgrade_retention": {
                "status": "grace_period",
                "grace_ends_at": (now_dt - timedelta(days=1)).isoformat(),
            },
        }
    )
    mocker.patch("backend.services.downgrade_retention_service.get_firestore_client", return_value=client)

    expired_users = service.list_users_with_expired_downgrade_retention(as_of=now_dt)

    assert expired_users == ["expired-user"]


def test_list_users_with_expired_downgrade_retention_skips_paid_accounts(mocker) -> None:
    client = FakeFirestoreClient()
    now_dt = datetime(2026, 3, 10, tzinfo=timezone.utc)
    client.collection("app_users").document("pro-user").seed(
        {
            "role": "pro",
            "downgrade_retention": {
                "status": "grace_period",
                "grace_ends_at": (now_dt - timedelta(days=1)).isoformat(),
            },
        }
    )
    client.collection("app_users").document("active-billing-user").seed(
        {
            "role": "base",
            "stripe_subscription_id": "sub_123",
            "stripe_subscription_status": "active",
            "downgrade_retention": {
                "status": "grace_period",
                "grace_ends_at": (now_dt - timedelta(days=1)).isoformat(),
            },
        }
    )
    client.collection("app_users").document("expired-base-user").seed(
        {
            "role": "base",
            "stripe_subscription_status": "canceled",
            "downgrade_retention": {
                "status": "grace_period",
                "grace_ends_at": (now_dt - timedelta(days=1)).isoformat(),
            },
        }
    )
    mocker.patch("backend.services.downgrade_retention_service.get_firestore_client", return_value=client)

    expired_users = service.list_users_with_expired_downgrade_retention(as_of=now_dt)

    assert expired_users == ["expired-base-user"]


def test_list_users_with_expired_downgrade_retention_uses_snapshot_retention_payload(mocker) -> None:
    client = FakeFirestoreClient()
    now_dt = datetime(2026, 3, 10, tzinfo=timezone.utc)
    client.collection("app_users").document("expired-user").seed(
        {
            "role": "base",
            "downgrade_retention": {
                "status": "grace_period",
                "policy_version": 2,
                "saved_forms_limit": 3,
                "fill_links_active_limit": 1,
                "kept_template_ids": ["tpl-1"],
                "pending_delete_template_ids": ["tpl-2"],
                "pending_delete_link_ids": ["link-2"],
                "grace_ends_at": (now_dt - timedelta(days=1)).isoformat(),
            },
        }
    )
    mocker.patch("backend.services.downgrade_retention_service.get_firestore_client", return_value=client)
    get_retention_mock = mocker.patch(
        "backend.services.downgrade_retention_service.get_user_downgrade_retention",
        side_effect=AssertionError("Should use the query snapshot instead of reloading retention."),
    )

    expired_users = service.list_users_with_expired_downgrade_retention(as_of=now_dt)

    assert expired_users == ["expired-user"]
    get_retention_mock.assert_not_called()
