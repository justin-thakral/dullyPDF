import { act, render, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { usePipelineModal, type UsePipelineModalDeps } from '../../../src/hooks/usePipelineModal';

const loadPdfFromFileMock = vi.hoisted(() => vi.fn());

vi.mock('../../../src/utils/pdf', () => ({
  loadPdfFromFile: loadPdfFromFileMock,
}));

function renderHookHarness(deps: UsePipelineModalDeps) {
  let latest: ReturnType<typeof usePipelineModal> | null = null;
  function Harness() {
    latest = usePipelineModal(deps);
    return null;
  }
  render(<Harness />);
  return {
    get current() {
      if (!latest) {
        throw new Error('hook not initialized');
      }
      return latest;
    },
  };
}

describe('usePipelineModal', () => {
  it('exposes page count, credit estimate, and remaining credits once the PDF is inspected', async () => {
    const deps: UsePipelineModalDeps = {
      verifiedUser: { uid: 'user-0' } as any,
      loadUserProfile: vi.fn().mockResolvedValue(null),
      userProfile: {
        role: 'pro',
        availableCredits: 9,
        creditsRemaining: 9,
        creditPricing: {
          pageBucketSize: 5,
          renameBaseCost: 1,
          remapBaseCost: 1,
          renameRemapBaseCost: 2,
        },
      },
      detectMaxPages: 10,
      schemaId: null,
      schemaUploadInProgress: false,
      pendingSchemaPayload: null,
      persistSchemaPayload: vi.fn().mockResolvedValue(null),
      setSchemaUploadInProgress: vi.fn(),
      runDetectUpload: vi.fn(),
    };
    loadPdfFromFileMock.mockResolvedValue({
      numPages: 6,
      destroy: vi.fn().mockResolvedValue(undefined),
    });
    const hook = renderHookHarness(deps);

    act(() => {
      hook.current.openModal(new File(['pdf'], 'estimate.pdf', { type: 'application/pdf' }));
      hook.current.setUploadWantsRename(true);
    });

    await waitFor(() => expect(hook.current.pendingDetectPageCountLoading).toBe(false));

    expect(hook.current.pendingDetectPageCount).toBe(6);
    expect(hook.current.pendingDetectWithinPageLimit).toBe(true);
    expect(hook.current.pendingDetectCreditEstimate).toMatchObject({
      totalCredits: 2,
      bucketCount: 2,
      baseCost: 1,
    });
    expect(hook.current.pendingDetectCreditsRemaining).toBe(9);
  });

  it('blocks rename+map when bucketed credit pricing exceeds remaining credits', async () => {
    const runDetectUpload = vi.fn();
    const deps: UsePipelineModalDeps = {
      verifiedUser: { uid: 'user-1' } as any,
      loadUserProfile: vi.fn().mockResolvedValue({
        role: 'pro',
        availableCredits: 3,
        creditsRemaining: 3,
        creditPricing: {
          pageBucketSize: 5,
          renameBaseCost: 1,
          remapBaseCost: 1,
          renameRemapBaseCost: 2,
        },
      }),
      userProfile: {
        role: 'pro',
        availableCredits: 3,
        creditsRemaining: 3,
      },
      detectMaxPages: 50,
      schemaId: 'schema-1',
      schemaUploadInProgress: false,
      pendingSchemaPayload: null,
      persistSchemaPayload: vi.fn().mockResolvedValue(null),
      setSchemaUploadInProgress: vi.fn(),
      runDetectUpload,
    };
    loadPdfFromFileMock.mockResolvedValue({
      numPages: 30,
      destroy: vi.fn().mockResolvedValue(undefined),
    });
    const hook = renderHookHarness(deps);
    const file = new File(['pdf'], 'sample.pdf', { type: 'application/pdf' });

    act(() => {
      hook.current.openModal(file);
      hook.current.setUploadWantsRename(true);
      hook.current.setUploadWantsMap(true);
    });
    await waitFor(() => expect(hook.current.pendingDetectPageCountLoading).toBe(false));
    await act(async () => {
      await hook.current.confirm();
    });

    expect(hook.current.pipelineError).toContain('required=12');
    expect(runDetectUpload).not.toHaveBeenCalled();
  });

  it('starts detect upload when remaining credits satisfy computed bucket cost', async () => {
    const runDetectUpload = vi.fn();
    const deps: UsePipelineModalDeps = {
      verifiedUser: { uid: 'user-2' } as any,
      loadUserProfile: vi.fn().mockResolvedValue({
        role: 'pro',
        availableCredits: 10,
        creditsRemaining: 10,
        creditPricing: {
          pageBucketSize: 5,
          renameBaseCost: 1,
          remapBaseCost: 1,
          renameRemapBaseCost: 2,
        },
      }),
      userProfile: {
        role: 'pro',
        availableCredits: 10,
        creditsRemaining: 10,
      },
      detectMaxPages: 20,
      schemaId: null,
      schemaUploadInProgress: false,
      pendingSchemaPayload: null,
      persistSchemaPayload: vi.fn().mockResolvedValue(null),
      setSchemaUploadInProgress: vi.fn(),
      runDetectUpload,
    };
    loadPdfFromFileMock.mockResolvedValue({
      numPages: 16,
      destroy: vi.fn().mockResolvedValue(undefined),
    });
    const hook = renderHookHarness(deps);
    const file = new File(['pdf'], 'rename-only.pdf', { type: 'application/pdf' });

    act(() => {
      hook.current.openModal(file);
      hook.current.setUploadWantsRename(true);
      hook.current.setUploadWantsMap(false);
    });
    await waitFor(() => expect(hook.current.pendingDetectPageCountLoading).toBe(false));
    await act(async () => {
      await hook.current.confirm();
    });

    expect(hook.current.pipelineError).toBeNull();
    expect(runDetectUpload).toHaveBeenCalledWith(
      file,
      {
        autoRename: true,
        autoMap: false,
        schemaIdOverride: null,
      },
    );
  });

  it('blocks detection before processing when the PDF exceeds the page limit', async () => {
    const runDetectUpload = vi.fn();
    const deps: UsePipelineModalDeps = {
      verifiedUser: { uid: 'user-3' } as any,
      loadUserProfile: vi.fn().mockResolvedValue(null),
      userProfile: {
        role: 'free',
        availableCredits: 4,
        creditsRemaining: 4,
      },
      detectMaxPages: 5,
      schemaId: null,
      schemaUploadInProgress: false,
      pendingSchemaPayload: null,
      persistSchemaPayload: vi.fn().mockResolvedValue(null),
      setSchemaUploadInProgress: vi.fn(),
      runDetectUpload,
    };
    loadPdfFromFileMock.mockResolvedValue({
      numPages: 9,
      destroy: vi.fn().mockResolvedValue(undefined),
    });
    const hook = renderHookHarness(deps);
    const file = new File(['pdf'], 'too-many-pages.pdf', { type: 'application/pdf' });

    act(() => {
      hook.current.openModal(file);
    });
    await waitFor(() => expect(hook.current.pendingDetectPageCountLoading).toBe(false));

    await act(async () => {
      await hook.current.confirm();
    });

    expect(hook.current.pipelineError).toBe('Detection uploads are limited to 5 pages on your plan.');
    expect(runDetectUpload).not.toHaveBeenCalled();
  });
});
