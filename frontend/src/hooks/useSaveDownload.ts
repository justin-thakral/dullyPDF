import { useCallback, useState } from 'react';
import type { PDFDocumentProxy } from 'pdfjs-dist/types/src/display/api';
import type { User } from 'firebase/auth';
import type {
  BannerNotice,
  CheckboxRule,
  ConfirmDialogOptions,
  PdfField,
  PromptDialogOptions,
  TextTransformRule,
} from '../types';
import { normaliseFormName, prepareFieldsForMaterialize } from '../utils/fields';
import { debugLog } from '../utils/debug';
import { buildSavedFormEditorSnapshot } from '../utils/savedFormHydration';
import { ApiError } from '../services/apiConfig';
import type { MaterializePdfExportMode } from '../services/api';
import { ApiService } from '../services/api';

export interface UseSaveDownloadDeps {
  pdfDoc: PDFDocumentProxy | null;
  sourceFile: File | null;
  sourceFileName: string | null;
  fields: PdfField[];
  pageSizes: Record<number, { width: number; height: number }>;
  pageCount: number;
  checkboxRules: CheckboxRule[];
  textTransformRules: TextTransformRule[];
  hasRenamedFields: boolean;
  hasMappedSchema: boolean;
  mappingSessionId: string | null;
  activeSavedFormId: string | null;
  activeSavedFormName: string | null;
  activeGroupId?: string | null;
  activeGroupName?: string | null;
  savedFormsCount: number;
  savedFormsMax: number;
  verifiedUser: User | null;
  setBannerNotice: (notice: BannerNotice | null) => void;
  setLoadError: (message: string | null) => void;
  requestConfirm: (options: ConfirmDialogOptions) => Promise<boolean>;
  requestPrompt: (options: PromptDialogOptions) => Promise<string | null>;
  refreshSavedForms: (opts?: { allowRetry?: boolean; throwOnError?: boolean }) => Promise<unknown>;
  refreshGroups?: () => Promise<unknown> | void;
  refreshProfile?: () => Promise<unknown> | void;
  setActiveSavedFormId: (id: string | null) => void;
  setActiveSavedFormName: (name: string | null) => void;
  markGroupTemplatesPersisted?: (formIds?: string[]) => void;
  queueSaveAfterLimit: (action: () => Promise<void>) => void;
  allowAnonymousDownload?: boolean;
  onSaveSuccess?: (fields: PdfField[], checkboxRules: CheckboxRule[]) => void;
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
        const editorSnapshot = buildSavedFormEditorSnapshot({
          pageCount: deps.pageCount || deps.pdfDoc.numPages,
          pageSizes: deps.pageSizes,
          fields: fieldsForSave,
          hasRenamedFields: deps.hasRenamedFields,
          hasMappedSchema: deps.hasMappedSchema,
        });
        const generatedBlob = await ApiService.materializeFormPdf(blob, fieldsForSave);
        const payload = await ApiService.saveFormToProfile(
          generatedBlob, saveName, deps.mappingSessionId || undefined,
          overwriteFormId || undefined, deps.checkboxRules, deps.textTransformRules,
          editorSnapshot,
        );
        deps.setActiveSavedFormId(payload?.id || null);
        deps.setActiveSavedFormName(payload?.name || saveName);
        const refreshResults = await Promise.allSettled([
          deps.refreshSavedForms(),
          Promise.resolve().then(() => deps.refreshGroups?.()),
          Promise.resolve().then(() => deps.refreshProfile?.()),
        ]);
        for (const result of refreshResults) {
          if (result.status === 'rejected') {
            debugLog('Failed to refresh workspace state after saving form', result.reason);
          }
        }
        if (overwriteFormId) {
          deps.markGroupTemplatesPersisted?.([overwriteFormId]);
        }
        deps.onSaveSuccess?.(deps.fields, deps.checkboxRules);
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
    if (deps.activeSavedFormId && deps.activeGroupId) {
      const overwrite = await deps.requestConfirm({
        title: 'Overwrite group template?',
        message: `Save changes back to "${deps.activeSavedFormName || defaultName}" in "${deps.activeGroupName || 'this group'}"? Saving a new copy is disabled while a group is open so the active template does not leave the group.`,
        confirmLabel: 'Overwrite',
        cancelLabel: 'Cancel',
        tone: 'danger',
      });
      if (overwrite) { shouldOverwrite = true; }
      else { return; }
    } else if (deps.activeSavedFormId) {
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

  const handleDownload = useCallback(async (exportMode: MaterializePdfExportMode = 'editable') => {
    if (!deps.pdfDoc) { deps.setLoadError('No PDF is loaded to download.'); return; }
    if (!deps.verifiedUser && !deps.allowAnonymousDownload) {
      deps.setLoadError('Sign in to download this form.');
      return;
    }
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
      const generatedBlob = await ApiService.materializeFormPdf(blob, fieldsForDownload, { exportMode });
      const baseName = normaliseFormName(deps.activeSavedFormName || deps.sourceFileName || deps.sourceFile?.name);
      const filename = exportMode === 'flat'
        ? `${baseName}-flat.pdf`
        : `${baseName}-editable.pdf`;
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
