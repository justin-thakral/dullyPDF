from backend.firebaseDB.group_database import TemplateGroupRecord
from backend.firebaseDB.fill_link_database import FillLinkRecord
from backend.firebaseDB.template_database import TemplateRecord


def _template_record(
    *,
    template_id: str,
    name: str,
    created_at: str = "2025-01-01T00:00:00.000Z",
) -> TemplateRecord:
    return TemplateRecord(
        id=template_id,
        pdf_bucket_path=f"gs://forms/{template_id}.pdf",
        template_bucket_path=f"gs://templates/{template_id}.pdf",
        metadata={},
        created_at=created_at,
        updated_at=created_at,
        name=name,
    )


def _group_record(
    *,
    group_id: str = "group-1",
    user_id: str = "user_base",
    name: str = "Admissions",
    template_ids: list[str] | None = None,
) -> TemplateGroupRecord:
    return TemplateGroupRecord(
        id=group_id,
        user_id=user_id,
        name=name,
        normalized_name=name.lower(),
        template_ids=template_ids or ["tpl-b", "tpl-a"],
        created_at="2025-01-02T00:00:00.000Z",
        updated_at="2025-01-02T00:00:00.000Z",
    )


def _fill_link_record(
    *,
    link_id: str = "link-1",
    group_id: str = "group-1",
    group_name: str = "Admissions",
    template_ids: list[str] | None = None,
    status: str = "active",
    title: str | None = "Admissions",
) -> FillLinkRecord:
    return FillLinkRecord(
        id=link_id,
        user_id="user_base",
        scope_type="group",
        template_id=None,
        template_name=None,
        group_id=group_id,
        group_name=group_name,
        template_ids=template_ids or ["tpl-b", "tpl-a"],
        title=title,
        public_token="token-1",
        status=status,
        closed_reason=None if status == "active" else "owner_closed",
        max_responses=5,
        response_count=0,
        questions=[{"key": "full_name", "label": "Full Name", "type": "text"}],
        require_all_fields=False,
        created_at="2025-01-02T00:00:00.000Z",
        updated_at="2025-01-02T00:00:00.000Z",
        published_at="2025-01-02T00:00:00.000Z",
        closed_at=None,
    )


def _patch_auth(mocker, app_main, user) -> None:
    mocker.patch.object(app_main, "_verify_token", return_value={"uid": user.app_user_id})
    mocker.patch.object(app_main, "ensure_user", return_value=user)


