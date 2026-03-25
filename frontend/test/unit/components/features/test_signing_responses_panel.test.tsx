import { beforeEach, describe, expect, it, vi } from 'vitest';
import userEvent from '@testing-library/user-event';
import { render, screen } from '@testing-library/react';

import { SigningResponsesPanel } from '../../../../src/components/features/SigningResponsesPanel';
import { ApiService } from '../../../../src/services/api';

function buildRequest(overrides: Record<string, unknown> = {}) {
  return {
    id: 'req-1',
    title: 'Bravo Packet Signature Request',
    mode: 'fill_and_sign',
    signatureMode: 'business',
    sourceType: 'fill_link_response',
    sourceId: 'resp-1',
    sourceLinkId: 'link-1',
    sourceRecordLabel: 'Ada Lovelace',
    sourceDocumentName: 'Bravo Packet',
    sourceTemplateId: 'tpl-1',
    sourceTemplateName: 'Bravo Template',
    sourcePdfSha256: 'a'.repeat(64),
    sourceVersion: 'fill_link_response:resp-1:aaaaaaaaaaaa',
    documentCategory: 'client_intake_form',
    documentCategoryLabel: 'Client intake form',
    manualFallbackEnabled: true,
    signerName: 'Ada Lovelace',
    signerEmail: 'ada@example.com',
    inviteDeliveryStatus: 'sent',
    inviteLastAttemptAt: '2026-03-24T12:02:00Z',
    inviteSentAt: '2026-03-24T12:02:00Z',
    inviteDeliveryError: null,
    status: 'completed',
    anchors: [],
    disclosureVersion: 'us-esign-business-v1',
    createdAt: '2026-03-24T12:00:00Z',
    updatedAt: '2026-03-24T12:05:00Z',
    ownerReviewConfirmedAt: '2026-03-24T12:01:00Z',
    sentAt: '2026-03-24T12:02:00Z',
    completedAt: '2026-03-24T12:05:00Z',
    invalidatedAt: null,
    invalidationReason: null,
    retentionUntil: null,
    publicToken: 'token-1',
    publicPath: '/sign/token-1',
    artifacts: {
      sourcePdf: {
        available: true,
        downloadPath: '/api/signing/requests/req-1/artifacts/source_pdf',
      },
      signedPdf: {
        available: true,
        downloadPath: '/api/signing/requests/req-1/artifacts/signed_pdf',
      },
      auditReceipt: {
        available: true,
        downloadPath: '/api/signing/requests/req-1/artifacts/audit_receipt',
      },
    },
    ...overrides,
  };
}

describe('SigningResponsesPanel', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: {
        writeText: vi.fn().mockResolvedValue(undefined),
      },
    });
  });

  it('filters to the active template, summarizes statuses, and exposes download actions', async () => {
    const user = userEvent.setup();
    const onRefresh = vi.fn().mockResolvedValue(undefined);
    const downloadSpy = vi.spyOn(ApiService, 'downloadAuthenticatedFile').mockResolvedValue(undefined);

    render(
      <SigningResponsesPanel
        sourceTemplateId="tpl-1"
        requests={[
          buildRequest(),
          buildRequest({
            id: 'req-2',
            signerName: 'Grace Hopper',
            signerEmail: 'grace@example.com',
            status: 'sent',
            completedAt: null,
            artifacts: {
              sourcePdf: {
                available: true,
                downloadPath: '/api/signing/requests/req-2/artifacts/source_pdf',
              },
              signedPdf: {
                available: false,
                downloadPath: null,
              },
              auditReceipt: {
                available: false,
                downloadPath: null,
              },
            },
          }),
          buildRequest({
            id: 'req-3',
            sourceTemplateId: 'tpl-2',
            signerName: 'Ignored Recipient',
            signerEmail: 'ignored@example.com',
          }),
        ]}
        onRefresh={onRefresh}
      />,
    );

    expect(screen.getAllByText('Signed').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Waiting').length).toBeGreaterThan(0);
    expect(screen.getByText('Manual follow-up')).toBeTruthy();
    expect(screen.queryByText('Ignored Recipient')).toBeNull();
    await user.click(screen.getAllByRole('button', { name: 'Download respondent form' })[0]);
    expect(downloadSpy).toHaveBeenCalledWith(
      '/api/signing/requests/req-1/artifacts/source_pdf',
      expect.objectContaining({ filename: 'respondent-form.pdf' }),
    );
    await user.click(screen.getByRole('button', { name: 'Download signed form' }));
    expect(downloadSpy).toHaveBeenCalledWith(
      '/api/signing/requests/req-1/artifacts/signed_pdf',
      expect.objectContaining({ filename: 'signed-form.pdf' }),
    );

    await user.click(screen.getAllByRole('button', { name: 'Copy signer link' })[0]);
    expect(screen.getByRole('button', { name: 'Copied signer link' })).toBeTruthy();

    await user.click(screen.getByRole('button', { name: 'Refresh' }));
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it('shows an empty state when the active document has no sends yet', () => {
    render(
      <SigningResponsesPanel
        sourceDocumentName="Bravo Packet"
        requests={[buildRequest({ sourceDocumentName: 'Other Packet' })]}
      />,
    );

    expect(screen.getByText('No sends yet')).toBeTruthy();
    expect(screen.getByText(/Once you create and send signing requests/i)).toBeTruthy();
  });

  it('does not expose signer links for drafts or invalidated requests', () => {
    render(
      <SigningResponsesPanel
        sourceTemplateId="tpl-1"
        requests={[
          buildRequest({
            id: 'req-draft',
            status: 'draft',
            sentAt: null,
            completedAt: null,
            inviteDeliveryStatus: null,
            artifacts: {
              sourcePdf: { available: false, downloadPath: null },
              signedPdf: { available: false, downloadPath: null },
              auditReceipt: { available: false, downloadPath: null },
            },
          }),
          buildRequest({
            id: 'req-invalid',
            status: 'invalidated',
            sentAt: null,
            completedAt: null,
            invalidationReason: 'Source changed',
            inviteDeliveryStatus: null,
            artifacts: {
              sourcePdf: { available: false, downloadPath: null },
              signedPdf: { available: false, downloadPath: null },
              auditReceipt: { available: false, downloadPath: null },
            },
          }),
        ]}
      />,
    );

    expect(screen.queryByRole('button', { name: 'Copy signer link' })).toBeNull();
    expect(screen.getByText(/Review and send this draft from the Prepare tab/i)).toBeTruthy();
    expect(screen.getByText(/This draft was invalidated after the source PDF changed/i)).toBeTruthy();
  });
});
