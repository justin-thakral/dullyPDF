import { useCallback, useRef, useState } from 'react';
import type { BannerNotice, ConfirmDialogOptions, DialogRequest, PromptDialogOptions } from '../types';

type DialogResolution = boolean | string | null;

export function useDialog() {
  const [dialogRequest, setDialogRequest] = useState<DialogRequest | null>(null);
  const [bannerNotice, setBannerNotice] = useState<BannerNotice | null>(null);
  const dialogResolverRef = useRef<((value: DialogResolution) => void) | null>(null);

  const resolveDialog = useCallback((value: DialogResolution) => {
    const resolver = dialogResolverRef.current;
    dialogResolverRef.current = null;
    setDialogRequest(null);
    if (resolver) {
      resolver(value);
    }
  }, []);

  const requestConfirm = useCallback((options: ConfirmDialogOptions) => {
    return new Promise<boolean | null>((resolve) => {
      dialogResolverRef.current = resolve as (value: DialogResolution) => void;
      setDialogRequest({ kind: 'confirm', ...options });
    });
  }, []);

  const requestPrompt = useCallback((options: PromptDialogOptions) => {
    return new Promise<string | null>((resolve) => {
      dialogResolverRef.current = resolve as (value: DialogResolution) => void;
      setDialogRequest({ kind: 'prompt', ...options });
    });
  }, []);

  const handleDismissBanner = useCallback((openAiError: string | null, schemaError: string | null) => {
    if (openAiError || schemaError) return;
    if (bannerNotice) {
      setBannerNotice(null);
    }
  }, [bannerNotice]);

  const dismissDialogOnClear = useCallback((currentRequest: DialogRequest | null) => {
    if (dialogResolverRef.current) {
      const fallback =
        currentRequest?.kind === 'confirm'
          ? false
          : currentRequest?.kind === 'prompt'
            ? null
            : null;
      dialogResolverRef.current(fallback);
    }
    dialogResolverRef.current = null;
    setDialogRequest(null);
  }, []);

  const reset = useCallback((currentRequest?: DialogRequest | null) => {
    setBannerNotice(null);
    dismissDialogOnClear(currentRequest ?? dialogRequest);
  }, [dialogRequest, dismissDialogOnClear]);

  return {
    dialogRequest,
    bannerNotice,
    setBannerNotice,
    resolveDialog,
    requestConfirm,
    requestPrompt,
    handleDismissBanner,
    dismissDialogOnClear,
    reset,
  };
}
