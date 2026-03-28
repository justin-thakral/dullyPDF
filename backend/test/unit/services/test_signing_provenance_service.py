from types import SimpleNamespace

from backend.services import signing_provenance_service


def test_record_signing_provenance_event_swallows_storage_failures(mocker) -> None:
    record = SimpleNamespace(id="sign-1", source_link_id="link-1")
    mocker.patch.object(signing_provenance_service, "serialize_signing_sender_provenance", return_value={})
    record_event_mock = mocker.patch.object(
        signing_provenance_service,
        "record_signing_event",
        side_effect=RuntimeError("firestore unavailable"),
    )
    logger_mock = mocker.patch.object(signing_provenance_service, "logger")

    result = signing_provenance_service.record_signing_provenance_event(
        record,
        event_type="request_sent",
        include_link_token=False,
    )

    assert result is None
    record_event_mock.assert_called_once()
    logger_mock.warning.assert_called_once()


def test_record_signing_provenance_event_dispatches_webhook_after_storage_write(mocker) -> None:
    record = SimpleNamespace(id="sign-1", source_link_id="link-1")
    mocker.patch.object(signing_provenance_service, "serialize_signing_sender_provenance", return_value={})
    record_event_mock = mocker.patch.object(signing_provenance_service, "record_signing_event", return_value={"id": "event-1"})
    webhook_mock = mocker.patch.object(signing_provenance_service, "dispatch_signing_webhook_event")

    result = signing_provenance_service.record_signing_provenance_event(
        record,
        event_type="request_sent",
        include_link_token=False,
        extra={"statusAfter": "sent"},
    )

    assert result == {"id": "event-1"}
    record_event_mock.assert_called_once()
    webhook_mock.assert_called_once()
    assert webhook_mock.call_args.kwargs["event_type"] == "request_sent"
    assert webhook_mock.call_args.kwargs["details"]["statusAfter"] == "sent"
