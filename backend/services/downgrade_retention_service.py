"""Downgrade retention planning, summarization, and purge helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional

from backend.firebaseDB.fill_link_database import close_fill_link, delete_fill_link, list_fill_links, update_fill_link
from backend.firebaseDB.firebase_service import get_firestore_client
from backend.firebaseDB.firestore_query_utils import where_equals
from backend.firebaseDB.group_database import list_groups
from backend.firebaseDB.template_database import list_templates
from backend.firebaseDB.user_database import (
    DOWNGRADE_RETENTION_FIELD,
    ROLE_BASE,
    UserDowngradeRetentionRecord,
    clear_user_downgrade_retention,
    get_user_billing_record,
    get_user_downgrade_retention,
    get_user_profile,
    normalize_role,
    set_user_downgrade_retention,
)
from backend.services.billing_service import is_subscription_active
from backend.services.limits_service import resolve_fill_links_active_limit, resolve_saved_forms_limit
from backend.services.template_cleanup_service import delete_saved_form_assets
from backend.time_utils import now_iso

DOWNGRADE_RETENTION_POLICY_VERSION = 1
DOWNGRADE_RETENTION_STATUS = "grace_period"
DOWNGRADE_RETENTION_GRACE_DAYS = max(1, int(os.getenv("SANDBOX_DOWNGRADE_RETENTION_GRACE_DAYS", "30")))
_HIGH_TIMESTAMP = "9999-12-31T23:59:59+00:00"


@dataclass(frozen=True)
class DowngradeRetentionComputation:
    state: Optional[UserDowngradeRetentionRecord]
    templates: list
    groups: list
    links: list
    pending_link_reasons: Dict[str, str]
    active_limit_close_link_ids: List[str]


@dataclass(frozen=True)
class DowngradeRetentionEligibility:
    should_apply: bool
    role: str
    has_active_subscription: bool


@dataclass(frozen=True)
class _RetentionLinkMutation:
    link_id: str
    user_id: str
    desired_status: str
    desired_closed_reason: Optional[str]
    original_status: str
    original_closed_reason: Optional[str]


class DowngradeRetentionInactiveError(RuntimeError):
    """Raised when a client tries to mutate a retention plan that no longer applies."""


def _sort_oldest_first(records: Iterable[object]) -> List[object]:
    return sorted(
        list(records),
        key=lambda record: (
            getattr(record, "created_at", None) or _HIGH_TIMESTAMP,
            getattr(record, "id", ""),
        ),
    )


def _dedupe_ids(values: Iterable[str]) -> List[str]:
    deduped: List[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in deduped:
            continue
        deduped.append(normalized)
    return deduped


def _resolve_retention_deadline(existing: Optional[UserDowngradeRetentionRecord]) -> tuple[str, str]:
    if existing and existing.downgraded_at and existing.grace_ends_at:
        return existing.downgraded_at, existing.grace_ends_at
    downgraded_at = now_iso()
    grace_ends_at = (datetime.now(timezone.utc) + timedelta(days=DOWNGRADE_RETENTION_GRACE_DAYS)).isoformat()
    return downgraded_at, grace_ends_at


def _parse_iso_timestamp(value: Optional[str]) -> Optional[datetime]:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _resolve_days_remaining(grace_ends_at: Optional[str]) -> int:
    deadline = _parse_iso_timestamp(grace_ends_at)
    if deadline is None:
        return 0
    remaining_seconds = (deadline - datetime.now(timezone.utc)).total_seconds()
    if remaining_seconds <= 0:
        return 0
    return max(1, int((remaining_seconds + 86399) // 86400))


def _resolve_kept_template_ids(
    ordered_template_ids: List[str],
    keep_limit: int,
    preferred_keep_ids: Optional[Iterable[str]],
) -> List[str]:
    if keep_limit <= 0:
        return []
    preferred = _dedupe_ids(preferred_keep_ids or [])
    current_id_set = set(ordered_template_ids)
    retained = [template_id for template_id in preferred if template_id in current_id_set]
    for template_id in ordered_template_ids:
        if len(retained) >= keep_limit:
            break
        if template_id in retained:
            continue
        retained.append(template_id)
    return retained[:keep_limit]


def _link_depends_on_pending_template(record, pending_template_ids: set[str]) -> bool:
    if not pending_template_ids:
        return False
    if record.scope_type == "template":
        return bool(record.template_id and record.template_id in pending_template_ids)
    return any(template_id in pending_template_ids for template_id in record.template_ids)


def _is_downgrade_managed_link(record) -> bool:
    return str(getattr(record, "closed_reason", "") or "").strip().lower() in {
        "downgrade_retention",
        "downgrade_link_limit",
    }


def _resolve_link_plan(
    ordered_links: List[object],
    pending_template_ids: set[str],
    active_limit: int,
) -> tuple[List[str], List[str], Dict[str, str]]:
    pending_link_ids: List[str] = []
    active_limit_close_link_ids: List[str] = []
    reasons: Dict[str, str] = {}
    active_candidates: List[object] = []
    for record in ordered_links:
        if _link_depends_on_pending_template(record, pending_template_ids):
            pending_link_ids.append(record.id)
            reasons[record.id] = "template_pending_delete"
            continue
        if record.status == "active" or _is_downgrade_managed_link(record):
            active_candidates.append(record)
    for record in active_candidates[active_limit:]:
        active_limit_close_link_ids.append(record.id)
    return _dedupe_ids(pending_link_ids), _dedupe_ids(active_limit_close_link_ids), reasons


def _resolve_current_base_retention_limits() -> tuple[int, int]:
    return (
        max(1, resolve_saved_forms_limit(ROLE_BASE)),
        max(1, resolve_fill_links_active_limit(ROLE_BASE)),
    )


def _has_confirmed_active_subscription(
    *,
    subscription_id: object,
    subscription_status: object,
) -> bool:
    normalized_subscription_id = str(subscription_id or "").strip()
    if not normalized_subscription_id:
        return False
    return is_subscription_active(str(subscription_status or ""))


def _compute_retention(
    user_id: str,
    *,
    existing: Optional[UserDowngradeRetentionRecord],
    override_keep_ids: Optional[Iterable[str]] = None,
    billing_state_deferred: bool = False,
) -> DowngradeRetentionComputation:
    ordered_templates = _sort_oldest_first(list_templates(user_id))
    ordered_groups = list_groups(user_id)
    ordered_links = _sort_oldest_first(list_fill_links(user_id))

    saved_forms_limit, active_links_limit = _resolve_current_base_retention_limits()

    ordered_template_ids = [template.id for template in ordered_templates]
    keep_limit = min(saved_forms_limit, len(ordered_template_ids))
    preferred_keep_ids = override_keep_ids if override_keep_ids is not None else (existing.kept_template_ids if existing else [])
    kept_template_ids = _resolve_kept_template_ids(ordered_template_ids, keep_limit, preferred_keep_ids)
    pending_delete_template_ids = [
        template_id
        for template_id in ordered_template_ids
        if template_id not in set(kept_template_ids)
    ]
    pending_link_ids, active_limit_close_link_ids, pending_link_reasons = _resolve_link_plan(
        ordered_links,
        set(pending_delete_template_ids),
        max(1, active_links_limit),
    )

    if not pending_delete_template_ids and not pending_link_ids:
        return DowngradeRetentionComputation(
            state=None,
            templates=ordered_templates,
            groups=ordered_groups,
            links=ordered_links,
            pending_link_reasons=pending_link_reasons,
            active_limit_close_link_ids=active_limit_close_link_ids,
        )

    downgraded_at, grace_ends_at = _resolve_retention_deadline(existing)
    state = UserDowngradeRetentionRecord(
        status=DOWNGRADE_RETENTION_STATUS,
        policy_version=DOWNGRADE_RETENTION_POLICY_VERSION,
        downgraded_at=downgraded_at,
        grace_ends_at=grace_ends_at,
        saved_forms_limit=max(1, saved_forms_limit),
        fill_links_active_limit=max(1, active_links_limit),
        kept_template_ids=kept_template_ids,
        pending_delete_template_ids=pending_delete_template_ids,
        pending_delete_link_ids=pending_link_ids,
        billing_state_deferred=bool(billing_state_deferred),
        updated_at=existing.updated_at if existing else None,
    )
    return DowngradeRetentionComputation(
        state=state,
        templates=ordered_templates,
        groups=ordered_groups,
        links=ordered_links,
        pending_link_reasons=pending_link_reasons,
        active_limit_close_link_ids=active_limit_close_link_ids,
    )


def _resolve_retention_eligibility(user_id: str) -> DowngradeRetentionEligibility:
    """Re-check current entitlement before applying retention side effects."""
    profile = get_user_profile(user_id)
    role = normalize_role(profile.role if profile else None)
    billing_record = get_user_billing_record(user_id)
    has_active_subscription = bool(
        billing_record
        and _has_confirmed_active_subscription(
            subscription_id=billing_record.subscription_id,
            subscription_status=billing_record.subscription_status,
        )
    )
    return DowngradeRetentionEligibility(
        should_apply=role == ROLE_BASE and not has_active_subscription,
        role=role,
        has_active_subscription=has_active_subscription,
    )


def _persist_retention_state(user_id: str, state: Optional[UserDowngradeRetentionRecord]) -> None:
    if state is None:
        clear_user_downgrade_retention(user_id)
        return
    set_user_downgrade_retention(
        user_id,
        status=state.status,
        policy_version=state.policy_version,
        downgraded_at=state.downgraded_at,
        grace_ends_at=state.grace_ends_at,
        saved_forms_limit=state.saved_forms_limit,
        fill_links_active_limit=state.fill_links_active_limit,
        kept_template_ids=state.kept_template_ids,
        pending_delete_template_ids=state.pending_delete_template_ids,
        pending_delete_link_ids=state.pending_delete_link_ids,
        billing_state_deferred=state.billing_state_deferred,
    )


def _should_preserve_retention_during_deferred_billing_sync(
    existing_state: Optional[UserDowngradeRetentionRecord],
    *,
    role: str,
    has_active_subscription: bool,
) -> bool:
    return bool(
        existing_state
        and existing_state.billing_state_deferred
        and role == ROLE_BASE
        and has_active_subscription
    )


def _retention_is_blocked_by_current_account_state(
    user_id: str,
    *,
    user_doc_data: Optional[Dict[str, object]] = None,
    eligibility_override: Optional[DowngradeRetentionEligibility] = None,
    existing_state: Optional[UserDowngradeRetentionRecord] = None,
) -> bool:
    if eligibility_override is not None:
        return not eligibility_override.should_apply
    if isinstance(user_doc_data, dict):
        role = normalize_role(user_doc_data.get("role"))
        has_active_subscription = _has_confirmed_active_subscription(
            subscription_id=user_doc_data.get("stripe_subscription_id"),
            subscription_status=user_doc_data.get("stripe_subscription_status"),
        )
        if _should_preserve_retention_during_deferred_billing_sync(
            existing_state,
            role=role,
            has_active_subscription=has_active_subscription,
        ):
            # Preserve a grace plan only when it was explicitly marked as waiting
            # for a deferred billing-state write after cancellation.
            return False
        return role != ROLE_BASE or has_active_subscription

    eligibility = _resolve_retention_eligibility(user_id)
    if _should_preserve_retention_during_deferred_billing_sync(
        existing_state,
        role=eligibility.role,
        has_active_subscription=eligibility.has_active_subscription,
    ):
        return False
    return not eligibility.should_apply


def _resolve_next_billing_state_deferred(
    user_id: str,
    *,
    existing: Optional[UserDowngradeRetentionRecord],
    explicit_value: Optional[bool] = None,
) -> bool:
    if explicit_value is not None:
        return bool(explicit_value)
    if not existing or not existing.billing_state_deferred:
        return False
    eligibility = _resolve_retention_eligibility(user_id)
    return bool(eligibility.role == ROLE_BASE and eligibility.has_active_subscription)


def _coerce_positive_int(value: object, *, default: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _retention_state_from_user_doc_data(user_doc_data: Optional[Dict[str, object]]) -> Optional[UserDowngradeRetentionRecord]:
    if not isinstance(user_doc_data, dict):
        return None
    raw = user_doc_data.get(DOWNGRADE_RETENTION_FIELD)
    if not isinstance(raw, dict):
        return None
    status = str(raw.get("status") or "").strip().lower()
    if not status:
        return None
    return UserDowngradeRetentionRecord(
        status=status,
        policy_version=_coerce_positive_int(raw.get("policy_version"), default=1),
        downgraded_at=str(raw.get("downgraded_at") or "").strip() or None,
        grace_ends_at=str(raw.get("grace_ends_at") or "").strip() or None,
        saved_forms_limit=_coerce_positive_int(raw.get("saved_forms_limit"), default=1),
        fill_links_active_limit=_coerce_positive_int(raw.get("fill_links_active_limit"), default=1),
        kept_template_ids=_dedupe_ids(raw.get("kept_template_ids") or []),
        pending_delete_template_ids=_dedupe_ids(raw.get("pending_delete_template_ids") or []),
        pending_delete_link_ids=_dedupe_ids(raw.get("pending_delete_link_ids") or []),
        billing_state_deferred=bool(raw.get("billing_state_deferred")),
        updated_at=str(raw.get("updated_at") or "").strip() or None,
    )


def _plan_retention_link_mutations(computation: DowngradeRetentionComputation) -> List[_RetentionLinkMutation]:
    pending_link_ids = set(computation.state.pending_delete_link_ids if computation.state else [])
    active_limit_close_link_ids = set(computation.active_limit_close_link_ids)
    mutations: List[_RetentionLinkMutation] = []
    for record in computation.links:
        if record.id in pending_link_ids:
            desired_reason = "downgrade_retention"
            if record.status != "closed" or getattr(record, "closed_reason", None) != desired_reason:
                mutations.append(
                    _RetentionLinkMutation(
                        link_id=record.id,
                        user_id=record.user_id,
                        desired_status="closed",
                        desired_closed_reason=desired_reason,
                        original_status=record.status,
                        original_closed_reason=getattr(record, "closed_reason", None),
                    )
                )
            continue
        if record.id in active_limit_close_link_ids:
            desired_reason = "downgrade_link_limit"
            if record.status != "closed" or getattr(record, "closed_reason", None) != desired_reason:
                mutations.append(
                    _RetentionLinkMutation(
                        link_id=record.id,
                        user_id=record.user_id,
                        desired_status="closed",
                        desired_closed_reason=desired_reason,
                        original_status=record.status,
                        original_closed_reason=getattr(record, "closed_reason", None),
                    )
                )
            continue
        if record.status != "active" and _is_downgrade_managed_link(record):
            mutations.append(
                _RetentionLinkMutation(
                    link_id=record.id,
                    user_id=record.user_id,
                    desired_status="active",
                    desired_closed_reason=None,
                    original_status=record.status,
                    original_closed_reason=getattr(record, "closed_reason", None),
                )
            )
    return mutations


def _apply_link_mutation(mutation: _RetentionLinkMutation) -> None:
    if mutation.desired_status == "closed":
        close_fill_link(
            mutation.link_id,
            mutation.user_id,
            closed_reason=mutation.desired_closed_reason or "owner_closed",
        )
        return
    update_fill_link(
        mutation.link_id,
        mutation.user_id,
        status=mutation.desired_status,
        closed_reason=mutation.desired_closed_reason,
    )


def _rollback_retention_link_mutations(applied_mutations: List[_RetentionLinkMutation]) -> None:
    for mutation in reversed(applied_mutations):
        update_fill_link(
            mutation.link_id,
            mutation.user_id,
            status=mutation.original_status,
            closed_reason=mutation.original_closed_reason,
        )


def _commit_retention_state(user_id: str, computation: DowngradeRetentionComputation) -> None:
    applied_mutations: List[_RetentionLinkMutation] = []
    try:
        for mutation in _plan_retention_link_mutations(computation):
            _apply_link_mutation(mutation)
            applied_mutations.append(mutation)
        _persist_retention_state(user_id, computation.state)
    except Exception:
        if applied_mutations:
            try:
                _rollback_retention_link_mutations(applied_mutations)
            except Exception:
                pass
        raise


def _serialize_summary(computation: DowngradeRetentionComputation) -> Optional[Dict[str, object]]:
    state = computation.state
    if state is None:
        return None
    pending_template_id_set = set(state.pending_delete_template_ids)
    pending_link_id_set = set(state.pending_delete_link_ids)
    active_limit_close_link_id_set = set(computation.active_limit_close_link_ids)
    effective_closed_link_ids = {
        record.id
        for record in computation.links
        if record.status == "active"
        and (record.id in pending_link_id_set or record.id in active_limit_close_link_id_set)
    }
    template_lookup = {template.id: template for template in computation.templates}
    templates_payload: List[Dict[str, object]] = []
    for template in computation.templates:
        templates_payload.append(
            {
                "id": template.id,
                "name": template.name or template.pdf_bucket_path or "Saved form",
                "createdAt": template.created_at,
                "updatedAt": template.updated_at,
                "status": "pending_delete" if template.id in pending_template_id_set else "kept",
            }
        )

    groups_payload: List[Dict[str, object]] = []
    for group in computation.groups:
        pending_group_templates = [template_id for template_id in group.template_ids if template_id in pending_template_id_set]
        if not pending_group_templates:
            continue
        groups_payload.append(
            {
                "id": group.id,
                "name": group.name,
                "templateCount": len(group.template_ids),
                "pendingTemplateCount": len(pending_group_templates),
                "willDelete": len(pending_group_templates) == len(group.template_ids),
            }
        )

    links_payload: List[Dict[str, object]] = []
    for link in computation.links:
        if link.id not in pending_link_id_set:
            continue
        template_name = template_lookup.get(link.template_id).name if link.template_id and template_lookup.get(link.template_id) else link.template_name
        links_payload.append(
            {
                "id": link.id,
                "title": link.title or link.group_name or link.template_name or "Fill By Link",
                "scopeType": link.scope_type,
                "status": "closed" if link.id in effective_closed_link_ids else link.status,
                "templateId": link.template_id,
                "templateName": template_name,
                "groupId": link.group_id,
                "groupName": link.group_name,
                "createdAt": link.created_at,
                "updatedAt": link.updated_at,
                "pendingDeleteReason": computation.pending_link_reasons.get(link.id) or "template_pending_delete",
            }
        )

    return {
        "status": state.status,
        "policyVersion": state.policy_version,
        "downgradedAt": state.downgraded_at,
        "graceEndsAt": state.grace_ends_at,
        "daysRemaining": _resolve_days_remaining(state.grace_ends_at),
        "savedFormsLimit": state.saved_forms_limit,
        "fillLinksActiveLimit": state.fill_links_active_limit,
        "keptTemplateIds": state.kept_template_ids,
        "pendingDeleteTemplateIds": state.pending_delete_template_ids,
        "pendingDeleteLinkIds": state.pending_delete_link_ids,
        "counts": {
            "keptTemplates": len(state.kept_template_ids),
            "pendingTemplates": len(state.pending_delete_template_ids),
            "affectedGroups": len(groups_payload),
            "pendingLinks": len(state.pending_delete_link_ids),
            "closedLinks": len(computation.active_limit_close_link_ids),
        },
        "templates": templates_payload,
        "groups": groups_payload,
        "links": links_payload,
    }


def apply_user_downgrade_retention(
    user_id: str,
    *,
    eligibility_override: Optional[DowngradeRetentionEligibility] = None,
    billing_state_deferred: bool = False,
) -> Optional[Dict[str, object]]:
    existing = get_user_downgrade_retention(user_id)
    if _retention_is_blocked_by_current_account_state(
        user_id,
        eligibility_override=eligibility_override,
        existing_state=existing,
    ):
        if existing is not None:
            clear_user_downgrade_retention(user_id)
        return None
    computation = _compute_retention(
        user_id,
        existing=existing,
        billing_state_deferred=_resolve_next_billing_state_deferred(
            user_id,
            existing=existing,
            explicit_value=billing_state_deferred,
        ),
    )
    _commit_retention_state(user_id, computation)
    return _serialize_summary(computation)


def sync_user_downgrade_retention(
    user_id: str,
    *,
    create_if_missing: bool = False,
) -> Optional[Dict[str, object]]:
    existing = get_user_downgrade_retention(user_id)
    if _retention_is_blocked_by_current_account_state(user_id, existing_state=existing):
        if existing is not None:
            clear_user_downgrade_retention(user_id)
        return None
    if not existing and not create_if_missing:
        return None
    computation = _compute_retention(
        user_id,
        existing=existing,
        billing_state_deferred=_resolve_next_billing_state_deferred(user_id, existing=existing),
    )
    _commit_retention_state(user_id, computation)
    return _serialize_summary(computation)


def select_user_retained_templates(user_id: str, kept_template_ids: List[str]) -> Dict[str, object]:
    existing = get_user_downgrade_retention(user_id)
    if not existing:
        raise ValueError("No downgrade retention plan exists for this user.")
    if _retention_is_blocked_by_current_account_state(user_id, existing_state=existing):
        clear_user_downgrade_retention(user_id)
        raise DowngradeRetentionInactiveError(
            "Downgrade retention is no longer active for this account."
        )

    ordered_templates = _sort_oldest_first(list_templates(user_id))
    ordered_template_ids = [template.id for template in ordered_templates]
    requested_keep_ids = _dedupe_ids(kept_template_ids)
    current_saved_forms_limit, _ = _resolve_current_base_retention_limits()
    expected_keep_count = min(current_saved_forms_limit, len(ordered_template_ids))
    if len(requested_keep_ids) != expected_keep_count:
        raise ValueError(f"Select exactly {expected_keep_count} saved forms to keep.")
    if any(template_id not in ordered_template_ids for template_id in requested_keep_ids):
        raise ValueError("One or more selected saved forms no longer exist.")

    computation = _compute_retention(
        user_id,
        existing=existing,
        override_keep_ids=requested_keep_ids,
        billing_state_deferred=_resolve_next_billing_state_deferred(user_id, existing=existing),
    )
    if computation.state is None:
        clear_user_downgrade_retention(user_id)
        return {}
    _commit_retention_state(user_id, computation)
    return _serialize_summary(computation) or {}


def delete_user_downgrade_retention_now(user_id: str) -> Dict[str, object]:
    existing = get_user_downgrade_retention(user_id)
    if _retention_is_blocked_by_current_account_state(user_id, existing_state=existing):
        if existing is not None:
            clear_user_downgrade_retention(user_id)
        return {
            "deletedTemplateIds": [],
            "deletedLinkIds": [],
        }

    computation = _compute_retention(user_id, existing=existing)
    state = computation.state
    if state is None:
        clear_user_downgrade_retention(user_id)
        return {
            "deletedTemplateIds": [],
            "deletedLinkIds": [],
        }

    deleted_template_ids: List[str] = []
    deleted_link_ids: List[str] = []
    deleted_template_id_set: set[str] = set()
    pending_link_lookup = {record.id: record for record in computation.links}
    for template_id in state.pending_delete_template_ids:
        if delete_saved_form_assets(template_id, user_id, hard_delete_link_records=True):
            deleted_template_ids.append(template_id)
            deleted_template_id_set.add(template_id)
    for link_id in state.pending_delete_link_ids:
        pending_link = pending_link_lookup.get(link_id)
        deleted_by_template_cascade = bool(
            pending_link
            and (
                (pending_link.template_id and pending_link.template_id in deleted_template_id_set)
                or any(template_id in deleted_template_id_set for template_id in pending_link.template_ids)
            )
        )
        if delete_fill_link(link_id, user_id) or deleted_by_template_cascade:
            deleted_link_ids.append(link_id)

    sync_user_downgrade_retention(user_id, create_if_missing=existing is None)
    return {
        "deletedTemplateIds": deleted_template_ids,
        "deletedLinkIds": _dedupe_ids(deleted_link_ids),
    }


def list_users_with_expired_downgrade_retention(*, as_of: Optional[datetime] = None) -> List[str]:
    now_dt = (as_of or datetime.now(timezone.utc)).astimezone(timezone.utc)
    client = get_firestore_client()
    snapshot = where_equals(
        client.collection("app_users"),
        f"{DOWNGRADE_RETENTION_FIELD}.status",
        DOWNGRADE_RETENTION_STATUS,
    ).get()
    expired_user_ids: List[str] = []
    for doc in snapshot:
        data = doc.to_dict() or {}
        retention = data.get(DOWNGRADE_RETENTION_FIELD)
        grace_ends_at = retention.get("grace_ends_at") if isinstance(retention, dict) else None
        deadline = _parse_iso_timestamp(grace_ends_at)
        if deadline is None or deadline > now_dt:
            continue
        existing = _retention_state_from_user_doc_data(data)
        if _retention_is_blocked_by_current_account_state(
            doc.id,
            user_doc_data=data,
            existing_state=existing,
        ):
            continue
        expired_user_ids.append(doc.id)
    return expired_user_ids
