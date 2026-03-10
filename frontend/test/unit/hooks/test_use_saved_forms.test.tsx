import { act, render } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useSavedForms } from '../../../src/hooks/useSavedForms';

const deleteSavedFormMock = vi.hoisted(() => vi.fn());

vi.mock('../../../src/services/api', () => ({
  ApiService: {
    deleteSavedForm: deleteSavedFormMock,
  },
}));

function renderHookHarness() {
  let latest: ReturnType<typeof useSavedForms> | null = null;
  const authUserRef = { current: { uid: 'user-1' } as any };
  const setBannerNotice = vi.fn();
  const requestConfirm = vi.fn().mockResolvedValue(true);
  const refreshGroups = vi.fn().mockResolvedValue(undefined);
  const refreshProfile = vi.fn().mockResolvedValue(undefined);

  function Harness() {
    latest = useSavedForms({
      authUserRef,
      setBannerNotice,
      requestConfirm,
      refreshGroups,
      refreshProfile,
    });
    return null;
  }

  render(<Harness />);

  return {
    setBannerNotice,
    requestConfirm,
    refreshGroups,
    refreshProfile,
    get current() {
      if (!latest) {
        throw new Error('hook not initialized');
      }
      return latest;
    },
  };
}

describe('useSavedForms', () => {
  beforeEach(() => {
    deleteSavedFormMock.mockReset().mockResolvedValue({ success: true });
  });

  it('clears the active saved-form selection when deleting the active template by default', async () => {
    const hook = renderHookHarness();

    act(() => {
      hook.current.setSavedForms([
        { id: 'form-1', name: 'Packet Alpha', createdAt: '2025-01-01T00:00:00.000Z' },
      ]);
      hook.current.setActiveSavedFormId('form-1');
      hook.current.setActiveSavedFormName('Packet Alpha');
    });

    await act(async () => {
      await hook.current.deleteSavedFormById('form-1');
    });

    expect(deleteSavedFormMock).toHaveBeenCalledWith('form-1');
    expect(hook.current.activeSavedFormId).toBeNull();
    expect(hook.current.activeSavedFormName).toBeNull();
  });

  it('supports preserving the active selection until the caller handles group teardown', async () => {
    const hook = renderHookHarness();
    const afterDelete = vi.fn();

    act(() => {
      hook.current.setSavedForms([
        { id: 'form-1', name: 'Packet Alpha', createdAt: '2025-01-01T00:00:00.000Z' },
      ]);
      hook.current.setActiveSavedFormId('form-1');
      hook.current.setActiveSavedFormName('Packet Alpha');
    });

    await act(async () => {
      await hook.current.deleteSavedFormById('form-1', {
        preserveActiveSelection: true,
        afterDelete,
      });
    });

    expect(deleteSavedFormMock).toHaveBeenCalledWith('form-1');
    expect(afterDelete).toHaveBeenCalledTimes(1);
    expect(hook.current.activeSavedFormId).toBe('form-1');
    expect(hook.current.activeSavedFormName).toBe('Packet Alpha');
  });

  it('passes delete preservation options through the saved-forms-limit flow before retrying save', async () => {
    const hook = renderHookHarness();
    const afterDelete = vi.fn();
    const queuedSave = vi.fn().mockResolvedValue(undefined);

    act(() => {
      hook.current.setSavedForms([
        { id: 'form-1', name: 'Packet Alpha', createdAt: '2025-01-01T00:00:00.000Z' },
      ]);
      hook.current.setActiveSavedFormId('form-1');
      hook.current.setActiveSavedFormName('Packet Alpha');
      hook.current.pendingSaveActionRef.current = queuedSave;
      hook.current.setShowSavedFormsLimitDialog(true);
    });

    await act(async () => {
      await hook.current.handleSavedFormsLimitDelete('form-1', {
        preserveActiveSelection: true,
        afterDelete,
      });
    });

    expect(afterDelete).toHaveBeenCalledTimes(1);
    expect(queuedSave).toHaveBeenCalledTimes(1);
    expect(hook.current.activeSavedFormId).toBe('form-1');
  });
});
