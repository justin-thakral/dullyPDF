import { StrictMode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import userEvent from '@testing-library/user-event';
import { render, screen, waitFor } from '@testing-library/react';
import PublicSigningPage from '../../../../src/components/pages/PublicSigningPage';

vi.mock('../../../../src/services/api', () => ({
  ApiService: {
    getPublicSigningRequest: vi.fn(),
    getPublicSigningValidation: vi.fn(),
    startPublicSigningSession: vi.fn(),
    sendPublicSigningVerificationCode: vi.fn(),
    verifyPublicSigningVerificationCode: vi.fn(),
    getPublicSigningDocumentBlob: vi.fn(),
    issuePublicSigningArtifactDownload: vi.fn(),
    downloadPublicSigningFile: vi.fn(),
    reviewPublicSigningRequest: vi.fn(),
    consentPublicSigningRequest: vi.fn(),
    withdrawPublicSigningConsent: vi.fn(),
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
    senderDisplayName: 'Owner Example',
    senderContactEmail: 'owner@example.com',
    signerName: 'Alex Signer',
    signerEmailHint: 'a***@example.com',
    anchors: [
      {
        kind: 'signature',
        page: 1,
        rect: { x: 20, y: 20, width: 100, height: 30 },
      },
    ],
    disclosureVersion: 'us-esign-business-v1',
    documentPath: '/api/signing/public/token-1/document',
    validationPath: '/verify-signing/validation-token-1',
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
    vi.stubGlobal('open', vi.fn());
    URL.createObjectURL = vi.fn(() => 'blob:signing-document');
    URL.revokeObjectURL = vi.fn();
    vi.mocked(ApiService.getPublicSigningDocumentBlob).mockResolvedValue({
      blob: new Blob(['pdf']),
      filename: 'signing-document.pdf',
      contentType: 'application/pdf',
    });
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
            downloadPath: null,
          },
          auditReceipt: {
            available: true,
            downloadPath: null,
          },
        },
      }),
    );
    vi.mocked(ApiService.issuePublicSigningArtifactDownload)
      .mockResolvedValueOnce({
        artifactKey: 'signed_pdf',
        downloadPath: '/api/signing/public/artifacts/artifact-token-signed',
      } as any)
      .mockResolvedValueOnce({
        artifactKey: 'audit_receipt',
        downloadPath: '/api/signing/public/artifacts/artifact-token-receipt',
      } as any);

    render(<PublicSigningPage token="token-1" />);

    await waitFor(() => {
      expect(ApiService.getPublicSigningRequest).toHaveBeenCalledWith('token-1');
      expect(ApiService.startPublicSigningSession).toHaveBeenCalledWith('token-1');
    });

    expect(screen.getByText('Bravo Packet')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'I reviewed this document' })).toBeTruthy();
    await waitFor(() => {
      expect(ApiService.getPublicSigningDocumentBlob).toHaveBeenCalledWith('token-1', 'session-token-1');
    });
    await waitFor(() => {
      expect((screen.getByRole('button', { name: 'I reviewed this document' }) as HTMLButtonElement).disabled).toBe(false);
    });

    await user.click(screen.getByRole('button', { name: 'I reviewed this document' }));
    await waitFor(() => {
      expect(ApiService.reviewPublicSigningRequest).toHaveBeenCalledWith('token-1', 'session-token-1');
    });

    const adoptedNameInput = await screen.findByLabelText('Adopted signature name');
    await user.clear(adoptedNameInput);
    await user.type(adoptedNameInput, 'Alex Signer');
    await user.click(screen.getByRole('button', { name: 'Adopt this signature' }));
    await waitFor(() => {
      expect(ApiService.adoptPublicSigningSignature).toHaveBeenCalledWith('token-1', 'session-token-1', {
        signatureType: 'typed',
        adoptedName: 'Alex Signer',
      });
    });

    await user.click(screen.getByLabelText('I adopt this signature and sign this exact record electronically.'));
    await user.click(screen.getByRole('button', { name: 'Finish Signing' }));
    await waitFor(() => {
      expect(ApiService.completePublicSigningRequest).toHaveBeenCalledWith('token-1', 'session-token-1');
    });

    expect(await screen.findByText(/This signing request was completed/i)).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Validate retained record' }).getAttribute('href')).toBe('/verify-signing/validation-token-1');
    await user.click(screen.getByRole('button', { name: 'Download signed PDF' }));
    await waitFor(() => {
      expect(ApiService.issuePublicSigningArtifactDownload).toHaveBeenCalledWith(
        'token-1',
        'session-token-1',
        'signed_pdf',
      );
      expect(ApiService.downloadPublicSigningFile).toHaveBeenCalledWith(
        '/api/signing/public/artifacts/artifact-token-signed',
        'session-token-1',
        'signed-document.pdf',
      );
    });
    await user.click(screen.getByRole('button', { name: 'Download audit receipt' }));
    await waitFor(() => {
      expect(ApiService.issuePublicSigningArtifactDownload).toHaveBeenCalledWith(
        'token-1',
        'session-token-1',
        'audit_receipt',
      );
      expect(ApiService.downloadPublicSigningFile).toHaveBeenCalledWith(
        '/api/signing/public/artifacts/artifact-token-receipt',
        'session-token-1',
        'audit-receipt.pdf',
      );
    });
  });

  it('shows an error and skips download when issuing a short-lived artifact link fails', async () => {
    const user = userEvent.setup();
    vi.mocked(ApiService.getPublicSigningRequest).mockResolvedValue(
      buildRequest({
        status: 'completed',
        statusMessage: 'This signing request has already been completed.',
        completedAt: '2026-03-24T12:05:00Z',
        artifacts: {
          signedPdf: {
            available: true,
            downloadPath: null,
          },
          auditReceipt: {
            available: true,
            downloadPath: null,
          },
        },
      }),
    );
    vi.mocked(ApiService.startPublicSigningSession).mockResolvedValue({
      request: buildRequest({
        status: 'completed',
        statusMessage: 'This signing request has already been completed.',
        completedAt: '2026-03-24T12:05:00Z',
        artifacts: {
          signedPdf: {
            available: true,
            downloadPath: null,
          },
          auditReceipt: {
            available: true,
            downloadPath: null,
          },
        },
      }),
      session: { id: 'session-1', token: 'session-token-1', expiresAt: '2026-03-24T13:02:00Z' },
    });
    vi.mocked(ApiService.issuePublicSigningArtifactDownload).mockRejectedValue(
      new Error('Artifact download expired. Reload the page and try again.'),
    );

    render(<PublicSigningPage token="token-issue-fail" />);

    expect(await screen.findByRole('button', { name: 'Download signed PDF' })).toBeTruthy();

    await user.click(screen.getByRole('button', { name: 'Download signed PDF' }));

    await waitFor(() => {
      expect(ApiService.issuePublicSigningArtifactDownload).toHaveBeenCalledWith(
        'token-issue-fail',
        'session-token-1',
        'signed_pdf',
      );
    });
    expect(ApiService.downloadPublicSigningFile).not.toHaveBeenCalled();
    expect(await screen.findByText('Artifact download expired. Reload the page and try again.')).toBeTruthy();
  });

  it('allows adopting the recorded signer name as the default signature style', async () => {
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
        signatureAdoptedMode: 'default',
      }),
    );

    render(<PublicSigningPage token="token-default" />);

    await user.click(await screen.findByRole('button', { name: 'I reviewed this document' }));
    await waitFor(() => {
      expect(ApiService.reviewPublicSigningRequest).toHaveBeenCalledWith('token-default', 'session-token-1');
    });

    await user.click(screen.getByRole('radio', { name: /Use legal name/i }));
    await user.click(screen.getByRole('button', { name: 'Adopt this signature' }));

    await waitFor(() => {
      expect(ApiService.adoptPublicSigningSignature).toHaveBeenCalledWith('token-default', 'session-token-1', {
        signatureType: 'default',
      });
    });
  });

  it('gates Fill By Link sourced requests behind email verification before review', async () => {
    const user = userEvent.setup();
    vi.mocked(ApiService.getPublicSigningRequest).mockResolvedValue(
      buildRequest({
        verificationRequired: true,
        verificationMethod: 'email_otp',
      }),
    );
    vi.mocked(ApiService.startPublicSigningSession).mockResolvedValue({
      request: buildRequest({
        openedAt: '2026-03-24T12:02:00Z',
        verificationRequired: true,
        verificationMethod: 'email_otp',
      }),
      session: { id: 'session-verify', token: 'session-token-verify', expiresAt: '2026-03-24T13:02:00Z' },
    });
    vi.mocked(ApiService.sendPublicSigningVerificationCode).mockResolvedValue({
      request: buildRequest({
        openedAt: '2026-03-24T12:02:00Z',
        verificationRequired: true,
        verificationMethod: 'email_otp',
      }),
      session: {
        id: 'session-verify',
        token: 'session-token-verify',
        expiresAt: '2026-03-24T13:02:00Z',
        verificationSentAt: '2026-03-24T12:03:00Z',
        verificationExpiresAt: '2026-03-24T12:13:00Z',
        verificationResendCount: 1,
        verificationResendAvailableAt: '2026-03-24T12:04:00Z',
      },
    });
    vi.mocked(ApiService.verifyPublicSigningVerificationCode).mockResolvedValue({
      request: buildRequest({
        openedAt: '2026-03-24T12:02:00Z',
        verificationRequired: true,
        verificationMethod: 'email_otp',
        verificationCompletedAt: '2026-03-24T12:03:30Z',
      }),
      session: {
        id: 'session-verify',
        token: 'session-token-verify',
        expiresAt: '2026-03-24T13:02:00Z',
        verifiedAt: '2026-03-24T12:03:30Z',
      },
    });

    render(<PublicSigningPage token="token-verify" />);

    expect(await screen.findByText('Verify your email')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'I reviewed this document' })).toBeNull();
    const verificationCodeInput = screen.getByLabelText('Verification code');
    expect(verificationCodeInput.getAttribute('id')).toBe('public-signing-verification-code');
    expect(verificationCodeInput.getAttribute('name')).toBe('verificationCode');

    await user.click(screen.getByRole('button', { name: 'Send code' }));
    await waitFor(() => {
      expect(ApiService.sendPublicSigningVerificationCode).toHaveBeenCalledWith('token-verify', 'session-token-verify');
    });

    await user.type(screen.getByLabelText('Verification code'), '123456');
    await user.click(screen.getByRole('button', { name: 'Verify code' }));
    await waitFor(() => {
      expect(ApiService.verifyPublicSigningVerificationCode).toHaveBeenCalledWith(
        'token-verify',
        'session-token-verify',
        '123456',
      );
    });

    expect(await screen.findByRole('button', { name: 'I reviewed this document' })).toBeTruthy();
    await waitFor(() => {
      expect(ApiService.getPublicSigningDocumentBlob).toHaveBeenCalledWith('token-verify', 'session-token-verify');
    });
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

  it('does not expose the document link before consumer e-consent is recorded', async () => {
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

    render(<PublicSigningPage token="token-consumer" />);

    await waitFor(() => {
      expect(ApiService.startPublicSigningSession).toHaveBeenCalledWith('token-consumer');
    });

    expect(screen.getByText('Consent to electronic records')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Open document in new tab' })).toBeNull();
  });

  it('requires the consumer access code before sending e-consent', async () => {
    const user = userEvent.setup();
    const consumerRequest = buildRequest({
      signatureMode: 'consumer',
      disclosureVersion: 'us-esign-consumer-v1',
      documentCategory: 'authorization_consent_form',
      documentCategoryLabel: 'Authorization or consent form',
      disclosure: {
        version: 'us-esign-consumer-v1',
        summaryLines: ['Consent applies to this signing request.'],
        sender: {
          displayName: 'Owner Example',
          contactEmail: 'owner@example.com',
        },
        paperOption: {
          instructions: 'Use the paper/manual fallback option on this page to switch out of electronic signing.',
          fees: 'No platform fee.',
        },
        withdrawal: {
          instructions: 'Withdraw before completion to stop the electronic process.',
          consequences: 'Manual follow-up is required after withdrawal.',
        },
        contactUpdates: 'Contact the sender if your email changes before completion.',
        paperCopy: 'You may request a paper copy after consenting.',
        hardwareSoftware: ['A PDF-capable device and browser.'],
        accessCheck: {
          required: true,
          instructions: 'Open the access PDF and enter the code shown there.',
          accessPath: '/api/signing/public/token-consumer/consumer-access-pdf',
        },
      },
    });
    vi.mocked(ApiService.getPublicSigningRequest).mockResolvedValue(consumerRequest);
    vi.mocked(ApiService.startPublicSigningSession).mockResolvedValue({
      request: {
        ...consumerRequest,
        openedAt: '2026-03-24T12:02:00Z',
      },
      session: { id: 'session-consumer', token: 'session-token-consumer', expiresAt: '2026-03-24T13:02:00Z' },
    });
    vi.mocked(ApiService.consentPublicSigningRequest).mockResolvedValue({
      ...consumerRequest,
      openedAt: '2026-03-24T12:02:00Z',
      consentedAt: '2026-03-24T12:03:00Z',
    });

    render(<PublicSigningPage token="token-consumer" />);

    const consentButton = await screen.findByRole('button', { name: 'I consent to electronic records' });
    expect((consentButton as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTitle('Consumer access check PDF')).toBeTruthy();
    expect(screen.getByText(/Use the paper\/manual fallback option on this page/i)).toBeTruthy();
    expect(screen.getByText(/Withdraw before completion to stop the electronic process/i)).toBeTruthy();
    expect(screen.getByText(/Manual follow-up is required after withdrawal/i)).toBeTruthy();
    expect(screen.getByText(/Contact the sender if your email changes before completion/i)).toBeTruthy();
    expect(screen.getByText(/You may request a paper copy after consenting/i)).toBeTruthy();
    expect(screen.getByText(/Owner Example · owner@example.com/i)).toBeTruthy();
    expect(screen.getByText('A PDF-capable device and browser.')).toBeTruthy();
    const accessCodeInput = screen.getByLabelText('Access code');
    expect(accessCodeInput.getAttribute('id')).toBe('public-signing-access-code');
    expect(accessCodeInput.getAttribute('name')).toBe('accessCode');

    await user.type(accessCodeInput, 'abc123');
    expect((screen.getByRole('button', { name: 'I consent to electronic records' }) as HTMLButtonElement).disabled).toBe(false);
    await user.click(screen.getByRole('button', { name: 'I consent to electronic records' }));

    await waitFor(() => {
      expect(ApiService.consentPublicSigningRequest).toHaveBeenCalledWith(
        'token-consumer',
        'session-token-consumer',
        { accessCode: 'ABC123' },
      );
    });
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

  it('does not promise an on-page manual fallback button when manual fallback is disabled', async () => {
    const consumerRequest = buildRequest({
      signatureMode: 'consumer',
      disclosureVersion: 'us-esign-consumer-v1',
      documentCategory: 'authorization_consent_form',
      documentCategoryLabel: 'Authorization or consent form',
      manualFallbackEnabled: false,
      disclosure: {
        version: 'us-esign-consumer-v1',
        summaryLines: ['Paper copies are available by emailing owner@example.com.'],
        sender: {
          displayName: 'Owner Example',
          contactEmail: 'owner@example.com',
        },
        paperOption: null,
        withdrawal: {
          instructions: 'Email owner@example.com before completion to withdraw.',
          consequences: 'Withdrawing consent ends the electronic process for this request.',
        },
        contactUpdates: 'Email owner@example.com if your contact details change before completion.',
        paperCopy: 'Email owner@example.com to request a paper copy for this request.',
        hardwareSoftware: ['A PDF-capable device and browser.'],
        accessCheck: {
          required: true,
          instructions: 'Open the access PDF and enter the code shown there.',
          accessPath: '/api/signing/public/token-consumer/consumer-access-pdf',
        },
      },
    });
    vi.mocked(ApiService.getPublicSigningRequest).mockResolvedValue(consumerRequest);
    vi.mocked(ApiService.startPublicSigningSession).mockResolvedValue({
      request: {
        ...consumerRequest,
        openedAt: '2026-03-24T12:02:00Z',
      },
      session: { id: 'session-consumer', token: 'session-token-consumer', expiresAt: '2026-03-24T13:02:00Z' },
    });

    render(<PublicSigningPage token="token-consumer-disabled-fallback" />);

    expect(await screen.findByText('Consent to electronic records')).toBeTruthy();
    expect(screen.queryByText(/paper\/manual option/i)).toBeNull();
    expect(screen.queryByRole('button', { name: 'Request paper/manual fallback' })).toBeNull();
    expect(screen.getByText(/Email owner@example.com to request a paper copy/i)).toBeTruthy();
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

  it('gates completed requests behind verification before exposing downloads', async () => {
    const user = userEvent.setup();
    const completedRequest = buildRequest({
      status: 'completed',
      statusMessage: 'This signing request has already been completed.',
      verificationRequired: true,
      verificationMethod: 'email_otp',
      completedAt: '2026-03-24T12:05:00Z',
      artifacts: {
        signedPdf: {
          available: true,
          downloadPath: null,
        },
        auditReceipt: {
          available: true,
          downloadPath: null,
        },
      },
    });
    vi.mocked(ApiService.getPublicSigningRequest).mockResolvedValue(completedRequest);
    vi.mocked(ApiService.startPublicSigningSession).mockResolvedValue({
      request: completedRequest,
      session: { id: 'session-complete', token: 'session-token-complete', expiresAt: '2026-03-24T13:05:00Z' },
    });
    vi.mocked(ApiService.verifyPublicSigningVerificationCode).mockResolvedValue({
      request: {
        ...completedRequest,
        verificationCompletedAt: '2026-03-24T12:06:00Z',
      },
      session: {
        id: 'session-complete',
        token: 'session-token-complete',
        expiresAt: '2026-03-24T13:05:00Z',
        verifiedAt: '2026-03-24T12:06:00Z',
      },
    });

    render(<PublicSigningPage token="token-complete" />);

    expect(await screen.findByText('Verify your email')).toBeTruthy();
    expect(screen.getByText(/Verify your email to open the immutable source PDF/i)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Download signed PDF' })).toBeNull();

    await user.type(screen.getByLabelText('Verification code'), '123456');
    await user.click(screen.getByRole('button', { name: 'Verify code' }));
    await waitFor(() => {
      expect(ApiService.verifyPublicSigningVerificationCode).toHaveBeenCalledWith(
        'token-complete',
        'session-token-complete',
        '123456',
      );
    });
    await waitFor(() => {
      expect(ApiService.getPublicSigningDocumentBlob).toHaveBeenCalledWith('token-complete', 'session-token-complete');
    });

    expect(await screen.findByRole('button', { name: 'Download signed PDF' })).toBeTruthy();
  });

  it('treats expired sent requests as inactive and skips session bootstrap', async () => {
    vi.mocked(ApiService.getPublicSigningRequest).mockResolvedValue(
      buildRequest({
        isExpired: true,
        statusMessage: 'This signing request has expired. Contact the sender for a fresh signing link.',
      }),
    );

    render(<PublicSigningPage token="token-expired" />);

    await waitFor(() => {
      expect(ApiService.getPublicSigningRequest).toHaveBeenCalledWith('token-expired');
    });

    expect(ApiService.startPublicSigningSession).not.toHaveBeenCalled();
    expect(await screen.findByText(/expired before it was completed/i)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'I reviewed this document' })).toBeNull();
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
    expect(intentCheckbox.getAttribute('id')).toBe('public-signing-intent-confirmed');
    expect(intentCheckbox.getAttribute('name')).toBe('intentConfirmed');
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
