import { StrictMode } from 'react';
import { act, render, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useWorkspaceSigning, type UseWorkspaceSigningDeps } from '../../../src/hooks/useWorkspaceSigning';
import type { ReviewedFillContext } from '../../../src/utils/signing';

const getSigningOptionsMock = vi.hoisted(() => vi.fn());
const createSigningRequestMock = vi.hoisted(() => vi.fn());
const sendSigningRequestMock = vi.hoisted(() => vi.fn());
const getSigningRequestMock = vi.hoisted(() => vi.fn());

vi.mock('../../../src/services/api', () => ({
  ApiService: {
    getSigningOptions: getSigningOptionsMock,
    createSigningRequest: createSigningRequestMock,
    sendSigningRequest: sendSigningRequestMock,
    getSigningRequest: getSigningRequestMock,
  },
}));

function createDeps(overrides: Partial<UseWorkspaceSigningDeps> = {}): UseWorkspaceSigningDeps {
  return {
    verifiedUser: { uid: 'user-1' } as any,
    hasDocument: true,
    sourceDocumentName: 'Bravo Packet',
    sourceTemplateId: 'form-1',
    sourceTemplateName: 'Bravo Packet',
    fields: [
      {
        id: 'sig-1',
        name: 'signature_primary',
        type: 'signature',
        page: 2,
        rect: { x: 10, y: 20, width: 120, height: 24 },
      },
      {
        id: 'signed-date-1',
        name: 'sign_date_primary',
        type: 'date',
        page: 2,
        rect: { x: 140, y: 20, width: 90, height: 24 },
      },
    ],
    resolveSourcePdfBytes: vi.fn().mockResolvedValue(new Uint8Array([1, 2, 3, 4])),
    ...overrides,
  };
}

function renderHookHarness(deps: UseWorkspaceSigningDeps, options?: { strictMode?: boolean }) {
  let latest: ReturnType<typeof useWorkspaceSigning> | null = null;

  function Harness() {
    latest = useWorkspaceSigning(deps);
    return null;
  }

  render(options?.strictMode ? (
    <StrictMode>
      <Harness />
    </StrictMode>
  ) : <Harness />);

  return {
    get current() {
      if (!latest) {
        throw new Error('hook not initialized');
      }
      return latest;
    },
  };
}

