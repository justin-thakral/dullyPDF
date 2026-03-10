from backend.firebaseDB.firebase_service import RequestUser
import backend.services.detection_service as detection_service


def _user(role: str = "base") -> RequestUser:
    return RequestUser(
        uid="uid-1",
        app_user_id="user-1",
        email="user@example.com",
        display_name="User One",
        role=role,
    )


def test_enqueue_local_detection_job_records_queued_state_and_submits_worker(mocker) -> None:
    mocker.patch.object(detection_service.uuid, "uuid4", return_value=type("_U", (), {"__str__": lambda self: "sess-local"})())
    store_mock = mocker.patch.object(detection_service, "_store_session_entry", return_value=None)
    record_mock = mocker.patch.object(detection_service, "record_detection_request", return_value=None)
    submit_mock = mocker.patch.object(detection_service._LOCAL_DETECTION_EXECUTOR, "submit", return_value=None)

    response = detection_service.enqueue_local_detection_job(
        b"%PDF-1.4\n",
        "sample.pdf",
        _user(),
        page_count=3,
        prewarm_rename=True,
        prewarm_remap=False,
    )

    assert response == {
        "sessionId": "sess-local",
        "status": detection_service.DETECTION_STATUS_QUEUED,
        "pipeline": "commonforms",
    }
    store_mock.assert_called_once()
    stored_entry = store_mock.call_args.args[1]
    assert stored_entry["detection_status"] == detection_service.DETECTION_STATUS_QUEUED
    assert stored_entry["detection_queue"] == "local"
    assert stored_entry["openai_prewarm_rename"] is True
    record_mock.assert_called_once_with(
        request_id="sess-local",
        session_id="sess-local",
        user_id="user-1",
        status=detection_service.DETECTION_STATUS_QUEUED,
        page_count=3,
    )
    submit_mock.assert_called_once()
    assert submit_mock.call_args.args[0] is detection_service._run_local_detection_job


def test_run_local_detection_job_marks_session_complete(mocker) -> None:
    update_session_mock = mocker.patch.object(detection_service, "_update_session_entry", return_value=None)
    update_request_mock = mocker.patch.object(detection_service, "update_detection_request", return_value=None)
    mocker.patch.object(
        detection_service,
        "run_local_detection",
        return_value={"pipeline": "commonforms", "fields": [{"name": "field_1"}]},
    )

    detection_service._run_local_detection_job(
        "sess-local",
        pdf_bytes=b"%PDF-1.4\n",
        source_pdf="sample.pdf",
        user_id="user-1",
        page_count=2,
        prewarm_rename=False,
        prewarm_remap=False,
    )

    assert update_session_mock.call_args_list[0].args[1]["detection_status"] == detection_service.DETECTION_STATUS_RUNNING
    assert update_session_mock.call_args_list[-1].args[1]["detection_status"] == detection_service.DETECTION_STATUS_COMPLETE
    assert update_session_mock.call_args_list[-1].kwargs["persist_fields"] is True
    assert update_session_mock.call_args_list[-1].kwargs["persist_result"] is True
    assert update_request_mock.call_args_list[0].kwargs["status"] == detection_service.DETECTION_STATUS_RUNNING
    assert update_request_mock.call_args_list[-1].kwargs["status"] == detection_service.DETECTION_STATUS_COMPLETE


def test_run_local_detection_job_marks_session_failed(mocker) -> None:
    update_session_mock = mocker.patch.object(detection_service, "_update_session_entry", return_value=None)
    update_request_mock = mocker.patch.object(detection_service, "update_detection_request", return_value=None)
    mocker.patch.object(
        detection_service,
        "run_local_detection",
        side_effect=RuntimeError("commonforms crashed"),
    )

    detection_service._run_local_detection_job(
        "sess-local",
        pdf_bytes=b"%PDF-1.4\n",
        source_pdf="sample.pdf",
        user_id="user-1",
        page_count=2,
        prewarm_rename=False,
        prewarm_remap=False,
    )

    assert update_session_mock.call_args_list[0].args[1]["detection_status"] == detection_service.DETECTION_STATUS_RUNNING
    assert update_session_mock.call_args_list[-1].args[1]["detection_status"] == detection_service.DETECTION_STATUS_FAILED
    assert "commonforms crashed" in update_session_mock.call_args_list[-1].args[1]["detection_error"]
    assert update_request_mock.call_args_list[-1].kwargs["status"] == detection_service.DETECTION_STATUS_FAILED
    assert "commonforms crashed" in update_request_mock.call_args_list[-1].kwargs["error"]
