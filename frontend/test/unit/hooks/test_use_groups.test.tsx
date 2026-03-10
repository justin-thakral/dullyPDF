import { act, render, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useGroups } from '../../../src/hooks/useGroups';

const getGroupsMock = vi.hoisted(() => vi.fn());
const createGroupMock = vi.hoisted(() => vi.fn());
const updateGroupMock = vi.hoisted(() => vi.fn());
const deleteGroupMock = vi.hoisted(() => vi.fn());

vi.mock('../../../src/services/api', () => ({
  ApiService: {
    getGroups: getGroupsMock,
    createGroup: createGroupMock,
    updateGroup: updateGroupMock,
    deleteGroup: deleteGroupMock,
  },
}));

function renderHookHarness() {
  let latest: ReturnType<typeof useGroups> | null = null;
  const setBannerNotice = vi.fn();
  const verifiedUser = { uid: 'user-1' };

  function Harness() {
    latest = useGroups({
      verifiedUser,
      setBannerNotice,
    });
    return null;
  }

  render(<Harness />);

  return {
    setBannerNotice,
    get current() {
      if (!latest) {
        throw new Error('hook not initialized');
      }
      return latest;
    },
  };
}

describe('useGroups', () => {
  beforeEach(() => {
    getGroupsMock.mockReset().mockResolvedValue([]);
    createGroupMock.mockReset();
    updateGroupMock.mockReset();
    deleteGroupMock.mockReset().mockResolvedValue({ success: true });
  });

  it('preserves the selected group label during refresh and only clears after the group is actually missing', async () => {
    let resolveGroups: ((value: Array<Record<string, unknown>>) => void) | null = null;
    getGroupsMock
      .mockResolvedValueOnce([])
      .mockImplementationOnce(() => new Promise((resolve) => {
        resolveGroups = resolve as (value: Array<Record<string, unknown>>) => void;
      }));

    const hook = renderHookHarness();

    await waitFor(() => {
      expect(hook.current.groupsLoading).toBe(false);
    });

    await act(async () => {
      hook.current.setGroups([
        {
          id: 'group-1',
          name: 'Admissions',
          templateIds: ['tpl-a'],
          templateCount: 1,
          templates: [],
        },
      ]);
      hook.current.setSelectedGroupFilterId('group-1');
    });

    await waitFor(() => {
      expect(hook.current.selectedGroupFilterId).toBe('group-1');
      expect(hook.current.selectedGroupFilterLabel).toBe('Admissions');
    });

    await act(async () => {
      hook.current.refreshGroups();
    });

    expect(hook.current.groupsLoading).toBe(true);
    expect(hook.current.selectedGroupFilterId).toBe('group-1');
    expect(hook.current.selectedGroupFilterLabel).toBe('Admissions');

    await act(async () => {
      resolveGroups?.([]);
    });

    await waitFor(() => {
      expect(hook.current.groupsLoading).toBe(false);
      expect(hook.current.selectedGroupFilterId).toBe('all');
      expect(hook.current.selectedGroupFilterLabel).toBe('All saved forms');
    });
  });

  it('tracks the selected group label through create and update flows', async () => {
    createGroupMock.mockResolvedValue({
      id: 'group-1',
      name: 'Admissions',
      templateIds: ['tpl-a'],
      templateCount: 1,
      templates: [],
    });
    updateGroupMock.mockResolvedValue({
      id: 'group-1',
      name: 'Admissions Intake',
      templateIds: ['tpl-a'],
      templateCount: 1,
      templates: [],
    });

    const hook = renderHookHarness();

    await waitFor(() => {
      expect(hook.current.groupsLoading).toBe(false);
    });

    await act(async () => {
      await hook.current.createGroup({ name: 'Admissions', templateIds: ['tpl-a'] });
    });

    expect(hook.current.selectedGroupFilterId).toBe('group-1');
    expect(hook.current.selectedGroupFilterLabel).toBe('Admissions');

    await act(async () => {
      await hook.current.updateExistingGroup('group-1', { name: 'Admissions Intake', templateIds: ['tpl-a'] });
    });

    expect(hook.current.selectedGroupFilterId).toBe('group-1');
    expect(hook.current.selectedGroupFilterLabel).toBe('Admissions Intake');
  });
});