describe('useWorkspaceSigning', () => {
  beforeEach(() => {
    getSigningOptionsMock.mockReset();
    createSigningRequestMock.mockReset();
    sendSigningRequestMock.mockReset();
    getSigningRequestMock.mockReset();
  });

  it('loads signing options when the owner opens the dialog and derives signing anchors from fields', async () => {
    getSigningOptionsMock.mockResolvedValue({
      modes: [{ key: 'sign', label: 'Sign' }],
      signatureModes: [{ key: 'business', label: 'Business' }],
      categories: [{ key: 'ordinary_business_form', label: 'Ordinary business form', blocked: false }],
    });
    const hook = renderHookHarness(createDeps());

    act(() => {
      hook.current.openDialog();
    });

    await waitFor(() => expect(getSigningOptionsMock).toHaveBeenCalledTimes(1));

    expect(hook.current.canShowAction).toBe(true);
    expect(hook.current.canSendForSignature).toBe(true);
    expect(hook.current.dialogProps.open).toBe(true);
    expect(hook.current.dialogProps.defaultAnchors).toEqual([
      {
        kind: 'signature',
        page: 2,
        rect: { x: 10, y: 20, width: 120, height: 24 },
        fieldId: 'sig-1',
        fieldName: 'signature_primary',
      },
      {
        kind: 'signed_date',
        page: 2,
        rect: { x: 140, y: 20, width: 90, height: 24 },
        fieldId: 'signed-date-1',
        fieldName: 'sign_date_primary',
      },
    ]);
  });

  it('recovers from Strict Mode effect replay while loading signing options', async () => {
    getSigningOptionsMock
      .mockResolvedValueOnce({
        modes: [{ key: 'sign', label: 'Sign' }],
        signatureModes: [{ key: 'business', label: 'Business' }],
        categories: [{ key: 'ordinary_business_form', label: 'Ordinary business form', blocked: false }],
      })
      .mockResolvedValueOnce({
        modes: [{ key: 'sign', label: 'Sign' }],
        signatureModes: [{ key: 'business', label: 'Business' }],
        categories: [{ key: 'ordinary_business_form', label: 'Ordinary business form', blocked: false }],
      });
    const hook = renderHookHarness(createDeps(), { strictMode: true });

    act(() => {
      hook.current.openDialog();
    });

    await waitFor(() => {
      expect(hook.current.dialogProps.options).toEqual(expect.objectContaining({
        categories: [{ key: 'ordinary_business_form', label: 'Ordinary business form', blocked: false }],
      }));
    });
    expect(hook.current.dialogProps.optionsLoading).toBe(false);
    expect(getSigningOptionsMock).toHaveBeenCalled();
  });

  it('stops after a failed signing-options fetch and retries only when the dialog is reopened', async () => {
    getSigningOptionsMock
      .mockRejectedValueOnce(new Error('backend unavailable'))
      .mockResolvedValueOnce({
        modes: [{ key: 'sign', label: 'Sign' }],
        signatureModes: [{ key: 'business', label: 'Business' }],
        categories: [{ key: 'ordinary_business_form', label: 'Ordinary business form', blocked: false }],
      });
    const hook = renderHookHarness(createDeps());

    act(() => {
      hook.current.openDialog();
    });

    await waitFor(() => {
      expect(hook.current.dialogProps.error).toBe('backend unavailable');
      expect(hook.current.dialogProps.optionsLoading).toBe(false);
    });
    expect(getSigningOptionsMock).toHaveBeenCalledTimes(1);

    act(() => {
      hook.current.closeDialog();
      hook.current.openDialog();
    });

    await waitFor(() => {
      expect(hook.current.dialogProps.options).toEqual(expect.objectContaining({
        categories: [{ key: 'ordinary_business_form', label: 'Ordinary business form', blocked: false }],
      }));
    });
    expect(getSigningOptionsMock).toHaveBeenCalledTimes(2);
  });

  it('stores the created signing draft after a successful owner save', async () => {
    getSigningOptionsMock.mockResolvedValue({
      modes: [{ key: 'sign', label: 'Sign' }],
      signatureModes: [{ key: 'business', label: 'Business' }],
      categories: [{ key: 'ordinary_business_form', label: 'Ordinary business form', blocked: false }],
    });
    createSigningRequestMock.mockResolvedValue({
      id: 'req-1',
      sourceDocumentName: 'Bravo Packet',
      publicPath: '/sign/token-1',
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
      status: 'draft',
    });
    const hook = renderHookHarness(createDeps());

    act(() => {
      hook.current.openDialog();
    });
    await waitFor(() => expect(getSigningOptionsMock).toHaveBeenCalledTimes(1));

    await act(async () => {
      await hook.current.dialogProps.onCreateDraft({
        title: 'Bravo Packet Signature Request',
        mode: 'sign',
        signatureMode: 'business',
        sourceType: 'workspace',
        sourceId: 'form-1',
        sourceDocumentName: 'Bravo Packet',
        sourceTemplateId: 'form-1',
        sourceTemplateName: 'Bravo Packet',
        documentCategory: 'ordinary_business_form',
        manualFallbackEnabled: true,
        signerName: 'Alex Signer',
        signerEmail: 'alex@example.com',
        anchors: [],
      });
    });

    expect(createSigningRequestMock).toHaveBeenCalledWith(expect.objectContaining({
      signerEmail: 'alex@example.com',
      sourceDocumentName: 'Bravo Packet',
      documentCategory: 'ordinary_business_form',
      sourcePdfSha256: expect.stringMatching(/^[0-9a-f]{64}$/),
    }));
    expect(hook.current.dialogProps.createdRequest).toEqual(expect.objectContaining({
      id: 'req-1',
      publicPath: '/sign/token-1',
    }));
  });

  it('sends a created draft by uploading the current PDF bytes', async () => {
    const resolveSourcePdfBytes = vi.fn().mockResolvedValue(new Uint8Array([1, 2, 3, 4]));
    getSigningOptionsMock.mockResolvedValue({
      modes: [{ key: 'sign', label: 'Sign' }],
      signatureModes: [{ key: 'business', label: 'Business' }],
      categories: [{ key: 'ordinary_business_form', label: 'Ordinary business form', blocked: false }],
    });
    createSigningRequestMock.mockResolvedValue({
      id: 'req-1',
      sourceDocumentName: 'Bravo Packet',
      publicPath: '/sign/token-1',
      anchors: [{ kind: 'signature', page: 2, rect: { x: 10, y: 20, width: 120, height: 24 } }],
      documentCategory: 'ordinary_business_form',
      documentCategoryLabel: 'Ordinary business form',
      disclosureVersion: 'us-esign-business-v1',
      manualFallbackEnabled: true,
      mode: 'sign',
      signatureMode: 'business',
      signerEmail: 'alex@example.com',
      signerName: 'Alex Signer',
      sourceType: 'workspace',
      sourcePdfSha256: '9f64a747e1b97f131fabb6b447296c9b6f0201e79fb3c5356e6c77e89b6a806a',
      sourceVersion: 'workspace:9f64a747e1b9',
      status: 'draft',
    });
    sendSigningRequestMock.mockResolvedValue({
      id: 'req-1',
      sourceDocumentName: 'Bravo Packet',
      publicPath: '/sign/token-1',
      anchors: [{ kind: 'signature', page: 2, rect: { x: 10, y: 20, width: 120, height: 24 } }],
      documentCategory: 'ordinary_business_form',
      documentCategoryLabel: 'Ordinary business form',
      disclosureVersion: 'us-esign-business-v1',
      manualFallbackEnabled: true,
      mode: 'sign',
      signatureMode: 'business',
      signerEmail: 'alex@example.com',
      signerName: 'Alex Signer',
      sourceType: 'workspace',
      sourcePdfSha256: '9f64a747e1b97f131fabb6b447296c9b6f0201e79fb3c5356e6c77e89b6a806a',
      sourceVersion: 'workspace:9f64a747e1b9',
      sourcePdfPath: 'gs://signing/user-1/req-1/source.pdf',
      status: 'sent',
      sentAt: '2026-03-24T20:00:00Z',
    });
    const hook = renderHookHarness(createDeps({ resolveSourcePdfBytes }));

    act(() => {
      hook.current.openDialog();
    });
    await waitFor(() => expect(getSigningOptionsMock).toHaveBeenCalledTimes(1));

    await act(async () => {
      await hook.current.dialogProps.onCreateDraft({
        title: 'Bravo Packet Signature Request',
        mode: 'sign',
        signatureMode: 'business',
        sourceType: 'workspace',
        sourceId: 'form-1',
        sourceDocumentName: 'Bravo Packet',
        sourceTemplateId: 'form-1',
        sourceTemplateName: 'Bravo Packet',
        documentCategory: 'ordinary_business_form',
        manualFallbackEnabled: true,
        signerName: 'Alex Signer',
        signerEmail: 'alex@example.com',
        anchors: [{ kind: 'signature', page: 2, rect: { x: 10, y: 20, width: 120, height: 24 } }],
      });
    });

    await act(async () => {
      await hook.current.dialogProps.onSendRequest?.();
    });

    expect(sendSigningRequestMock).toHaveBeenCalledWith('req-1', expect.objectContaining({
      filename: 'Bravo Packet.pdf',
      sourcePdfSha256: '9f64a747e1b97f131fabb6b447296c9b6f0201e79fb3c5356e6c77e89b6a806a',
      pdf: expect.any(Blob),
    }));
    expect(resolveSourcePdfBytes).toHaveBeenNthCalledWith(1, 'sign');
    expect(resolveSourcePdfBytes).toHaveBeenNthCalledWith(2, 'sign');
    expect(hook.current.dialogProps.createdRequest).toEqual(expect.objectContaining({
      status: 'sent',
      sourcePdfPath: 'gs://signing/user-1/req-1/source.pdf',
    }));
  });

  it('refreshes the draft after a failed send so invalidation state is surfaced to the owner', async () => {
    const resolveSourcePdfBytes = vi.fn().mockResolvedValue(new Uint8Array([1, 2, 3, 4]));
    getSigningOptionsMock.mockResolvedValue({
      modes: [{ key: 'sign', label: 'Sign' }],
      signatureModes: [{ key: 'business', label: 'Business' }],
      categories: [{ key: 'ordinary_business_form', label: 'Ordinary business form', blocked: false }],
    });
    createSigningRequestMock.mockResolvedValue({
      id: 'req-1',
      sourceDocumentName: 'Bravo Packet',
      publicPath: '/sign/token-1',
      anchors: [{ kind: 'signature', page: 2, rect: { x: 10, y: 20, width: 120, height: 24 } }],
      documentCategory: 'ordinary_business_form',
      documentCategoryLabel: 'Ordinary business form',
      disclosureVersion: 'us-esign-business-v1',
      manualFallbackEnabled: true,
      mode: 'sign',
      signatureMode: 'business',
      signerEmail: 'alex@example.com',
      signerName: 'Alex Signer',
      sourceType: 'workspace',
      sourcePdfSha256: '9f64a747e1b97f131fabb6b447296c9b6f0201e79fb3c5356e6c77e89b6a806a',
      sourceVersion: 'workspace:9f64a747e1b9',
      status: 'draft',
    });
    sendSigningRequestMock.mockRejectedValue(new Error('The source PDF changed after this signing draft was created. Create a new draft before sending.'));
    getSigningRequestMock.mockResolvedValue({
      id: 'req-1',
      sourceDocumentName: 'Bravo Packet',
      publicPath: '/sign/token-1',
      anchors: [{ kind: 'signature', page: 2, rect: { x: 10, y: 20, width: 120, height: 24 } }],
      documentCategory: 'ordinary_business_form',
      documentCategoryLabel: 'Ordinary business form',
      disclosureVersion: 'us-esign-business-v1',
      manualFallbackEnabled: true,
      mode: 'sign',
      signatureMode: 'business',
      signerEmail: 'alex@example.com',
      signerName: 'Alex Signer',
      sourceType: 'workspace',
      sourcePdfSha256: '9f64a747e1b97f131fabb6b447296c9b6f0201e79fb3c5356e6c77e89b6a806a',
      sourceVersion: 'workspace:9f64a747e1b9',
      status: 'invalidated',
      invalidationReason: 'The source PDF changed after this signing draft was created. Create a new draft before sending.',
    });
    const hook = renderHookHarness(createDeps({ resolveSourcePdfBytes }));

    act(() => {
      hook.current.openDialog();
    });
    await waitFor(() => expect(getSigningOptionsMock).toHaveBeenCalledTimes(1));

    await act(async () => {
      await hook.current.dialogProps.onCreateDraft({
        title: 'Bravo Packet Signature Request',
        mode: 'sign',
        signatureMode: 'business',
        sourceType: 'workspace',
        sourceId: 'form-1',
        sourceDocumentName: 'Bravo Packet',
        sourceTemplateId: 'form-1',
        sourceTemplateName: 'Bravo Packet',
        documentCategory: 'ordinary_business_form',
        manualFallbackEnabled: true,
        signerName: 'Alex Signer',
        signerEmail: 'alex@example.com',
        anchors: [{ kind: 'signature', page: 2, rect: { x: 10, y: 20, width: 120, height: 24 } }],
      });
    });

    await act(async () => {
      await hook.current.dialogProps.onSendRequest?.();
    });

    expect(sendSigningRequestMock).toHaveBeenCalledWith('req-1', expect.objectContaining({
      sourcePdfSha256: '9f64a747e1b97f131fabb6b447296c9b6f0201e79fb3c5356e6c77e89b6a806a',
    }));
    expect(getSigningRequestMock).toHaveBeenCalledWith('req-1');
    expect(hook.current.dialogProps.error).toBe(
      'The source PDF changed after this signing draft was created. Create a new draft before sending.',
    );
    expect(hook.current.dialogProps.createdRequest).toEqual(expect.objectContaining({
      status: 'invalidated',
      invalidationReason: 'The source PDF changed after this signing draft was created. Create a new draft before sending.',
    }));
    expect(hook.current.dialogProps.sendDisabledReason).toBe(
      'The source PDF changed after this signing draft was created. Create a new draft before sending.',
    );
  });

  it('captures reviewed Fill By Link provenance for fill-and-sign drafts and sends with owner review confirmation', async () => {
    const resolveSourcePdfBytes = vi.fn().mockResolvedValue(new Uint8Array([5, 6, 7, 8]));
    const reviewedFillContext: ReviewedFillContext = {
      sourceType: 'fill_link_response',
      sourceId: 'resp-42',
      sourceLinkId: 'link-7',
      sourceRecordLabel: 'Ada Lovelace',
      reviewedAt: '2026-03-24T21:00:00Z',
      sourceLabel: 'Fill By Link respondents',
    };
    getSigningOptionsMock.mockResolvedValue({
      modes: [{ key: 'fill_and_sign', label: 'Fill and Sign' }],
      signatureModes: [{ key: 'business', label: 'Business' }],
      categories: [{ key: 'ordinary_business_form', label: 'Ordinary business form', blocked: false }],
    });
    createSigningRequestMock.mockResolvedValue({
      id: 'req-fill-1',
      sourceDocumentName: 'Bravo Packet',
      publicPath: '/sign/token-fill-1',
      anchors: [{ kind: 'signature', page: 2, rect: { x: 10, y: 20, width: 120, height: 24 } }],
      documentCategory: 'ordinary_business_form',
      documentCategoryLabel: 'Ordinary business form',
      disclosureVersion: 'us-esign-business-v1',
      manualFallbackEnabled: true,
      mode: 'fill_and_sign',
      signatureMode: 'business',
      signerEmail: 'alex@example.com',
      signerName: 'Alex Signer',
      sourceType: 'fill_link_response',
      sourceId: 'resp-42',
      sourceLinkId: 'link-7',
      sourceRecordLabel: 'Ada Lovelace',
      sourcePdfSha256: '55e5509f8052998294266ee5b50cb592938191fb5d67f73cac2e60b0276b1bdd',
      sourceVersion: 'fill_link_response:resp-42:55e5509f8052',
      status: 'draft',
    });
    sendSigningRequestMock.mockResolvedValue({
      id: 'req-fill-1',
      sourceDocumentName: 'Bravo Packet',
      publicPath: '/sign/token-fill-1',
      anchors: [{ kind: 'signature', page: 2, rect: { x: 10, y: 20, width: 120, height: 24 } }],
      documentCategory: 'ordinary_business_form',
      documentCategoryLabel: 'Ordinary business form',
      disclosureVersion: 'us-esign-business-v1',
      manualFallbackEnabled: true,
      mode: 'fill_and_sign',
      signatureMode: 'business',
      signerEmail: 'alex@example.com',
      signerName: 'Alex Signer',
      sourceType: 'fill_link_response',
      sourceId: 'resp-42',
      sourceLinkId: 'link-7',
      sourceRecordLabel: 'Ada Lovelace',
      sourcePdfSha256: '55e5509f8052998294266ee5b50cb592938191fb5d67f73cac2e60b0276b1bdd',
      sourceVersion: 'fill_link_response:resp-42:55e5509f8052',
      ownerReviewConfirmedAt: '2026-03-24T21:10:00Z',
      status: 'sent',
      sentAt: '2026-03-24T21:10:00Z',
    });

    const hook = renderHookHarness(createDeps({
      resolveSourcePdfBytes,
      reviewedFillContext,
      fields: [
        {
          id: 'sig-1',
          name: 'signature_primary',
          type: 'signature',
          page: 2,
          rect: { x: 10, y: 20, width: 120, height: 24 },
        },
        {
          id: 'full-name',
          name: 'full_name',
          type: 'text',
          page: 1,
          rect: { x: 20, y: 40, width: 160, height: 24 },
          value: 'Ada Lovelace',
        },
      ],
    }));

    act(() => {
      hook.current.openDialog();
    });
    await waitFor(() => expect(getSigningOptionsMock).toHaveBeenCalledTimes(1));

    await act(async () => {
      await hook.current.dialogProps.onCreateDraft({
        title: 'Bravo Packet Fill And Sign',
        mode: 'fill_and_sign',
        signatureMode: 'business',
        sourceType: 'workspace',
        sourceId: 'form-1',
        sourceDocumentName: 'Bravo Packet',
        sourceTemplateId: 'form-1',
        sourceTemplateName: 'Bravo Packet',
        documentCategory: 'ordinary_business_form',
        manualFallbackEnabled: true,
        signerName: 'Alex Signer',
        signerEmail: 'alex@example.com',
        anchors: [{ kind: 'signature', page: 2, rect: { x: 10, y: 20, width: 120, height: 24 } }],
      });
    });

    expect(createSigningRequestMock).toHaveBeenCalledWith(expect.objectContaining({
      mode: 'fill_and_sign',
      sourceType: 'fill_link_response',
      sourceId: 'resp-42',
      sourceLinkId: 'link-7',
      sourceRecordLabel: 'Ada Lovelace',
    }));

    await act(async () => {
      await hook.current.dialogProps.onSendRequest?.({ ownerReviewConfirmed: true });
    });

    expect(sendSigningRequestMock).toHaveBeenCalledWith('req-fill-1', expect.objectContaining({
      ownerReviewConfirmed: true,
      pdf: expect.any(Blob),
    }));
    expect(resolveSourcePdfBytes).toHaveBeenNthCalledWith(1, 'fill_and_sign');
    expect(resolveSourcePdfBytes).toHaveBeenNthCalledWith(2, 'fill_and_sign');
    expect(hook.current.dialogProps.createdRequest).toEqual(expect.objectContaining({
      status: 'sent',
      ownerReviewConfirmedAt: '2026-03-24T21:10:00Z',
    }));
  });
});
