"""Blueprint for unit tests of user/template operations in `backend/firebaseDB/app_database.py`.

Required coverage:
- `normalize_role`
- `ensure_user` upsert behavior
- `list_templates`, `get_template`
- `create_template`, `update_template`, `delete_template`

Edge cases:
- ownership mismatch handling
- missing defaults backfilled on existing user docs
- sort ordering by created_at desc

Important context:
- Template ownership and user metadata are core to saved-forms access control.
"""
