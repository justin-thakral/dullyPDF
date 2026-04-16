# Deployment Runbook

This runbook covers how DullyPDF is deployed, how GitHub Actions authenticates,
and how to verify a dev deploy before promoting anything further.

## Current Deploy Model

DullyPDF uses one explicit deploy workflow:

- `.github/workflows/controlled-deploy.yml`

Deploys do not happen on ordinary branch pushes. Normal pushes and pull requests
run Hybrid QA only. Deploys require either:

1. `workflow_dispatch`
2. a deploy tag push

`Hybrid QA` now uses a short `changes` job plus a single `qa` job. The `qa` job
runs the baseline gate first, then the targeted backend and real Playwright
selectors inside the same job so GitHub does not show padded skipped-job counts.

Supported deploy components:

- `frontend`
- `backend`
- `detectors`
- `workers`
- `all`

Supported deploy environments:

- `dev`
- `prod`

`backend_image` is allowed only for `backend` and `all`.

## Auth

GitHub-hosted deploys should authenticate with Workload Identity Federation
(WIF), not with long-lived service-account keys.

Configured WIF providers:

- dev: `projects/696001046696/locations/global/workloadIdentityPools/github-actions/providers/github`
- prod: `projects/916039292611/locations/global/workloadIdentityPools/github-actions/providers/github`

Configured service accounts:

- dev: `github-actions-dev@dullypdf-dev.iam.gserviceaccount.com`
- prod: `github-actions-prod@dullypdf.iam.gserviceaccount.com`

Required IAM bindings on those service accounts:

- `roles/iam.workloadIdentityUser` for the GitHub OIDC principal set
- `roles/iam.serviceAccountTokenCreator` granted to the service account itself

Required repo-level auth secrets:

- `GCP_WORKLOAD_IDENTITY_PROVIDER_DEV`
- `GCP_SERVICE_ACCOUNT_DEV`
- `GCP_WORKLOAD_IDENTITY_PROVIDER_PROD`
- `GCP_SERVICE_ACCOUNT_PROD`

Required environment-level deploy material:

- `development/BACKEND_ENV_FILE_B64_DEV`
- `development/FRONTEND_ENV_OVERRIDE_B64_DEV`
- `production/BACKEND_ENV_FILE_B64_PROD`
- `production/FRONTEND_ENV_OVERRIDE_B64_PROD`

Operational expectation:

- WIF is the normal auth path.
- If WIF is healthy, remove any leftover long-lived key secret such as `GCP_CREDENTIALS_JSON_DEV`.
- Deploy jobs should fail loudly if WIF or environment material is missing.
- Hybrid QA also exports `FIREBASE_SERVICE_ACCOUNT_ID` for seeded browser
  fixtures so Firebase Admin can mint custom tokens via IAM `signBlob` under
  WIF instead of trying metadata-server discovery.

## Trigger Examples

Manual dispatch is the cleanest option when you need an explicit target or a
custom backend image.

Tag examples:

```bash
git tag deploy-dev-frontend-20260403-1
git push origin deploy-dev-frontend-20260403-1
```

```bash
git tag deploy-dev-backend-20260403-1
git push origin deploy-dev-backend-20260403-1
```

```bash
git tag deploy-dev-all-20260403-1
git push origin deploy-dev-all-20260403-1
```

Dry-run examples:

```bash
git tag deploy-dev-all-dryrun-20260403-1
git push origin deploy-dev-all-dryrun-20260403-1
```

Manual dispatch inputs:

- `environment`
- `component`
- `backend_image`
- `dry_run`

Manual dispatch examples:

```bash
gh workflow run controlled-deploy.yml \
  -f environment=dev \
  -f component=frontend \
  -f dry_run=false
```

```bash
gh workflow run controlled-deploy.yml \
  -f environment=dev \
  -f component=backend \
  -f backend_image=us-east4-docker.pkg.dev/dullypdf-dev/dullypdf-backend/backend:20260404-024357 \
  -f dry_run=false
```

