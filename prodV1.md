# DullyPDF Production v1 Guide (Firebase Hosting + Cloud Run)

This guide describes a secure, production-ready setup for:
- Frontend hosted on Firebase Hosting.
- Backend hosted on Cloud Run.
- Firebase Auth for user sessions.
- Firestore + Storage for app data and PDFs.
- Secret Manager for sensitive credentials.

It assumes the main pipeline is CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) -> OpenAI rename -> OpenAI schema mapping.
The legacy OpenCV pipeline is archived under `legacy/` and not used.

---

## 1) Architecture overview

Components:
- Frontend (React + Vite): `frontend/` -> Firebase Hosting.
- Backend (FastAPI): `backend/main.py` -> Cloud Run.
- Detector services (FastAPI): `backend/detector_main.py` -> Cloud Run (light + heavy profiles).
- Cloud Tasks: dispatches detection jobs to the light/heavy detector services.
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

## Plan (Secure coordinated rollout)

1) Build and tag backend + detector images from the same git SHA, then run the
   local smoke test (backend + detector + frontend) to validate auth + detection.
2) Create the Cloud Tasks queues (light/heavy) and grant the Cloud Tasks service agent
   `roles/iam.serviceAccountTokenCreator` on `DETECTOR_TASKS_SERVICE_ACCOUNT`.
3) Deploy the detector services from `Dockerfile.detector` with
   `--no-allow-unauthenticated` and `--ingress all`, set the detector env vars,
   and record the Cloud Run URLs for `DETECTOR_TASKS_AUDIENCE_LIGHT/HEAVY`.
4) Deploy the main backend from `Dockerfile` with `DETECTOR_MODE=tasks`, the
   Cloud Tasks env vars (`DETECTOR_TASKS_*`, `DETECTOR_SERVICE_URL_*`), and
   `roles/run.invoker` on both detector services.
5) Deploy the frontend with the Cloud Run URL and verify detection/rename flows.
6) Run the smoke test in section 14 and monitor logs for task failures.

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
- `cloudtasks.googleapis.com`
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
  cloudtasks.googleapis.com \
  secretmanager.googleapis.com \
  identitytoolkit.googleapis.com \
  firestore.googleapis.com \
  storage.googleapis.com \
  --project dullypdf
```

Create the detection queues:
```
gcloud tasks queues create commonforms-detect-light \
  --location us-central1 \
  --max-attempts 5 \
  --max-concurrent-dispatches=5 \
  --project dullypdf

gcloud tasks queues create commonforms-detect-heavy \
  --location us-central1 \
  --max-attempts 5 \
  --max-concurrent-dispatches=2 \
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
- Cloud Tasks enqueue: `roles/cloudtasks.enqueuer` (create detection tasks)

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

gcloud projects add-iam-policy-binding dullypdf \
  --member="serviceAccount:dullypdf-backend-runtime@dullypdf.iam.gserviceaccount.com" \
  --role="roles/cloudtasks.enqueuer"
```

Detector service invoker:
- Grant `roles/run.invoker` on both detector services to the same backend runtime SA.
- If the detector services use a dedicated runtime SA, grant it Firestore + Storage roles as well.

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
- (Optional) `dullypdf-prod-firebase-admin` for local prod testing or non-GCP runs

Commands:
```
# OpenAI key
echo -n "<OPENAI_KEY>" | gcloud secrets create dullypdf-prod-openai-key \
  --data-file=- --project dullypdf

# Admin token
echo -n "<ADMIN_TOKEN>" | gcloud secrets create dullypdf-prod-admin-token \
  --data-file=- --project dullypdf

# HuggingFace token (optional; only needed to download weights for GCS seeding)
echo -n "<HF_TOKEN>" | gcloud secrets create dullypdf-prod-hf-token \
  --data-file=- --project dullypdf
```

Security note:
- Prefer ADC on Cloud Run (no JSON keys at rest).
- Only use `dullypdf-prod-firebase-admin` if you must run outside GCP.
- When using GCS-hosted CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) weights, the detector runtime does not need
  HuggingFace tokens.

---

## 6b) CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) weights in GCS (recommended)

1) Create a private models bucket:
```
gcloud storage buckets create gs://dullypdf-models \
  --location=us-central1 \
  --project dullypdf
