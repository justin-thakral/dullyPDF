import { useCallback, useState } from 'react';
import type { PDFDocumentProxy } from 'pdfjs-dist/types/src/display/api';
import type { User } from 'firebase/auth';
import type { BannerNotice, CheckboxHint, CheckboxRule, ConfirmDialogOptions, PdfField, PromptDialogOptions } from '../types';
import { normaliseFormName, prepareFieldsForMaterialize } from '../utils/fields';
import { debugLog } from '../utils/debug';
import { ApiError } from '../services/apiConfig';
import { ApiService } from '../services/api';

export interface UseSaveDownloadDeps {
  pdfDoc: PDFDocumentProxy | null;
  sourceFile: File | null;
  sourceFileName: string | null;
  fields: PdfField[];
  checkboxRules: CheckboxRule[];
  checkboxHints: CheckboxHint[];
  mappingSessionId: string | null;
  activeSavedFormId: string | null;
  activeSavedFormName: string | null;
  savedFormsCount: number;
  savedFormsMax: number;
  verifiedUser: User | null;
  setBannerNotice: (notice: BannerNotice | null) => void;
  setLoadError: (message: string | null) => void;
  requestConfirm: (options: ConfirmDialogOptions) => Promise<boolean>;
  requestPrompt: (options: PromptDialogOptions) => Promise<string | null>;
  refreshSavedForms: (opts?: { allowRetry?: boolean }) => Promise<void>;
  setActiveSavedFormId: (id: string | null) => void;
  setActiveSavedFormName: (name: string | null) => void;
  queueSaveAfterLimit: (action: () => Promise<void>) => void;
}

