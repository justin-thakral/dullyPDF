import { useCallback, useEffect, useMemo, useState } from 'react';
import type { User } from 'firebase/auth';
import type { CreditPricingConfig } from '../services/api';
import {
  estimateCreditsForPageCount,
  resolveClientCreditPricing,
  resolveOpenAiCreditOperation,
} from '../utils/creditPricing';
import { loadPdfFromFile } from '../utils/pdf';

type PipelineProfileSnapshot = {
  role?: string | null;
  availableCredits?: number | null;
  creditsRemaining?: number | null;
  creditPricing?: CreditPricingConfig | null;
} | null;

export interface UsePipelineModalDeps {
  verifiedUser: User | null;
  loadUserProfile: () => Promise<any>;
  userProfile?: PipelineProfileSnapshot;
  detectMaxPages: number;
  schemaId: string | null;
  schemaUploadInProgress: boolean;
  pendingSchemaPayload: any;
  persistSchemaPayload: (payload: any) => Promise<string | null>;
  setSchemaUploadInProgress: (value: boolean) => void;
  runDetectUpload: (
    file: File,
    options?: { autoRename?: boolean; autoMap?: boolean; schemaIdOverride?: string | null },
  ) => void;
}

export function usePipelineModal(deps: UsePipelineModalDeps) {
  const [showPipelineModal, setShowPipelineModal] = useState(false);
  const [pendingDetectFile, setPendingDetectFile] = useState<File | null>(null);
  const [pipelineError, setPipelineError] = useState<string | null>(null);
  const [uploadWantsRename, setUploadWantsRename] = useState(false);
  const [uploadWantsMap, setUploadWantsMap] = useState(false);
  const [pendingDetectPageCount, setPendingDetectPageCount] = useState<number | null>(null);
  const [pendingDetectPageCountLoading, setPendingDetectPageCountLoading] = useState(false);

  const openModal = useCallback((file: File) => {
    setPendingDetectFile(file);
    setShowPipelineModal(true);
    setPipelineError(null);
    setUploadWantsRename(false);
    setUploadWantsMap(false);
    setPendingDetectPageCount(null);
    setPendingDetectPageCountLoading(true);
  }, []);

  const cancel = useCallback(() => {
    setPendingDetectFile(null);
    setShowPipelineModal(false);
    setPipelineError(null);
    setPendingDetectPageCount(null);
    setPendingDetectPageCountLoading(false);
  }, []);

  useEffect(() => {
    if (!pendingDetectFile) {
      setPendingDetectPageCount(null);
      setPendingDetectPageCountLoading(false);
      return;
    }
    let cancelled = false;
    setPendingDetectPageCountLoading(true);
    void (async () => {
      let pdfDoc: { numPages?: number; destroy?: () => Promise<void> | void } | null = null;
      try {
        pdfDoc = await loadPdfFromFile(pendingDetectFile);
        if (cancelled) return;
        setPendingDetectPageCount(Math.max(1, Number(pdfDoc.numPages) || 1));
      } catch {
        if (!cancelled) {
          setPendingDetectPageCount(null);
        }
      } finally {
        if (pdfDoc && typeof pdfDoc.destroy === 'function') {
          const destroyResult = pdfDoc.destroy();
          if (destroyResult && typeof destroyResult === 'object' && 'catch' in destroyResult && typeof destroyResult.catch === 'function') {
            void destroyResult.catch(() => {});
          }
        }
        if (!cancelled) {
          setPendingDetectPageCountLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [pendingDetectFile]);

  const pendingDetectOperation = useMemo(
    () => resolveOpenAiCreditOperation(uploadWantsRename, uploadWantsMap),
    [uploadWantsMap, uploadWantsRename],
  );
  const pendingDetectPricing = useMemo(
    () => resolveClientCreditPricing(deps.userProfile?.creditPricing),
    [deps.userProfile?.creditPricing],
  );
  const pendingDetectCreditEstimate = useMemo(() => {
    if (!pendingDetectOperation || !pendingDetectPageCount) return null;
    return estimateCreditsForPageCount(
      pendingDetectOperation,
      pendingDetectPageCount,
      pendingDetectPricing,
    );
  }, [pendingDetectOperation, pendingDetectPageCount, pendingDetectPricing]);
  const pendingDetectWithinPageLimit = useMemo(() => {
    if (!pendingDetectPageCount) return true;
    return pendingDetectPageCount <= deps.detectMaxPages;
  }, [deps.detectMaxPages, pendingDetectPageCount]);
  const pendingDetectCreditsRemaining = useMemo(() => {
    const profile = deps.userProfile;
    if (!profile) return null;
    if (typeof profile.availableCredits === 'number') {
      return profile.availableCredits;
    }
    if (typeof profile.creditsRemaining === 'number') {
      return profile.creditsRemaining;
    }
    return null;
  }, [deps.userProfile]);

  const confirm = useCallback(async () => {
    if (!pendingDetectFile) return;
    if (pendingDetectPageCountLoading) {
      setPipelineError('Still counting PDF pages. Please wait a moment and try again.');
      return;
    }
    if (pendingDetectPageCount && pendingDetectPageCount > deps.detectMaxPages) {
      setPipelineError(`Detection uploads are limited to ${deps.detectMaxPages} pages on your plan.`);
      return;
    }
    const wantsRename = uploadWantsRename;
    const wantsMap = uploadWantsMap;
    if (wantsRename || wantsMap) {
      if (!deps.verifiedUser) {
        setPipelineError('Sign in to use OpenAI actions.');
        return;
      }
      const profile = await deps.loadUserProfile();
      if (!profile) {
        setPipelineError('Unable to check OpenAI credits. Try signing out and signing in again.');
        return;
      }
      const role = String(profile.role || '').toLowerCase();
      if (role !== 'god') {
        const operation = wantsRename && wantsMap ? 'rename_remap' : (wantsRename ? 'rename' : 'remap');
        const pricing = resolveClientCreditPricing(profile.creditPricing);
        const fallbackEstimate = estimateCreditsForPageCount(operation, 1, pricing);
        const requiredCredits = pendingDetectPageCount
          ? estimateCreditsForPageCount(operation, pendingDetectPageCount, pricing).totalCredits
          : fallbackEstimate.totalCredits;
        const remaining = typeof profile.availableCredits === 'number'
          ? profile.availableCredits
          : (typeof profile.creditsRemaining === 'number' ? profile.creditsRemaining : 0);
        if (remaining < requiredCredits) {
          if (role === 'pro') {
            setPipelineError(
              `OpenAI credits exhausted. Remaining=${remaining}, required=${requiredCredits}. ` +
              'Purchase a 500-credit refill from your profile to continue.',
            );
          } else {
            setPipelineError(
              `OpenAI credits exhausted. Remaining=${remaining}, required=${requiredCredits}. ` +
              'Upgrade to Pro from your profile to continue.',
            );
          }
          return;
        }
      }
    }
    let resolvedSchemaId = wantsMap ? deps.schemaId : null;
    if (wantsMap) {
      if (deps.schemaUploadInProgress) {
        setPipelineError('Schema file is still processing. Please wait.');
        return;
      }
      if (!resolvedSchemaId) {
        if (!deps.pendingSchemaPayload) {
          setPipelineError('Upload a schema file before running mapping.');
          return;
        }
        if (!deps.verifiedUser) {
          setPipelineError('Sign in to upload a schema file before running mapping.');
          return;
        }
        deps.setSchemaUploadInProgress(true);
        try {
          resolvedSchemaId = await deps.persistSchemaPayload(deps.pendingSchemaPayload);
        } finally {
          deps.setSchemaUploadInProgress(false);
        }
        if (!resolvedSchemaId) {
          setPipelineError('Failed to store schema metadata. Please re-upload your schema file.');
          return;
        }
      }
    }
    const file = pendingDetectFile;
    setPendingDetectFile(null);
    setShowPipelineModal(false);
    setPipelineError(null);
    setUploadWantsRename(false);
    setUploadWantsMap(false);
    setPendingDetectPageCount(null);
    setPendingDetectPageCountLoading(false);
    deps.runDetectUpload(file, {
      autoRename: wantsRename,
      autoMap: wantsMap,
      schemaIdOverride: wantsMap ? resolvedSchemaId : null,
    });
  }, [
    deps,
    pendingDetectFile,
    pendingDetectPageCount,
    pendingDetectPageCountLoading,
    uploadWantsMap,
    uploadWantsRename,
  ]);

  const reset = useCallback(() => {
    setPendingDetectFile(null);
    setShowPipelineModal(false);
    setPipelineError(null);
    setUploadWantsRename(false);
    setUploadWantsMap(false);
    setPendingDetectPageCount(null);
    setPendingDetectPageCountLoading(false);
  }, []);

  return {
    showPipelineModal,
    pendingDetectFile,
    pendingDetectPageCount,
    pendingDetectPageCountLoading,
    pendingDetectCreditEstimate,
    pendingDetectWithinPageLimit,
    pendingDetectCreditsRemaining,
    pipelineError,
    setPipelineError,
    uploadWantsRename,
    setUploadWantsRename,
    uploadWantsMap,
    setUploadWantsMap,
    openModal,
    cancel,
    confirm,
    reset,
  };
}
