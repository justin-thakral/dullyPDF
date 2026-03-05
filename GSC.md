# Google Search Console API Access (GSC)

This doc shows how to fetch Google Search Console data with `curl` when authentication is already configured.

## 1) Set shared variables

```bash
PROJECT_ID="dullypdf"
TOKEN="$(gcloud auth application-default print-access-token)"
```

Notes:
- Keep using the `x-goog-user-project` header in requests.
- In this repo environment, that header is required for ADC user credentials.

## 2) List accessible properties

```bash
curl -s \
  -H "Authorization: Bearer $TOKEN" \
  -H "x-goog-user-project: $PROJECT_ID" \
  "https://www.googleapis.com/webmasters/v3/sites" | jq
```

Expected result includes entries like:
- `siteUrl`: property identifier (for example `sc-domain:dullypdf.com`)
- `permissionLevel`: your access level

## 3) Query Search Analytics

Use URL-encoded property value in the endpoint path.

Example property:
- Raw: `sc-domain:dullypdf.com`
- Encoded: `sc-domain%3Adullypdf.com`

```bash
SITE_ENC="sc-domain%3Adullypdf.com"
START_DATE="2026-02-24"
END_DATE="2026-03-03"

curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "x-goog-user-project: $PROJECT_ID" \
  -H "Content-Type: application/json" \
  "https://www.googleapis.com/webmasters/v3/sites/${SITE_ENC}/searchAnalytics/query" \
  --data-binary "{\"startDate\":\"$START_DATE\",\"endDate\":\"$END_DATE\",\"dimensions\":[\"query\"],\"rowLimit\":25,\"type\":\"web\"}" | jq
```

## 4) Useful query templates

Top pages:

```bash
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "x-goog-user-project: $PROJECT_ID" \
  -H "Content-Type: application/json" \
  "https://www.googleapis.com/webmasters/v3/sites/${SITE_ENC}/searchAnalytics/query" \
  --data-binary "{\"startDate\":\"$START_DATE\",\"endDate\":\"$END_DATE\",\"dimensions\":[\"page\"],\"rowLimit\":25,\"type\":\"web\"}" | jq
```

By country + device:

```bash
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "x-goog-user-project: $PROJECT_ID" \
  -H "Content-Type: application/json" \
  "https://www.googleapis.com/webmasters/v3/sites/${SITE_ENC}/searchAnalytics/query" \
  --data-binary "{\"startDate\":\"$START_DATE\",\"endDate\":\"$END_DATE\",\"dimensions\":[\"country\",\"device\"],\"rowLimit\":100,\"type\":\"web\"}" | jq
```

Date trend:

```bash
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "x-goog-user-project: $PROJECT_ID" \
  -H "Content-Type: application/json" \
  "https://www.googleapis.com/webmasters/v3/sites/${SITE_ENC}/searchAnalytics/query" \
  --data-binary "{\"startDate\":\"$START_DATE\",\"endDate\":\"$END_DATE\",\"dimensions\":[\"date\"],\"rowLimit\":1000,\"type\":\"web\"}" | jq
```

## 5) Save output for local analysis

```bash
curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "x-goog-user-project: $PROJECT_ID" \
  -H "Content-Type: application/json" \
  "https://www.googleapis.com/webmasters/v3/sites/${SITE_ENC}/searchAnalytics/query" \
  --data-binary "{\"startDate\":\"$START_DATE\",\"endDate\":\"$END_DATE\",\"dimensions\":[\"query\"],\"rowLimit\":25000,\"type\":\"web\"}" \
  > tmp/gsc-query-report.json
```

## 6) Common errors

- `403 ACCESS_TOKEN_SCOPE_INSUFFICIENT`
  - Token does not include Search Console scope.
- `403 SERVICE_DISABLED` or quota project error
  - Request missing `x-goog-user-project` header or wrong project.
- `200` with no `rows`
  - Valid response, but no data for that date range/filter.

## 7) Response fields

Search Analytics row metrics:
- `clicks`
- `impressions`
- `ctr`
- `position`
- `keys` (dimension values in dimension order)

## 8) Minimal smoke-test sequence

```bash
PROJECT_ID="dullypdf"
TOKEN="$(gcloud auth application-default print-access-token)"

curl -s -H "Authorization: Bearer $TOKEN" -H "x-goog-user-project: $PROJECT_ID" \
  "https://www.googleapis.com/webmasters/v3/sites" | jq

SITE_ENC="sc-domain%3Adullypdf.com"
START_DATE="2026-02-24"
END_DATE="2026-03-03"

curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "x-goog-user-project: $PROJECT_ID" -H "Content-Type: application/json" \
  "https://www.googleapis.com/webmasters/v3/sites/${SITE_ENC}/searchAnalytics/query" \
  --data-binary "{\"startDate\":\"$START_DATE\",\"endDate\":\"$END_DATE\",\"dimensions\":[\"query\"],\"rowLimit\":10,\"type\":\"web\"}" | jq
```