```

2) Download weights locally (one-time), then upload to GCS:
```
huggingface-cli download jbarrow/FFDNet-L FFDNet-L.pt --local-dir /tmp/commonforms
gcloud storage cp /tmp/commonforms/FFDNet-L.pt gs://dullypdf-models/commonforms/FFDNet-L.pt
```

3) Allow the detector runtime SA to read the weights:
```
gcloud storage buckets add-iam-policy-binding gs://dullypdf-models \
  --member=serviceAccount:dullypdf-backend-runtime@dullypdf.iam.gserviceaccount.com \
  --role=roles/storage.objectViewer
```

If you use a different model or `COMMONFORMS_FAST=true`, upload the matching
weight filename (see `backend/fieldDetecting/docs/commonforms.md`).

---

## 7) Backend env vars (prod)

These must be set on Cloud Run:
- `ENV=prod`
- `FIREBASE_PROJECT_ID=dullypdf`
- `FIREBASE_USE_ADC=true`
- `FORMS_BUCKET=dullypdf-forms`
- `TEMPLATES_BUCKET=dullypdf-templates`
- `SANDBOX_CORS_ORIGINS=https://your-domain.com`
- `FIREBASE_CHECK_REVOKED=true`
- `SANDBOX_LOG_OPENAI_RESPONSE=false`
- `BASE_OPENAI_CREDITS=10`
- `DETECTOR_MODE=tasks`
- `DETECTOR_TASKS_PROJECT=dullypdf`
- `DETECTOR_TASKS_LOCATION=us-central1`
- `DETECTOR_TASKS_QUEUE_LIGHT=commonforms-detect-light`
- `DETECTOR_TASKS_QUEUE_HEAVY=commonforms-detect-heavy`
- `DETECTOR_SERVICE_URL_LIGHT=https://dullypdf-detector-light-xxxxx-uc.a.run.app`
- `DETECTOR_SERVICE_URL_HEAVY=https://dullypdf-detector-heavy-xxxxx-uc.a.run.app`
- `DETECTOR_TASKS_AUDIENCE_LIGHT=https://dullypdf-detector-light-xxxxx-uc.a.run.app`
- `DETECTOR_TASKS_AUDIENCE_HEAVY=https://dullypdf-detector-heavy-xxxxx-uc.a.run.app`
- `DETECTOR_TASKS_HEAVY_PAGE_THRESHOLD=10`
- `DETECTOR_TASKS_SERVICE_ACCOUNT=dullypdf-backend-runtime@dullypdf.iam.gserviceaccount.com`

If you use Secret Manager for keys:
- `OPENAI_API_KEY` via Secret Manager
- `ADMIN_TOKEN` via Secret Manager

If you use ADC:
- Do not set `FIREBASE_CREDENTIALS` or `GOOGLE_APPLICATION_CREDENTIALS`.

Note:
- If you only deploy one detector service, set `DETECTOR_TASKS_QUEUE` and
  `DETECTOR_SERVICE_URL` instead of the light/heavy variants.

---

## 8) Detector env vars (prod)

These must be set on each detector Cloud Run service:
- `ENV=prod`
- `FIREBASE_PROJECT_ID=dullypdf`
- `FIREBASE_USE_ADC=true`
- `FORMS_BUCKET=dullypdf-forms`
- `TEMPLATES_BUCKET=dullypdf-templates`
- `DETECTOR_TASKS_AUDIENCE=https://<this-service-url>`
- `DETECTOR_CALLER_SERVICE_ACCOUNT=dullypdf-backend-runtime@dullypdf.iam.gserviceaccount.com`
- `DETECTOR_ALLOW_UNAUTHENTICATED=false`
- `DETECTOR_TASKS_MAX_ATTEMPTS=5`
- `DETECTOR_RETRY_AFTER_SECONDS=5`
- `COMMONFORMS_MODEL=FFDNet-L`
- `COMMONFORMS_MODEL_GCS_URI=gs://dullypdf-models/commonforms/FFDNet-L.pt`
- `COMMONFORMS_WEIGHTS_CACHE_DIR=/tmp/commonforms-models`
- `COMMONFORMS_WEIGHTS_LOCK_TIMEOUT_SECONDS=600`