```bash
gh workflow run controlled-deploy.yml \
  -f environment=dev \
  -f component=all \
  -f backend_image=us-east4-docker.pkg.dev/dullypdf-dev/dullypdf-backend/backend:20260404-024357 \
  -f dry_run=false
```

```bash
gh workflow run controlled-deploy.yml \
  -f environment=prod \
  -f component=frontend \
  -f dry_run=false
```

```bash
gh workflow run controlled-deploy.yml \
  -f environment=prod \
  -f component=backend \
  -f backend_image=us-east4-docker.pkg.dev/dullypdf/dullypdf-backend/backend:20260401-223101 \
  -f dry_run=false
```

```bash
gh workflow run controlled-deploy.yml \
  -f environment=prod \
  -f component=all \
  -f backend_image=us-east4-docker.pkg.dev/dullypdf/dullypdf-backend/backend:20260401-223101 \
  -f dry_run=false
```

## Region Topology

Both environments standardize on the same four-service footprint with all
services in `us-east4`:

| Service                        | Prod (`dullypdf`) region | Dev (`dullypdf-dev`) region |
| ------------------------------ | ------------------------ | --------------------------- |
| `dullypdf-backend-east4`       | `us-east4`               | `us-east4`                  |
| `dullypdf-openai-rename-remap` | `us-east4`               | `us-east4`                  |
| `dullypdf-detector-light-gpu`  | `us-east4`               | `us-east4`                  |
| `dullypdf-session-cleanup` (Job) | `us-east4`              | `us-east4`                  |

CPU detectors (`dullypdf-detector-light`, `dullypdf-detector-heavy`) are
unsupported in both environments. The deploy scripts refuse any non-GPU
routing mode and any region drift:

- `scripts/deploy-backend.sh` — requires `BACKEND_REGION=us-east4` and the
  `dullypdf-backend-east4` service name.
- `scripts/deploy-openai-workers.sh` — requires `REGION=us-east4` and
  `OPENAI_RENAME_REMAP_TASKS_LOCATION=us-east4`.
- `scripts/deploy-detector-services.sh` — requires `DETECTOR_ROUTING_MODE=gpu`,
  `REGION=us-east4` (tasks queue), and `DETECTOR_GPU_REGION=us-east4`.
- `scripts/deploy-session-cleanup-job.sh` — prod-only today; requires
  `us-east4`.

### Future work: move dev GPU detector to us-central1

Cloud Run L4 GPU quota in `us-east4` is 1 per project. Dev and prod each have
their own 1-slot quota, but rolling a new GPU revision requires the prior
revision to be fully released first, so every dev GPU detector deploy goes
through a delete-then-retry dance that adds 15-20 min to the deploy. The
medium-term plan is to move the dev GPU detector to `us-central1` so dev can
claim an independent per-region quota slot. That is currently blocked on a
GCP quota request for `Cloud Run GPU` (L4, no zonal redundancy) in
`us-central1` for the `dullypdf-dev` project.

Once the quota is approved:

1. Set `DETECTOR_GPU_REGION=us-central1` in the dev env secret.
2. Reintroduce the project-aware guard in `deploy-detector-services.sh` that
   expects `us-central1` for `dullypdf-dev`.
3. Redeploy dev detectors (lands in us-central1).
4. Delete the orphan `dullypdf-detector-light-gpu` in `us-east4` from
   `dullypdf-dev`.

The Cloud Tasks queue still lives in `us-east4` and dispatches cross-region to
the new us-central1 service, which Cloud Tasks supports natively.

## Verification Checklist

For a dev deploy, verify all of the following:

1. `Hybrid QA` passed on the same commit you intend to deploy.
2. `Controlled Deploy` completed successfully for the requested component.
3. The relevant Cloud Run service revision is healthy in `dullypdf-dev`.
4. `npm run dev:stack` boots locally on `http://localhost:5173` + `http://localhost:8010`.
5. The localhost baseline smoke passes against that stack.

Note:

- `dullypdf-dev.web.app` is intentionally disabled. Dev verification happens through the localhost prod-topology stack, not a shared hosted frontend.

Recommended additional local verification before merging risky runtime changes:

1. Start `npm run dev:stack`
2. Run the targeted backend selector:

