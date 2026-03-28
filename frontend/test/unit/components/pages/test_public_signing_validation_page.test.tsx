import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import PublicSigningValidationPage from '../../../../src/components/pages/PublicSigningValidationPage';

vi.mock('../../../../src/services/api', () => ({
  ApiService: {
    getPublicSigningValidation: vi.fn(),
  },
}));

import { ApiService } from '../../../../src/services/api';

describe('PublicSigningValidationPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders a valid completed signing record', async () => {
    vi.mocked(ApiService.getPublicSigningValidation).mockResolvedValue({
      available: true,
      valid: true,
      status: 'valid',
      statusMessage: 'DullyPDF verified the retained audit evidence for this completed signing record.',
      validatedAt: '2026-03-28T12:06:00Z',
      requestId: 'req-1',
      title: 'Bravo Packet Signature Request',
      sourceDocumentName: 'Bravo Packet',
      sourceVersion: 'workspace:form-alpha:abc123',
      documentCategory: 'ordinary_business_form',
      documentCategoryLabel: 'Ordinary business form',
      completedAt: '2026-03-28T12:05:00Z',
      retentionUntil: '2033-03-28T12:05:00Z',
      sender: { displayName: 'Owner Example', contactEmail: 'owner@example.com' },
      signer: { name: 'Alex Signer', adoptedName: 'Alex Signer' },
      validationPath: '/verify-signing/token-1',
      validationUrl: 'https://dullypdf.com/verify-signing/token-1',
      sourcePdfSha256: 'a'.repeat(64),
      signedPdfSha256: 'b'.repeat(64),
      auditManifestSha256: 'c'.repeat(64),
      auditReceiptSha256: 'd'.repeat(64),
      checks: [
        { key: 'audit_manifest_signature', label: 'Audit manifest envelope signature', passed: true },
        { key: 'signed_pdf_hash', label: 'Signed PDF hash matches the retained audit manifest', passed: true },
      ],
      eventCount: 11,
      signature: {
        method: 'dev_hmac_sha256',
        algorithm: 'HS256',
        keyVersionName: 'dev-key',
        digestSha256: 'e'.repeat(64),
      },
    });

    render(<PublicSigningValidationPage token="token-1" />);

    await waitFor(() => {
      expect(ApiService.getPublicSigningValidation).toHaveBeenCalledWith('token-1');
    });
    expect(await screen.findByText(/validate a completed signing record/i)).toBeTruthy();
    expect(screen.getByText(/DullyPDF verified the retained audit evidence/i)).toBeTruthy();
    expect(screen.getByText('Bravo Packet')).toBeTruthy();
    expect(screen.getByText(/Audit manifest envelope signature/i)).toBeTruthy();
    expect(screen.getByText(/dev_hmac_sha256/i)).toBeTruthy();
  });
});
