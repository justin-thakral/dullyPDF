import { act, render } from '@testing-library/react';
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
});
