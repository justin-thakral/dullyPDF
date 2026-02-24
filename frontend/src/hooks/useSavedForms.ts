import { useCallback, useRef, useState } from 'react';
import type { User } from 'firebase/auth';
import type { BannerNotice, ConfirmDialogOptions } from '../types';
import { ApiService } from '../services/api';
import {
  SAVED_FORMS_RETRY_BASE_MS,
  SAVED_FORMS_RETRY_LIMIT,
  SAVED_FORMS_RETRY_MAX_MS,
  SAVED_FORMS_TIMEOUT_MS,
} from '../config/appConstants';
import { debugLog } from '../utils/debug';

export function useSavedForms(deps: {
  authUserRef: React.MutableRefObject<User | null>;
  setBannerNotice: (notice: BannerNotice | null) => void;
  requestConfirm: (options: ConfirmDialogOptions) => Promise<boolean>;
}) {
  const [savedForms, setSavedForms] = useState<Array<{ id: string; name: string; createdAt: string }>>([]);
  const [savedFormsLoading, setSavedFormsLoading] = useState(false);
  const [activeSavedFormId, setActiveSavedFormId] = useState<string | null>(null);
  const [activeSavedFormName, setActiveSavedFormName] = useState<string | null>(null);
  const [deletingFormId, setDeletingFormId] = useState<string | null>(null);
  const [showSavedFormsLimitDialog, setShowSavedFormsLimitDialog] = useState(false);
  const savedFormsRetryRef = useRef(0);
  const savedFormsRetryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingSaveActionRef = useRef<(() => Promise<void>) | null>(null);

  const clearSavedFormsRetry = useCallback(() => {
    if (savedFormsRetryTimerRef.current) {
      clearTimeout(savedFormsRetryTimerRef.current);
      savedFormsRetryTimerRef.current = null;
    }
    savedFormsRetryRef.current = 0;
  }, []);

  const refreshSavedForms = useCallback(
    async (options?: { allowRetry?: boolean }) => {
      const currentUser = deps.authUserRef.current;
      if (!currentUser) return;
      setSavedFormsLoading(true);
      try {
        const forms = await ApiService.getSavedForms({
          suppressErrors: false,
          timeoutMs: SAVED_FORMS_TIMEOUT_MS,
        });
        setSavedForms(forms || []);
        setSavedFormsLoading(false);
        clearSavedFormsRetry();
      } catch (error) {
        if (!options?.allowRetry || !(error instanceof TypeError)) {
          setSavedFormsLoading(false);
          debugLog('Failed to load saved forms', error);
          return;
        }
        const attempt = savedFormsRetryRef.current + 1;
        if (attempt > SAVED_FORMS_RETRY_LIMIT) {
          setSavedFormsLoading(false);
          debugLog('Saved forms retry limit reached', error);
          return;
        }
        savedFormsRetryRef.current = attempt;
        const delay = Math.min(
          SAVED_FORMS_RETRY_MAX_MS,
          SAVED_FORMS_RETRY_BASE_MS * 2 ** (attempt - 1),
        );
        if (savedFormsRetryTimerRef.current) {
          clearTimeout(savedFormsRetryTimerRef.current);
        }
        savedFormsRetryTimerRef.current = setTimeout(() => {
          void refreshSavedForms(options);
        }, delay);
      }
    },
    [clearSavedFormsRetry, deps.authUserRef],
  );

  const deleteSavedFormById = useCallback(
    async (formId: string): Promise<boolean> => {
      setDeletingFormId(formId);
      try {
        await ApiService.deleteSavedForm(formId);
        setSavedForms((prev) => prev.filter((form) => form.id !== formId));
        setActiveSavedFormId((prev) => {
          if (prev === formId) {
            setActiveSavedFormName(null);
            return null;
          }
          return prev;
        });
        return true;
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Failed to delete saved form.';
        deps.setBannerNotice({ tone: 'error', message });
        debugLog('Failed to delete saved form', message);
        return false;
      } finally {
        setDeletingFormId(null);
      }
    },
    [deps],
  );

  const handleDeleteSavedForm = useCallback(
    async (formId: string) => {
      const target = savedForms.find((form) => form.id === formId);
      const name = target?.name ? `"${target.name}"` : 'this saved form';
      const confirmDelete = await deps.requestConfirm({
        title: 'Delete saved form?',
        message: `Delete ${name}? This removes it from your saved forms.`,
        confirmLabel: 'Delete',
        cancelLabel: 'Cancel',
        tone: 'danger',
      });
      if (!confirmDelete) return;
      await deleteSavedFormById(formId);
    },
    [deleteSavedFormById, deps, savedForms],
  );

  const handleSavedFormsLimitDelete = useCallback(
    async (formId: string) => {
      const removed = await deleteSavedFormById(formId);
      if (!removed) return;
      const pendingAction = pendingSaveActionRef.current;
      if (!pendingAction) return;
      pendingSaveActionRef.current = null;
      setShowSavedFormsLimitDialog(false);
      await pendingAction();
    },
    [deleteSavedFormById],
  );

  const queueSaveAfterLimit = useCallback(
    (action: () => Promise<void>) => {
      pendingSaveActionRef.current = action;
      setShowSavedFormsLimitDialog(true);
      void refreshSavedForms({ allowRetry: true });
    },
    [refreshSavedForms],
  );

  const closeSavedFormsLimitDialog = useCallback(() => {
    pendingSaveActionRef.current = null;
    setShowSavedFormsLimitDialog(false);
  }, []);

  const clearSavedForms = useCallback(() => {
    setSavedForms([]);
    setSavedFormsLoading(false);
  }, []);

  const reset = useCallback(() => {
    setActiveSavedFormId(null);
    setActiveSavedFormName(null);
    setSavedFormsLoading(false);
    setShowSavedFormsLimitDialog(false);
    pendingSaveActionRef.current = null;
  }, []);

  return {
    savedForms,
    savedFormsLoading,
    setSavedForms,
    activeSavedFormId,
    setActiveSavedFormId,
    activeSavedFormName,
    setActiveSavedFormName,
    deletingFormId,
    showSavedFormsLimitDialog,
    setShowSavedFormsLimitDialog,
    pendingSaveActionRef,
    clearSavedFormsRetry,
    clearSavedForms,
    refreshSavedForms,
    deleteSavedFormById,
    handleDeleteSavedForm,
    handleSavedFormsLimitDelete,
    queueSaveAfterLimit,
    closeSavedFormsLimitDialog,
    reset,
  };
}