CommonForms (by [jbarrow](https://github.com/jbarrow/commonforms)) tuning is optional; see `config/detector.prod.env.example`.

---

## 9) Deploy detector to Cloud Run

1) Build and push a container image (Dockerfile at repo root):
```
gcloud builds submit \
  --tag us-central1-docker.pkg.dev/dullypdf/dullypdf-detector/dullypdf-detector:latest \
  --project dullypdf \
  -f Dockerfile.detector \
  .
```

2) Deploy light (standard CPU):
```
gcloud run deploy dullypdf-detector-light \
  --image us-central1-docker.pkg.dev/dullypdf/dullypdf-detector/dullypdf-detector:latest \
  --region us-central1 \
  --project dullypdf \
  --service-account dullypdf-backend-runtime@dullypdf.iam.gserviceaccount.com \
  --ingress all \
  --no-allow-unauthenticated \
  --cpu 2 \
  --memory 4Gi \
  --max-instances 5 \
  --set-env-vars ENV=prod,FIREBASE_PROJECT_ID=dullypdf,FIREBASE_USE_ADC=true,FORMS_BUCKET=dullypdf-forms,TEMPLATES_BUCKET=dullypdf-templates,DETECTOR_TASKS_AUDIENCE=https://dullypdf-detector-light-xxxxx-uc.a.run.app,DETECTOR_CALLER_SERVICE_ACCOUNT=dullypdf-backend-runtime@dullypdf.iam.gserviceaccount.com,DETECTOR_ALLOW_UNAUTHENTICATED=false,DETECTOR_TASKS_MAX_ATTEMPTS=5,DETECTOR_RETRY_AFTER_SECONDS=5,COMMONFORMS_MODEL=FFDNet-L,COMMONFORMS_MODEL_GCS_URI=gs://dullypdf-models/commonforms/FFDNet-L.pt,COMMONFORMS_WEIGHTS_CACHE_DIR=/tmp/commonforms-models,COMMONFORMS_WEIGHTS_LOCK_TIMEOUT_SECONDS=600
```

3) Deploy heavy (high-capacity CPU):
```
gcloud run deploy dullypdf-detector-heavy \
  --image us-central1-docker.pkg.dev/dullypdf/dullypdf-detector/dullypdf-detector:latest \
  --region us-central1 \
  --project dullypdf \
  --service-account dullypdf-backend-runtime@dullypdf.iam.gserviceaccount.com \
  --ingress all \
  --no-allow-unauthenticated \
  --cpu 4 \
  --memory 8Gi \
  --max-instances 2 \
  --set-env-vars ENV=prod,FIREBASE_PROJECT_ID=dullypdf,FIREBASE_USE_ADC=true,FORMS_BUCKET=dullypdf-forms,TEMPLATES_BUCKET=dullypdf-templates,DETECTOR_TASKS_AUDIENCE=https://dullypdf-detector-heavy-xxxxx-uc.a.run.app,DETECTOR_CALLER_SERVICE_ACCOUNT=dullypdf-backend-runtime@dullypdf.iam.gserviceaccount.com,DETECTOR_ALLOW_UNAUTHENTICATED=false,DETECTOR_TASKS_MAX_ATTEMPTS=5,DETECTOR_RETRY_AFTER_SECONDS=5,COMMONFORMS_MODEL=FFDNet-L,COMMONFORMS_MODEL_GCS_URI=gs://dullypdf-models/commonforms/FFDNet-L.pt,COMMONFORMS_WEIGHTS_CACHE_DIR=/tmp/commonforms-models,COMMONFORMS_WEIGHTS_LOCK_TIMEOUT_SECONDS=600
```

Security notes:
- Require auth (`--no-allow-unauthenticated`) and grant `roles/run.invoker` to the backend runtime SA.
- Keep ingress `all` so Cloud Tasks can reach the service URL.

