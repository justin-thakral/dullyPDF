# DullyPDF Production v1 Guide (Firebase Hosting + Cloud Run)

This guide describes a secure, production-ready setup for:
- Frontend hosted on Firebase Hosting.
- Backend hosted on Cloud Run.
- Firebase Auth for user sessions.
- Firestore + Storage for app data and PDFs.
- Secret Manager for sensitive credentials.

It assumes the main pipeline is CommonForms -> OpenAI rename -> OpenAI schema mapping.
The legacy OpenCV pipeline is archived under `legacy/` and not used.

---

## 1) Architecture overview

Components:
- Frontend (React + Vite): `frontend/` -> Firebase Hosting.
- Backend (FastAPI): `backend/main.py` -> Cloud Run.
- Firebase Auth: client sign-in, ID tokens used by the backend.
- Firestore: user roles, OpenAI credits, schema + template metadata.
- Cloud Storage: stored PDFs and templates.
- Secret Manager: OpenAI key, admin token, optional Firebase Admin JSON.

Auth flow:
- Frontend signs in via Firebase Auth.
- Frontend attaches `Authorization: Bearer <id-token>` to API requests.
- Backend verifies token via Firebase Admin SDK.
- God-only routes require `role=god` in custom claims (or admin override token in dev only).

Files that implement auth and credentials:
- Backend:
  - `backend/firebaseDB/firebase_service.py`
  - `backend/firebaseDB/app_database.py`
  - `backend/firebaseDB/role_cli.py`
  - `backend/main.py`
  - `backend/firebaseDB/storage_service.py`
  - `backend/firebaseDB/schema_database.py`
- Frontend:
  - `frontend/src/config/firebaseConfig.ts`
  - `frontend/src/services/firebaseClient.ts`
  - `frontend/src/services/auth.ts`
  - `frontend/src/services/authTokenStore.ts`
  - `frontend/src/services/apiConfig.ts`
- Scripts + env:
  - `scripts/_load_firebase_secret.sh`
  - `scripts/run-backend-dev.sh`
  - `scripts/run-backend-prod.sh`
  - `scripts/set-role-dev.sh`
  - `scripts/set-role-prod.sh`
  - `config/backend.*.env.example`
  - `env/backend.*.env`

---

## 2) Projects and environments

Recommended layout:
- `dullypdf` (prod)
- `dullypdf-dev` (dev)

Keep Firebase Auth, Firestore, Storage, and secrets isolated between projects.

---

## 3) Enable required services (prod project)

Enable these APIs on `dullypdf`:
- `run.googleapis.com`
- `artifactregistry.googleapis.com` (if building containers)
- `cloudbuild.googleapis.com` (if using `gcloud run deploy --source`)
- `secretmanager.googleapis.com`
- `identitytoolkit.googleapis.com` (Firebase Auth Admin)
- `firestore.googleapis.com`
- `storage.googleapis.com`

Commands:
```
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  identitytoolkit.googleapis.com \
  firestore.googleapis.com \
  storage.googleapis.com \
  --project dullypdf
```

---

## 4) Firebase setup (prod)

1) Add Firebase to the `dullypdf` project.
2) Enable Firebase Auth (Email/Password or providers you need).
3) Create Firestore (Native mode).
4) Ensure Storage buckets exist:
   - `dullypdf-forms`
   - `dullypdf-templates`

Security note:
- Storage objects are accessed via Admin SDK; keep bucket IAM private.
- Do not make buckets public.

---

## 5) Service accounts and IAM

### A) Cloud Run runtime service account (recommended)
Create a dedicated SA for the backend runtime:
```
gcloud iam service-accounts create dullypdf-backend-runtime \
  --project dullypdf
```

Grant minimal roles:
- Firestore: `roles/datastore.user` or `roles/firestore.user`
- Storage: `roles/storage.objectAdmin` (uploads + deletes)
- Secret Manager: `roles/secretmanager.secretAccessor` (if secrets are pulled at runtime)

Example:
```
gcloud projects add-iam-policy-binding dullypdf \
  --member="serviceAccount:dullypdf-backend-runtime@dullypdf.iam.gserviceaccount.com" \
  --role="roles/datastore.user"

gcloud projects add-iam-policy-binding dullypdf \
  --member="serviceAccount:dullypdf-backend-runtime@dullypdf.iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"

gcloud projects add-iam-policy-binding dullypdf \
  --member="serviceAccount:dullypdf-backend-runtime@dullypdf.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

### B) Admin role management (custom claims)
The backend runtime does not need Firebase Auth admin permissions.
Only admin tools like `backend/firebaseDB/role_cli.py` need:
- `roles/firebaseauth.admin`

Assign this only to an admin user or a dedicated admin SA.

---

## 6) Secrets (prod)

Store secrets in Secret Manager:
- `dullypdf-prod-openai-key`
- `dullypdf-prod-admin-token`
- (Optional) `dullypdf-prod-firebase-admin` if you are not using ADC

Commands:
```
# OpenAI key
echo -n "<OPENAI_KEY>" | gcloud secrets create dullypdf-prod-openai-key \
  --data-file=- --project dullypdf

# Admin token
echo -n "<ADMIN_TOKEN>" | gcloud secrets create dullypdf-prod-admin-token \
  --data-file=- --project dullypdf