export function useSaveDownload(deps: UseSaveDownloadDeps) {
  const [saveInProgress, setSaveInProgress] = useState(false);
  const [downloadInProgress, setDownloadInProgress] = useState(false);

  const saveFormToProfile = useCallback(
    async ({
      saveName,
      overwriteFormId,
    }: { saveName: string; overwriteFormId?: string | null }): Promise<{ success: boolean; limitReached: boolean }> => {
      if (!deps.pdfDoc) {
        deps.setBannerNotice({ tone: 'error', message: 'No PDF is loaded to save.' });
        return { success: false, limitReached: false };
      }
      setSaveInProgress(true);
      try {
        let blob: Blob;
        if (deps.sourceFile) { blob = deps.sourceFile; }
        else {
          const data = await deps.pdfDoc.getData();
          blob = new Blob([new Uint8Array(data)], { type: 'application/pdf' });
        }
        const fieldsForSave = prepareFieldsForMaterialize(deps.fields);
        const generatedBlob = await ApiService.materializeFormPdf(blob, fieldsForSave);
        const rulesForSave = deps.checkboxRules.length ? deps.checkboxRules : undefined;
        const hintsForSave = deps.checkboxHints.length ? deps.checkboxHints : undefined;
        const payload = await ApiService.saveFormToProfile(
          generatedBlob, saveName, deps.mappingSessionId || undefined,
          overwriteFormId || undefined, rulesForSave, hintsForSave,
        );
        deps.setActiveSavedFormId(payload?.id || null);
        deps.setActiveSavedFormName(payload?.name || saveName);
        await deps.refreshSavedForms();
        return { success: true, limitReached: false };
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Failed to save form to profile.';
        const limitReached =
          error instanceof ApiError && error.status === 403 && message.toLowerCase().includes('saved form limit');
        if (!limitReached) deps.setBannerNotice({ tone: 'error', message });
        debugLog('Failed to save form', message);
        return { success: false, limitReached };
      } finally {
        setSaveInProgress(false);
      }
    },
    [deps],
  );

  const handleSaveToProfile = useCallback(async () => {
    if (!deps.pdfDoc) { deps.setBannerNotice({ tone: 'error', message: 'No PDF is loaded to save.' }); return; }
    if (!deps.verifiedUser) { deps.setBannerNotice({ tone: 'error', message: 'Sign in to save this form to your profile.' }); return; }
    const maxSavedForms = deps.savedFormsMax;
    const savedFormsLimitReached = deps.savedFormsCount >= maxSavedForms;
    deps.setLoadError(null);
    const defaultName = normaliseFormName(deps.activeSavedFormName || deps.sourceFileName || deps.sourceFile?.name);
    const promptForName = async ({ forceSave = false }: { forceSave?: boolean } = {}) => {
      const raw = await deps.requestPrompt({
        title: 'Name this saved form', message: 'Enter a name to store this PDF in your saved forms list.',
        defaultValue: defaultName, placeholder: 'Saved form name', confirmLabel: 'Save',
        cancelLabel: 'Cancel', requireValue: true,
      });
      if (raw === null) return forceSave ? defaultName : null;
      const trimmed = raw.trim();
      if (!trimmed) {
        if (forceSave) return defaultName;
        deps.setBannerNotice({ tone: 'error', message: 'A form name is required to save.' });
        return null;
      }
      return normaliseFormName(trimmed);
    };
    const attemptSaveNew = async ({ forceSave = false }: { forceSave?: boolean } = {}) => {
      const nextName = await promptForName({ forceSave });
      if (!nextName) return;
      const result = await saveFormToProfile({ saveName: nextName });
      if (!result.success && result.limitReached) {
        deps.queueSaveAfterLimit(() => attemptSaveNew({ forceSave: true }));
      }
    };
    let shouldOverwrite = false;
    if (deps.activeSavedFormId) {
      const overwrite = await deps.requestConfirm({
        title: 'Overwrite saved form?',
        message: 'This form is already saved. Overwrite it or save a new copy with a different name.',
        confirmLabel: 'Overwrite', cancelLabel: 'Save new copy', tone: 'danger',
      });
      if (overwrite) { shouldOverwrite = true; }
      else {
        if (savedFormsLimitReached) { deps.queueSaveAfterLimit(() => attemptSaveNew({ forceSave: true })); return; }
        await attemptSaveNew(); return;
      }
    } else {
      if (savedFormsLimitReached) { deps.queueSaveAfterLimit(() => attemptSaveNew({ forceSave: true })); return; }
      await attemptSaveNew(); return;
    }
    if (shouldOverwrite) {
      const result = await saveFormToProfile({ saveName: defaultName, overwriteFormId: deps.activeSavedFormId });
      if (!result.success && result.limitReached) {
        deps.setBannerNotice({ tone: 'error', message: 'Unable to overwrite saved form at the current limit.' });
      }
    }
  }, [deps, saveFormToProfile]);

  const handleDownload = useCallback(async () => {
    if (!deps.pdfDoc) { deps.setLoadError('No PDF is loaded to download.'); return; }
    if (!deps.verifiedUser) { deps.setLoadError('Sign in to download this form.'); return; }
    deps.setLoadError(null);
    setDownloadInProgress(true);
    try {
      let blob: Blob;
      if (deps.sourceFile) { blob = deps.sourceFile; }
      else {
        const data = await deps.pdfDoc.getData();
        blob = new Blob([new Uint8Array(data)], { type: 'application/pdf' });
      }
      const fieldsForDownload = prepareFieldsForMaterialize(deps.fields);
      const generatedBlob = await ApiService.materializeFormPdf(blob, fieldsForDownload);
      const baseName = normaliseFormName(deps.activeSavedFormName || deps.sourceFileName || deps.sourceFile?.name);
      const filename = `${baseName}-fillable.pdf`;
      const url = URL.createObjectURL(generatedBlob);
      const link = document.createElement('a');
      link.href = url; link.download = filename;
      document.body.appendChild(link); link.click(); link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to download form.';
      deps.setLoadError(message); debugLog('Failed to download form', message);
    } finally { setDownloadInProgress(false); }
  }, [deps]);

  return {
    saveInProgress,
    downloadInProgress,
    handleSaveToProfile,
    handleDownload,
  };
}