---

## 10) Deploy backend to Cloud Run

Option A: deploy from source (Cloud Build)
```
gcloud run deploy dullypdf-backend \
  --source backend \
  --region us-central1 \
  --project dullypdf \
  --service-account dullypdf-backend-runtime@dullypdf.iam.gserviceaccount.com \
  --allow-unauthenticated \
  --set-env-vars ENV=prod,FIREBASE_PROJECT_ID=dullypdf,FIREBASE_USE_ADC=true,FORMS_BUCKET=dullypdf-forms,TEMPLATES_BUCKET=dullypdf-templates,SANDBOX_CORS_ORIGINS=https://your-domain.com,SANDBOX_LOG_OPENAI_RESPONSE=false,BASE_OPENAI_CREDITS=10,DETECTOR_MODE=tasks,DETECTOR_TASKS_PROJECT=dullypdf,DETECTOR_TASKS_LOCATION=us-central1,DETECTOR_TASKS_QUEUE_LIGHT=commonforms-detect-light,DETECTOR_TASKS_QUEUE_HEAVY=commonforms-detect-heavy,DETECTOR_SERVICE_URL_LIGHT=https://dullypdf-detector-light-xxxxx-uc.a.run.app,DETECTOR_SERVICE_URL_HEAVY=https://dullypdf-detector-heavy-xxxxx-uc.a.run.app,DETECTOR_TASKS_AUDIENCE_LIGHT=https://dullypdf-detector-light-xxxxx-uc.a.run.app,DETECTOR_TASKS_AUDIENCE_HEAVY=https://dullypdf-detector-heavy-xxxxx-uc.a.run.app,DETECTOR_TASKS_SERVICE_ACCOUNT=dullypdf-backend-runtime@dullypdf.iam.gserviceaccount.com,DETECTOR_TASKS_HEAVY_PAGE_THRESHOLD=10 \
  --set-secrets OPENAI_API_KEY=dullypdf-prod-openai-key:latest,ADMIN_TOKEN=dullypdf-prod-admin-token:latest
```

Option B: container build and deploy
1) Build and push a container to Artifact Registry (Dockerfile at repo root):
```
gcloud builds submit \
  --tag us-central1-docker.pkg.dev/dullypdf/dullypdf-backend/dullypdf-backend:latest \
  --project dullypdf \
  .
```
2) Deploy with `gcloud run deploy --image ...`.

Security notes:
- `--allow-unauthenticated` is acceptable because the app enforces Firebase auth on protected routes.

---

## 11) Frontend deploy to Firebase Hosting

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

---

## 12) Role management

Roles are stored in Firebase custom claims and Firestore:
- `base`: max 10 OpenAI renames lifetime.
- `god`: unlimited renames + DB connect/search/mapping.

Set roles using the CLI (run in a secure admin environment):
```
FIREBASE_PROJECT_ID=dullypdf \
python -m backend.firebaseDB.role_cli --email justin@ttcommercial.com --role god
```

---

## 13) Production security checklist

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

## 14) Quick local prod smoke test

1) Run local backend with prod env:
```
./scripts/run-backend-prod.sh env/backend.prod.env
```

2) Sign in via frontend (prod Firebase config) and verify:
- Base users cannot use DB endpoints.
- God users can use DB endpoints.
- Base users stop at 10 rename calls.

---

## 15) Multi-instance session consistency (resolved)

Current behavior:
- L1 session cache uses TTL/LRU (`SANDBOX_SESSION_TTL_SECONDS`, `SANDBOX_SESSION_SWEEP_INTERVAL_SECONDS`, `SANDBOX_SESSION_MAX_ENTRIES`).
- L2 session metadata lives in Firestore (`session_cache`) with session artifacts in GCS (`sessions/<session_id>/`).
- L2 access updates are throttled by `SANDBOX_SESSION_L2_TOUCH_SECONDS`.

Operational follow-through:
1) Enable Firestore TTL on `session_cache.expires_at`.
2) Add a GCS lifecycle rule for `sessions/` objects aligned to `SANDBOX_SESSION_TTL_SECONDS`.
