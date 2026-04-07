import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { User } from 'firebase/auth';
import type { PDFDocumentProxy } from 'pdfjs-dist/types/src/display/api';
import type {
  BannerNotice,
  CheckboxRule,
  PageSize,
  PdfField,
  PendingAutoActions,
  ProcessingMode,
  RadioGroupSuggestion,
  TextTransformRule,
} from '../types';
import {
  DETECTION_WAITING_DETECTOR_MESSAGE,
  mapDetectionFields,
  resolveDetectionStatusMessage,
} from '../utils/detection';
import { extractFieldsFromPdf, loadPageSizes, loadPdfFromFile } from '../utils/pdf';
import { buildTemplateFields } from '../utils/fields';
import { debugLog } from '../utils/debug';
import {
  buildSavedFormEditorSnapshot,
  extractSavedFormFillRuleState,
  normalizeSavedFormEditorSnapshot,
} from '../utils/savedFormHydration';
import { ApiError } from '../services/apiConfig';
import { ApiService } from '../services/api';
import { detectFields, pollDetectionStatus } from '../services/detectionApi';
import {
  DETECTION_POST_WARMUP_MESSAGE,
  DETECTION_WARMUP_DELAY_MS,
  DETECTION_WARMUP_DURATION_MS,
  DETECTION_WARMUP_MESSAGE,
  DETECTION_WARMUP_PAGE_THRESHOLD,
  DEMO_ASSETS,
  DETECTION_BACKGROUND_MAX_RETRIES,
  DETECTION_BACKGROUND_POLL_TIMEOUT_MS,
  DETECTION_BACKGROUND_RETRY_BASE_MS,
  DETECTION_BACKGROUND_RETRY_MAX_MS,
  QUEUE_WAIT_THRESHOLD_MS,
} from '../config/appConstants';
import { resolveProcessingCopy, type ProcessingVariant } from '../utils/processing';

const DEMO_ASSET_NAME_SET = new Set(Object.values(DEMO_ASSETS));

export type SavedFormSessionResume = {
  sessionId: string;
  fieldCount: number | null;
  pageCount: number | null;
};

export type WorkspaceSessionRestoreSnapshot = {
  sessionId: string;
  detectionStatus: string | null;
  fields: PdfField[];
  checkboxRules: CheckboxRule[];
  textTransformRules: TextTransformRule[];
};

export interface UseDetectionDeps {
  verifiedUser: User | null;
  profileLimits: { detectMaxPages: number; fillableMaxPages: number };
  fieldsRef: React.MutableRefObject<PdfField[]>;
  historyRef: React.MutableRefObject<{ undo: PdfField[][]; redo: PdfField[][] }>;
  resetFieldHistory: (fields?: PdfField[]) => void;
  updateFields: (fields: PdfField[], options?: { trackHistory?: boolean }) => void;
  setSelectedFieldId: (updater: string | null | ((prev: string | null) => string | null)) => void;
  clearWorkspace: () => void;
  setBannerNotice: (notice: BannerNotice | null) => void;
  setShowHomepage: (value: boolean) => void;
  setHasRenamedFields: (value: boolean) => void;
  setHasMappedSchema: (value: boolean) => void;
  setCheckboxRules: (rules: CheckboxRule[]) => void;
  setRadioGroupSuggestions: (suggestions: RadioGroupSuggestion[]) => void;
  setTextTransformRules: (rules: TextTransformRule[]) => void;
  setSchemaError: (value: string | null) => void;
  setOpenAiError: (value: string | null) => void;
  setSourceFile: (file: File | null) => void;
  setSourceFileName: (name: string | null) => void;
  setSourceFileIsDemo: (value: boolean) => void;
  markSavedFillLinkSnapshot: (fields: PdfField[], checkboxRules: CheckboxRule[]) => void;
  setActiveSavedFormId: (id: string | null) => void;
  setActiveSavedFormName: (name: string | null) => void;
  setShowSearchFill: (value: boolean) => void;
  setSearchFillSessionId: (updater: (prev: number) => number) => void;
  setLoadError: (message: string | null) => void;
  runOpenAiRename: (options?: {
    confirm?: boolean;
    allowDefer?: boolean;
    sessionId?: string | null;
    schemaId?: string | null;
  }) => Promise<PdfField[] | null>;
  applySchemaMappings: (options?: {
    fieldsOverride?: PdfField[];
    schemaIdOverride?: string | null;
  }) => Promise<boolean>;
  handleMappingSuccess: () => void;
  schemaId: string | null;
  // Session keep-alive deps
  pdfDoc: PDFDocumentProxy | null;
  sourceFileIsDemo: boolean;
  sourceFileName: string | null;
  demoStateRef: React.MutableRefObject<{ demoActive: boolean; demoCompletionOpen: boolean }>;
}

function isAbortError(error: unknown): boolean {
  if (error instanceof DOMException && error.name === 'AbortError') {
    return true;
  }
  return error instanceof Error && (error.name === 'AbortError' || error.message.toLowerCase().includes('aborted'));
}

function clonePdfFields(fields: PdfField[]): PdfField[] {
  return fields.map((field) => ({
    ...field,
    rect: { ...field.rect },
  }));
}

function hasMappedSchemaState(
  fields: PdfField[],
  checkboxRules: CheckboxRule[],
  textTransformRules: TextTransformRule[],
): boolean {
  return (
    fields.some((field) => typeof field.mappingConfidence === 'number')
    || checkboxRules.length > 0
    || textTransformRules.length > 0
  );
}

