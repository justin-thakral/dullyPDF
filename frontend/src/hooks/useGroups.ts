import { useCallback, useEffect, useMemo, useState, type SetStateAction } from 'react';
import type { BannerNotice } from '../types';
import { ApiService, type TemplateGroupSummary } from '../services/api';

const ALL_SAVED_FORMS_FILTER_ID = 'all';
const ALL_SAVED_FORMS_FILTER_LABEL = 'All saved forms';

type UseGroupsDeps = {
  verifiedUser: unknown;
  setBannerNotice: (notice: BannerNotice | null) => void;
};

export function useGroups(deps: UseGroupsDeps) {
  const { verifiedUser, setBannerNotice } = deps;
  const [groups, setGroups] = useState<TemplateGroupSummary[]>([]);
  const [groupsLoading, setGroupsLoading] = useState(false);
  const [groupsCreating, setGroupsCreating] = useState(false);
  const [updatingGroupId, setUpdatingGroupId] = useState<string | null>(null);
  const [deletingGroupId, setDeletingGroupId] = useState<string | null>(null);
  const [selectedGroupFilterState, setSelectedGroupFilterState] = useState<{
    id: string;
    label: string | null;
  }>({
    id: ALL_SAVED_FORMS_FILTER_ID,
    label: ALL_SAVED_FORMS_FILTER_LABEL,
  });

  const selectedGroupFilterId = selectedGroupFilterState.id;
  const selectedGroupFilterLabel = selectedGroupFilterState.label;

  const setSelectedGroupFilterId = useCallback((value: SetStateAction<string>) => {
    setSelectedGroupFilterState((prev) => {
      const nextId = typeof value === 'function' ? value(prev.id) : value;
      if (nextId === ALL_SAVED_FORMS_FILTER_ID) {
        return {
          id: ALL_SAVED_FORMS_FILTER_ID,
          label: ALL_SAVED_FORMS_FILTER_LABEL,
        };
      }
      const nextGroup = groups.find((group) => group.id === nextId) ?? null;
      return {
        id: nextId,
        label: nextGroup?.name ?? (prev.id === nextId ? prev.label : null),
      };
    });
  }, [groups]);

  const refreshGroups = useCallback(async (options?: { throwOnError?: boolean }) => {
    if (!verifiedUser) {
      setGroups([]);
      setGroupsLoading(false);
      return [];
    }
    setGroupsLoading(true);
    try {
      const nextGroups = await ApiService.getGroups();
      setGroups(nextGroups);
      return nextGroups;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to load groups.';
      setBannerNotice({ tone: 'error', message });
      if (options?.throwOnError) {
        throw error;
      }
      return [];
    } finally {
      setGroupsLoading(false);
    }
  }, [setBannerNotice, verifiedUser]);

  const createGroup = useCallback(async (
    payload: { name: string; templateIds: string[] },
    options?: { signal?: AbortSignal },
  ) => {
    setGroupsCreating(true);
    try {
      const nextGroup = await ApiService.createGroup(payload, options);
      setGroups((prev) => {
        const others = prev.filter((group) => group.id !== nextGroup.id);
        return [...others, nextGroup].sort((left, right) => left.name.localeCompare(right.name));
      });
      setSelectedGroupFilterState({
        id: nextGroup.id,
        label: nextGroup.name,
      });
      return nextGroup;
    } finally {
      setGroupsCreating(false);
    }
  }, []);

  const updateExistingGroup = useCallback(async (
    groupId: string,
    payload: { name: string; templateIds: string[] },
  ) => {
    setUpdatingGroupId(groupId);
    try {
      const nextGroup = await ApiService.updateGroup(groupId, payload);
      setGroups((prev) => {
        const others = prev.filter((group) => group.id !== nextGroup.id);
        return [...others, nextGroup].sort((left, right) => left.name.localeCompare(right.name));
      });
      setSelectedGroupFilterState((prev) => (
        prev.id === groupId
          ? { id: nextGroup.id, label: nextGroup.name }
          : prev
      ));
      return nextGroup;
    } finally {
      setUpdatingGroupId(null);
    }
  }, []);

  const deleteGroup = useCallback(async (groupId: string) => {
    setDeletingGroupId(groupId);
    try {
      await ApiService.deleteGroup(groupId);
      setGroups((prev) => prev.filter((group) => group.id !== groupId));
      setSelectedGroupFilterState((prev) => (
        prev.id === groupId
          ? { id: ALL_SAVED_FORMS_FILTER_ID, label: ALL_SAVED_FORMS_FILTER_LABEL }
          : prev
      ));
    } finally {
      setDeletingGroupId(null);
    }
  }, []);

  const activeFilterGroup = useMemo(
    () => groups.find((group) => group.id === selectedGroupFilterId) ?? null,
    [groups, selectedGroupFilterId],
  );

  useEffect(() => {
    void refreshGroups();
  }, [refreshGroups]);

  useEffect(() => {
    if (selectedGroupFilterId === ALL_SAVED_FORMS_FILTER_ID) return;
    const selectedGroup = groups.find((group) => group.id === selectedGroupFilterId) ?? null;
    if (selectedGroup) {
      if (selectedGroupFilterLabel === selectedGroup.name) {
        return;
      }
      setSelectedGroupFilterState({
        id: selectedGroup.id,
        label: selectedGroup.name,
      });
      return;
    }
    if (groupsLoading) {
      return;
    }
    setSelectedGroupFilterState({
      id: ALL_SAVED_FORMS_FILTER_ID,
      label: ALL_SAVED_FORMS_FILTER_LABEL,
    });
  }, [groups, groupsLoading, selectedGroupFilterId, selectedGroupFilterLabel]);

  return {
    groups,
    setGroups,
    groupsLoading,
    groupsCreating,
    updatingGroupId,
    deletingGroupId,
    selectedGroupFilterId,
    selectedGroupFilterLabel,
    setSelectedGroupFilterId,
    activeFilterGroup,
    refreshGroups,
    createGroup,
    updateExistingGroup,
    deleteGroup,
  };
}
