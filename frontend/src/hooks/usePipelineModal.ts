import { useCallback, useState } from 'react';
import type { User } from 'firebase/auth';
import { loadPdfFromFile } from '../utils/pdf';

export interface UsePipelineModalDeps {
  verifiedUser: User | null;
  loadUserProfile: () => Promise<any>;
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

  const openModal = useCallback((file: File) => {
    setPendingDetectFile(file);
    setShowPipelineModal(true);
    setPipelineError(null);
    setUploadWantsRename(false);
    setUploadWantsMap(false);
  }, []);

  const cancel = useCallback(() => {
    setPendingDetectFile(null);
    setShowPipelineModal(false);
    setPipelineError(null);
  }, []);

  const confirm = useCallback(async () => {
    if (!pendingDetectFile) return;
    const wantsRename = uploadWantsRename;
    const wantsMap = uploadWantsMap;
    if (wantsRename || wantsMap) {
      if (!deps.verifiedUser) { setPipelineError('Sign in to use OpenAI actions.'); return; }
      const profile = await deps.loadUserProfile();
      if (!profile) { setPipelineError('Unable to check OpenAI credits. Try signing out and signing in again.'); return; }
      const role = String(profile.role || '').toLowerCase();
      if (role !== 'god') {
        const operation = wantsRename && wantsMap ? 'rename_remap' : (wantsRename ? 'rename' : 'remap');
        const pricing = profile.creditPricing ?? {
          pageBucketSize: 5,
          renameBaseCost: 1,
          remapBaseCost: 1,
          renameRemapBaseCost: 2,
        };
        const baseCost = operation === 'rename_remap'
          ? pricing.renameRemapBaseCost
          : (operation === 'rename' ? pricing.renameBaseCost : pricing.remapBaseCost);
        let requiredCredits = baseCost;
        try {
          const pdfDoc = await loadPdfFromFile(pendingDetectFile);
          const pageCount = Math.max(1, Number(pdfDoc.numPages) || 1);
          const bucketSize = Math.max(1, Number(pricing.pageBucketSize) || 1);
          const bucketCount = Math.ceil(pageCount / bucketSize);
          requiredCredits = Math.max(1, baseCost * bucketCount);
          void pdfDoc.destroy().catch(() => {});
        } catch {
          // If local page counting fails, continue with the single-bucket estimate
          // and rely on server-side pricing enforcement as a final guard.
          requiredCredits = Math.max(1, baseCost);
        }
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
      if (deps.schemaUploadInProgress) { setPipelineError('Schema file is still processing. Please wait.'); return; }
      if (!resolvedSchemaId) {
        if (!deps.pendingSchemaPayload) { setPipelineError('Upload a schema file before running mapping.'); return; }
        if (!deps.verifiedUser) { setPipelineError('Sign in to upload a schema file before running mapping.'); return; }
        deps.setSchemaUploadInProgress(true);
        try { resolvedSchemaId = await deps.persistSchemaPayload(deps.pendingSchemaPayload); }
        finally { deps.setSchemaUploadInProgress(false); }
        if (!resolvedSchemaId) { setPipelineError('Failed to store schema metadata. Please re-upload your schema file.'); return; }
      }
    }
    const file = pendingDetectFile;
    setPendingDetectFile(null); setShowPipelineModal(false); setPipelineError(null);
    setUploadWantsRename(false); setUploadWantsMap(false);
    deps.runDetectUpload(file, { autoRename: wantsRename, autoMap: wantsMap, schemaIdOverride: wantsMap ? resolvedSchemaId : null });
  }, [deps, pendingDetectFile, uploadWantsMap, uploadWantsRename]);

  const reset = useCallback(() => {
    setPendingDetectFile(null);
    setShowPipelineModal(false);
    setPipelineError(null);
    setUploadWantsRename(false);
    setUploadWantsMap(false);
  }, []);

  return {
    showPipelineModal,
    pendingDetectFile,
    pipelineError, setPipelineError,
    uploadWantsRename, setUploadWantsRename,
    uploadWantsMap, setUploadWantsMap,
    openModal,
    cancel,
    confirm,
    reset,
  };
}
