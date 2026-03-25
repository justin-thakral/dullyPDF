import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiConfigMocks = vi.hoisted(() => ({
  apiFetch: vi.fn(),
  apiJsonFetch: vi.fn(),
  buildApiUrl: vi.fn((...segments: string[]) => `https://api.local/${segments.filter(Boolean).join('/')}`),
}));

vi.mock('../../../src/services/apiConfig', () => ({
  ApiError: class ApiError extends Error {
    status: number;

    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  },
  apiFetch: apiConfigMocks.apiFetch,
  apiJsonFetch: apiConfigMocks.apiJsonFetch,
  buildApiUrl: apiConfigMocks.buildApiUrl,
}));

import { ApiService } from '../../../src/services/api';

describe('ApiService', () => {
  beforeEach(() => {
    apiConfigMocks.apiFetch.mockReset();
    apiConfigMocks.apiJsonFetch.mockReset();
    apiConfigMocks.buildApiUrl.mockClear();
  });

  it('wires profile and public JSON endpoints with expected methods and payloads', async () => {
    apiConfigMocks.apiFetch
      .mockResolvedValueOnce({ status: 401 })
      .mockResolvedValueOnce({ id: 'contact-response' })
      .mockResolvedValueOnce({ id: 'recaptcha-response' })
      .mockResolvedValueOnce({ id: 'schema-response' });

    apiConfigMocks.apiJsonFetch
      .mockResolvedValueOnce({ success: true })
      .mockResolvedValueOnce({ success: true })
      .mockResolvedValueOnce({ schemaId: 'schema-1', fieldCount: 1, fields: [{ name: 'first_name', type: 'text' }] });

    const profile = await ApiService.getProfile();
    const contact = await ApiService.submitContact({ issueType: 'bug', summary: 'S', message: 'M' });
    const recaptcha = await ApiService.verifyRecaptcha({ token: 'token-1', action: 'signup' });
    const schema = await ApiService.createSchema({ fields: [{ name: 'first_name' }], sampleCount: 2 });

    expect(profile).toBeNull();
    expect(contact).toEqual({ success: true });
    expect(recaptcha).toEqual({ success: true });
    expect(schema.schemaId).toBe('schema-1');

    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(1, 'GET', '/api/profile', {
      allowStatuses: [401, 403],
    });

    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(2, 'POST', '/api/contact', {
      authMode: 'anonymous',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ issueType: 'bug', summary: 'S', message: 'M' }),
    });

    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(3, 'POST', '/api/recaptcha/assess', {
      authMode: 'anonymous',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: 'token-1', action: 'signup' }),
    });

    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(4, 'POST', '/api/schemas', {
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fields: [{ name: 'first_name' }], sampleCount: 2 }),
    });
  });

  it('wires downgrade retention update and delete endpoints', async () => {
    apiConfigMocks.apiFetch
      .mockResolvedValueOnce({ id: 'retention-update-response' })
      .mockResolvedValueOnce({ id: 'retention-delete-response' });
    apiConfigMocks.apiJsonFetch
      .mockResolvedValueOnce({ retention: { status: 'grace_period', keptTemplateIds: ['tpl-1', 'tpl-2', 'tpl-3'] } })
      .mockResolvedValueOnce({ success: true, deletedTemplateIds: ['tpl-4'], deletedLinkIds: ['link-4'] });

    const retention = await ApiService.updateDowngradeRetention(['tpl-1', 'tpl-2', 'tpl-3']);
    const deleted = await ApiService.deleteDowngradeRetentionNow();

    expect(retention?.keptTemplateIds).toEqual(['tpl-1', 'tpl-2', 'tpl-3']);
    expect(deleted.deletedTemplateIds).toEqual(['tpl-4']);
    expect(deleted.deletedLinkIds).toEqual(['link-4']);

    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(1, 'PATCH', '/api/profile/downgrade-retention', {
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ keptTemplateIds: ['tpl-1', 'tpl-2', 'tpl-3'] }),
    });
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(2, 'POST', '/api/profile/downgrade-retention/delete-now');
  });

  it('wires targeted billing reconciliation payloads', async () => {
    apiConfigMocks.apiFetch.mockResolvedValueOnce({ id: 'billing-reconcile-response' });
    apiConfigMocks.apiJsonFetch.mockResolvedValueOnce({
      success: true,
      dryRun: false,
      scope: 'self',
      auditedEventCount: 1,
      candidateEventCount: 1,
      pendingReconciliationCount: 1,
      reconciledCount: 1,
      alreadyProcessedCount: 0,
      processingCount: 0,
      retryableCount: 0,
      failedCount: 0,
      invalidCount: 0,
      skippedForUserCount: 0,
      events: [],
    });

    const payload = await ApiService.reconcileBillingCheckoutFulfillment({
      lookbackHours: 72,
      dryRun: false,
      sessionId: 'cs_reconcile_123',
      attemptId: 'attempt_reconcile_123',
    });

    expect(payload.success).toBe(true);
    expect(apiConfigMocks.apiFetch).toHaveBeenCalledWith('POST', '/api/billing/reconcile', {
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        lookbackHours: 72,
        maxEvents: undefined,
        dryRun: false,
        sessionId: 'cs_reconcile_123',
        attemptId: 'attempt_reconcile_123',
      }),
    });
  });

  it('wires Fill By Link owner and public endpoints', async () => {
    apiConfigMocks.apiFetch
      .mockResolvedValueOnce({ id: 'fill-links-response' })
      .mockResolvedValueOnce({ id: 'fill-link-create-response' })
      .mockResolvedValueOnce({ id: 'fill-link-update-response' })
      .mockResolvedValueOnce({ id: 'fill-link-close-response' })
      .mockResolvedValueOnce({ id: 'fill-link-responses-response' })
      .mockResolvedValueOnce({ id: 'fill-link-response-detail' })
      .mockResolvedValueOnce({ id: 'fill-link-public-response' })
      .mockResolvedValueOnce({ id: 'fill-link-public-submit' })
      .mockResolvedValueOnce({ id: 'fill-link-public-retry' })
      .mockResolvedValueOnce({
        ok: true,
        statusText: 'OK',
        headers: {
          get: vi.fn((name: string) => (name.toLowerCase() === 'content-disposition'
            ? 'attachment; filename="submitted-link-1.pdf"'
            : null)),
        },
        blob: vi.fn().mockResolvedValue(new Blob(['pdf'])),
      });

    apiConfigMocks.apiJsonFetch
      .mockResolvedValueOnce({ links: [{ id: 'link-1', publicPath: '/respond/token-1' }] })
      .mockResolvedValueOnce({ link: { id: 'link-1', publicPath: '/respond/token-1', respondentPdfDownloadEnabled: true } })
      .mockResolvedValueOnce({ link: { id: 'link-1', status: 'active', respondentPdfDownloadEnabled: true } })
      .mockResolvedValueOnce({ link: { id: 'link-1', status: 'closed' } })
      .mockResolvedValueOnce({ link: { id: 'link-1' }, responses: [{ id: 'resp-1' }] })
      .mockResolvedValueOnce({ response: { id: 'resp-1', answers: { full_name: 'Ada Lovelace' } } })
      .mockResolvedValueOnce({ link: { id: 'link-1', questions: [], respondentPdfDownloadEnabled: true } })
      .mockResolvedValueOnce({
        success: true,
        responseId: 'resp-1',
        link: { id: 'link-1', respondentPdfDownloadEnabled: true },
        download: {
          enabled: true,
          responseId: 'resp-1',
          downloadPath: '/api/fill-links/public/token-1/responses/resp-1/download',
        },
      });
    apiConfigMocks.apiJsonFetch.mockResolvedValueOnce({
      success: true,
      responseId: 'resp-1',
      link: { id: 'link-1', respondentPdfDownloadEnabled: true },
      signing: {
        enabled: true,
        available: true,
        requestId: 'sign-1',
        status: 'sent',
        publicPath: '/sign/sign-1',
      },
    });

    const links = await ApiService.getFillLinks('tpl-1');
    const created = await ApiService.createFillLink({
      templateId: 'tpl-1',
      templateName: 'Template One',
      requireAllFields: true,
      allowRespondentPdfDownload: true,
      fields: [{ name: 'full_name', type: 'text', page: 1 }],
    });
    const updated = await ApiService.updateFillLink('link-1', {
      status: 'active',
      requireAllFields: true,
      allowRespondentPdfDownload: true,
    });
    const closed = await ApiService.closeFillLink('link-1');
    const responses = await ApiService.getFillLinkResponses('link-1', { search: 'ada', limit: 25 });
    const response = await ApiService.getFillLinkResponse('link-1', 'resp-1');
    const publicLink = await ApiService.getPublicFillLink('token-1');
    const submitted = await ApiService.submitPublicFillLink('token-1', {
      answers: { full_name: 'Ada Lovelace' },
      recaptchaToken: 'token',
      recaptchaAction: 'fill_link_submit',
    });
    const retriedSigning = await ApiService.retryPublicFillLinkSigning('token-1', {
      responseId: 'resp-1',
    });
    const downloaded = await ApiService.downloadPublicFillLinkResponsePdf('token-1', 'resp-1', {
      downloadPath: '/api/fill-links/public/token-1/responses/resp-1/download',
    });

    expect(links[0].id).toBe('link-1');
    expect(created.id).toBe('link-1');
    expect(created.respondentPdfDownloadEnabled).toBe(true);
    expect(created.allowRespondentPdfDownload).toBe(true);
    expect(updated.status).toBe('active');
    expect(closed.status).toBe('closed');
    expect(responses.responses[0].id).toBe('resp-1');
    expect(response.id).toBe('resp-1');
    expect(publicLink.id).toBe('link-1');
    expect(publicLink.respondentPdfDownloadEnabled).toBe(true);
    expect(submitted.success).toBe(true);
    expect(submitted.responseDownloadAvailable).toBe(true);
    expect(submitted.responseDownloadPath).toBe('/api/fill-links/public/token-1/responses/resp-1/download');
    expect(retriedSigning.signing?.publicPath).toBe('/sign/sign-1');
    expect(downloaded.filename).toBe('submitted-link-1.pdf');

    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(1, 'GET', '/api/fill-links?templateId=tpl-1');
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(2, 'POST', '/api/fill-links', expect.objectContaining({
      headers: { 'Content-Type': 'application/json' },
      body: expect.any(String),
    }));
    expect(JSON.parse(String(apiConfigMocks.apiFetch.mock.calls[1][2]?.body))).toEqual({
      templateId: 'tpl-1',
      templateName: 'Template One',
      requireAllFields: true,
      respondentPdfDownloadEnabled: true,
      fields: [{ name: 'full_name', type: 'text', page: 1 }],
    });
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(3, 'PATCH', '/api/fill-links/link-1', expect.objectContaining({
      headers: { 'Content-Type': 'application/json' },
      body: expect.any(String),
    }));
    expect(JSON.parse(String(apiConfigMocks.apiFetch.mock.calls[2][2]?.body))).toEqual({
      status: 'active',
      requireAllFields: true,
      respondentPdfDownloadEnabled: true,
    });
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(4, 'POST', '/api/fill-links/link-1/close');
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(5, 'GET', '/api/fill-links/link-1/responses?search=ada&limit=25');
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(6, 'GET', '/api/fill-links/link-1/responses/resp-1');
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(7, 'GET', '/api/fill-links/public/token-1', {
      authMode: 'anonymous',
    });
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(8, 'POST', '/api/fill-links/public/token-1/submit', {
      authMode: 'anonymous',
      headers: { 'Content-Type': 'application/json' },
      body: expect.any(String),
    });
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(9, 'POST', '/api/fill-links/public/token-1/retry-signing', {
      authMode: 'anonymous',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ responseId: 'resp-1' }),
    });
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(10, 'GET', '/api/fill-links/public/token-1/responses/resp-1/download', {
      authMode: 'anonymous',
    });
    const publicSubmitBody = JSON.parse(String(apiConfigMocks.apiFetch.mock.calls[7][2]?.body));
    expect(publicSubmitBody).toMatchObject({
      answers: { full_name: 'Ada Lovelace' },
      recaptchaToken: 'token',
      recaptchaAction: 'fill_link_submit',
    });
    expect(publicSubmitBody.attemptId).toEqual(expect.any(String));
  });

  it('wires signing draft, detail, send, and public ceremony endpoints', async () => {
    apiConfigMocks.apiFetch
      .mockResolvedValueOnce({ id: 'signing-options-response' })
      .mockResolvedValueOnce({ id: 'signing-list-response' })
      .mockResolvedValueOnce({ id: 'signing-create-response' })
      .mockResolvedValueOnce({ id: 'signing-detail-response' })
      .mockResolvedValueOnce({ id: 'signing-artifacts-response' })
      .mockResolvedValueOnce({ id: 'signing-send-response' })
      .mockResolvedValueOnce({ id: 'signing-public-response' })
      .mockResolvedValueOnce({ id: 'signing-bootstrap-response' })
      .mockResolvedValueOnce({ id: 'signing-review-response' })
      .mockResolvedValueOnce({ id: 'signing-consent-response' })
      .mockResolvedValueOnce({ id: 'signing-fallback-response' })
      .mockResolvedValueOnce({ id: 'signing-adopt-response' })
      .mockResolvedValueOnce({ id: 'signing-complete-response' });

    apiConfigMocks.apiJsonFetch
      .mockResolvedValueOnce({
        modes: [{ key: 'sign', label: 'Sign' }],
        signatureModes: [{ key: 'business', label: 'Business' }],
        categories: [{ key: 'ordinary_business_form', label: 'Ordinary business form', blocked: false }],
      })
      .mockResolvedValueOnce({
        requests: [{ id: 'req-1', status: 'draft', publicPath: null, publicToken: null }],
      })
      .mockResolvedValueOnce({
        request: {
          id: 'req-1',
          status: 'draft',
          sourceDocumentName: 'Bravo Packet',
          publicPath: null,
          publicToken: null,
          anchors: [],
          documentCategory: 'ordinary_business_form',
          documentCategoryLabel: 'Ordinary business form',
          disclosureVersion: 'us-esign-business-v1',
          manualFallbackEnabled: true,
          mode: 'sign',
          signatureMode: 'business',
          signerEmail: 'alex@example.com',
          signerName: 'Alex Signer',
          sourceType: 'workspace',
          sourceLinkId: null,
          sourceRecordLabel: null,
          sourcePdfSha256: 'abc',
          sourceVersion: 'workspace:abc',
        },
      })
      .mockResolvedValueOnce({
        request: {
          id: 'req-1',
          status: 'draft',
          sourceDocumentName: 'Bravo Packet',
          publicPath: null,
          publicToken: null,
          anchors: [],
          documentCategory: 'ordinary_business_form',
          documentCategoryLabel: 'Ordinary business form',
          disclosureVersion: 'us-esign-business-v1',
          manualFallbackEnabled: true,
          mode: 'sign',
          signatureMode: 'business',
          signerEmail: 'alex@example.com',
          signerName: 'Alex Signer',
          sourceType: 'workspace',
          sourceLinkId: null,
          sourceRecordLabel: null,
        },
      })
      .mockResolvedValueOnce({
        requestId: 'req-1',
        retentionUntil: '2033-03-24T12:09:00Z',
        artifacts: {
          signedPdf: {
            available: true,
            downloadPath: '/api/signing/requests/req-1/artifacts/signed_pdf',
          },
          auditManifest: {
            available: true,
            downloadPath: '/api/signing/requests/req-1/artifacts/audit_manifest',
          },
          auditReceipt: {
            available: true,
            downloadPath: '/api/signing/requests/req-1/artifacts/audit_receipt',
          },
        },
      })
      .mockResolvedValueOnce({
        request: {
          id: 'req-1',
          status: 'sent',
          sourceDocumentName: 'Bravo Packet',
          publicPath: '/sign/token-1',
          publicToken: 'token-1',
          anchors: [],
          documentCategory: 'ordinary_business_form',
          documentCategoryLabel: 'Ordinary business form',
          disclosureVersion: 'us-esign-business-v1',
          manualFallbackEnabled: true,
          mode: 'sign',
          signatureMode: 'business',
          signerEmail: 'alex@example.com',
          signerName: 'Alex Signer',
          sourceType: 'workspace',
          sourceLinkId: null,
          sourceRecordLabel: null,
          sourcePdfSha256: 'def',
          sourceVersion: 'workspace:def',
          sourcePdfPath: 'gs://signing/path.pdf',
        },
      })
      .mockResolvedValueOnce({
        request: {
          id: 'req-1',
          status: 'sent',
          statusMessage: 'This signing request is ready for review and signature.',
          sourceDocumentName: 'Bravo Packet',
          signerName: 'Alex Signer',
          anchors: [],
          documentCategory: 'ordinary_business_form',
          documentCategoryLabel: 'Ordinary business form',
          disclosureVersion: 'us-esign-business-v1',
          manualFallbackEnabled: true,
          mode: 'sign',
          signatureMode: 'business',
          sourcePdfSha256: 'def',
          sourceVersion: 'workspace:def',
          documentPath: '/api/signing/public/token-1/document',
        },
      })
      .mockResolvedValueOnce({
        request: {
          id: 'req-1',
          status: 'sent',
          statusMessage: 'This signing request is ready for review and signature.',
          sourceDocumentName: 'Bravo Packet',
          signerName: 'Alex Signer',
          anchors: [],
          documentCategory: 'ordinary_business_form',
          documentCategoryLabel: 'Ordinary business form',
          disclosureVersion: 'us-esign-business-v1',
          manualFallbackEnabled: true,
          mode: 'sign',
          signatureMode: 'business',
          sourcePdfSha256: 'def',
          sourceVersion: 'workspace:def',
          documentPath: '/api/signing/public/token-1/document',
        },
        session: {
          id: 'session-1',
          token: 'session-token-1',
          expiresAt: '2026-03-24T12:30:00Z',
        },
      })
      .mockResolvedValueOnce({
        request: {
          id: 'req-1',
          status: 'sent',
          statusMessage: 'This signing request is ready for review and signature.',
          sourceDocumentName: 'Bravo Packet',
          signerName: 'Alex Signer',
          anchors: [],
          documentCategory: 'ordinary_business_form',
          documentCategoryLabel: 'Ordinary business form',
          disclosureVersion: 'us-esign-business-v1',
          manualFallbackEnabled: true,
          mode: 'sign',
          signatureMode: 'business',
          reviewedAt: '2026-03-24T12:05:00Z',
          documentPath: '/api/signing/public/token-1/document',
        },
      })
      .mockResolvedValueOnce({
        request: {
          id: 'req-2',
          status: 'sent',
          statusMessage: 'This signing request is ready for review and signature.',
          sourceDocumentName: 'Consumer Packet',
          signerName: 'Pat Consumer',
          anchors: [],
          documentCategory: 'authorization_consent_form',
          documentCategoryLabel: 'Authorization or consent form',
          disclosureVersion: 'us-esign-consumer-v1',
          manualFallbackEnabled: true,
          mode: 'sign',
          signatureMode: 'consumer',
          consentedAt: '2026-03-24T12:06:00Z',
          documentPath: '/api/signing/public/token-2/document',
        },
      })
      .mockResolvedValueOnce({
        request: {
          id: 'req-1',
          status: 'sent',
          statusMessage: 'This signing request is ready for review and signature.',
          sourceDocumentName: 'Bravo Packet',
          signerName: 'Alex Signer',
          anchors: [],
          documentCategory: 'ordinary_business_form',
          documentCategoryLabel: 'Ordinary business form',
          disclosureVersion: 'us-esign-business-v1',
          manualFallbackEnabled: true,
          mode: 'sign',
          signatureMode: 'business',
          manualFallbackRequestedAt: '2026-03-24T12:07:00Z',
          documentPath: '/api/signing/public/token-1/document',
        },
      })
      .mockResolvedValueOnce({
        request: {
          id: 'req-1',
          status: 'sent',
          statusMessage: 'This signing request is ready for review and signature.',
          sourceDocumentName: 'Bravo Packet',
          signerName: 'Alex Signer',
          anchors: [],
          documentCategory: 'ordinary_business_form',
          documentCategoryLabel: 'Ordinary business form',
          disclosureVersion: 'us-esign-business-v1',
          manualFallbackEnabled: true,
          mode: 'sign',
          signatureMode: 'business',
          signatureAdoptedAt: '2026-03-24T12:08:00Z',
          signatureAdoptedName: 'Alex Signer',
          documentPath: '/api/signing/public/token-1/document',
        },
      })
      .mockResolvedValueOnce({
        request: {
          id: 'req-1',
          status: 'completed',
          statusMessage: 'This signing request has already been completed.',
          sourceDocumentName: 'Bravo Packet',
          signerName: 'Alex Signer',
          anchors: [],
          documentCategory: 'ordinary_business_form',
          documentCategoryLabel: 'Ordinary business form',
          disclosureVersion: 'us-esign-business-v1',
          manualFallbackEnabled: true,
          mode: 'sign',
          signatureMode: 'business',
          completedAt: '2026-03-24T12:09:00Z',
          documentPath: '/api/signing/public/token-1/document',
        },
      });

    const options = await ApiService.getSigningOptions();
    const requests = await ApiService.getSigningRequests();
    const created = await ApiService.createSigningRequest({
      title: 'Bravo Packet Signature Request',
      mode: 'sign',
      signatureMode: 'business',
      sourceType: 'workspace',
      sourceId: 'form-1',
      sourceLinkId: 'link-1',
      sourceRecordLabel: 'Ada Lovelace',
      sourceDocumentName: 'Bravo Packet',
      sourceTemplateId: 'form-1',
      sourceTemplateName: 'Bravo Packet',
      sourcePdfSha256: 'abc',
      documentCategory: 'ordinary_business_form',
      manualFallbackEnabled: true,
      signerName: 'Alex Signer',
      signerEmail: 'alex@example.com',
      anchors: [],
    });
    const detail = await ApiService.getSigningRequest('req-1');
    const artifactSummary = await ApiService.getSigningRequestArtifacts('req-1');
    const sent = await ApiService.sendSigningRequest('req-1', {
      pdf: new Blob(['pdf'], { type: 'application/pdf' }),
      filename: 'bravo.pdf',
      sourcePdfSha256: 'def',
      ownerReviewConfirmed: true,
    });
    const publicRequest = await ApiService.getPublicSigningRequest('token-1');
    const bootstrap = await ApiService.startPublicSigningSession('token-1');
    const reviewed = await ApiService.reviewPublicSigningRequest('token-1', 'session-token-1');
    const consented = await ApiService.consentPublicSigningRequest('token-2', 'session-token-2');
    const fallback = await ApiService.requestPublicSigningManualFallback('token-1', 'session-token-1', 'Need paper');
    const adopted = await ApiService.adoptPublicSigningSignature('token-1', 'session-token-1', 'Alex Signer');
    const completed = await ApiService.completePublicSigningRequest('token-1', 'session-token-1');

    expect(options.modes[0].key).toBe('sign');
    expect(requests[0].id).toBe('req-1');
    expect(created.sourceVersion).toBe('workspace:abc');
    expect(detail.id).toBe('req-1');
    expect(artifactSummary.artifacts.auditManifest?.available).toBe(true);
    expect(sent.status).toBe('sent');
    expect(sent.sourcePdfPath).toBe('gs://signing/path.pdf');
    expect(publicRequest.sourceVersion).toBe('workspace:def');
    expect(bootstrap.session?.token).toBe('session-token-1');
    expect(reviewed.reviewedAt).toBe('2026-03-24T12:05:00Z');
    expect(consented.consentedAt).toBe('2026-03-24T12:06:00Z');
    expect(fallback.manualFallbackRequestedAt).toBe('2026-03-24T12:07:00Z');
    expect(adopted.signatureAdoptedName).toBe('Alex Signer');
    expect(completed.status).toBe('completed');

    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(1, 'GET', '/api/signing/options');
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(2, 'GET', '/api/signing/requests');
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(3, 'POST', '/api/signing/requests', expect.objectContaining({
      headers: { 'Content-Type': 'application/json' },
      body: expect.any(String),
    }));
    expect(JSON.parse(String(apiConfigMocks.apiFetch.mock.calls[2][2]?.body))).toEqual({
      title: 'Bravo Packet Signature Request',
      mode: 'sign',
      signatureMode: 'business',
      sourceType: 'workspace',
      sourceId: 'form-1',
      sourceLinkId: 'link-1',
      sourceRecordLabel: 'Ada Lovelace',
      sourceDocumentName: 'Bravo Packet',
      sourceTemplateId: 'form-1',
      sourceTemplateName: 'Bravo Packet',
      sourcePdfSha256: 'abc',
      documentCategory: 'ordinary_business_form',
      manualFallbackEnabled: true,
      signerName: 'Alex Signer',
      signerEmail: 'alex@example.com',
      anchors: [],
    });
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(4, 'GET', '/api/signing/requests/req-1');
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(5, 'GET', '/api/signing/requests/req-1/artifacts');
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(6, 'POST', '/api/signing/requests/req-1/send', expect.objectContaining({
      body: expect.any(FormData),
    }));
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(7, 'GET', '/api/signing/public/token-1', {
      authMode: 'anonymous',
    });
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(8, 'POST', '/api/signing/public/token-1/bootstrap', {
      authMode: 'anonymous',
    });
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(9, 'POST', '/api/signing/public/token-1/review', {
      authMode: 'anonymous',
      headers: {
        'Content-Type': 'application/json',
        'X-Signing-Session': 'session-token-1',
      },
      body: JSON.stringify({ reviewConfirmed: true }),
    });
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(10, 'POST', '/api/signing/public/token-2/consent', {
      authMode: 'anonymous',
      headers: {
        'Content-Type': 'application/json',
        'X-Signing-Session': 'session-token-2',
      },
      body: JSON.stringify({ accepted: true }),
    });
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(11, 'POST', '/api/signing/public/token-1/manual-fallback', {
      authMode: 'anonymous',
      headers: {
        'Content-Type': 'application/json',
        'X-Signing-Session': 'session-token-1',
      },
      body: JSON.stringify({ note: 'Need paper' }),
    });
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(12, 'POST', '/api/signing/public/token-1/adopt-signature', {
      authMode: 'anonymous',
      headers: {
        'Content-Type': 'application/json',
        'X-Signing-Session': 'session-token-1',
      },
      body: JSON.stringify({ adoptedName: 'Alex Signer' }),
    });
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(13, 'POST', '/api/signing/public/token-1/complete', {
      authMode: 'anonymous',
      headers: {
        'Content-Type': 'application/json',
        'X-Signing-Session': 'session-token-1',
      },
      body: JSON.stringify({ intentConfirmed: true }),
    });
    const sendForm = apiConfigMocks.apiFetch.mock.calls[5][2]?.body as FormData;
    expect(sendForm.get('sourcePdfSha256')).toBe('def');
    expect(sendForm.get('ownerReviewConfirmed')).toBe('true');
    const sendFile = sendForm.get('pdf');
    expect(sendFile).toBeTruthy();
  });

  it('wires group-scoped Fill By Link owner endpoints', async () => {
    apiConfigMocks.apiFetch
      .mockResolvedValueOnce({ id: 'group-fill-links-response' })
      .mockResolvedValueOnce({ id: 'group-fill-link-create-response' })
      .mockResolvedValueOnce({ id: 'group-fill-link-update-response' });

    apiConfigMocks.apiJsonFetch
      .mockResolvedValueOnce({ links: [{ id: 'group-link-1', scopeType: 'group', groupId: 'group-1' }] })
      .mockResolvedValueOnce({ link: { id: 'group-link-1', scopeType: 'group', groupId: 'group-1' } })
      .mockResolvedValueOnce({ link: { id: 'group-link-1', status: 'active', scopeType: 'group' } });

    const links = await ApiService.getFillLinks({ groupId: 'group-1', scopeType: 'group' });
    const created = await ApiService.createFillLink({
      scopeType: 'group',
      groupId: 'group-1',
      groupName: 'Admissions Packet',
      requireAllFields: true,
      fields: [],
      groupTemplates: [
        {
          templateId: 'tpl-1',
          templateName: 'Template One',
          fields: [{ name: 'full_name', type: 'text', page: 1 }],
          checkboxRules: [],
        },
      ],
    });
    const updated = await ApiService.updateFillLink('group-link-1', {
      groupName: 'Admissions Packet',
      status: 'active',
      groupTemplates: [
        {
          templateId: 'tpl-1',
          templateName: 'Template One',
          fields: [{ name: 'full_name', type: 'text', page: 1 }],
          checkboxRules: [],
        },
      ],
    });

    expect(links[0].groupId).toBe('group-1');
    expect(created.scopeType).toBe('group');
    expect(updated.status).toBe('active');

    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(1, 'GET', '/api/fill-links?groupId=group-1&scopeType=group');
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(2, 'POST', '/api/fill-links', {
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        scopeType: 'group',
        groupId: 'group-1',
        groupName: 'Admissions Packet',
        requireAllFields: true,
        fields: [],
        groupTemplates: [
          {
            templateId: 'tpl-1',
            templateName: 'Template One',
            fields: [{ name: 'full_name', type: 'text', page: 1 }],
            checkboxRules: [],
          },
        ],
      }),
    });
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(3, 'PATCH', '/api/fill-links/group-link-1', {
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        groupName: 'Admissions Packet',
        status: 'active',
        groupTemplates: [
          {
            templateId: 'tpl-1',
            templateName: 'Template One',
            fields: [{ name: 'full_name', type: 'text', page: 1 }],
            checkboxRules: [],
          },
        ],
      }),
    });
  });

  it('wires group list, create, update, fetch, and delete endpoints', async () => {
    const signal = new AbortController().signal;
    apiConfigMocks.apiFetch
      .mockResolvedValueOnce({ status: 401 })
      .mockResolvedValueOnce({ id: 'group-create-response' })
      .mockResolvedValueOnce({ id: 'group-update-response' })
      .mockResolvedValueOnce({ id: 'group-detail-response' })
      .mockResolvedValueOnce({ id: 'group-delete-response' });
    apiConfigMocks.apiJsonFetch
      .mockResolvedValueOnce({ group: { id: 'group-1', name: 'Admissions', templateIds: ['tpl-1'] } })
      .mockResolvedValueOnce({ group: { id: 'group-1', name: 'Admissions Updated', templateIds: ['tpl-1', 'tpl-2'] } })
      .mockResolvedValueOnce({ group: { id: 'group-1', name: 'Admissions Updated', templateIds: ['tpl-1', 'tpl-2'] } })
      .mockResolvedValueOnce({ success: true });

    const groups = await ApiService.getGroups();
    const created = await ApiService.createGroup({ name: 'Admissions', templateIds: ['tpl-1'] }, { signal });
    const updated = await ApiService.updateGroup('group-1', {
      name: 'Admissions Updated',
      templateIds: ['tpl-1', 'tpl-2'],
    });
    const detail = await ApiService.getGroup('group-1');
    const deleted = await ApiService.deleteGroup('group-1');

    expect(groups).toEqual([]);
    expect(created.id).toBe('group-1');
    expect(updated.name).toBe('Admissions Updated');
    expect(detail.id).toBe('group-1');
    expect(deleted.success).toBe(true);

    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(1, 'GET', '/api/groups', {
      allowStatuses: [401],
    });
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(2, 'POST', '/api/groups', {
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'Admissions', templateIds: ['tpl-1'] }),
      signal,
    });
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(3, 'PATCH', '/api/groups/group-1', {
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'Admissions Updated', templateIds: ['tpl-1', 'tpl-2'] }),
    });
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(4, 'GET', '/api/groups/group-1');
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(5, 'DELETE', '/api/groups/group-1');
  });

  it('creates billing checkout sessions with supported kinds', async () => {
    apiConfigMocks.apiFetch
      .mockResolvedValueOnce({ id: 'billing-response' })
      .mockResolvedValueOnce({ id: 'reconcile-response' })
      .mockResolvedValueOnce({ id: 'cancel-response' });
    apiConfigMocks.apiJsonFetch.mockResolvedValueOnce({
      success: true,
      kind: 'pro_yearly',
      sessionId: 'cs_123',
      checkoutUrl: 'https://checkout.local/session',
      attemptId: 'attempt_123',
      checkoutPriceId: 'price_yearly_123',
    }).mockResolvedValueOnce({
      success: true,
      dryRun: false,
      scope: 'self',
      auditedEventCount: 1,
      candidateEventCount: 1,
      pendingReconciliationCount: 1,
      reconciledCount: 1,
      alreadyProcessedCount: 0,
      processingCount: 0,
      retryableCount: 0,
      failedCount: 0,
      invalidCount: 0,
      skippedForUserCount: 0,
      events: [{
        eventId: 'evt_1',
        checkoutSessionId: 'cs_123',
        checkoutAttemptId: 'attempt_123',
        checkoutKind: 'pro_yearly',
        checkoutPriceId: 'price_yearly_123',
      }],
    }).mockResolvedValueOnce({
      success: true,
      subscriptionId: 'sub_123',
      status: 'active',
      cancelAtPeriodEnd: true,
    });

    const response = await ApiService.createBillingCheckoutSession('pro_yearly');
    const reconcileResponse = await ApiService.reconcileBillingCheckoutFulfillment({ lookbackHours: 24 });
    const cancelResponse = await ApiService.cancelBillingSubscription();

    expect(response.success).toBe(true);
    expect(response.kind).toBe('pro_yearly');
    expect(response.checkoutUrl).toBe('https://checkout.local/session');
    expect(response.attemptId).toBe('attempt_123');
    expect(response.checkoutPriceId).toBe('price_yearly_123');
    expect(reconcileResponse.success).toBe(true);
    expect(reconcileResponse.reconciledCount).toBe(1);
    expect(reconcileResponse.events[0].checkoutAttemptId).toBe('attempt_123');
    expect(cancelResponse.success).toBe(true);
    expect(cancelResponse.subscriptionId).toBe('sub_123');
    expect(cancelResponse.cancelAtPeriodEnd).toBe(true);
    expect(apiConfigMocks.apiFetch).toHaveBeenCalledWith('POST', '/api/billing/checkout-session', {
      headers: { 'Content-Type': 'application/json' },
      body: expect.any(String),
    });
    const billingPayload = JSON.parse(String(apiConfigMocks.apiFetch.mock.calls[0][2]?.body));
    expect(billingPayload.kind).toBe('pro_yearly');
    expect(typeof billingPayload.attemptId).toBe('string');
    expect(billingPayload.attemptId.length).toBeGreaterThan(0);
    expect(apiConfigMocks.apiFetch).toHaveBeenCalledWith('POST', '/api/billing/reconcile', {
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        lookbackHours: 24,
        maxEvents: undefined,
        dryRun: undefined,
      }),
    });
    expect(apiConfigMocks.apiFetch).toHaveBeenCalledWith('POST', '/api/billing/subscription/cancel');
  });

  it('wires rename/map endpoints and payload shape through buildApiUrl', async () => {
    apiConfigMocks.apiFetch
      .mockResolvedValueOnce({ id: 'rename-response' })
      .mockResolvedValueOnce({ id: 'map-response' });
    apiConfigMocks.apiJsonFetch
      .mockResolvedValueOnce({ renamed: true })
      .mockResolvedValueOnce({ mapped: true });

    await ApiService.renameFields({
      sessionId: 'sess-1',
      schemaId: 'schema-1',
      templateFields: [{ name: 'First Name', type: 'text' }],
    });

    await ApiService.mapSchema(
      'schema-1',
      [{ name: 'First Name', type: 'text' }],
      'template-1',
      'sess-1',
    );

    expect(apiConfigMocks.buildApiUrl).toHaveBeenCalledWith('api', 'renames', 'ai');
    expect(apiConfigMocks.buildApiUrl).toHaveBeenCalledWith('api', 'schema-mappings', 'ai');

    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(1, 'POST', 'https://api.local/api/renames/ai', {
      headers: { 'Content-Type': 'application/json' },
      body: expect.any(String),
    });

    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(2, 'POST', 'https://api.local/api/schema-mappings/ai', {
      headers: { 'Content-Type': 'application/json' },
      body: expect.any(String),
    });

    const renameBody = JSON.parse(String(apiConfigMocks.apiFetch.mock.calls[0][2]?.body));
    const mapBody = JSON.parse(String(apiConfigMocks.apiFetch.mock.calls[1][2]?.body));
    expect(renameBody).toMatchObject({
      sessionId: 'sess-1',
      schemaId: 'schema-1',
      templateFields: [{ name: 'First Name', type: 'text' }],
    });
    expect(renameBody.requestId).toEqual(expect.any(String));
    expect(mapBody).toMatchObject({
      schemaId: 'schema-1',
      templateId: 'template-1',
      templateFields: [{ name: 'First Name', type: 'text' }],
      sessionId: 'sess-1',
    });
    expect(mapBody.requestId).toEqual(expect.any(String));
    expect(mapBody.requestId).not.toBe(renameBody.requestId);
  });

  it('clears cached request ids after abort-like transport failures so retries start fresh OpenAI jobs', async () => {
    const timeoutError = new TypeError('Request timed out.');
    apiConfigMocks.apiFetch
      .mockRejectedValueOnce(timeoutError)
      .mockResolvedValueOnce({ id: 'rename-response' })
      .mockRejectedValueOnce(timeoutError)
      .mockResolvedValueOnce({ id: 'map-response' });
    apiConfigMocks.apiJsonFetch
      .mockResolvedValueOnce({ renamed: true })
      .mockResolvedValueOnce({ mapped: true });

    await expect(ApiService.renameFields({
      sessionId: 'sess-1',
      templateFields: [{ name: 'First Name', type: 'text' }],
    })).rejects.toThrow('Request timed out.');

    await ApiService.renameFields({
      sessionId: 'sess-1',
      templateFields: [{ name: 'First Name', type: 'text' }],
    });

    await expect(ApiService.mapSchema(
      'schema-1',
      [{ name: 'First Name', type: 'text' }],
      'template-1',
      'sess-1',
    )).rejects.toThrow('Request timed out.');

    await ApiService.mapSchema(
      'schema-1',
      [{ name: 'First Name', type: 'text' }],
      'template-1',
      'sess-1',
    );

    const renameBody1 = JSON.parse(String(apiConfigMocks.apiFetch.mock.calls[0][2]?.body));
    const renameBody2 = JSON.parse(String(apiConfigMocks.apiFetch.mock.calls[1][2]?.body));
    const mapBody1 = JSON.parse(String(apiConfigMocks.apiFetch.mock.calls[2][2]?.body));
    const mapBody2 = JSON.parse(String(apiConfigMocks.apiFetch.mock.calls[3][2]?.body));

    expect(renameBody2.requestId).not.toBe(renameBody1.requestId);
    expect(mapBody2.requestId).not.toBe(mapBody1.requestId);
    expect(mapBody1.requestId).not.toBe(renameBody1.requestId);
  });

  it('polls queued OpenAI jobs until completion for rename and mapping calls', async () => {
    const signal = new AbortController().signal;
    apiConfigMocks.apiFetch
      .mockResolvedValueOnce({ id: 'rename-enqueue' })
      .mockResolvedValueOnce({ id: 'rename-status-complete' })
      .mockResolvedValueOnce({ id: 'map-enqueue' })
      .mockResolvedValueOnce({ id: 'map-status-complete' });

    apiConfigMocks.apiJsonFetch
      .mockResolvedValueOnce({ status: 'queued', jobId: 'rename-job-1' })
      .mockResolvedValueOnce({
        status: 'complete',
        result: { success: true, fields: [{ name: 'first_name' }], checkboxRules: [] },
      })
      .mockResolvedValueOnce({ status: 'queued', jobId: 'map-job-1' })
      .mockResolvedValueOnce({
        status: 'complete',
        result: { success: true, mappingResults: { mappings: [{ pdfField: 'first_name' }] } },
      });

    const rename = await ApiService.renameFields({
      sessionId: 'sess-1',
      templateFields: [{ name: 'First Name', type: 'text' }],
    }, { signal });
    const mapping = await ApiService.mapSchema(
      'schema-1',
      [{ name: 'First Name', type: 'text' }],
      undefined,
      'sess-1',
      { signal },
    );

    expect(rename.fields).toEqual([{ name: 'first_name' }]);
    expect(mapping.mappingResults.mappings).toHaveLength(1);

    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(
      1,
      'POST',
      'https://api.local/api/renames/ai',
      {
        headers: { 'Content-Type': 'application/json' },
        body: expect.any(String),
        signal,
      },
    );
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(
      2,
      'GET',
      'https://api.local/api/renames/ai/rename-job-1',
      { signal },
    );
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(
      3,
      'POST',
      'https://api.local/api/schema-mappings/ai',
      {
        headers: { 'Content-Type': 'application/json' },
        body: expect.any(String),
        signal,
      },
    );
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(
      4,
      'GET',
      'https://api.local/api/schema-mappings/ai/map-job-1',
      { signal },
    );

    const renameBody = JSON.parse(String(apiConfigMocks.apiFetch.mock.calls[0][2]?.body));
    const mapBody = JSON.parse(String(apiConfigMocks.apiFetch.mock.calls[2][2]?.body));
    expect(renameBody.requestId).toEqual(expect.any(String));
    expect(mapBody.requestId).toEqual(expect.any(String));
  });

  it('clears cached request ids after a queued OpenAI job fails so the next retry starts fresh', async () => {
    apiConfigMocks.apiFetch
      .mockResolvedValueOnce({ id: 'rename-enqueue-1' })
      .mockResolvedValueOnce({ id: 'rename-status-failed' })
      .mockResolvedValueOnce({ id: 'rename-enqueue-2' });
    apiConfigMocks.apiJsonFetch
      .mockResolvedValueOnce({ status: 'queued', jobId: 'rename-job-1' })
      .mockResolvedValueOnce({ status: 'failed', error: 'Worker failed.' })
      .mockResolvedValueOnce({ renamed: true });

    await expect(ApiService.renameFields({
      sessionId: 'sess-1',
      templateFields: [{ name: 'First Name', type: 'text' }],
    })).rejects.toThrow('Worker failed.');

    await ApiService.renameFields({
      sessionId: 'sess-1',
      templateFields: [{ name: 'First Name', type: 'text' }],
    });

    const renameBody1 = JSON.parse(String(apiConfigMocks.apiFetch.mock.calls[0][2]?.body));
    const renameBody2 = JSON.parse(String(apiConfigMocks.apiFetch.mock.calls[2][2]?.body));
    expect(renameBody2.requestId).not.toBe(renameBody1.requestId);
  });

  it('handles saved-form list/load/download/delete/session/touch operations', async () => {
    apiConfigMocks.apiFetch
      .mockResolvedValueOnce({ status: 200, id: 'saved-forms' })
      .mockResolvedValueOnce({ status: 200, id: 'load-saved' })
      .mockResolvedValueOnce({ ok: true, blob: vi.fn().mockResolvedValue(new Blob(['pdf'])) })
      .mockResolvedValueOnce({ status: 200, id: 'create-saved-session' })
      .mockResolvedValueOnce({ status: 200, id: 'touch-session' })
      .mockResolvedValueOnce({ status: 200, id: 'update-saved-editor-snapshot' })
      .mockResolvedValueOnce({ status: 200, id: 'delete-saved' });

    apiConfigMocks.apiJsonFetch
      .mockResolvedValueOnce({ forms: [{ id: 'f-1', name: 'A', createdAt: '2026-01-01' }] })
      .mockResolvedValueOnce({
        id: 'f-1',
        name: 'A',
        url: 'https://file.local/a.pdf',
        editorSnapshot: {
          version: 1,
          pageCount: 1,
          pageSizes: { 1: { width: 612, height: 792 } },
          fields: [],
          hasRenamedFields: false,
          hasMappedSchema: false,
        },
      })
      .mockResolvedValueOnce({ success: true, sessionId: 'sess-1', fieldCount: 1 })
      .mockResolvedValueOnce({ success: true, sessionId: 'sess-1' })
      .mockResolvedValueOnce({ success: true })
      .mockResolvedValueOnce({ success: true });

    const savedForms = await ApiService.getSavedForms({ suppressErrors: false, timeoutMs: 3210 });
    const loaded = await ApiService.loadSavedForm('form id/with spaces');
    const blob = await ApiService.downloadSavedForm('form id/with spaces');
    const session = await ApiService.createSavedFormSession('form id/with spaces', {
      fields: [{ name: 'first_name' }],
      pageCount: 2,
    });
    const touched = await ApiService.touchSession('session / id');
    const updatedSnapshot = await ApiService.updateSavedFormEditorSnapshot('form id/with spaces', {
      version: 1,
      pageCount: 1,
      pageSizes: { 1: { width: 612, height: 792 } },
      fields: [],
      hasRenamedFields: false,
      hasMappedSchema: false,
    });
    const deleted = await ApiService.deleteSavedForm('form id/with spaces');

    expect(savedForms).toHaveLength(1);
    expect(loaded.id).toBe('f-1');
    expect(blob).toBeInstanceOf(Blob);
    expect(session.sessionId).toBe('sess-1');
    expect(touched.success).toBe(true);
    expect(updatedSnapshot.success).toBe(true);
    expect(deleted.success).toBe(true);

    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(1, 'GET', '/api/saved-forms', {
      allowStatuses: [401],
      timeoutMs: 3210,
    });
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(
      2,
      'GET',
      '/api/saved-forms/form%20id%2Fwith%20spaces',
      {
        signal: undefined,
        timeoutMs: undefined,
      },
    );
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(
      3,
      'GET',
      'https://api.local/api/saved-forms/form id/with spaces/download',
      {
        signal: undefined,
        timeoutMs: undefined,
      },
    );
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(
      4,
      'POST',
      '/api/saved-forms/form%20id%2Fwith%20spaces/session',
      {
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fields: [{ name: 'first_name' }], pageCount: 2 }),
      },
    );
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(
      5,
      'POST',
      '/api/sessions/session%20%2F%20id/touch',
    );
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(
      6,
      'PATCH',
      '/api/saved-forms/form%20id%2Fwith%20spaces/editor-snapshot',
      {
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          snapshot: {
            version: 1,
            pageCount: 1,
            pageSizes: { 1: { width: 612, height: 792 } },
            fields: [],
            hasRenamedFields: false,
            hasMappedSchema: false,
          },
        }),
      },
    );
    expect(apiConfigMocks.apiFetch).toHaveBeenNthCalledWith(
      7,
      'DELETE',
      '/api/saved-forms/form%20id%2Fwith%20spaces',
    );
  });

  it('builds FormData payloads for template sessions and save/materialize flows', async () => {
    const signal = new AbortController().signal;
    apiConfigMocks.apiFetch
      .mockResolvedValueOnce({ id: 'template-session' })
      .mockResolvedValueOnce({ id: 'save-form' })
      .mockResolvedValueOnce({ ok: true, blob: vi.fn().mockResolvedValue(new Blob(['fillable'])) });

    apiConfigMocks.apiJsonFetch
      .mockResolvedValueOnce({ success: true, sessionId: 'tmpl-1', fieldCount: 2 })
      .mockResolvedValueOnce({ success: true, id: 'saved-1', name: 'My Saved Form' });

    const templateFile = new File(['pdf'], 'template.pdf', { type: 'application/pdf' });
    const sourceBlob = new Blob(['pdf'], { type: 'application/pdf' });

    const templateSession = await ApiService.createTemplateSession(templateFile, {
      fields: [{ name: 'first_name' }, { name: 'last_name' }],
      pageCount: 3,
    }, { signal });

    const saved = await ApiService.saveFormToProfile(
      sourceBlob,
      'Patient Intake',
      'sess-99',
      'overwrite-1',
      [{ fieldName: 'insurance_opt_in' }],
      [{ targetField: 'insurance_name', operation: 'copy', sources: ['insurance_name'] }],
      {
        version: 1,
        pageCount: 1,
        pageSizes: { 1: { width: 612, height: 792 } },
        fields: [],
        hasRenamedFields: false,
        hasMappedSchema: false,
      },
      { signal },
    );

    const materialized = await ApiService.materializeFormPdf(sourceBlob, [
      {
        id: 'f-1',
        name: 'First Name',
        type: 'text',
        page: 1,
        rect: { x: 0, y: 0, width: 10, height: 10 },
        value: 'Alex',
      },
    ] as any, { signal });

    expect(templateSession.success).toBe(true);
    expect(saved.id).toBe('saved-1');
    expect(materialized).toBeInstanceOf(Blob);

    const templateBody = apiConfigMocks.apiFetch.mock.calls[0][2].body as FormData;
    expect(templateBody).toBeInstanceOf(FormData);
    expect((templateBody.get('pdf') as File).name).toBe('template.pdf');
    expect(templateBody.get('fields')).toBe(
      JSON.stringify({ fields: [{ name: 'first_name' }, { name: 'last_name' }] }),
    );
    expect(templateBody.get('pageCount')).toBe('3');
    expect(apiConfigMocks.apiFetch.mock.calls[0][2]).toMatchObject({ signal });

    const saveBody = apiConfigMocks.apiFetch.mock.calls[1][2].body as FormData;
    expect((saveBody.get('pdf') as File).name).toBe('Patient Intake.pdf');
    expect(saveBody.get('name')).toBe('Patient Intake');
    expect(saveBody.get('sessionId')).toBe('sess-99');
    expect(saveBody.get('overwriteFormId')).toBe('overwrite-1');
    expect(saveBody.get('checkboxRules')).toBe(JSON.stringify([{ fieldName: 'insurance_opt_in' }]));
    expect(saveBody.get('checkboxHints')).toBeNull();
    expect(saveBody.get('textTransformRules')).toBe(JSON.stringify([
      { targetField: 'insurance_name', operation: 'copy', sources: ['insurance_name'] },
    ]));
    expect(saveBody.get('editorSnapshot')).toBe(JSON.stringify({
      version: 1,
      pageCount: 1,
      pageSizes: { 1: { width: 612, height: 792 } },
      fields: [],
      hasRenamedFields: false,
      hasMappedSchema: false,
    }));
    expect(apiConfigMocks.apiFetch.mock.calls[1][2]).toMatchObject({ signal });

    const materializeBody = apiConfigMocks.apiFetch.mock.calls[2][2].body as FormData;
    expect((materializeBody.get('pdf') as File).name).toBe('form.pdf');
    expect(materializeBody.get('fields')).toBe(
      JSON.stringify({
        fields: [
          {
            id: 'f-1',
            name: 'First Name',
            type: 'text',
            page: 1,
            rect: { x: 0, y: 0, width: 10, height: 10 },
            value: 'Alex',
          },
        ],
      }),
    );
    expect(apiConfigMocks.apiFetch.mock.calls[2][2]).toMatchObject({ signal });
  });

  it('throws clear errors for non-ok blob endpoints', async () => {
    apiConfigMocks.apiFetch
      .mockResolvedValueOnce({ ok: false, statusText: 'Forbidden' })
      .mockResolvedValueOnce({ ok: false, statusText: 'Unprocessable Entity' });

    await expect(ApiService.downloadSavedForm('x')).rejects.toThrow(
      'Failed to download saved form: Forbidden',
    );

    await expect(
      ApiService.materializeFormPdf(new Blob(['pdf']), [
        {
          id: 'f-1',
          name: 'x',
          type: 'text',
          page: 1,
          rect: { x: 0, y: 0, width: 1, height: 1 },
        },
      ] as any),
    ).rejects.toThrow('Failed to generate fillable PDF: Unprocessable Entity');
  });
});
