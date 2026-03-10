"""Shared saved-form cleanup helpers used by routes and retention jobs."""

from __future__ import annotations

from backend.firebaseDB.fill_link_database import (
    close_fill_links_for_template,
    close_group_fill_links_for_template,
    delete_fill_links_for_template,
    delete_group_fill_links_for_template,
)
from backend.firebaseDB.group_database import remove_template_from_all_groups
from backend.firebaseDB.storage_service import delete_pdf, is_gcs_path
from backend.firebaseDB.template_database import delete_template, get_template
from backend.services.saved_form_snapshot_service import get_saved_form_editor_snapshot_path


def _is_storage_not_found_error(exc: Exception) -> bool:
    if isinstance(exc, FileNotFoundError):
        return True
    status_code = getattr(exc, "status_code", None)
    if status_code is None:
        status_code = getattr(exc, "code", None)
    if status_code == 404:
        return True
    return exc.__class__.__name__.lower() == "notfound"


def delete_saved_form_assets(
    form_id: str,
    user_id: str,
    *,
    hard_delete_link_records: bool = False,
) -> bool:
    """Delete a saved form, its storage objects, and dependent group/link metadata."""
    template = get_template(form_id, user_id)
    if not template:
        return False

    deletion_targets: list[str] = []
    if template.pdf_bucket_path and is_gcs_path(template.pdf_bucket_path):
        deletion_targets.append(template.pdf_bucket_path)
    if template.template_bucket_path and template.template_bucket_path != template.pdf_bucket_path:
        if is_gcs_path(template.template_bucket_path):
            deletion_targets.append(template.template_bucket_path)
    snapshot_path = get_saved_form_editor_snapshot_path(
        template.metadata if isinstance(template.metadata, dict) else None,
    )
    if snapshot_path and is_gcs_path(snapshot_path):
        deletion_targets.append(snapshot_path)

    for bucket_path in deletion_targets:
        try:
            delete_pdf(bucket_path)
        except Exception as exc:
            if _is_storage_not_found_error(exc):
                continue
            raise

    if hard_delete_link_records:
        delete_fill_links_for_template(form_id, user_id)
        delete_group_fill_links_for_template(form_id, user_id)
    else:
        close_fill_links_for_template(form_id, user_id, closed_reason="template_deleted")
        close_group_fill_links_for_template(form_id, user_id, closed_reason="template_deleted")

    removed = delete_template(form_id, user_id)
    if not removed:
        return False

    remove_template_from_all_groups(form_id, user_id)
    return True
