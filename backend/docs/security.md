# Security hardening guide (dev -> production)

This project is still in development, so the default setup favors speed over strict security. Before moving to production, make the changes below.

## 1) Admin endpoints: do not expose admin tokens to the client

Current behavior:
- The backend can accept an `ADMIN_TOKEN` (or `SANDBOX_DEBUG_PASSWORD` with `--debug`) to unlock admin endpoints.
- The frontend can optionally send an `x-admin-token` header in development.

Production hardening:
1) **Do not set `VITE_ADMIN_TOKEN` in production builds.** Vite inlines `VITE_*` values into the client bundle, which makes them public.
2) **Set `ADMIN_TOKEN` only on the backend server** (via environment or secret manager).
3) **Require admin token for DB endpoints** by setting:
   - `SANDBOX_DB_REQUIRE_ADMIN=true`
4) **Prefer server-side privilege checks** instead of client tokens. Two options:
   - Use Firebase custom claims (e.g., `admin=true`) and enforce in the backend before DB actions.
   - Create a backend-only service route that performs DB operations without exposing any token to the client.

## 2) Firebase token revocation enforcement

Current behavior:
- Tokens are verified without revocation checks.

Production hardening:
1) Update verification to enforce revocation:
   - Use `firebase_admin.auth.verify_id_token(token, check_revoked=True)`.
2) Handle revocation errors explicitly:
   - Expect `RevokedIdTokenError` and return `401` with a user-friendly message.
3) Plan for a small latency increase:
   - Revocation checks require additional calls to Firebase.

## 3) Debug flags

Debug-only behavior should never be enabled in production.

Checklist:
- Use `--debug` only for local development.
- Keep `SANDBOX_CORS_ORIGINS=*` disabled in production.
- Keep `SANDBOX_LOG_OPENAI_RESPONSE` disabled in production.

## 4) Environment + secrets hygiene

Checklist:
- Store credentials in a secret manager (not `.env` files) for production.
- Never commit `.env` files to git.
- Rotate admin tokens when moving to production.

## 5) Minimum production config

Set these on the backend server:
- `ADMIN_TOKEN=<secure random value>`
- `SANDBOX_DB_REQUIRE_ADMIN=true`
- `SANDBOX_CORS_ORIGINS=https://your-domain.com`

And keep these unset/false:
- `SANDBOX_LOG_OPENAI_RESPONSE`
- `SANDBOX_CORS_ORIGINS=*`