```bash
RUN_TEMPLATE_API=true RUN_WORKSPACE=true RUN_SHARED_RUNTIME=true bash scripts/ci/run_targeted_backend_suites.sh
```

3. Run the targeted Playwright selector:

```bash
RUN_TEMPLATE_API=true RUN_WORKSPACE=true RUN_SHARED_RUNTIME=true RUN_PLAYWRIGHT_SAFE=true bash scripts/ci/run_targeted_playwright_suites.sh
```

## Required Pre-Prod Baseline Smoke

Before any prod deploy, run a manual baseline smoke against the local dev stack.
This is intentionally smaller than full regression coverage. The baseline proves
the primary operator path still works. Every other smoke should be targeted to
the feature area changed in the release.

Required setup:

1. Start `npm run dev:stack`
2. Start Chrome for MCP using `mcp/devtools.md`
3. Load operator smoke credentials from env only. Do not commit them.

Recommended local env names:

- `SMOKE_LOGIN_EMAIL`
- `SMOKE_LOGIN_PASSWORD`

Current operator smoke account:

- set `SMOKE_LOGIN_EMAIL=justin@ttcommercial.com` outside git
- keep `SMOKE_LOGIN_PASSWORD` outside git as well

Recommended storage:

- `mcp/.env.local`
- a shell session export
- a local non-committed env file sourced before the smoke

The manual baseline smoke is:

1. Sign in with `SMOKE_LOGIN_EMAIL` / `SMOKE_LOGIN_PASSWORD`
2. Open `/ui/profile` and verify the profile page loads successfully
3. Upload `quickTestFiles/new_patient_forms_1915ccb015.pdf`
4. Verify field detection completes and the field list populates
5. Attach `quickTestFiles/new_patient_forms_1915ccb015_mock.csv`
6. Run OpenAI Rename + Map and verify the mapped state appears
7. Verify API Fill works from the same template flow

Detection timing note:

- On local `npm run dev:stack`, field detection can legitimately take a while.
- The standard CPU path may sit on `Processing Document` / `Detecting fields on the standard CPU...` for multiple minutes before the editor appears.
- Treat this as expected latency unless the UI stops progressing entirely, the backend returns an error, or the flow clearly stalls past the normal local wait window for that machine.

Chrome DevTools baseline expectations:

- Login succeeds and the workspace opens
- Profile data loads without auth or fetch errors
- Detection completes on `new_patient_forms_1915ccb015.pdf`
- Rename + Map succeeds using `new_patient_forms_1915ccb015_mock.csv`
- API Fill publishes and a sample fill succeeds

Important constraint:

- This baseline is required before prod deploys.
- All other smoke should be targeted to the changed feature only.
- Do not expand the baseline into a full exploratory pass every release.

Reference docs for the operator smoke:

- `mcp/devtools.md`
- `mcp/debugger.md`
- `mcp/security-debugger.md`

## Important Real Browser Coverage

GitHub Hybrid QA uses only real Playwright flows. The rename+remap smoke uses a
smaller real consent PDF rather than the 211-field intake packet because the
smaller asset keeps synchronous OpenAI mapping within stable CI latency bounds
while still exercising the live rename and remap backend paths.

Current important GitHub Playwright flows:

- `npm run test:playwright:template-api:real`
- `npm run test:playwright:openai-rename`
- `npm run test:playwright:openai-rename-remap`
- `npm run test:playwright:saved-form-snapshot:real`
- `npm run test:playwright:fill-link-download:real`
- `npm run test:playwright:signing-envelope`

## History Cleanup Rule

When cleaning deploy history on `main`, only remove commits whose CI/CD runs
failed and have since been replaced by a green commit carrying the same intent.
Do not rewrite away commits that already have fully green QA and deploy history.

## Dev Cleanup

After repeated dev verification runs, clean only unused cloud artifacts:

- stale Artifact Registry images not referenced by active Cloud Run revisions
- stale dev-only Cloud Run revisions or services no longer used by deploy scripts
- temporary verification branches and tags

Do not delete active images or revisions that are still serving `dullypdf-dev`.