def test_list_groups_serializes_template_summaries_in_alphabetical_order(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(
        app_main,
        "list_templates",
        return_value=[
            _template_record(template_id="tpl-a", name="Alpha Packet"),
            _template_record(template_id="tpl-b", name="Bravo Intake"),
        ],
    )
    mocker.patch.object(
        app_main,
        "list_groups",
        return_value=[_group_record(template_ids=["tpl-b", "tpl-a"])],
    )

    response = client.get("/api/groups", headers=auth_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["groups"][0]["name"] == "Admissions"
    assert payload["groups"][0]["templateIds"] == ["tpl-a", "tpl-b"]
    assert [entry["name"] for entry in payload["groups"][0]["templates"]] == [
        "Alpha Packet",
        "Bravo Intake",
    ]


def test_create_group_rejects_unknown_template_ids(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(
        app_main,
        "list_templates",
        return_value=[_template_record(template_id="tpl-a", name="Alpha Packet")],
    )
    mocker.patch.object(app_main, "list_groups", return_value=[])

    response = client.post(
        "/api/groups",
        json={"name": "Admissions", "templateIds": ["tpl-a", "tpl-missing"]},
        headers=auth_headers,
    )

    assert response.status_code == 404
    assert "not found" in response.text.lower()


def test_create_group_rejects_duplicate_normalized_name(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(
        app_main,
        "list_templates",
        return_value=[_template_record(template_id="tpl-a", name="Alpha Packet")],
    )
    mocker.patch.object(app_main, "normalize_group_name", side_effect=lambda value: "admissions intake")
    mocker.patch.object(
        app_main,
        "list_groups",
        return_value=[_group_record(name="Admissions Intake", template_ids=["tpl-a"])],
    )

    response = client.post(
        "/api/groups",
        json={"name": "  Admissions   Intake ", "templateIds": ["tpl-a"]},
        headers=auth_headers,
    )

    assert response.status_code == 409
    assert "already exists" in response.text


def test_create_group_returns_created_group_payload(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    templates = [
        _template_record(template_id="tpl-a", name="Alpha Packet"),
        _template_record(template_id="tpl-b", name="Bravo Intake"),
    ]
    created_group = _group_record(name="Admissions", template_ids=["tpl-b", "tpl-a"])
    mocker.patch.object(app_main, "list_templates", return_value=templates)
    mocker.patch.object(app_main, "list_groups", return_value=[])
    create_group_mock = mocker.patch.object(app_main, "create_group", return_value=created_group)

    response = client.post(
        "/api/groups",
        json={"name": "Admissions", "templateIds": ["tpl-b", "tpl-a"]},
        headers=auth_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["group"]["name"] == "Admissions"
    assert payload["group"]["templateIds"] == ["tpl-a", "tpl-b"]
    create_group_mock.assert_called_once_with(base_user.app_user_id, name="Admissions", template_ids=["tpl-b", "tpl-a"])


def test_get_group_returns_404_when_missing(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "get_group", return_value=None)

    response = client.get("/api/groups/missing", headers=auth_headers)

    assert response.status_code == 404
    assert "Group not found" in response.text


def test_update_group_rejects_duplicate_name(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "get_group", return_value=_group_record(group_id="group-1", name="Admissions"))
    mocker.patch.object(
        app_main,
        "list_templates",
        return_value=[_template_record(template_id="tpl-a", name="Alpha Packet")],
    )
    mocker.patch.object(app_main, "normalize_group_name", side_effect=lambda value: "admissions intake")
    mocker.patch.object(
        app_main,
        "list_groups",
        return_value=[
            _group_record(group_id="group-1", name="Admissions", template_ids=["tpl-a"]),
            _group_record(group_id="group-2", name="Admissions Intake", template_ids=["tpl-a"]),
        ],
    )

    response = client.patch(
        "/api/groups/group-1",
        json={"name": "Admissions Intake", "templateIds": ["tpl-a"]},
        headers=auth_headers,
    )

    assert response.status_code == 409
    assert "already exists" in response.text


def test_update_group_returns_updated_payload(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    templates = [
        _template_record(template_id="tpl-a", name="Alpha Packet"),
        _template_record(template_id="tpl-b", name="Bravo Intake"),
    ]
    mocker.patch.object(app_main, "get_group", return_value=_group_record(group_id="group-1", name="Admissions"))
    mocker.patch.object(app_main, "list_templates", return_value=templates)
    mocker.patch.object(app_main, "list_groups", return_value=[_group_record(group_id="group-1", name="Admissions")])
    update_group_mock = mocker.patch.object(
        app_main,
        "update_group",
        return_value=_group_record(group_id="group-1", name="Updated Admissions", template_ids=["tpl-b", "tpl-a"]),
    )

    response = client.patch(
        "/api/groups/group-1",
        json={"name": "Updated Admissions", "templateIds": ["tpl-b", "tpl-a"]},
        headers=auth_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["group"]["name"] == "Updated Admissions"
    assert payload["group"]["templateIds"] == ["tpl-a", "tpl-b"]
    update_group_mock.assert_called_once_with(
        "group-1",
        base_user.app_user_id,
        name="Updated Admissions",
        template_ids=["tpl-b", "tpl-a"],
    )


def test_update_group_closes_active_group_fill_link_when_template_membership_changes(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    existing_group = _group_record(group_id="group-1", name="Admissions", template_ids=["tpl-a", "tpl-b"])
    updated_group = _group_record(group_id="group-1", name="Admissions", template_ids=["tpl-a"])
    mocker.patch.object(app_main, "get_group", return_value=existing_group)
    mocker.patch.object(
        app_main,
        "list_templates",
        return_value=[
            _template_record(template_id="tpl-a", name="Alpha Packet"),
            _template_record(template_id="tpl-b", name="Bravo Intake"),
        ],
    )
    mocker.patch.object(app_main, "list_groups", return_value=[existing_group])
    mocker.patch.object(app_main, "update_group", return_value=updated_group)
    mocker.patch.object(app_main, "get_fill_link_for_group", return_value=_fill_link_record(template_ids=["tpl-a", "tpl-b"]))
    close_fill_link_mock = mocker.patch.object(app_main, "close_fill_link", return_value=_fill_link_record(status="closed", template_ids=["tpl-a", "tpl-b"]))
    update_fill_link_mock = mocker.patch.object(app_main, "update_fill_link", return_value=None)

    response = client.patch(
        "/api/groups/group-1",
        json={"name": "Admissions", "templateIds": ["tpl-a"]},
        headers=auth_headers,
    )

    assert response.status_code == 200
    close_fill_link_mock.assert_called_once_with("link-1", base_user.app_user_id, closed_reason="group_updated")
    update_fill_link_mock.assert_not_called()


def test_update_group_syncs_existing_group_fill_link_name_without_closing_when_membership_is_unchanged(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    existing_group = _group_record(group_id="group-1", name="Admissions", template_ids=["tpl-a", "tpl-b"])
    updated_group = _group_record(group_id="group-1", name="Updated Admissions", template_ids=["tpl-a", "tpl-b"])
    mocker.patch.object(app_main, "get_group", return_value=existing_group)
    mocker.patch.object(
        app_main,
        "list_templates",
        return_value=[
            _template_record(template_id="tpl-a", name="Alpha Packet"),
            _template_record(template_id="tpl-b", name="Bravo Intake"),
        ],
    )
    mocker.patch.object(app_main, "list_groups", return_value=[existing_group])
    mocker.patch.object(app_main, "update_group", return_value=updated_group)
    mocker.patch.object(app_main, "get_fill_link_for_group", return_value=_fill_link_record(group_name="Admissions", title="Admissions"))
    close_fill_link_mock = mocker.patch.object(app_main, "close_fill_link", return_value=None)
    update_fill_link_mock = mocker.patch.object(app_main, "update_fill_link", return_value=_fill_link_record(group_name="Updated Admissions", title="Updated Admissions"))

    response = client.patch(
        "/api/groups/group-1",
        json={"name": "Updated Admissions", "templateIds": ["tpl-a", "tpl-b"]},
        headers=auth_headers,
    )

    assert response.status_code == 200
    close_fill_link_mock.assert_not_called()
    update_fill_link_mock.assert_called_once_with(
        "link-1",
        base_user.app_user_id,
        group_name="Updated Admissions",
        title="Updated Admissions",
    )


def test_delete_group_returns_success(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "get_group", return_value=_group_record(group_id="group-1", name="Admissions", template_ids=["tpl-a"]))
    call_order: list[str] = []

    def _close_links(*args, **kwargs):
        call_order.append("close")
        return 1

    def _delete_group(*args, **kwargs):
        call_order.append("delete")
        return True

    delete_group_mock = mocker.patch.object(app_main, "delete_group", side_effect=_delete_group)
    close_links_mock = mocker.patch.object(app_main, "close_fill_links_for_group", side_effect=_close_links)

    response = client.delete("/api/groups/group-1", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {"success": True}
    assert call_order == ["close", "delete"]
    delete_group_mock.assert_called_once_with("group-1", base_user.app_user_id)
    close_links_mock.assert_called_once_with("group-1", base_user.app_user_id, closed_reason="group_deleted")


def test_delete_group_returns_404_when_missing(
    client,
    app_main,
    base_user,
    mocker,
    auth_headers,
) -> None:
    _patch_auth(mocker, app_main, base_user)
    mocker.patch.object(app_main, "get_group", return_value=None)

    response = client.delete("/api/groups/missing", headers=auth_headers)

    assert response.status_code == 404
    assert "Group not found" in response.text
