import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SignatureRequestDialog } from '../../../../src/components/features/SignatureRequestDialog';
import type { SigningOptions } from '../../../../src/services/api';


const SIGNING_OPTIONS: SigningOptions = {
  modes: [
    { key: 'sign', label: 'Sign' },
    { key: 'fill_and_sign', label: 'Fill and Sign' },
  ],
  signatureModes: [
    { key: 'business', label: 'Business' },
    { key: 'consumer', label: 'Consumer' },
  ],
  categories: [
    { key: 'ordinary_business_form', label: 'Ordinary business form', blocked: false },
    { key: 'court_document', label: 'Court document', blocked: true, reason: 'Blocked in v1.' },
  ],
};


describe('SignatureRequestDialog', () => {
  it('creates a draft payload with sign mode defaults', async () => {
    const user = userEvent.setup();
    const onCreateDraft = vi.fn().mockResolvedValue(undefined);

    render(
      <SignatureRequestDialog
        open
        onClose={vi.fn()}
        hasDocument
        sourceDocumentName="Bravo Packet"
        sourceTemplateId="form-1"
        sourceTemplateName="Bravo Packet"
        options={SIGNING_OPTIONS}
        defaultAnchors={[
          {
            kind: 'signature',
            page: 2,
            rect: { x: 10, y: 20, width: 100, height: 25 },
            fieldId: 'sig-1',
            fieldName: 'signature_primary',
          },
        ]}
        onCreateDraft={onCreateDraft}
      />,
    );

    await user.type(screen.getByLabelText('Signer name'), 'Alex Signer');
    await user.type(screen.getByLabelText('Signer email'), 'alex@example.com');
    await user.click(screen.getByRole('button', { name: 'Save Signing Draft' }));

    expect(onCreateDraft).toHaveBeenCalledTimes(1);
    expect(onCreateDraft).toHaveBeenCalledWith({
      title: 'Bravo Packet Signature Request',
      mode: 'sign',
      signatureMode: 'business',
      sourceType: 'workspace',
      sourceId: 'form-1',
      sourceLinkId: undefined,
      sourceRecordLabel: undefined,
      sourceDocumentName: 'Bravo Packet',
      sourceTemplateId: 'form-1',
      sourceTemplateName: 'Bravo Packet',
      documentCategory: 'ordinary_business_form',
      manualFallbackEnabled: true,
      signerName: 'Alex Signer',
      signerEmail: 'alex@example.com',
      anchors: [
        {
          kind: 'signature',
          page: 2,
          rect: { x: 10, y: 20, width: 100, height: 25 },
          fieldId: 'sig-1',
          fieldName: 'signature_primary',
        },
      ],
    });
  });

  it('renders blocked categories as unavailable choices', () => {
    const onCreateDraft = vi.fn();

    render(
      <SignatureRequestDialog
        open
        onClose={vi.fn()}
        hasDocument
        sourceDocumentName="Bravo Packet"
        options={SIGNING_OPTIONS}
        onCreateDraft={onCreateDraft}
      />,
    );

    const categorySelect = screen.getByLabelText('Document category') as HTMLSelectElement;
    const blockedOption = screen.getByRole('option', { name: 'Court document (Blocked)' }) as HTMLOptionElement;
    expect(categorySelect.value).toBe('ordinary_business_form');
    expect(blockedOption.disabled).toBe(true);
    const saveButton = screen.getByRole('button', { name: 'Save Signing Draft' }) as HTMLButtonElement;
    expect(saveButton.disabled).toBe(true);
  });

  it('shows review-and-send details for a created draft', () => {
    const onSendRequest = vi.fn();

    render(
      <SignatureRequestDialog
        open
        onClose={vi.fn()}
        hasDocument
        sourceDocumentName="Bravo Packet"
        options={SIGNING_OPTIONS}
        createdRequest={{
          id: 'req-1',
          title: 'Bravo Packet Signature Request',
          mode: 'sign',
          signatureMode: 'business',
          sourceType: 'workspace',
          sourceDocumentName: 'Bravo Packet',
          sourcePdfSha256: '9f64a747e1b97f131fabb6b447296c9b6f0201e79fb3c5356e6c77e89b6a806a',
          sourceVersion: 'workspace:9f64a747e1b9',
          documentCategory: 'ordinary_business_form',
          documentCategoryLabel: 'Ordinary business form',
          manualFallbackEnabled: true,
          signerName: 'Alex Signer',
          signerEmail: 'alex@example.com',
          status: 'draft',
          anchors: [
            {
              kind: 'signature',
              page: 1,
              rect: { x: 20, y: 20, width: 100, height: 30 },
            },
          ],
          disclosureVersion: 'us-esign-business-v1',
          publicToken: 'token-1',
          publicPath: '/sign/token-1',
        }}
        onCreateDraft={vi.fn()}
        onSendRequest={onSendRequest}
      />,
    );

    expect(screen.getByText('workspace:9f64a747e1b9')).toBeTruthy();
    expect(screen.getByText('Draft saved. The signer link stays inactive until you click Review and Send.')).toBeTruthy();
    expect(screen.queryByText('/sign/token-1')).toBeNull();
    const sendButton = screen.getByRole('button', { name: 'Review and Send' }) as HTMLButtonElement;
    expect(sendButton.disabled).toBe(false);
  });

  it('uses reviewed Fill By Link provenance for fill-and-sign drafts and requires owner review before send', async () => {
    const user = userEvent.setup();
    const onCreateDraft = vi.fn().mockResolvedValue(undefined);
    const onSendRequest = vi.fn().mockResolvedValue(undefined);

    render(
      <SignatureRequestDialog
        open
        onClose={vi.fn()}
        hasDocument
        sourceDocumentName="Bravo Packet"
        sourceTemplateId="form-1"
        sourceTemplateName="Bravo Packet"
        options={SIGNING_OPTIONS}
        hasMeaningfulFillValues
        fillAndSignContext={{
          sourceType: 'fill_link_response',
          sourceId: 'resp-42',
          sourceLinkId: 'link-7',
          sourceRecordLabel: 'Ada Lovelace',
          reviewedAt: '2026-03-24T21:00:00Z',
          sourceLabel: 'Fill By Link respondents',
        }}
        createdRequest={{
          id: 'req-1',
          title: 'Bravo Packet Fill And Sign',
          mode: 'fill_and_sign',
          signatureMode: 'business',
          sourceType: 'fill_link_response',
          sourceId: 'resp-42',
          sourceLinkId: 'link-7',
          sourceRecordLabel: 'Ada Lovelace',
          sourceDocumentName: 'Bravo Packet',
          sourcePdfSha256: '9f64a747e1b97f131fabb6b447296c9b6f0201e79fb3c5356e6c77e89b6a806a',
          sourceVersion: 'fill_link_response:resp-42:9f64a747e1b9',
          documentCategory: 'ordinary_business_form',
          documentCategoryLabel: 'Ordinary business form',
          manualFallbackEnabled: true,
          signerName: 'Alex Signer',
          signerEmail: 'alex@example.com',
          status: 'draft',
          anchors: [
            {
              kind: 'signature',
              page: 1,
              rect: { x: 20, y: 20, width: 100, height: 30 },
            },
          ],
          disclosureVersion: 'us-esign-business-v1',
          publicToken: 'token-1',
          publicPath: '/sign/token-1',
          artifacts: {
            signedPdf: { available: false },
            auditReceipt: { available: false },
          },
        }}
        onCreateDraft={onCreateDraft}
        onSendRequest={onSendRequest}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Fill and Sign' }));
    await user.type(screen.getByLabelText('Signer name'), 'Alex Signer');
    await user.type(screen.getByLabelText('Signer email'), 'alex@example.com');
    await user.click(screen.getByRole('button', { name: 'Save Signing Draft' }));

    expect(onCreateDraft).toHaveBeenCalledWith(expect.objectContaining({
      mode: 'fill_and_sign',
      sourceType: 'fill_link_response',
      sourceId: 'resp-42',
      sourceLinkId: 'link-7',
      sourceRecordLabel: 'Ada Lovelace',
    }));

    const sendButton = screen.getByRole('button', { name: 'Review and Send' }) as HTMLButtonElement;
    expect(sendButton.disabled).toBe(true);

    await user.click(screen.getByLabelText('I reviewed the filled PDF and want to freeze this exact version for signature.'));
    await waitFor(() => expect(sendButton.disabled).toBe(false));

    await user.click(sendButton);
    expect(onSendRequest).toHaveBeenCalledWith({ ownerReviewConfirmed: true });
  });
});
