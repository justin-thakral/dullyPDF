# Cloud Architecture

This is the current production-oriented service map for DullyPDF. It shows how
the React frontend, Firebase Hosting/Auth, the public FastAPI backend, Cloud
Tasks, detector/OpenAI worker services, Firestore, and Cloud Storage fit
together.

The naming here matches the live production deployment verified on March 20,
2026. Exact Cloud Run service names and routing modes can change over time, so
keep this doc aligned with deploy config and GCP service settings when infra
changes land.

## Mermaid Diagram

```mermaid
flowchart LR
    WEB["Browsers + Crawlers<br/>Users request the site over HTTPS"]

    subgraph FRONT["Frontend Layer"]
        BUILD["Build + SEO prerender<br/>TypeScript + React (Vite SPA)<br/>generate-static-html.mjs creates route-specific HTML + sitemap<br/>Public routes become crawler-readable before React hydrates"]
        HOST["Firebase Hosting<br/>Hosts built SPA assets + prerendered public HTML<br/>Serves same-origin frontend requests<br/>Rewrites /api/* and /detect-fields* to dullypdf-backend-east4"]
        FE["Browser app runtime<br/>TypeScript + React<br/>Homepage, upload flow, profile, workspace, public docs"]
        AUTH["Firebase Auth<br/>Email/password, Google, GitHub login flows<br/>Returns Firebase ID token (JWT) to the browser"]
        DETREQ["Field detection request shape<br/>Method: POST /detect-fields<br/>Body: multipart/form-data<br/>Fields: file, pipeline, prewarmRename, prewarmRemap<br/>Header: Authorization: Bearer Firebase ID token"]

        BUILD -->|"deploy built assets + prerendered route HTML"| HOST
        WEB -->|"HTTPS"| HOST
        HOST -->|"serves app shell + prerendered HTML"| FE
        FE -->|"login/signup/reset over HTTPS"| AUTH
        AUTH -->|"returns Firebase ID token (JWT)"| FE
        FE -->|"compose upload + auth headers"| DETREQ
    end

    API["dullypdf-backend-east4<br/>Public API entrypoint behind Firebase Hosting rewrites<br/>Cloud Run service<br/>Python + FastAPI<br/><br/>Top endpoints<br/>GET /api/health<br/>POST /detect-fields<br/>GET /detect-fields/{sessionId}<br/>POST /api/renames/ai<br/>GET /api/profile"]

    TASKS["Google Cloud Tasks API + queues<br/>Backend enqueues async jobs here<br/>CreateTask via Google client SDK<br/>Typically gRPC under the library transport<br/><br/>Active detector queues<br/>commonforms-detect-light<br/>commonforms-detect-heavy<br/><br/>OpenAI queues<br/>openai-rename-*, openai-remap-*"]

    subgraph WORKERS["Async Worker Microservices (Cloud Run)"]
        DETECTORS["Field detector microservice group<br/>Current services include CPU + GPU light/heavy variants<br/>Main task endpoint: POST /internal/detect<br/>Downloads PDF from GCS, runs CommonForms detection,<br/>writes fields/result artifacts, updates session state"]
        OPENAI["Rename + Remap microservice group<br/>OpenAI worker services for async rename and schema mapping<br/>Task endpoints: POST /internal/rename and POST /internal/remap<br/>Reads session/template context, runs OpenAI work,<br/>updates job state and outputs"]
    end

    subgraph DATA["Persistent Data Layer"]
        FIRESTORE["Firestore<br/>NoSQL document database<br/>Stores session metadata, detection status, OpenAI job state,<br/>profiles, groups, saved-form metadata, schemas, fill-link metadata"]
        GCS["Google Cloud Storage buckets<br/>Stores uploaded PDFs, session artifacts, detection fields/result JSON,<br/>saved templates, respondent download assets, and model weights"]
    end

    DETREQ -->|"HTTPS HTTP API call over TCP"| API
    FE -->|"other HTTPS API calls over TCP<br/>profile, health, rename, remap, groups, saved forms, billing"| API

    API -->|"verify bearer token, enforce auth, orchestrate workflows"| AUTH
    API -->|"Firebase Admin / Firestore client<br/>gRPC-backed SDK calls"| FIRESTORE
    API -->|"Cloud Storage client<br/>HTTPS / JSON API"| GCS
    API -->|"enqueue jobs with Cloud Tasks<br/>CreateTask via Google client SDK"| TASKS

    TASKS -->|"HTTPS POST + OIDC token<br/>dispatch detection tasks"| DETECTORS
    TASKS -->|"HTTPS POST + OIDC token<br/>dispatch rename/remap tasks"| OPENAI

    DETECTORS -->|"session status + metadata updates<br/>Firestore Admin SDK / gRPC-backed calls"| FIRESTORE
    DETECTORS -->|"download PDFs + upload artifacts<br/>GCS API over HTTPS"| GCS

    OPENAI -->|"job status + usage + output updates<br/>Firestore Admin SDK / gRPC-backed calls"| FIRESTORE
    OPENAI -->|"read/write session or template artifacts as needed<br/>GCS API over HTTPS"| GCS
```

## Key Notes

- `dullypdf-backend-east4` is the current public backend entrypoint because
  Firebase Hosting rewrites send `/api/*` and `/detect-fields*` traffic there.
  It is fine to call it the "API gateway" informally, but it is not the separate
  Google API Gateway product. It is a Cloud Run FastAPI service acting as the
  public API entrypoint.
- Cloud Tasks is not a worker and it does not "create" detector instances. The
  detector and OpenAI services already exist as deployed Cloud Run services.
  Cloud Tasks stores a job, then later sends an authenticated HTTPS request to
  the correct worker endpoint.
- There are two different communication hops around Cloud Tasks:
  - Backend -> Cloud Tasks API: `CreateTask` through the Google client library,
    typically using gRPC under the hood.
  - Cloud Tasks -> worker service: HTTPS `POST` with an OIDC token to
    `/internal/detect`, `/internal/rename`, or `/internal/remap`.
- Firestore is a NoSQL document database. In this architecture it mainly holds
  metadata and status: session docs, OpenAI job docs, user/profile metadata,
  saved-form metadata, schema metadata, and related workflow state.
- GCS holds the larger binary/object artifacts: uploaded PDFs, session output
  JSON, saved templates, respondent download artifacts, and model weights.

## Current Production Snapshot

- Public backend entrypoint: `dullypdf-backend-east4` in `us-east4`
- Additional direct backend deployment: `dullypdf-backend` in `us-central1`
- Detector services:
  - `dullypdf-detector-light`
  - `dullypdf-detector-heavy`
  - `dullypdf-detector-light-gpu`
  - `dullypdf-detector-heavy-gpu`
- Session cleanup batch job: `dullypdf-session-cleanup`
- Current prod backend routing is configured for GPU-backed detector URLs, while
  Cloud Tasks detector queues still live in `us-central1`

## Related Docs

- [frontend/docs/overview.md](/home/dully/projects/dullyPDF/frontend/docs/overview.md)
- [frontend/docs/api-routing.md](/home/dully/projects/dullyPDF/frontend/docs/api-routing.md)
- [backend/README.md](/home/dully/projects/dullyPDF/backend/README.md)
- [backend/fieldDetecting/docs/detectingPipeline.md](/home/dully/projects/dullyPDF/backend/fieldDetecting/docs/detectingPipeline.md)
- [backend/fieldDetecting/docs/rename-flow.md](/home/dully/projects/dullyPDF/backend/fieldDetecting/docs/rename-flow.md)