```

Security note:
- Prefer ADC on Cloud Run (no JSON keys at rest).
- Only use `dullypdf-prod-firebase-admin` if you must run outside GCP.

---

## 7) Backend env vars (prod)

These must be set on Cloud Run:
- `ENV=prod`
- `FIREBASE_PROJECT_ID=dullypdf`
- `FORMS_BUCKET=dullypdf-forms`
- `TEMPLATES_BUCKET=dullypdf-templates`
- `SANDBOX_CORS_ORIGINS=https://your-domain.com`
- `FIREBASE_CHECK_REVOKED=true`
- `SANDBOX_LOG_OPENAI_RESPONSE=false`
- `BASE_OPENAI_CREDITS=10`

If you use Secret Manager for keys:
- `OPENAI_API_KEY` via Secret Manager
- `ADMIN_TOKEN` via Secret Manager

If you use ADC:
- Do not set `FIREBASE_CREDENTIALS` or `GOOGLE_APPLICATION_CREDENTIALS`.

---

## 8) Deploy backend to Cloud Run

Option A: deploy from source (Cloud Build)
```
gcloud run deploy dullypdf-backend \
  --source . \
  --region us-central1 \
  --project dullypdf \
  --service-account dullypdf-backend-runtime@dullypdf.iam.gserviceaccount.com \
  --allow-unauthenticated \
  --set-env-vars ENV=prod,FIREBASE_PROJECT_ID=dullypdf,FORMS_BUCKET=dullypdf-forms,TEMPLATES_BUCKET=dullypdf-templates,SANDBOX_CORS_ORIGINS=https://your-domain.com,SANDBOX_LOG_OPENAI_RESPONSE=false,BASE_OPENAI_CREDITS=10 \
  --set-secrets OPENAI_API_KEY=dullypdf-prod-openai-key:latest,ADMIN_TOKEN=dullypdf-prod-admin-token:latest
```

Option B: container build and deploy
1) Build and push a container to Artifact Registry.
2) Deploy with `gcloud run deploy --image ...`.

Security notes:
- `--allow-unauthenticated` is acceptable because the app enforces Firebase auth on protected routes.
- If you want additional protection, use Cloud Armor + rate limiting or place Cloud Run behind a load balancer.

---

## 9) Frontend deploy to Firebase Hosting

1) Build the frontend with prod env values:
```
cd frontend
VITE_API_URL=https://<cloud-run-url> \
VITE_FIREBASE_API_KEY=... \
VITE_FIREBASE_AUTH_DOMAIN=... \
VITE_FIREBASE_PROJECT_ID=dullypdf \
VITE_FIREBASE_APP_ID=... \
VITE_FIREBASE_STORAGE_BUCKET=dullypdf.firebasestorage.app \
VITE_FIREBASE_MESSAGING_SENDER_ID=... \
npm run build
```

2) Deploy hosting:
```
firebase deploy --only hosting --project dullypdf
```

Security notes:
- Do not set `VITE_ADMIN_TOKEN` in prod.
- Restrict Firebase Auth authorized domains to your Hosting domain.
- Optionally add a Hosting rewrite to Cloud Run if you want same-domain APIs.

---

## 10) Role management

Roles are stored in Firebase custom claims and Firestore:
- `base`: max 10 OpenAI renames lifetime.
- `god`: unlimited renames + DB connect/search/mapping.

Set roles using the CLI (run in a secure admin environment):
```
FIREBASE_PROJECT_ID=dullypdf \
python -m backend.firebaseDB.role_cli --email justin@ttcommercial.com --role god
```

---

## 11) Production security checklist

- Admin override token (`ADMIN_TOKEN`) is server-only and stored in Secret Manager.
- `VITE_ADMIN_TOKEN` is empty in prod builds.
- `SANDBOX_DB_REQUIRE_ADMIN=true`.
- `SANDBOX_LOG_OPENAI_RESPONSE=false`.
- CORS is locked to your Hosting domain.
- Cloud Run uses a minimal-privilege service account.
- Secrets are only accessible to the backend runtime SA.
- Firestore and Storage access is controlled via IAM (buckets are private).
- Token revocation checks are enabled.

---

## 12) Recommended hardening (post-v1)

- Add rate limiting (Cloud Armor or API Gateway).
- Enable Firestore TTL on `rate_limits.expires_at` to auto-expire distributed rate-limit counters.
- Add audit logs for admin actions (role changes, DB connections).
- Add Sentry/Cloud Logging alerts for failed auth spikes.
- Move DB connection config to a secure store if you add persistent connectors.

---

## 13) Quick local prod smoke test

1) Run local backend with prod env:
```
./scripts/run-backend-prod.sh env/backend.prod.env
```

2) Sign in via frontend (prod Firebase config) and verify:
- Base users cannot use DB endpoints.
- God users can use DB endpoints.
- Base users stop at 10 rename calls.

---

## 14) Pre-prod gap to close: multi-instance session consistency

Resolved since last review:
- Legacy session endpoints now require Firebase auth and enforce session ownership.
- Legacy endpoints are disabled in production (dev-only `SANDBOX_ENABLE_LEGACY_ENDPOINTS`).
- `_API_SESSION_CACHE` entries expire after `SANDBOX_SESSION_TTL_SECONDS` and are capped by `SANDBOX_SESSION_MAX_ENTRIES` (LRU).

Issue found in the current codebase:
- `_API_SESSION_CACHE` is in-process, so multi-instance deployments can lose sessions between requests unless traffic is sticky.

Next steps to move forward:
1) Decide whether to enforce sticky sessions or move sessions to Redis/Firestore with TTL.
2) Document the chosen strategy and expected session lifetime in `backend/README.md`.
