import { useEffect, useMemo, useState } from 'react';
import { Dialog } from '../ui/Dialog';
import type { MaterializePdfExportMode, TemplateApiSchema } from '../../services/api';
import { resolveApiUrl } from '../../services/apiConfig';
import type { ApiFillManagerDialogProps } from '../../hooks/useWorkspaceTemplateApi';
import './ApiFillManagerDialog.css';

function formatDateLabel(value?: string | null): string {
  if (!value) return 'Never';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return 'Unknown';
  return parsed.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

function formatMonthLabel(value?: string | null): string {
  const normalized = String(value || '').trim();
  if (!normalized) return 'Current month';
  const match = normalized.match(/^(\d{4})-(\d{2})$/);
  if (!match) return normalized;
  const year = Number.parseInt(match[1], 10);
  const monthIndex = Number.parseInt(match[2], 10) - 1;
  if (!Number.isFinite(year) || !Number.isFinite(monthIndex) || monthIndex < 0 || monthIndex > 11) {
    return normalized;
  }
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  }).format(new Date(Date.UTC(year, monthIndex, 1)));
}

function buildPayloadSnippet(schema: TemplateApiSchema | null): string {
  return JSON.stringify(schema?.exampleData || {}, null, 2);
}

function buildPythonLiteral(value: unknown): string {
  if (value === null || value === undefined) {
    return 'None';
  }
  if (typeof value === 'boolean') {
    return value ? 'True' : 'False';
  }
  if (typeof value === 'number') {
    return Number.isFinite(value) ? String(value) : 'None';
  }
  if (typeof value === 'string') {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((entry) => buildPythonLiteral(entry)).join(', ')}]`;
  }
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>).map(
      ([key, entry]) => `${JSON.stringify(key)}: ${buildPythonLiteral(entry)}`,
    );
    return `{${entries.join(', ')}}`;
  }
  return JSON.stringify(String(value));
}

function buildCurlSnippet(fillUrl: string, payload: string, exportMode: MaterializePdfExportMode): string {
  return [
    `curl -X POST "${fillUrl}" \\`,
    '  -H "Authorization: Basic $(printf \'%s:\' \"$API_KEY\" | base64)" \\',
    '  -H "Content-Type: application/json" \\',
    `  -d '${JSON.stringify({ data: JSON.parse(payload), exportMode, strict: true }, null, 2)}'`,
  ].join('\n');
}

function buildNodeSnippet(fillUrl: string, payload: string, exportMode: MaterializePdfExportMode): string {
  return [
    "const apiKey = process.env.DULLYPDF_API_KEY;",
    `const response = await fetch(${JSON.stringify(fillUrl)}, {`,
    "  method: 'POST',",
    '  headers: {',
    "    'Content-Type': 'application/json',",
    "    Authorization: `Basic ${Buffer.from(`${apiKey}:`).toString('base64')}`,",
    '  },',
    `  body: JSON.stringify({ data: ${payload}, exportMode: ${JSON.stringify(exportMode)}, strict: true }),`,
    '});',
    '',
    "if (!response.ok) throw new Error(await response.text());",
    "const pdf = Buffer.from(await response.arrayBuffer());",
  ].join('\n');
}

function buildPythonSnippet(fillUrl: string, payloadLiteral: string, exportMode: MaterializePdfExportMode): string {
  return [
    'import base64',
    'import os',
    'import requests',
    '',
    "api_key = os.environ['DULLYPDF_API_KEY']",
    `url = ${JSON.stringify(fillUrl)}`,
    `payload = {"data": ${payloadLiteral}, "exportMode": ${JSON.stringify(exportMode)}, "strict": True}`,
    "auth = base64.b64encode(f'{api_key}:'.encode('utf-8')).decode('ascii')",
    "response = requests.post(url, json=payload, headers={",
    "    'Authorization': f'Basic {auth}',",
    "    'Content-Type': 'application/json',",
    '})',
    'response.raise_for_status()',
    "open('filled.pdf', 'wb').write(response.content)",
  ].join('\n');
}

async function copyText(value: string): Promise<boolean> {
  if (!value) return false;
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    return false;
  }
}

function EndpointSchemaSummary({ schema }: { schema: TemplateApiSchema }) {
  return (
    <div className="template-api-dialog__schema-grid">
      <div className="template-api-dialog__schema-card">
        <span className="template-api-dialog__schema-count">{schema.fields.length}</span>
        <span className="template-api-dialog__schema-label">Scalar fields</span>
      </div>
      <div className="template-api-dialog__schema-card">
        <span className="template-api-dialog__schema-count">{schema.checkboxFields.length}</span>
        <span className="template-api-dialog__schema-label">Checkbox fields</span>
      </div>
      <div className="template-api-dialog__schema-card">
        <span className="template-api-dialog__schema-count">{schema.checkboxGroups.length}</span>
        <span className="template-api-dialog__schema-label">Checkbox groups</span>
      </div>
      <div className="template-api-dialog__schema-card">
        <span className="template-api-dialog__schema-count">{schema.radioGroups.length}</span>
        <span className="template-api-dialog__schema-label">Radio groups</span>
      </div>
    </div>
  );
}

export default function ApiFillManagerDialog({
  open,
  onClose,
  templateName,
  hasActiveTemplate,
  endpoint,
  schema,
  limits,
  recentEvents,
  loading,
  publishing,
  rotating,
  revoking,
  error,
  latestSecret,
  onPublish,
  onRotate,
  onRevoke,
  onRefresh,
}: ApiFillManagerDialogProps) {
  const [exportMode, setExportMode] = useState<MaterializePdfExportMode>('flat');
  const [copyNotice, setCopyNotice] = useState<string | null>(null);

  useEffect(() => {
    const nextMode = schema?.defaultExportMode === 'editable' ? 'editable' : 'flat';
    setExportMode(nextMode);
  }, [schema?.defaultExportMode, endpoint?.id]);

  const payloadSnippet = useMemo(() => buildPayloadSnippet(schema), [schema]);
  const pythonPayloadLiteral = useMemo(
    () => buildPythonLiteral(schema?.exampleData || {}),
    [schema],
  );
  const fillUrl = useMemo(() => resolveApiUrl(String(endpoint?.fillPath || '').trim()), [endpoint?.fillPath]);
  const schemaUrl = useMemo(
    () => resolveApiUrl(endpoint?.id ? `/api/v1/fill/${encodeURIComponent(endpoint.id)}/schema` : ''),
    [endpoint?.id],
  );
  const snippetExportMode = schema?.defaultExportMode === 'editable' ? 'editable' : 'flat';
  const curlSnippet = useMemo(
    () => buildCurlSnippet(fillUrl, payloadSnippet, snippetExportMode),
    [fillUrl, payloadSnippet, snippetExportMode],
  );
  const nodeSnippet = useMemo(
    () => buildNodeSnippet(fillUrl, payloadSnippet, snippetExportMode),
    [fillUrl, payloadSnippet, snippetExportMode],
  );
  const pythonSnippet = useMemo(
    () => buildPythonSnippet(fillUrl, pythonPayloadLiteral, snippetExportMode),
    [fillUrl, pythonPayloadLiteral, snippetExportMode],
  );

  const endpointStatusLabel = endpoint?.status === 'revoked' ? 'Revoked' : endpoint ? 'Active' : 'Not published';
  const publishButtonLabel = !endpoint || endpoint.status === 'revoked' ? 'Generate key' : 'Republish snapshot';
  const isActiveEndpoint = endpoint?.status === 'active';
  const trackedFailureCount = (endpoint?.authFailureCount || 0) + (endpoint?.validationFailureCount || 0) + (endpoint?.runtimeFailureCount || 0);

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="API Fill"
      description="Publish a saved template as a scoped PDF fill endpoint. The generated key is server-side only and authenticates one template snapshot at a time."
      className="template-api-dialog"
    >
      <div className="template-api-dialog__body">
        <section className="template-api-dialog__hero">
          <div>
            <p className="template-api-dialog__eyebrow">Saved template</p>
            <h3>{templateName || 'No saved template selected'}</h3>
            <p className="template-api-dialog__support">
              API Fill uses the last published snapshot for this template. Save editor changes before publishing or republishing to update the live endpoint.
            </p>
          </div>
          <div className={`template-api-dialog__status template-api-dialog__status--${endpoint?.status || 'idle'}`}>
            {endpointStatusLabel}
          </div>
        </section>

        {!hasActiveTemplate ? (
          <div className="template-api-dialog__empty">
            Save the current PDF as a template first. API Fill is only available for saved templates because the public endpoint must publish a frozen snapshot.
          </div>
        ) : null}

        {error ? <div className="template-api-dialog__error">{error}</div> : null}
        {copyNotice ? <div className="template-api-dialog__notice">{copyNotice}</div> : null}

        {hasActiveTemplate ? (
          <section className="template-api-dialog__card">
            <div className="template-api-dialog__card-header">
              <div>
                <h4>Publish settings</h4>
                <p>Choose how generated PDFs should be returned by default.</p>
              </div>
              <button
                type="button"
                className="ui-button ui-button--ghost ui-button--compact"
                onClick={() => void onRefresh()}
                disabled={loading}
              >
                {loading ? 'Refreshing...' : 'Refresh'}
              </button>
            </div>
            <div className="template-api-dialog__mode-row" role="radiogroup" aria-label="Default export mode">
              <button
                type="button"
                className={exportMode === 'flat' ? 'template-api-dialog__mode template-api-dialog__mode--active' : 'template-api-dialog__mode'}
                onClick={() => setExportMode('flat')}
              >
                <strong>Flat PDF</strong>
                <span>Return a non-editable final PDF.</span>
              </button>
              <button
                type="button"
                className={exportMode === 'editable' ? 'template-api-dialog__mode template-api-dialog__mode--active' : 'template-api-dialog__mode'}
                onClick={() => setExportMode('editable')}
              >
                <strong>Editable PDF</strong>
                <span>Keep form fields intact in the response.</span>
              </button>
            </div>
            <div className="template-api-dialog__actions">
              <button
                type="button"
                className="ui-button ui-button--primary"
                onClick={() => void onPublish(exportMode)}
                disabled={publishing}
              >
                {publishing ? 'Publishing...' : publishButtonLabel}
              </button>
              <button
                type="button"
                className="ui-button ui-button--ghost"
                onClick={() => void onRotate()}
                disabled={!endpoint || endpoint.status !== 'active' || rotating}
              >
                {rotating ? 'Rotating...' : 'Rotate key'}
              </button>
              <button
                type="button"
                className="ui-button ui-button--ghost"
                onClick={() => void onRevoke()}
                disabled={!endpoint || endpoint.status !== 'active' || revoking}
              >
                {revoking ? 'Revoking...' : 'Revoke'}
              </button>
            </div>
          </section>
        ) : null}

        {latestSecret ? (
          <section className="template-api-dialog__secret-card">
            <div>
              <p className="template-api-dialog__eyebrow">API key</p>
              <h4>Shown once</h4>
              <p>Store this key on your server. DullyPDF only stores a hash after publish or rotation.</p>
            </div>
            <div className="template-api-dialog__secret-row">
              <code>{latestSecret}</code>
              <button
                type="button"
                className="ui-button ui-button--ghost ui-button--compact"
                onClick={async () => {
                  const copied = await copyText(latestSecret);
                  setCopyNotice(copied ? 'API key copied.' : 'Copy failed. Copy the key manually.');
                }}
              >
                Copy key
              </button>
            </div>
          </section>
        ) : null}

        {endpoint && schema ? (
          <>
            <section className="template-api-dialog__card">
              <div className="template-api-dialog__card-header">
                <div>
                  <h4>Endpoint</h4>
                  <p>
                    {isActiveEndpoint
                      ? 'Use Basic auth with the API key as the username and a blank password.'
                      : 'This endpoint is revoked. Generate a new key to publish a fresh live URL before running server-side fill requests.'}
                  </p>
                </div>
              </div>
              {isActiveEndpoint ? (
                <>
                  <div className="template-api-dialog__endpoint-row">
                    <div>
                      <span className="template-api-dialog__meta-label">URL</span>
                      <code>{fillUrl}</code>
                    </div>
                    <button
                      type="button"
                      className="ui-button ui-button--ghost ui-button--compact"
                      onClick={async () => {
                        const copied = await copyText(fillUrl);
                        setCopyNotice(copied ? 'Endpoint URL copied.' : 'Copy failed. Copy the URL manually.');
                      }}
                    >
                      Copy URL
                    </button>
                  </div>
                  <div className="template-api-dialog__endpoint-row">
                    <div>
                      <span className="template-api-dialog__meta-label">Schema URL</span>
                      <code>{schemaUrl}</code>
                    </div>
                    <button
                      type="button"
                      className="ui-button ui-button--ghost ui-button--compact"
                      onClick={async () => {
                        const copied = await copyText(schemaUrl);
                        setCopyNotice(copied ? 'Schema URL copied.' : 'Copy failed. Copy the schema URL manually.');
                      }}
                    >
                      Copy schema URL
                    </button>
                  </div>
                </>
              ) : (
                <p className="template-api-dialog__support">
                  The previous public endpoint is inactive. The schema and activity history below are still available for reference.
                </p>
              )}
              <div className="template-api-dialog__metadata-grid">
                <div>
                  <span className="template-api-dialog__meta-label">Key prefix</span>
                  <strong>{endpoint.keyPrefix || 'Unavailable'}</strong>
                </div>
                <div>
                  <span className="template-api-dialog__meta-label">Snapshot version</span>
                  <strong>{endpoint.snapshotVersion}</strong>
                </div>
                <div>
                  <span className="template-api-dialog__meta-label">Usage count</span>
                  <strong>{endpoint.usageCount}</strong>
                </div>
                <div>
                  <span className="template-api-dialog__meta-label">Last used</span>
                  <strong>{formatDateLabel(endpoint.lastUsedAt)}</strong>
                </div>
              </div>
            </section>

            {limits ? (
              <section className="template-api-dialog__card">
                <div className="template-api-dialog__card-header">
                  <div>
                    <h4>Limits and activity</h4>
                    <p>API Fill runs on DullyPDF servers. Search & Fill stays local in the browser, but API Fill sends record data to the backend at request time.</p>
                  </div>
                </div>
                <div className="template-api-dialog__metadata-grid">
                  <div>
                    <span className="template-api-dialog__meta-label">Active endpoints</span>
                    <strong>{limits.activeEndpointsUsed} / {limits.activeEndpointsMax}</strong>
                  </div>
                  <div>
                    <span className="template-api-dialog__meta-label">Requests this month</span>
                    <strong>{limits.requestsThisMonth} / {limits.requestsPerMonthMax}</strong>
                    <span className="template-api-dialog__meta-support">{formatMonthLabel(limits.requestUsageMonth)}</span>
                  </div>
                  <div>
                    <span className="template-api-dialog__meta-label">Template pages</span>
                    <strong>{limits.templatePageCount} / {limits.maxPagesPerRequest}</strong>
                  </div>
                  <div>
                    <span className="template-api-dialog__meta-label">Failure signals</span>
                    <strong>{endpoint.suspiciousFailureCount || 0} suspicious</strong>
                    <span className="template-api-dialog__meta-support">{trackedFailureCount} tracked failures</span>
                  </div>
                </div>
                {endpoint.lastFailureReason ? (
                  <p className="template-api-dialog__support">
                    Last failure: {endpoint.lastFailureReason} ({formatDateLabel(endpoint.lastFailureAt)})
                  </p>
                ) : null}
              </section>
            ) : null}

            {recentEvents.length ? (
              <section className="template-api-dialog__card">
                <div className="template-api-dialog__card-header">
                  <div>
                    <h4>Recent activity</h4>
                    <p>Rotation, revoke, publish, and public fill outcomes are recorded without storing raw field values by default.</p>
                  </div>
                </div>
                <div className="template-api-dialog__events">
                  {recentEvents.map((event) => (
                    <article key={event.id} className="template-api-dialog__event">
                      <div className="template-api-dialog__event-header">
                        <strong>{event.summary}</strong>
                        <span>{formatDateLabel(event.createdAt)}</span>
                      </div>
                      <div className="template-api-dialog__event-meta">
                        <span>{event.outcome}</span>
                        {event.snapshotVersion ? <span>Snapshot v{event.snapshotVersion}</span> : null}
                        {typeof event.metadata?.exportMode === 'string' ? <span>{event.metadata.exportMode}</span> : null}
                      </div>
                      {typeof event.metadata?.reason === 'string' && event.metadata.reason ? (
                        <p className="template-api-dialog__event-reason">{event.metadata.reason}</p>
                      ) : null}
                    </article>
                  ))}
                </div>
              </section>
            ) : null}

            <section className="template-api-dialog__card">
              <div className="template-api-dialog__card-header">
                <div>
                  <h4>Schema</h4>
                  <p>These are the JSON keys the published endpoint currently accepts.</p>
                </div>
              </div>
              <EndpointSchemaSummary schema={schema} />
              <pre className="template-api-dialog__code-block">{payloadSnippet}</pre>
            </section>

            {isActiveEndpoint ? (
              <section className="template-api-dialog__examples">
                <article className="template-api-dialog__example">
                  <div className="template-api-dialog__card-header">
                    <div>
                      <h4>cURL</h4>
                      <p>Quick server-side smoke test with <code>strict=true</code>.</p>
                    </div>
                  </div>
                  <pre className="template-api-dialog__code-block">{curlSnippet}</pre>
                </article>
                <article className="template-api-dialog__example">
                  <div className="template-api-dialog__card-header">
                    <div>
                      <h4>Node</h4>
                      <p>Uses native `fetch`, returns PDF bytes, and fails closed on unknown keys.</p>
                    </div>
                  </div>
                  <pre className="template-api-dialog__code-block">{nodeSnippet}</pre>
                </article>
                <article className="template-api-dialog__example">
                  <div className="template-api-dialog__card-header">
                    <div>
                      <h4>Python</h4>
                      <p>Basic `requests` example for backend jobs with schema-checked smoke-test defaults.</p>
                    </div>
                  </div>
                  <pre className="template-api-dialog__code-block">{pythonSnippet}</pre>
                </article>
              </section>
            ) : null}
          </>
        ) : null}
      </div>
    </Dialog>
  );
}
