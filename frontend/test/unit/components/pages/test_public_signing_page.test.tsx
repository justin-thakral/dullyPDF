import { StrictMode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import userEvent from '@testing-library/user-event';
import { render, screen, waitFor } from '@testing-library/react';
import PublicSigningPage from '../../../../src/components/pages/PublicSigningPage';

vi.mock('../../../../src/services/api', () => ({
  ApiService: {
    getPublicSigningRequest: vi.fn(),
    startPublicSigningSession: vi.fn(),
    reviewPublicSigningRequest: vi.fn(),
    consentPublicSigningRequest: vi.fn(),
    requestPublicSigningManualFallback: vi.fn(),
    adoptPublicSigningSignature: vi.fn(),
    completePublicSigningRequest: vi.fn(),
  },
}));

import { ApiService } from '../../../../src/services/api';

function buildRequest(overrides: Record<string, unknown> = {}) {
  return {
    id: 'req-1',
    title: 'Bravo Packet Signature Request',
    mode: 'sign',
    signatureMode: 'business',
    status: 'sent',
    statusMessage: 'This signing request is ready for review and signature.',
    sourceDocumentName: 'Bravo Packet',
    sourcePdfSha256: 'abc123',
    sourceVersion: 'workspace:abc123',
    documentCategory: 'ordinary_business_form',
    documentCategoryLabel: 'Ordinary business form',
    manualFallbackEnabled: true,
    signerName: 'Alex Signer',
    anchors: [
      {
        kind: 'signature',
        page: 1,
        rect: { x: 20, y: 20, width: 100, height: 30 },
      },
    ],
    disclosureVersion: 'us-esign-business-v1',
    documentPath: '/api/signing/public/token-1/document',
    artifacts: {
      signedPdf: {
        available: false,
        downloadPath: null,
      },
      auditReceipt: {
        available: false,
        downloadPath: null,
      },
    },
    createdAt: '2026-03-24T12:00:00Z',
    sentAt: '2026-03-24T12:01:00Z',
    ...overrides,
  };
}

describe('PublicSigningPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('loads the business signer ceremony and completes the explicit sign flow', async () => {
    const user = userEvent.setup();
    vi.mocked(ApiService.getPublicSigningRequest).mockResolvedValue(buildRequest());
    vi.mocked(ApiService.startPublicSigningSession).mockResolvedValue({
      request: buildRequest({ openedAt: '2026-03-24T12:02:00Z' }),
      session: { id: 'session-1', token: 'session-token-1', expiresAt: '2026-03-24T13:02:00Z' },
    });
    vi.mocked(ApiService.reviewPublicSigningRequest).mockResolvedValue(
      buildRequest({
        openedAt: '2026-03-24T12:02:00Z',
        reviewedAt: '2026-03-24T12:03:00Z',
      }),
    );
    vi.mocked(ApiService.adoptPublicSigningSignature).mockResolvedValue(
      buildRequest({
        openedAt: '2026-03-24T12:02:00Z',
        reviewedAt: '2026-03-24T12:03:00Z',
        signatureAdoptedAt: '2026-03-24T12:04:00Z',
        signatureAdoptedName: 'Alex Signer',
      }),
    );
    vi.mocked(ApiService.completePublicSigningRequest).mockResolvedValue(
      buildRequest({
        status: 'completed',
        statusMessage: 'This signing request has already been completed.',
        openedAt: '2026-03-24T12:02:00Z',
        reviewedAt: '2026-03-24T12:03:00Z',
        signatureAdoptedAt: '2026-03-24T12:04:00Z',
        signatureAdoptedName: 'Alex Signer',
        completedAt: '2026-03-24T12:05:00Z',
        artifacts: {
          signedPdf: {
            available: true,
            downloadPath: '/api/signing/public/token-1/artifacts/signed_pdf',
          },
          auditReceipt: {
            available: true,
            downloadPath: '/api/signing/public/token-1/artifacts/audit_receipt',
          },
        },
      }),
    );

    render(<PublicSigningPage token="token-1" />);

    await waitFor(() => {
      expect(ApiService.getPublicSigningRequest).toHaveBeenCalledWith('token-1');
      expect(ApiService.startPublicSigningSession).toHaveBeenCalledWith('token-1');
    });

    expect(screen.getByText('Bravo Packet')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'I reviewed this document' })).toBeTruthy();

    await user.click(screen.getByRole('button', { name: 'I reviewed this document' }));
    await waitFor(() => {
      expect(ApiService.reviewPublicSigningRequest).toHaveBeenCalledWith('token-1', 'session-token-1');
    });

    const adoptedNameInput = await screen.findByLabelText('Adopted signature name');
    await user.clear(adoptedNameInput);
    await user.type(adoptedNameInput, 'Alex Signer');
    await user.click(screen.getByRole('button', { name: 'Adopt this signature' }));
    await waitFor(() => {
      expect(ApiService.adoptPublicSigningSignature).toHaveBeenCalledWith('token-1', 'session-token-1', 'Alex Signer');
    });

    await user.click(screen.getByLabelText('I adopt this signature and sign this exact record electronically.'));
    await user.click(screen.getByRole('button', { name: 'Finish Signing' }));
    await waitFor(() => {
      expect(ApiService.completePublicSigningRequest).toHaveBeenCalledWith('token-1', 'session-token-1');
    });

    expect(await screen.findByText(/This signing request was completed/i)).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Download signed PDF' }).getAttribute('href')).toBe(
      '/api/signing/public/token-1/artifacts/signed_pdf',
    );
    expect(screen.getByRole('link', { name: 'Download audit receipt' }).getAttribute('href')).toBe(
      '/api/signing/public/token-1/artifacts/audit_receipt',
    );
  });

  it('locks the electronic ceremony after manual fallback is requested', async () => {
    const user = userEvent.setup();
    vi.mocked(ApiService.getPublicSigningRequest).mockResolvedValue(
      buildRequest({
        signatureMode: 'consumer',
        disclosureVersion: 'us-esign-consumer-v1',
        documentCategory: 'authorization_consent_form',
        documentCategoryLabel: 'Authorization or consent form',
      }),
    );
    vi.mocked(ApiService.startPublicSigningSession).mockResolvedValue({
      request: buildRequest({
        signatureMode: 'consumer',
        disclosureVersion: 'us-esign-consumer-v1',
        documentCategory: 'authorization_consent_form',
        documentCategoryLabel: 'Authorization or consent form',
        openedAt: '2026-03-24T12:02:00Z',
      }),
      session: { id: 'session-2', token: 'session-token-2', expiresAt: '2026-03-24T13:02:00Z' },
    });
    vi.mocked(ApiService.requestPublicSigningManualFallback).mockResolvedValue(
      buildRequest({
        signatureMode: 'consumer',
        disclosureVersion: 'us-esign-consumer-v1',
        documentCategory: 'authorization_consent_form',
        documentCategoryLabel: 'Authorization or consent form',
        openedAt: '2026-03-24T12:02:00Z',
        manualFallbackRequestedAt: '2026-03-24T12:03:00Z',
      }),
    );
    vi.mocked(ApiService.consentPublicSigningRequest).mockResolvedValue(
      buildRequest({
        signatureMode: 'consumer',
        disclosureVersion: 'us-esign-consumer-v1',
        documentCategory: 'authorization_consent_form',
        documentCategoryLabel: 'Authorization or consent form',
        openedAt: '2026-03-24T12:02:00Z',
        consentedAt: '2026-03-24T12:04:00Z',
      }),
    );

    render(<PublicSigningPage token="token-2" />);

    await waitFor(() => {
      expect(ApiService.startPublicSigningSession).toHaveBeenCalledWith('token-2');
    });

    expect(screen.getByText('Consent to electronic records')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'I reviewed this document' })).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Request paper/manual fallback' }));
    await waitFor(() => {
      expect(ApiService.requestPublicSigningManualFallback).toHaveBeenCalledWith('token-2', 'session-token-2');
    });

    expect(await screen.findByText(/Electronic signing is now paused until the sender follows up/i)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'I consent to electronic records' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'I reviewed this document' })).toBeNull();
    expect(ApiService.consentPublicSigningRequest).not.toHaveBeenCalled();
  });

  it('tells signers when a request exists but has not been sent yet', async () => {
    vi.mocked(ApiService.getPublicSigningRequest).mockResolvedValue(
      buildRequest({
        status: 'draft',
        statusMessage: 'This signing request has not been sent yet.',
      }),
    );

    render(<PublicSigningPage token="token-draft" />);

    await waitFor(() => {
      expect(ApiService.getPublicSigningRequest).toHaveBeenCalledWith('token-draft');
    });

    expect(ApiService.startPublicSigningSession).not.toHaveBeenCalled();
    expect(await screen.findByText('This signing request has not been sent yet.')).toBeTruthy();
    expect(
      screen.getByText('This signing request has been prepared but not sent yet. Ask the sender to finish Review and Send before using this link.'),
    ).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'I reviewed this document' })).toBeNull();
  });

  it('does not bootstrap a new session when manual fallback already locked the request', async () => {
    vi.mocked(ApiService.getPublicSigningRequest).mockResolvedValue(
      buildRequest({
        manualFallbackRequestedAt: '2026-03-24T12:03:00Z',
      }),
    );

    render(<PublicSigningPage token="token-locked" />);

    await waitFor(() => {
      expect(ApiService.getPublicSigningRequest).toHaveBeenCalledWith('token-locked');
    });

    expect(ApiService.startPublicSigningSession).not.toHaveBeenCalled();
    expect(await screen.findByText(/Electronic signing is now paused until the sender follows up/i)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Request paper/manual fallback' })).toBeNull();
  });

  it('bootstraps a sent signing request only once under StrictMode', async () => {
    vi.mocked(ApiService.getPublicSigningRequest).mockResolvedValue(buildRequest());
    vi.mocked(ApiService.startPublicSigningSession).mockResolvedValue({
      request: buildRequest({ openedAt: '2026-03-24T12:02:00Z' }),
      session: { id: 'session-1', token: 'session-token-1', expiresAt: '2026-03-24T13:02:00Z' },
    });

    render(
      <StrictMode>
        <PublicSigningPage token="token-1" />
      </StrictMode>,
    );

    expect(await screen.findByRole('button', { name: 'I reviewed this document' })).toBeTruthy();
    expect(ApiService.getPublicSigningRequest).toHaveBeenCalledTimes(1);
    expect(ApiService.getPublicSigningRequest).toHaveBeenCalledWith('token-1');
    expect(ApiService.startPublicSigningSession).toHaveBeenCalledTimes(1);
    expect(ApiService.startPublicSigningSession).toHaveBeenCalledWith('token-1');
  });

  it('resets final-sign intent when the public signing token changes', async () => {
    const user = userEvent.setup();
    const readyForComplete = buildRequest({
      reviewedAt: '2026-03-24T12:03:00Z',
      signatureAdoptedAt: '2026-03-24T12:04:00Z',
      signatureAdoptedName: 'Alex Signer',
    });
    const nextReadyForComplete = buildRequest({
      signerName: 'Pat Signer',
      reviewedAt: '2026-03-24T12:13:00Z',
      signatureAdoptedAt: '2026-03-24T12:14:00Z',
      signatureAdoptedName: 'Pat Signer',
    });
    vi.mocked(ApiService.getPublicSigningRequest)
      .mockResolvedValueOnce(readyForComplete)
      .mockResolvedValueOnce(nextReadyForComplete);
    vi.mocked(ApiService.startPublicSigningSession)
      .mockResolvedValueOnce({
        request: readyForComplete,
        session: { id: 'session-1', token: 'session-token-1', expiresAt: '2026-03-24T13:02:00Z' },
      })
      .mockResolvedValueOnce({
        request: nextReadyForComplete,
        session: { id: 'session-2', token: 'session-token-2', expiresAt: '2026-03-24T13:12:00Z' },
      });

    const { rerender } = render(<PublicSigningPage token="token-1" />);

    const intentCheckbox = await screen.findByLabelText('I adopt this signature and sign this exact record electronically.');
    await user.click(intentCheckbox);
    expect((screen.getByRole('button', { name: 'Finish Signing' }) as HTMLButtonElement).disabled).toBe(false);

    rerender(<PublicSigningPage token="token-2" />);

    await waitFor(() => {
      expect(ApiService.getPublicSigningRequest).toHaveBeenCalledWith('token-2');
      expect(ApiService.startPublicSigningSession).toHaveBeenCalledWith('token-2');
    });

    const resetCheckbox = await screen.findByLabelText('I adopt this signature and sign this exact record electronically.');
    expect((resetCheckbox as HTMLInputElement).checked).toBe(false);
    expect((screen.getByRole('button', { name: 'Finish Signing' }) as HTMLButtonElement).disabled).toBe(true);
  });
});
