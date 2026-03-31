# Google Search Console API Access (GSC)

Preferred local Search Console credentials now live in `search_console/`, following
the same local-only pattern as `google_ads/` and `porkbun/`.

Use the local bundle when it exists:
- `search_console/.env`
- `search_console/search-console-api-service-account.json`
- `search_console/README.md`

## Current supported access path

The working DullyPDF setup uses a dedicated service account:
- Service account: `search-console-api@dullypdf.iam.gserviceaccount.com`
- Quota project: `dullypdf`
- Domain property: `sc-domain:dullypdf.com`
- Encoded property: `sc-domain%3Adullypdf.com`

Important details:
- Search Console ownership alone is not enough. The owner also needs the property added with `sites.add`.
- Requests should send `x-goog-user-project: dullypdf`.
- The service account needs `roles/serviceusage.serviceUsageConsumer` on project `dullypdf`.
- `sites.get` and `searchAnalytics.query` are the reliable smoke tests. `sites.list` can lag after a fresh bootstrap.

## Minimal smoke test

```bash
cd /home/dully/projects/DullyPDF
set -a
source search_console/.env
set +a

TMP_GCLOUD_CONFIG="$(mktemp -d)"
CLOUDSDK_CONFIG="$TMP_GCLOUD_CONFIG" gcloud auth login \
  --cred-file="$SEARCH_CONSOLE_SERVICE_ACCOUNT_KEY_PATH" \
  --quiet

ACCESS_TOKEN="$(CLOUDSDK_CONFIG="$TMP_GCLOUD_CONFIG" gcloud auth print-access-token \
  --scopes='https://www.googleapis.com/auth/webmasters.readonly')"

curl -sS \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "x-goog-user-project: ${SEARCH_CONSOLE_QUOTA_PROJECT}" \
  "${SEARCH_CONSOLE_WEBMASTERS_API_BASE}/sites/${SEARCH_CONSOLE_SITE_PROPERTY_ENCODED}" | jq

curl -sS -X POST \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "x-goog-user-project: ${SEARCH_CONSOLE_QUOTA_PROJECT}" \
  -H "Content-Type: application/json" \
  "${SEARCH_CONSOLE_WEBMASTERS_API_BASE}/sites/${SEARCH_CONSOLE_SITE_PROPERTY_ENCODED}/searchAnalytics/query" \
  --data-binary '{"startDate":"2026-02-23","endDate":"2026-03-22","dimensions":["query"],"rowLimit":25,"type":"web"}' | jq

rm -rf "$TMP_GCLOUD_CONFIG"
```

## Ownership bootstrap summary

If the service account is recreated or replaced:
1. Get a DNS TXT token with the Site Verification API.
2. Add the TXT token at the root of `dullypdf.com`.
3. Call Site Verification `insert` with `verificationMethod=DNS_TXT`.
4. Call Search Console `sites.add` for `sc-domain:dullypdf.com`.

The local `search_console/README.md` contains the exact commands.