function resolveAutoOpenAiInProgressMessage(options: {
  autoRename: boolean;
  autoMap: boolean;
}): string | null {
  if (options.autoRename && options.autoMap) {
    return 'Fields are still renaming and mapping. You can review the editor while OpenAI finishes.';
  }
  if (options.autoRename) {
    return 'Fields are still renaming. You can review the editor while OpenAI finishes.';
  }
  if (options.autoMap) {
    return 'Field mappings are still generating. You can review the editor while OpenAI finishes.';
  }
  return null;
}

export function useDetection(deps: UseDetectionDeps) {
  const [detectSessionId, setDetectSessionId] = useState<string | null>(null);
  const [mappingSessionId, setMappingSessionId] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingMode, setProcessingMode] = useState<ProcessingMode>(null);
  const [processingVariant, setProcessingVariant] = useState<ProcessingVariant>('detect');
  const [processingDetail, setProcessingDetail] = useState(resolveProcessingCopy('detect').detail);
  const processingHeading = useMemo(
    () => resolveProcessingCopy(processingVariant).heading,
    [processingVariant],
  );
  const loadTokenRef = useRef(0);
  const detectionRetryRef = useRef<Map<string, number>>(new Map());
  const resumeDetectionPollingRef = useRef<((sessionId: string, loadToken: number) => void) | null>(null);
  const pendingAutoActionsRef = useRef<PendingAutoActions | null>(null);
  const savedFormLoadInFlightRef = useRef<{
    key: string;
    promise: Promise<boolean>;
  } | null>(null);
  const activeDetectionAbortRef = useRef<AbortController | null>(null);
  const keepAliveBootstrapRef = useRef<{
    sessionId: string;
    startedAt: number;
  } | null>(null);
  const backgroundDetectionAbortRefs = useRef<Map<string, AbortController>>(new Map());
  const detectionRetryTimeoutsRef = useRef<Map<string, number>>(new Map());
  const detectionPipeline = 'commonforms' as const;
  const activeSessionId = detectSessionId || mappingSessionId;

  const clearScheduledDetectionRetry = useCallback((sessionId?: string) => {
    if (sessionId) {
      const timeoutId = detectionRetryTimeoutsRef.current.get(sessionId);
      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId);
        detectionRetryTimeoutsRef.current.delete(sessionId);
      }
      return;
    }
    for (const timeoutId of detectionRetryTimeoutsRef.current.values()) {
      window.clearTimeout(timeoutId);
    }
    detectionRetryTimeoutsRef.current.clear();
  }, []);

  const cancelBackgroundDetectionPolling = useCallback(() => {
    clearScheduledDetectionRetry();
    detectionRetryRef.current.clear();
    for (const controller of backgroundDetectionAbortRefs.current.values()) {
      controller.abort();
    }
    backgroundDetectionAbortRefs.current.clear();
  }, [clearScheduledDetectionRetry]);

  const cancelAllDetectionPolling = useCallback(() => {
    pendingAutoActionsRef.current = null;
    activeDetectionAbortRef.current?.abort();
    activeDetectionAbortRef.current = null;
    cancelBackgroundDetectionPolling();
  }, [cancelBackgroundDetectionPolling]);

  const scheduleDetectionRetry = useCallback((sessionId: string, loadToken: number) => {
    const attempts = detectionRetryRef.current.get(sessionId) ?? 0;
    const nextAttempt = attempts + 1;
    if (nextAttempt > DETECTION_BACKGROUND_MAX_RETRIES) {
      clearScheduledDetectionRetry(sessionId);
      detectionRetryRef.current.delete(sessionId);
      return;
    }
    detectionRetryRef.current.set(sessionId, nextAttempt);
    const delay = Math.min(
      DETECTION_BACKGROUND_RETRY_MAX_MS,
      DETECTION_BACKGROUND_RETRY_BASE_MS * 2 ** (nextAttempt - 1),
    );
    clearScheduledDetectionRetry(sessionId);
    const timeoutId = window.setTimeout(() => {
      detectionRetryTimeoutsRef.current.delete(sessionId);
      if (loadTokenRef.current !== loadToken) return;
      resumeDetectionPollingRef.current?.(sessionId, loadToken);
    }, delay);
    detectionRetryTimeoutsRef.current.set(sessionId, timeoutId);
  }, [clearScheduledDetectionRetry]);

  const announceAutoOpenAiInProgress = useCallback((options: {
    autoRename: boolean;
    autoMap: boolean;
  }) => {
    const message = resolveAutoOpenAiInProgressMessage(options);
    if (!message) {
      return;
    }
    deps.setBannerNotice({
      tone: 'info',
      message,
      autoDismissMs: 8000,
    });
  }, [deps]);

  const resumeDetectionPolling = useCallback(
    async (sessionId: string, loadToken: number) => {
      clearScheduledDetectionRetry(sessionId);
      backgroundDetectionAbortRefs.current.get(sessionId)?.abort();
      const controller = new AbortController();
      backgroundDetectionAbortRefs.current.set(sessionId, controller);
      try {
        const payload = await pollDetectionStatus(sessionId, {
          signal: controller.signal,
          timeoutMs: DETECTION_BACKGROUND_POLL_TIMEOUT_MS,
        });
        if (loadTokenRef.current !== loadToken) return;
        const status = String(payload?.status || '').toLowerCase();
        if (status === 'complete') {
          clearScheduledDetectionRetry(sessionId);
          detectionRetryRef.current.delete(sessionId);
          const nextFields = mapDetectionFields(payload);
          if (!nextFields.length) {
            setIsProcessing(false);
            setProcessingMode(null);
            deps.setBannerNotice({ tone: 'info', message: 'Detection finished but no fields were found.', autoDismissMs: 8000 });
            return;
          }
          const hasEdits = deps.historyRef.current.undo.length > 0;
          if (hasEdits) {
            deps.updateFields(nextFields);
          } else {
            deps.resetFieldHistory(nextFields);
          }
          deps.setSelectedFieldId(null);
          deps.setHasRenamedFields(false);
          deps.setHasMappedSchema(false);
          deps.setCheckboxRules([]);
          deps.setRadioGroupSuggestions([]);
          deps.setTextTransformRules([]);
          setDetectSessionId(sessionId);
          setMappingSessionId(sessionId);
          setIsProcessing(false);
          setProcessingMode(null);
          const pendingAutoActions = pendingAutoActionsRef.current;
          if (
            pendingAutoActions &&
            pendingAutoActions.loadToken === loadToken &&
            pendingAutoActions.sessionId === sessionId
          ) {
            pendingAutoActionsRef.current = null;
            announceAutoOpenAiInProgress({
              autoRename: pendingAutoActions.autoRename,
              autoMap: pendingAutoActions.autoMap,
            });
            if (pendingAutoActions.autoRename && pendingAutoActions.autoMap) {
              const renamed = await deps.runOpenAiRename({
                confirm: false, allowDefer: true, sessionId, schemaId: pendingAutoActions.schemaId,
              });
              if (renamed && pendingAutoActions.schemaId) {
                const mapped = await deps.applySchemaMappings({
                  fieldsOverride: renamed,
                  schemaIdOverride: pendingAutoActions.schemaId,
                });
                if (mapped) deps.handleMappingSuccess();
              }
            } else if (pendingAutoActions.autoRename) {
              await deps.runOpenAiRename({ confirm: false, allowDefer: true, sessionId });
            } else if (pendingAutoActions.autoMap) {
              if (!pendingAutoActions.schemaId) {
                deps.setSchemaError('Upload a schema file before running mapping.');
              } else {
                const mapped = await deps.applySchemaMappings({ schemaIdOverride: pendingAutoActions.schemaId });
                if (mapped) deps.handleMappingSuccess();
              }
            }
          }
          deps.setBannerNotice({
            tone: 'success',
            message: `Detection finished in the background (${nextFields.length} fields).`,
            autoDismissMs: 7000,
          });
          return;
        }
        if (status === 'failed') {
          clearScheduledDetectionRetry(sessionId);
          detectionRetryRef.current.delete(sessionId);
          setIsProcessing(false);
          setProcessingMode(null);
          const message = payload?.error || 'Detection failed on the backend.';
          deps.setBannerNotice({ tone: 'error', message: String(message), autoDismissMs: 8000 });
          return;
        }
        if (payload?.timedOut) {
          deps.setBannerNotice({
            tone: 'info', message: 'Detection is still running on the backend. It may take a few more minutes.', autoDismissMs: 8000,
          });
          scheduleDetectionRetry(sessionId, loadToken);
        }
      } catch (error) {
        if (isAbortError(error)) return;
        if (loadTokenRef.current !== loadToken) return;
        if (error instanceof ApiError && (error.status === 401 || error.status === 403 || error.status === 404)) {
          clearScheduledDetectionRetry(sessionId);
          detectionRetryRef.current.delete(sessionId);
          pendingAutoActionsRef.current = null;
          setDetectSessionId(null);
          setMappingSessionId(null);
          deps.setBannerNotice({ tone: 'error', message: (error as Error).message, autoDismissMs: 8000 });
          return;
        }
        const message = error instanceof Error ? error.message : 'Detection failed on the backend.';
        deps.setBannerNotice({ tone: 'error', message, autoDismissMs: 8000 });
        scheduleDetectionRetry(sessionId, loadToken);
      } finally {
        const activeController = backgroundDetectionAbortRefs.current.get(sessionId);
        if (activeController === controller) {
          backgroundDetectionAbortRefs.current.delete(sessionId);
        }
      }
    },
    [announceAutoOpenAiInProgress, clearScheduledDetectionRetry, scheduleDetectionRetry, deps],
  );

  useEffect(() => {
    resumeDetectionPollingRef.current = resumeDetectionPolling;
  }, [resumeDetectionPolling]);

  useEffect(() => () => {
    cancelAllDetectionPolling();
  }, [cancelAllDetectionPolling]);

  const commitPdfLoad = useCallback(
    (
      doc: PDFDocumentProxy,
      sizes: Record<number, PageSize>,
      initialFields: PdfField[],
      loadToken: number,
      pdfState: {
        setPdfDoc: (doc: PDFDocumentProxy | null) => void;
        setPageSizes: (sizes: Record<number, PageSize>) => void;
        setPageCount: (count: number) => void;
        setCurrentPage: (page: number) => void;
        setScale: (scale: number) => void;
        setPendingPageJump: (page: number | null) => void;
      },
      options: {
        keepProcessing?: boolean;
      } = {},
    ) => {
      if (loadTokenRef.current !== loadToken) return false;
      pdfState.setPdfDoc(doc);
      pdfState.setPageSizes(sizes);
      pdfState.setPageCount(doc.numPages);
      pdfState.setCurrentPage(1);
      pdfState.setScale(1);
      pdfState.setPendingPageJump(null);
      deps.resetFieldHistory(initialFields);
      deps.setSelectedFieldId(null);
      if (!options.keepProcessing) {
        setIsProcessing(false);
        setProcessingMode(null);
      }
      return true;
    },
    [deps],
  );

  const handleFillableUpload = useCallback(
    async (
      file: File,
      options: { isDemo?: boolean; skipExistingFields?: boolean } = {},
      pdfState: {
        setPdfDoc: (doc: PDFDocumentProxy | null) => void;
        setPageSizes: (sizes: Record<number, PageSize>) => void;
        setPageCount: (count: number) => void;
        setCurrentPage: (page: number) => void;
        setScale: (scale: number) => void;
        setPendingPageJump: (page: number | null) => void;
      },
    ) => {
      cancelAllDetectionPolling();
      const loadToken = loadTokenRef.current + 1;
      loadTokenRef.current = loadToken;
      deps.setShowSearchFill(false);
      deps.setSearchFillSessionId((prev) => prev + 1);
      setProcessingMode('fillable');
      setIsProcessing(true);
      setProcessingVariant('fillable');
      setProcessingDetail(resolveProcessingCopy('fillable').detail);
      deps.setLoadError(null);
      deps.setShowHomepage(false);
      setMappingSessionId(null);
      setDetectSessionId(null);
      deps.setHasRenamedFields(false);
      deps.setHasMappedSchema(false);
      deps.setCheckboxRules([]);
      deps.setRadioGroupSuggestions([]);
      deps.setTextTransformRules([]);
      deps.setSchemaError(null);
      deps.setOpenAiError(null);
      deps.setSourceFile(file);
      deps.setSourceFileName(file.name);
      deps.setSourceFileIsDemo(Boolean(options.isDemo));
      deps.setActiveSavedFormId(null);
      deps.setActiveSavedFormName(null);
      try {
        const doc = await loadPdfFromFile(file);
        if (doc.numPages > deps.profileLimits.fillableMaxPages) {
          if (loadTokenRef.current !== loadToken) return;
          deps.clearWorkspace();
          setIsProcessing(false);
          setProcessingMode(null);
          deps.setLoadError(`Fillable uploads are limited to ${deps.profileLimits.fillableMaxPages} pages on your plan.`);
          return;
        }
        const sizesPromise = loadPageSizes(doc);
        const existingFieldsPromise = options.skipExistingFields
          ? null
          : (async () => {
              try { return await extractFieldsFromPdf(doc); }
              catch (error) {
                debugLog('Failed to extract existing fields', error);
                deps.setBannerNotice({ tone: 'warning', message: 'Could not extract existing PDF fields. Fields may need to be re-created.', autoDismissMs: 8000 });
                return [];
              }
            })();
        const sizes = await sizesPromise;
        if (!commitPdfLoad(doc, sizes, [], loadToken, pdfState)) return;

        if (!existingFieldsPromise) {
          debugLog('Loaded fillable PDF (existing fields suppressed)', { name: file.name, pages: doc.numPages });
          return;
        }

        void (async () => {
          const existingFields = await existingFieldsPromise;
          if (loadTokenRef.current !== loadToken) return;
          deps.resetFieldHistory(existingFields);
          deps.setSelectedFieldId(null);
          debugLog('Extracted existing PDF fields', { total: existingFields.length });
          debugLog('Loaded fillable PDF', { name: file.name, pages: doc.numPages, fields: existingFields.length });
          if (!existingFields.length) return;
          if (!deps.verifiedUser) return;
          try {
            const sessionPayload = await ApiService.createTemplateSession(file, {
              fields: buildTemplateFields(existingFields),
              pageCount: doc.numPages,
            });
            if (loadTokenRef.current !== loadToken) return;
            setDetectSessionId(sessionPayload.sessionId);
            setMappingSessionId(sessionPayload.sessionId);
          } catch (error) {
            if (loadTokenRef.current !== loadToken) return;
            deps.setBannerNotice({ tone: 'info', message: 'Rename is unavailable for this template.', autoDismissMs: 8000 });
            debugLog('Failed to register template session', error);
          }
        })();
      } catch (error) {
        if (loadTokenRef.current !== loadToken) return;
        const message = error instanceof Error ? error.message : 'Unable to load PDF.';
        deps.clearWorkspace();
        setIsProcessing(false);
        setProcessingMode(null);
        deps.setLoadError(message);
        debugLog('Failed to load PDF', message);
      }
    },
    [commitPdfLoad, deps],
  );

  const handleSelectSavedForm = useCallback(
    async (
      formId: string,
      pdfState: {
        setPdfDoc: (doc: PDFDocumentProxy | null) => void;
        setPageSizes: (sizes: Record<number, PageSize>) => void;
        setPageCount: (count: number) => void;
        setCurrentPage: (page: number) => void;
        setScale: (scale: number) => void;
        setPendingPageJump: (page: number | null) => void;
      },
      options: {
        source?: 'saved-form' | 'saved-group';
        preferredSession?: SavedFormSessionResume | null;
      } = {},
    ) => {
      const savedSource = options.source === 'saved-group' ? 'saved-group' : 'saved-form';
      const inFlightKey = `${savedSource}:${formId}`;
      if (savedFormLoadInFlightRef.current?.key === inFlightKey) {
        return savedFormLoadInFlightRef.current.promise;
      }

      const loadPromise = (async () => {
        cancelAllDetectionPolling();
        const loadToken = loadTokenRef.current + 1;
        loadTokenRef.current = loadToken;
        deps.setShowSearchFill(false);
        deps.setSearchFillSessionId((prev) => prev + 1);
        setProcessingMode('saved');
        setIsProcessing(true);
        setProcessingVariant(savedSource);
        setProcessingDetail(resolveProcessingCopy(savedSource).detail);
        deps.setLoadError(null);
        deps.setShowHomepage(false);
        setMappingSessionId(null);
        setDetectSessionId(null);
        deps.setHasRenamedFields(false);
        deps.setHasMappedSchema(false);
        deps.setSchemaError(null);
        deps.setOpenAiError(null);

        try {
          const [savedMeta, blob] = await Promise.all([
            ApiService.loadSavedForm(formId),
            ApiService.downloadSavedForm(formId),
          ]);
          const name = savedMeta?.name || 'saved-form.pdf';
          const file = new File([blob], name, { type: 'application/pdf' });
          deps.setSourceFile(file);
          deps.setSourceFileName(name);
          deps.setSourceFileIsDemo(false);
          // Attach the saved-template identity before the PDF hydration work
          // continues so header actions do not briefly treat the workspace as
          // an unsaved draft while a saved form is opening.
          deps.setActiveSavedFormId(formId);
          deps.setActiveSavedFormName(savedMeta?.name || null);
          const doc = await loadPdfFromFile(file);
          const hydratedSnapshot = normalizeSavedFormEditorSnapshot(savedMeta?.editorSnapshot, {
            expectedPageCount: doc.numPages,
          });
          const sizesPromise = hydratedSnapshot
            ? Promise.resolve(hydratedSnapshot.pageSizes)
            : loadPageSizes(doc);
          const existingFieldsPromise = hydratedSnapshot
            ? Promise.resolve(clonePdfFields(hydratedSnapshot.fields))
            : (async () => {
                try { return await extractFieldsFromPdf(doc); }
                catch (error) {
                  debugLog('Failed to extract saved form fields', error);
                  deps.setBannerNotice({ tone: 'warning', message: 'Could not extract saved form fields. Some fields may be missing.', autoDismissMs: 8000 });
                  return [];
                }
              })();
          const sizes = await sizesPromise;
          const initialFields = hydratedSnapshot ? clonePdfFields(hydratedSnapshot.fields) : [];
          if (!commitPdfLoad(doc, sizes, initialFields, loadToken, pdfState)) return false;
          const {
            checkboxRules: savedCheckboxRules,
            legacyRadioGroupSuggestions,
            textTransformRules: savedTextTransformRules,
          } = extractSavedFormFillRuleState(savedMeta, { fields: initialFields });
          deps.setCheckboxRules(savedCheckboxRules);
          deps.setRadioGroupSuggestions(legacyRadioGroupSuggestions);
          deps.setTextTransformRules(savedTextTransformRules);
          const derivedHasMappedSchema = Boolean(
            savedCheckboxRules.length ||
            savedTextTransformRules.length
          );
          deps.setHasRenamedFields(Boolean(hydratedSnapshot?.hasRenamedFields));
          deps.setHasMappedSchema(hydratedSnapshot?.hasMappedSchema ?? derivedHasMappedSchema);

          const registerSavedFormSession = async (fieldsForSession: PdfField[]) => {
            if (!fieldsForSession.length) {
              deps.setBannerNotice({ tone: 'info', message: 'No fields found in this saved form. Rename is unavailable.', autoDismissMs: 8000 });
              return true;
            }
            const preferredSession = options.preferredSession;
            if (
              preferredSession?.sessionId &&
              (preferredSession.fieldCount === null || preferredSession.fieldCount === fieldsForSession.length) &&
              (preferredSession.pageCount === null || preferredSession.pageCount === doc.numPages)
            ) {
              try {
                await ApiService.touchSession(preferredSession.sessionId);
                if (loadTokenRef.current !== loadToken) return false;
                setDetectSessionId(preferredSession.sessionId);
                setMappingSessionId(preferredSession.sessionId);
                return true;
              } catch (error) {
                debugLog('Failed to reuse saved form session, creating a fresh session instead', preferredSession.sessionId, error);
              }
            }
            try {
              const sessionPayload = await ApiService.createSavedFormSession(formId, {
                fields: buildTemplateFields(fieldsForSession),
                pageCount: doc.numPages,
              });
              if (loadTokenRef.current !== loadToken) return false;
              if (!sessionPayload?.sessionId) {
                throw new Error('Saved form session creation returned no session id.');
              }
              setDetectSessionId(sessionPayload.sessionId);
              setMappingSessionId(sessionPayload.sessionId);
              return true;
            } catch (error) {
              if (loadTokenRef.current !== loadToken) return false;
              deps.setBannerNotice({ tone: 'info', message: 'Rename is unavailable for this saved form.', autoDismissMs: 8000 });
              debugLog('Failed to register saved form session', error);
              return false;
            }
          };

          if (hydratedSnapshot) {
            deps.markSavedFillLinkSnapshot(initialFields, savedCheckboxRules);
            debugLog('Loaded saved form from editor snapshot', { name, pages: doc.numPages, fields: initialFields.length });
            if (deps.verifiedUser) {
              void registerSavedFormSession(initialFields);
            }
            return true;
          }

          void (async () => {
            const existingFields = await existingFieldsPromise;
            if (loadTokenRef.current !== loadToken) return;
            const {
              legacyRadioGroupSuggestions: extractedLegacyRadioSuggestions,
            } = extractSavedFormFillRuleState(savedMeta, { fields: existingFields });
            deps.resetFieldHistory(existingFields);
            deps.setSelectedFieldId(null);
            deps.setRadioGroupSuggestions(extractedLegacyRadioSuggestions);
            deps.markSavedFillLinkSnapshot(existingFields, savedCheckboxRules);
            debugLog('Extracted saved form fields', { total: existingFields.length });
            debugLog('Loaded saved form', { name, pages: doc.numPages, fields: existingFields.length });
            if (deps.verifiedUser && existingFields.length) {
              void Promise.resolve(
                ApiService.updateSavedFormEditorSnapshot(
                  formId,
                  buildSavedFormEditorSnapshot({
                    pageCount: doc.numPages,
                    pageSizes: sizes,
                    fields: existingFields,
                    hasRenamedFields: false,
                    hasMappedSchema: derivedHasMappedSchema,
                  }),
                ),
              ).catch((error) => {
                debugLog('Failed to backfill saved form editor snapshot', formId, error);
              });
            }
            if (!deps.verifiedUser) return;
            await registerSavedFormSession(existingFields);
          })();
          return true;
        } catch (error) {
          if (loadTokenRef.current !== loadToken) return false;
          const message = error instanceof Error ? error.message : 'Unable to load saved form.';
          deps.clearWorkspace();
          setIsProcessing(false);
          setProcessingMode(null);
          deps.setLoadError(message);
          debugLog('Failed to load saved form', message);
          return false;
        }
      })();

      const trackedPromise = loadPromise.finally(() => {
        if (savedFormLoadInFlightRef.current?.promise === trackedPromise) {
          savedFormLoadInFlightRef.current = null;
        }
      });
      savedFormLoadInFlightRef.current = { key: inFlightKey, promise: trackedPromise };
      return trackedPromise;
    },
    [cancelAllDetectionPolling, commitPdfLoad, deps],
  );

  const restoreSessionWorkspace = useCallback(
    async (
      sourceFile: File,
      snapshot: WorkspaceSessionRestoreSnapshot,
      pdfState: {
        setPdfDoc: (doc: PDFDocumentProxy | null) => void;
        setPageSizes: (sizes: Record<number, PageSize>) => void;
        setPageCount: (count: number) => void;
        setCurrentPage: (page: number) => void;
        setScale: (scale: number) => void;
        setPendingPageJump: (page: number | null) => void;
      },
    ) => {
      cancelAllDetectionPolling();
      const loadToken = loadTokenRef.current + 1;
      loadTokenRef.current = loadToken;
      pendingAutoActionsRef.current = null;
      detectionRetryRef.current.clear();
      deps.setShowSearchFill(false);
      deps.setSearchFillSessionId((prev) => prev + 1);
      deps.setLoadError(null);
      deps.setShowHomepage(false);
      setMappingSessionId(null);
      setDetectSessionId(null);
      deps.setHasRenamedFields(false);
      deps.setHasMappedSchema(false);
      deps.setCheckboxRules([]);
      deps.setRadioGroupSuggestions([]);
      deps.setTextTransformRules([]);
      deps.setSchemaError(null);
      deps.setOpenAiError(null);
      deps.setSourceFile(sourceFile);
      deps.setSourceFileName(sourceFile.name);
      deps.setSourceFileIsDemo(false);
      deps.setActiveSavedFormId(null);
      deps.setActiveSavedFormName(null);

      const waitingForRemoteDetection =
        (snapshot.detectionStatus === 'queued' || snapshot.detectionStatus === 'running')
        && snapshot.fields.length === 0;

      if (waitingForRemoteDetection) {
        setIsProcessing(true);
        setProcessingMode('detect');
        setProcessingVariant('detect');
        setProcessingDetail('Detection is still running on the backend. Opening the editor once fields are ready.');
      }

      try {
        const doc = await loadPdfFromFile(sourceFile);
        const sizes = await loadPageSizes(doc);
        const nextFields = clonePdfFields(snapshot.fields);
        if (!commitPdfLoad(doc, sizes, nextFields, loadToken, pdfState, {
          keepProcessing: waitingForRemoteDetection,
        })) {
          return false;
        }
        setDetectSessionId(snapshot.sessionId);
        setMappingSessionId(snapshot.sessionId);
        deps.setCheckboxRules(snapshot.checkboxRules.map((rule) => ({
          ...rule,
          valueMap: rule.valueMap ? { ...rule.valueMap } : undefined,
        })));
        deps.setRadioGroupSuggestions([]);
        deps.setTextTransformRules(snapshot.textTransformRules.map((rule) => ({
          ...rule,
          sources: Array.isArray(rule.sources) ? [...rule.sources] : [],
        })));
        deps.setHasRenamedFields(nextFields.some((field) => typeof field.renameConfidence === 'number'));
        deps.setHasMappedSchema(hasMappedSchemaState(nextFields, snapshot.checkboxRules, snapshot.textTransformRules));
        if (waitingForRemoteDetection) {
          void resumeDetectionPolling(snapshot.sessionId, loadToken);
        }
        return true;
      } catch (error) {
        if (loadTokenRef.current !== loadToken) return false;
        setIsProcessing(false);
        setProcessingMode(null);
        debugLog('Failed to restore session workspace', snapshot.sessionId, error);
        return false;
      }
    },
    [cancelAllDetectionPolling, commitPdfLoad, resumeDetectionPolling, deps],
  );

  const runDetectUpload = useCallback(
    async (
      file: File,
      options: { autoRename?: boolean; autoMap?: boolean; schemaIdOverride?: string | null } = {},
      pdfState: {
        setPdfDoc: (doc: PDFDocumentProxy | null) => void;
        setPageSizes: (sizes: Record<number, PageSize>) => void;
        setPageCount: (count: number) => void;
        setCurrentPage: (page: number) => void;
        setScale: (scale: number) => void;
        setPendingPageJump: (page: number | null) => void;
      },
    ) => {
      cancelAllDetectionPolling();
      const loadToken = loadTokenRef.current + 1;
      loadTokenRef.current = loadToken;
      pendingAutoActionsRef.current = null;
      detectionRetryRef.current.clear();
      deps.setShowSearchFill(false);
      deps.setSearchFillSessionId((prev) => prev + 1);
      setProcessingMode('detect');
      setIsProcessing(true);
      setProcessingVariant('detect');
      setProcessingDetail(resolveProcessingCopy('detect').detail);
      deps.setLoadError(null);
      deps.setShowHomepage(false);
      setMappingSessionId(null);
      setDetectSessionId(null);
      deps.setHasRenamedFields(false);
      deps.setHasMappedSchema(false);
      deps.setCheckboxRules([]);
      deps.setRadioGroupSuggestions([]);
      deps.setTextTransformRules([]);
      deps.setSchemaError(null);
      deps.setOpenAiError(null);
      deps.setSourceFile(file);
      deps.setSourceFileName(file.name);
      deps.setSourceFileIsDemo(false);
      deps.setActiveSavedFormId(null);
      deps.setActiveSavedFormName(null);
      const openAiActionsRequested = Boolean(options.autoRename || options.autoMap);
      let warmupActive = false;
      let warmupCompleted = false;
      let warmupStartTimer: number | null = null;
      let warmupEndTimer: number | null = null;
      let shouldShowRenameWarmup = false;
      let latestDetectionStatusMessage: string | null = null;
      const clearWarmupTimers = () => {
        if (warmupStartTimer !== null) {
          window.clearTimeout(warmupStartTimer);
          warmupStartTimer = null;
        }
        if (warmupEndTimer !== null) {
          window.clearTimeout(warmupEndTimer);
          warmupEndTimer = null;
        }
      };
      const scheduleRenameWarmup = () => {
        if (!shouldShowRenameWarmup || warmupCompleted || warmupActive || warmupStartTimer !== null) return;
        warmupStartTimer = window.setTimeout(() => {
          warmupStartTimer = null;
          if (loadTokenRef.current !== loadToken || !shouldShowRenameWarmup || warmupCompleted) return;
          warmupActive = true;
          setProcessingDetail(DETECTION_WARMUP_MESSAGE);
          warmupEndTimer = window.setTimeout(() => {
            warmupEndTimer = null;
            if (loadTokenRef.current !== loadToken) return;
            warmupActive = false;
            warmupCompleted = true;
            setProcessingDetail(latestDetectionStatusMessage || DETECTION_POST_WARMUP_MESSAGE);
          }, DETECTION_WARMUP_DURATION_MS);
        }, DETECTION_WARMUP_DELAY_MS);
      };
      try {
        const doc = await loadPdfFromFile(file);
        if (doc.numPages > deps.profileLimits.detectMaxPages) {
          if (loadTokenRef.current !== loadToken) return;
          deps.clearWorkspace();
          setIsProcessing(false);
          setProcessingMode(null);
          deps.setLoadError(`Detection uploads are limited to ${deps.profileLimits.detectMaxPages} pages on your plan.`);
          return;
        }
        const sizes = await loadPageSizes(doc);
        if (loadTokenRef.current !== loadToken) return;
        shouldShowRenameWarmup = openAiActionsRequested && doc.numPages < DETECTION_WARMUP_PAGE_THRESHOLD;
        if (shouldShowRenameWarmup) {
          setProcessingDetail(DETECTION_WAITING_DETECTOR_MESSAGE);
        }
        const activeSchemaId = options.schemaIdOverride ?? deps.schemaId;

        let detectedFields: PdfField[] = [];
        let detectedSessionId: string | null = null;
        let detectionTimedOut = false;
        let detectionError: string | null = null;
        let authFailure: ApiError | null = null;
        const detectionController = new AbortController();

        try {
          activeDetectionAbortRef.current = detectionController;
          const detection = await detectFields(file, {
            pipeline: detectionPipeline,
            prewarmRename: Boolean(options.autoRename),
            prewarmRemap: Boolean(options.autoMap),
            signal: detectionController.signal,
            onStatus: (payload) => {
              if (loadTokenRef.current !== loadToken) return;
              const message = resolveDetectionStatusMessage(payload, QUEUE_WAIT_THRESHOLD_MS);
              if (!message) return;
              latestDetectionStatusMessage = message;
              if (warmupActive) return;
              const status = String(payload?.status || '').toLowerCase();
              if (shouldShowRenameWarmup && status === 'running') {
                setProcessingDetail(message);
                scheduleRenameWarmup();
                return;
              }
              setProcessingDetail(message);
            },
          });
          detectedSessionId = detection?.sessionId || null;
          detectionTimedOut = Boolean(detection?.timedOut);
          detectedFields = mapDetectionFields(detection);
          debugLog('Field detection returned', { total: detectedFields.length });
        } catch (error) {
          if (isAbortError(error)) {
            return;
          }
          if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
            authFailure = error;
          } else {
            detectionError = error instanceof Error ? error.message : 'Field detection failed.';
          }
          debugLog('Field detection failed', error);
        } finally {
          if (activeDetectionAbortRef.current === detectionController) {
            activeDetectionAbortRef.current = null;
          }
        }

        if (authFailure) {
          if (loadTokenRef.current !== loadToken) return;
          deps.clearWorkspace();
          setIsProcessing(false);
          setProcessingMode(null);
          deps.setLoadError(authFailure.message);
          deps.setBannerNotice({ tone: 'error', message: authFailure.message, autoDismissMs: 8000 });
          return;
        }

        if (!detectedFields.length) {
          try {
            detectedFields = await extractFieldsFromPdf(doc);
            debugLog('Fallback PDF field extraction returned', { total: detectedFields.length });
          } catch (error) {
            debugLog('Failed to extract existing fields', error);
          }
        }
        if (!detectedFields.length && detectionError && !detectionTimedOut) {
          deps.setBannerNotice({
            tone: 'error',
            message: `${detectionError} No embedded fields were found.`,
            autoDismissMs: 10000,
          });
        }
        const waitingForRemoteDetection = detectionTimedOut && !detectedFields.length && Boolean(detectedSessionId);
        if (waitingForRemoteDetection) {
          setIsProcessing(true);
          setProcessingMode('detect');
          setProcessingDetail('Detection is still running on the backend. Opening the editor once fields are ready.');
        } else if (detectionTimedOut) {
          deps.setBannerNotice({
            tone: 'info',
            message: 'Detection is still running on the backend. Continuing with the fields available so far.',
            autoDismissMs: 8000,
          });
        }

        if (!commitPdfLoad(doc, sizes, detectedFields, loadToken, pdfState, {
          keepProcessing: waitingForRemoteDetection,
        })) return;
        setDetectSessionId(detectedSessionId);
        if (detectedSessionId) setMappingSessionId(detectedSessionId);
        debugLog('Loaded PDF', { name: file.name, pages: doc.numPages, fields: detectedFields.length });

        if (detectionTimedOut && detectedSessionId) {
          void resumeDetectionPolling(detectedSessionId, loadToken);
        }

        if (loadTokenRef.current !== loadToken) return;
        if (!options.autoRename && !options.autoMap) return;

        if (detectionTimedOut && detectedSessionId) {
          pendingAutoActionsRef.current = {
            loadToken, sessionId: detectedSessionId, schemaId: activeSchemaId,
            autoRename: Boolean(options.autoRename), autoMap: Boolean(options.autoMap),
          };
          deps.setBannerNotice({
            tone: 'info',
            message: 'Detection is still running. OpenAI actions will start once fields are ready.',
            autoDismissMs: 8000,
          });
          return;
        }
        if (!detectedFields.length) {
          deps.setBannerNotice({ tone: 'info', message: 'No fields detected. OpenAI actions were skipped.', autoDismissMs: 8000 });
          return;
        }

        announceAutoOpenAiInProgress({
          autoRename: Boolean(options.autoRename),
          autoMap: Boolean(options.autoMap),
        });

        if (options.autoRename && options.autoMap) {
          const renamed = await deps.runOpenAiRename({
            confirm: false, allowDefer: true, sessionId: detectedSessionId, schemaId: activeSchemaId,
          });
          if (renamed && activeSchemaId) {
            const mapped = await deps.applySchemaMappings({
              fieldsOverride: renamed,
              schemaIdOverride: activeSchemaId,
            });
            if (mapped) deps.handleMappingSuccess();
          }
          return;
        }
        if (options.autoRename) {
          await deps.runOpenAiRename({ confirm: false, allowDefer: true, sessionId: detectedSessionId });
        }
        if (options.autoMap) {
          const mapped = await deps.applySchemaMappings({ schemaIdOverride: activeSchemaId });
          if (mapped) deps.handleMappingSuccess();
        }
      } catch (error) {
        if (loadTokenRef.current !== loadToken) return;
        const message = error instanceof Error ? error.message : 'Unable to load PDF.';
        deps.clearWorkspace();
        setIsProcessing(false);
        setProcessingMode(null);
        deps.setLoadError(message);
        debugLog('Failed to load PDF', message);
      } finally {
        clearWarmupTimers();
      }
    },
    [announceAutoOpenAiInProgress, commitPdfLoad, resumeDetectionPolling, deps],
  );

  // ── Session keep-alive ────────────────────────────────────────────
  useEffect(() => {
    const isDemoAsset = Boolean(deps.sourceFileIsDemo && deps.sourceFileName && DEMO_ASSET_NAME_SET.has(deps.sourceFileName));
    const { demoActive, demoCompletionOpen } = deps.demoStateRef.current;
    const demoSessionSuppressed = demoActive || demoCompletionOpen || isDemoAsset;
    if (!activeSessionId || !deps.verifiedUser || !deps.pdfDoc || demoSessionSuppressed) return;
    let cancelled = false;
    let intervalId: number | null = null;
    const intervalMs = 60_000;
    const shouldSkipImmediatePing = (() => {
      const lastBootstrap = keepAliveBootstrapRef.current;
      if (!lastBootstrap || lastBootstrap.sessionId !== activeSessionId) {
        return false;
      }
      return Date.now() - lastBootstrap.startedAt < 5_000;
    })();
    const reportExpired = () => {
      deps.setBannerNotice({ tone: 'info', message: 'This session expired. Re-upload the PDF to run Rename or Map again.', autoDismissMs: 8000 });
      setDetectSessionId(null); setMappingSessionId(null);
    };
    const ping = async () => {
      try { await ApiService.touchSession(activeSessionId); }
      catch (error) {
        if (cancelled) return;
        if (error instanceof ApiError && (error.status === 403 || error.status === 404)) { reportExpired(); return; }
        debugLog('Failed to refresh session TTL', error);
      }
    };
    const start = () => {
      if (intervalId !== null) return;
      intervalId = window.setInterval(() => { if (!document.hidden) void ping(); }, intervalMs);
      if (shouldSkipImmediatePing) {
        return;
      }
      keepAliveBootstrapRef.current = {
        sessionId: activeSessionId,
        startedAt: Date.now(),
      };
      void ping();
    };
    const stop = () => { if (intervalId === null) return; window.clearInterval(intervalId); intervalId = null; };
    const handleVisibility = () => { if (document.hidden) stop(); else start(); };
    document.addEventListener('visibilitychange', handleVisibility);
    if (!document.hidden) start();
    return () => { cancelled = true; stop(); document.removeEventListener('visibilitychange', handleVisibility); };
  }, [activeSessionId, deps.verifiedUser, deps.pdfDoc, deps.sourceFileIsDemo, deps.sourceFileName, deps.setBannerNotice, deps.demoStateRef]);

  const reset = useCallback(() => {
    cancelAllDetectionPolling();
    setProcessingMode(null);
    setMappingSessionId(null);
    setDetectSessionId(null);
    detectionRetryRef.current.clear();
  }, [cancelAllDetectionPolling]);

  return {
    detectSessionId, setDetectSessionId,
    mappingSessionId, setMappingSessionId,
    isProcessing, setIsProcessing,
    processingMode, setProcessingMode,
    processingHeading,
    processingDetail,
    loadTokenRef,
    detectionRetryRef,
    pendingAutoActionsRef,
    commitPdfLoad,
    handleFillableUpload,
    handleSelectSavedForm,
    restoreSessionWorkspace,
    runDetectUpload,
    resumeDetectionPolling,
    scheduleDetectionRetry,
    reset,
    setProcessingDetail,
  };
}
