def test_role_limit_helpers_base_and_god_branching(app_main, mocker) -> None:
    mocker.patch.object(app_main, "_int_env", return_value=99)
    assert app_main._resolve_detect_max_pages("god") == 99
    assert app_main._resolve_fillable_max_pages("god") == 99
    assert app_main._resolve_saved_forms_limit("god") == 99

    mocker.patch.object(app_main, "_int_env", return_value=5)
    assert app_main._resolve_detect_max_pages("base") == 5
    assert app_main._resolve_fillable_max_pages("base") == 5
    assert app_main._resolve_saved_forms_limit("base") == 5


def test_role_limit_helpers_clamp_to_minimum_one(app_main, mocker) -> None:
    mocker.patch.object(app_main, "_int_env", return_value=0)
    assert app_main._resolve_detect_max_pages("base") == 1
    assert app_main._resolve_fillable_max_pages("base") == 1
    assert app_main._resolve_saved_forms_limit("base") == 1

    mocker.patch.object(app_main, "_int_env", return_value=-10)
    assert app_main._resolve_detect_max_pages("god") == 1


def test_resolve_role_limits_aggregates_helpers(app_main, mocker) -> None:
    mocker.patch.object(app_main, "_resolve_detect_max_pages", return_value=7)
    mocker.patch.object(app_main, "_resolve_fillable_max_pages", return_value=55)
    mocker.patch.object(app_main, "_resolve_saved_forms_limit", return_value=4)
    assert app_main._resolve_role_limits("base") == {
        "detectMaxPages": 7,
        "fillableMaxPages": 55,
        "savedFormsMax": 4,
    }
