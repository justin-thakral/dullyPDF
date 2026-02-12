import { useCallback, useState } from 'react';
import type { User } from 'firebase/auth';

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
      const requiredCredits = wantsRename && wantsMap ? 2 : 1;
      const profile = await deps.loadUserProfile();
      if (!profile) { setPipelineError('Unable to check OpenAI credits. Try signing out and signing in again.'); return; }
      const role = String(profile.role || '').toLowerCase();
      if (role !== 'god') {
        const remaining = typeof profile.creditsRemaining === 'number' ? profile.creditsRemaining : 0;
        if (remaining < requiredCredits) {
          setPipelineError(`OpenAI credits exhausted. Remaining=${remaining}, required=${requiredCredits}. Uncheck OpenAI actions to run field detection without AI.`);
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
