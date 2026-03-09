# Frontend Public Env Files

This directory contains committed frontend environment files for each mode:

- `frontend.dev.env`
- `frontend.stack.env`
- `frontend.prod.env`

These files may contain public browser config (`VITE_*`) such as Firebase web config and API base URLs.
Do not store backend secrets here.
Google Ads / analytics browser tag IDs are acceptable here because they are public client-side identifiers.

## Local overrides (gitignored)

Use local override files in `env/` for machine-specific values:

- `env/frontend.dev.local.env`
- `env/frontend.stack.local.env`
- `env/frontend.prod.local.env`

Legacy local override files (`env/frontend.dev.env`, `env/frontend.stack.env`, `env/frontend.prod.env`) are still supported.

## Loading behavior

`scripts/use-frontend-env.sh <mode>` writes `frontend/.env.local` by combining:

1. `config/public/frontend.<mode>.env`
2. `env/frontend.<mode>.env` (legacy, if present)
3. `env/frontend.<mode>.local.env` (if present)

Later entries override earlier ones.
