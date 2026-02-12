"""CLI tool for managing Firebase user roles and rename quotas.
"""

import argparse

from firebase_admin import auth as firebase_auth

from .user_database import (
    RENAME_COUNT_FIELD,
    ROLE_BASE,
    ROLE_FIELD,
    ROLE_GOD,
    USERS_COLLECTION,
    normalize_role,
)
from ..time_utils import now_iso
from .firebase_service import get_firestore_client, init_firebase


def main() -> None:
    """Parse CLI args and update Firebase custom claims and Firestore fields.
    """
    parser = argparse.ArgumentParser(description="Set Firebase custom role claims for DullyPDF users")
    parser.add_argument("--email", help="User email (preferred)")
    parser.add_argument("--uid", help="User UID (alternative to email)")
    parser.add_argument("--role", choices=[ROLE_BASE, ROLE_GOD], default=ROLE_BASE)
    parser.add_argument(
        "--reset-rename-count",
        action="store_true",
        help="Reset rename quota counter to 0",
    )
    args = parser.parse_args()

    if not args.email and not args.uid:
        raise SystemExit("Provide --email or --uid")

    init_firebase()

    if args.uid:
        user = firebase_auth.get_user(args.uid)
    else:
        user = firebase_auth.get_user_by_email(args.email)

    role = normalize_role(args.role)
    claims = user.custom_claims or {}
    claims[ROLE_FIELD] = role
    firebase_auth.set_custom_user_claims(user.uid, claims)

    client = get_firestore_client()
    updates = {
        ROLE_FIELD: role,
        "updated_at": now_iso(),
        "firebase_uid": user.uid,
        "email": user.email,
    }
    if args.reset_rename_count:
        updates[RENAME_COUNT_FIELD] = 0
    client.collection(USERS_COLLECTION).document(user.uid).set(updates, merge=True)

    print(f"Updated user {user.uid} ({user.email}) -> role={role}")


if __name__ == "__main__":
    main()
