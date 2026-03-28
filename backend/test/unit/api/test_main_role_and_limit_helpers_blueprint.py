def test_role_limit_helpers_base_and_god_branching(app_main, mocker) -> None:
    mocker.patch.object(app_main, "_int_env", return_value=99)
    assert app_main._resolve_detect_max_pages("god") == 99
    assert app_main._resolve_fillable_max_pages("god") == 99
    assert app_main._resolve_saved_forms_limit("god") == 99
    assert app_main._resolve_fill_links_active_limit("god") == 99
    assert app_main._resolve_fill_link_response_limit("god") == 99
    assert app_main._resolve_template_api_active_limit("god") == 99
    assert app_main._resolve_template_api_requests_monthly_limit("god") == 99
    assert app_main._resolve_template_api_max_pages("god") == 99
    assert app_main._resolve_signing_requests_per_document_limit("god") == 99

    mocker.patch.object(app_main, "_int_env", return_value=5)
    assert app_main._resolve_detect_max_pages("base") == 5
    assert app_main._resolve_fillable_max_pages("base") == 5
    assert app_main._resolve_saved_forms_limit("base") == 5
    assert app_main._resolve_fill_links_active_limit("base") == 5
    assert app_main._resolve_fill_link_response_limit("base") == 5
    assert app_main._resolve_template_api_active_limit("base") == 5
    assert app_main._resolve_template_api_requests_monthly_limit("base") == 5
    assert app_main._resolve_template_api_max_pages("base") == 5
    assert app_main._resolve_signing_requests_per_document_limit("base") == 5


def test_role_limit_helpers_clamp_to_minimum_one(app_main, mocker) -> None:
    mocker.patch.object(app_main, "_int_env", return_value=0)
    assert app_main._resolve_detect_max_pages("base") == 1
    assert app_main._resolve_fillable_max_pages("base") == 1
    assert app_main._resolve_saved_forms_limit("base") == 1
    assert app_main._resolve_fill_links_active_limit("base") == 1
    assert app_main._resolve_fill_link_response_limit("base") == 1
    assert app_main._resolve_template_api_active_limit("base") == 0
    assert app_main._resolve_template_api_requests_monthly_limit("base") == 0
    assert app_main._resolve_template_api_max_pages("base") == 1
    assert app_main._resolve_signing_requests_per_document_limit("base") == 1

    mocker.patch.object(app_main, "_int_env", return_value=-10)
    assert app_main._resolve_detect_max_pages("god") == 1
    assert app_main._resolve_signing_requests_per_document_limit("god") == 1


def test_resolve_role_limits_aggregates_helpers(app_main, mocker) -> None:
    mocker.patch.object(app_main, "_resolve_detect_max_pages", return_value=7)
    mocker.patch.object(app_main, "_resolve_fillable_max_pages", return_value=55)
    mocker.patch.object(app_main, "_resolve_saved_forms_limit", return_value=4)
    mocker.patch.object(app_main, "_resolve_fill_links_active_limit", return_value=1)
    mocker.patch.object(app_main, "_resolve_fill_link_response_limit", return_value=5)
    mocker.patch.object(app_main, "_resolve_template_api_active_limit", return_value=2)
    mocker.patch.object(app_main, "_resolve_template_api_requests_monthly_limit", return_value=250)
    mocker.patch.object(app_main, "_resolve_template_api_max_pages", return_value=25)
    mocker.patch.object(app_main, "_resolve_signing_requests_per_document_limit", return_value=10)
    assert app_main._resolve_role_limits("base") == {
        "detectMaxPages": 7,
        "fillableMaxPages": 55,
        "savedFormsMax": 4,
        "fillLinksActiveMax": 1,
        "fillLinkResponsesMax": 5,
        "templateApiActiveMax": 2,
        "templateApiRequestsMonthlyMax": 250,
        "templateApiMaxPages": 25,
        "signingRequestsPerDocumentMax": 10,
    }


def test_signing_request_document_limit_defaults_for_free_and_pro(app_main, monkeypatch) -> None:
    monkeypatch.delenv("SANDBOX_SIGNING_REQUESTS_PER_DOCUMENT_MAX_BASE", raising=False)
    monkeypatch.delenv("SANDBOX_SIGNING_REQUESTS_PER_DOCUMENT_MAX_PRO", raising=False)
    monkeypatch.delenv("SANDBOX_SIGNING_REQUESTS_PER_DOCUMENT_MAX_GOD", raising=False)

    assert app_main._resolve_signing_requests_per_document_limit("base") == 10
    assert app_main._resolve_signing_requests_per_document_limit("pro") == 1000
    assert app_main._resolve_signing_requests_per_document_limit("god") == 100000
