/**
 * App shell that orchestrates PDF detection, mapping, and viewer state.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ChangeEvent, ReactNode } from 'react';
import type { User } from 'firebase/auth';
import type { PDFDocumentProxy } from 'pdfjs-dist/types/src/display/api';
import './App.css';
import type { CheckboxRule, ConfidenceFilter, ConfidenceTier, FieldType, PageSize, PdfField } from './types';
import { createField, ensureUniqueFieldName, makeId } from './utils/fields';
import { fieldConfidenceTierForField, parseConfidence } from './utils/confidence';
import { parseCsv } from './utils/csv';
import { pickIdentifierKey } from './utils/dataSource';
import { inferSchemaFromRows, parseSchemaText } from './utils/schema';
import { parseExcel } from './utils/excel';
import { extractFieldsFromPdf, loadPageSizes, loadPdfFromFile } from './utils/pdf';
import { ALERT_MESSAGES, buildImportFileBeforeMapping } from './utils/alertMessages';
import { detectFields, fetchDetectionStatus, pollDetectionStatus } from './services/detectionApi';
import { Auth } from './services/auth';
import { setAuthToken } from './services/authTokenStore';
import { ApiService, type ProfileLimits, type UserProfile } from './api';
import Homepage from './components/pages/Homepage';
import LoginPage from './components/pages/LoginPage';
import ProfilePage from './components/pages/ProfilePage';
import VerifyEmailPage from './components/pages/VerifyEmailPage';
import { HeaderBar, type DataSourceKind } from './components/layout/HeaderBar';
import LegacyHeader from './components/layout/LegacyHeader';
import SearchFillModal from './components/features/SearchFillModal';
import { FieldInspectorPanel } from './components/panels/FieldInspectorPanel';
import { FieldListPanel } from './components/panels/FieldListPanel';
import { PdfViewer } from './components/viewer/PdfViewer';
import UploadComponent from './components/features/UploadComponent';
import { Alert, type AlertTone } from './components/ui/Alert';
import { ConfirmDialog, PromptDialog, type DialogTone } from './components/ui/Dialog';

const DEBUG_UI = false;
const MAX_FIELD_HISTORY = 10;
const SAVED_FORMS_RETRY_LIMIT = 3;
const SAVED_FORMS_RETRY_BASE_MS = 500;
const SAVED_FORMS_RETRY_MAX_MS = 4000;
const env = import.meta.env;
const PROCESSING_AD_VIDEO_URL =
  typeof env.VITE_PROCESSING_AD_VIDEO_URL === 'string' ? env.VITE_PROCESSING_AD_VIDEO_URL.trim() : '';
const PROCESSING_AD_POSTER_URL =
  typeof env.VITE_PROCESSING_AD_POSTER_URL === 'string' ? env.VITE_PROCESSING_AD_POSTER_URL.trim() : '';
const DEFAULT_PROCESSING_MESSAGE = 'Detecting fields and building the editor.';
const QUEUE_WAIT_THRESHOLD_MS = 15000;
const DETECTION_BACKGROUND_POLL_TIMEOUT_MS = (() => {
  const raw = env.VITE_DETECTION_BACKGROUND_TIMEOUT_MS;
  const parsed = Number(raw);
  if (Number.isFinite(parsed) && parsed >= 0) {
    return parsed;
  }
  return 10 * 60 * 1000;
})();
const DEFAULT_PROFILE_LIMITS: ProfileLimits = {
  detectMaxPages: 5,
  fillableMaxPages: 50,
  savedFormsMax: 3,
};

type ProcessingMode = 'detect' | 'fillable' | 'saved' | null;
type SchemaPayload = {
  name?: string;
  fields: Array<{ name: string; type?: string }>;
  source?: string;
  sampleCount?: number;
};
type PendingAutoActions = {
  loadToken: number;
  sessionId: string;
  schemaId: string | null;
  autoRename: boolean;
  autoMap: boolean;
};

/**
 * Conditional UI debug logger.
 */
function debugLog(...args: unknown[]) {
  if (!DEBUG_UI) return;
  console.log('[dullypdf-ui]', ...args);
}

/**
 * Normalize backend field types into UI field categories.
 */
function normaliseFieldType(raw: unknown): FieldType {
  const candidate = String(raw || '').toLowerCase();
  if (candidate === 'checkbox') return 'checkbox';
  if (candidate === 'signature') return 'signature';
  if (candidate === 'date') return 'date';
  return 'text';
}

/**
 * Coerce rect inputs into a consistent {x,y,width,height} shape.
 */
function rectToBox(rect: unknown): { x: number; y: number; width: number; height: number } | null {
  if (!rect) return null;
  if (Array.isArray(rect) && rect.length === 4) {
    const [x1, y1, x2, y2] = rect.map((value) => Number(value));
    if ([x1, y1, x2, y2].some((val) => Number.isNaN(val))) return null;
    return { x: x1, y: y1, width: x2 - x1, height: y2 - y1 };
  }
  if (typeof rect === 'object') {
    const candidate = rect as { x?: number; y?: number; width?: number; height?: number };
    if (
      typeof candidate.x === 'number' &&
      typeof candidate.y === 'number' &&
      typeof candidate.width === 'number' &&
      typeof candidate.height === 'number'
    ) {
      return {
        x: candidate.x,
        y: candidate.y,
        width: candidate.width,
        height: candidate.height,
      };
    }
  }
  return null;
}

/**
 * Convert raw filenames into a display-friendly saved form name.
 */
function normaliseFormName(raw: string | null | undefined): string {
  const trimmed = String(raw || '').trim();
  if (!trimmed.length) return 'Saved form';
  return trimmed.replace(/\.pdf$/i, '');
}

/**
 * Estimate confidence for a rename mapping based on string similarity.
 */
function deriveMappingConfidence(originalName: string, nextName: string): number {
  const normalise = (value: string) =>
    value
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, ' ')
      .trim();
  const left = normalise(originalName);
  const right = normalise(nextName);
  if (!left || !right) return 0.7;
  if (left === right) return 0.95;
  if (left.includes(right) || right.includes(left)) return 0.85;
  return 0.7;
}

/**
 * Normalize values so fillable PDFs receive consistent defaults.
 */
function normaliseFieldValueForMaterialize(field: PdfField): PdfField['value'] {
  const value = field.value;
  if (field.type === 'checkbox') {
    if (value === null || value === undefined) return false;
    if (typeof value === 'string' && value.trim().length === 0) return false;
    return value;
  }
  if (value === null || value === undefined) return '';
  if (typeof value === 'string' && value.trim().length === 0) return '';
  return value;
}

/**
 * Apply value normalization across all fields before materialization.
 */
function prepareFieldsForMaterialize(fields: PdfField[]): PdfField[] {
  return fields.map((field) => {
    const value = normaliseFieldValueForMaterialize(field);
    return value === field.value ? field : { ...field, value };
  });
}

type FieldNameUpdate = {
  newName?: string;
  mappingConfidence?: unknown;
};

type BannerNotice = {
  tone: AlertTone;
  message: string;
  autoDismissMs?: number;
};

type ConfirmDialogOptions = {
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: DialogTone;
};

type PromptDialogOptions = {
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: DialogTone;
  defaultValue?: string;
  placeholder?: string;
  requireValue?: boolean;
};

type DialogRequest =
  | ({ kind: 'confirm' } & ConfirmDialogOptions)
  | ({ kind: 'prompt' } & PromptDialogOptions);

/**
 * Apply rename updates while enforcing unique field names.
 */
function applyFieldNameUpdatesToList(
  fields: PdfField[],
  updatesByCurrentName: Map<string, FieldNameUpdate>,
): PdfField[] {
  if (!updatesByCurrentName.size) return fields;
  const existingNames = new Set(fields.map((field) => field.name));
  return fields.map((field) => {
    const update = updatesByCurrentName.get(field.name);
    if (!update) return field;

    let next = field;
    const nextMappingConfidence = parseConfidence(update.mappingConfidence);
    if (nextMappingConfidence !== undefined && nextMappingConfidence !== field.mappingConfidence) {
      next = { ...next, mappingConfidence: nextMappingConfidence };
    }

    const desiredName = update.newName;
    if (!desiredName || desiredName === field.name) {
      return next;
    }

    existingNames.delete(field.name);
    const uniqueName = ensureUniqueFieldName(desiredName, existingNames);
    existingNames.add(uniqueName);

    if (uniqueName === next.name) {
      return next;
    }

    return { ...next, name: uniqueName };
  });
}

/**
 * Convert backend detection payloads into client field models.
 */
function mapDetectionFields(payload: any): PdfField[] {
  const rawFields = Array.isArray(payload?.fields) ? payload.fields : [];
  return rawFields
    .map((field: any, index: number) => {
      const rect = rectToBox(field?.rect || field?.bbox);
      if (!rect) return null;
      const fieldConfidence = parseConfidence(field?.isItAfieldConfidence ?? field?.confidence);
      const renameConfidence = parseConfidence(field?.renameConfidence ?? field?.rename_confidence);
      return {
        id: makeId(),
        name: String(field?.name || `field_${index + 1}`),
        type: normaliseFieldType(field?.type),
        page: Number(field?.page) || 1,
        rect,
        fieldConfidence,
        renameConfidence,
        groupKey: field?.groupKey ?? field?.group_key,
        optionKey: field?.optionKey ?? field?.option_key,
        optionLabel: field?.optionLabel ?? field?.option_label,
        groupLabel: field?.groupLabel ?? field?.group_label,
      } as PdfField;
    })
    .filter(Boolean) as PdfField[];
}

function parseIsoTimestamp(value: unknown): number | null {
  if (typeof value !== 'string' || !value) return null;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

function resolveDetectionStatusMessage(payload: any): string | null {
  const status = String(payload?.status || '').toLowerCase();
  if (!status) return null;
  const profile = String(payload?.detectionProfile || '').toLowerCase();
  const profileLabel =
    profile === 'heavy' ? 'high-capacity CPU' : profile === 'light' ? 'standard CPU' : 'CPU';
  if (status === 'queued') {
    const startedAt = parseIsoTimestamp(payload?.detectionStartedAt);
    if (!startedAt) {
      const queuedAt = parseIsoTimestamp(payload?.detectionQueuedAt);
      if (queuedAt && Date.now() - queuedAt > QUEUE_WAIT_THRESHOLD_MS) {
        return `Waiting for an available ${profileLabel}...`;
      }
      return `Waiting for ${profileLabel} to start...`;
    }
  }
  if (status === 'running') {
    return `Detecting fields on the ${profileLabel}...`;
  }
  return null;
}

/**
 * Main application component that coordinates auth, detection, and editing.
 */
function App() {
  const [authReady, setAuthReady] = useState(false);
  const [authUser, setAuthUser] = useState<User | null>(null);
  const [authSignInProvider, setAuthSignInProvider] = useState<string | null>(null);
  const [showLogin, setShowLogin] = useState(false);
  const [showProfile, setShowProfile] = useState(false);
  const [userProfile, setUserProfile] = useState<UserProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [showHomepage, setShowHomepage] = useState(true);
  const detectionPipeline: 'commonforms' = 'commonforms';
  const [pendingDetectFile, setPendingDetectFile] = useState<File | null>(null);
  const [showPipelineModal, setShowPipelineModal] = useState(false);
  const [pipelineError, setPipelineError] = useState<string | null>(null);
  const [uploadWantsRename, setUploadWantsRename] = useState(false);
  const [uploadWantsMap, setUploadWantsMap] = useState(false);
  const [detectSessionId, setDetectSessionId] = useState<string | null>(null);

  const [pdfDoc, setPdfDoc] = useState<PDFDocumentProxy | null>(null);
  const [pageSizes, setPageSizes] = useState<Record<number, PageSize>>({});
  const [pageCount, setPageCount] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [scale, setScale] = useState(1);
  const [pendingPageJump, setPendingPageJump] = useState<number | null>(null);
  const [fields, setFields] = useState<PdfField[]>([]);
  const [showFields, setShowFields] = useState(true);
  const [showFieldNames, setShowFieldNames] = useState(true);
  const [showFieldInfo, setShowFieldInfo] = useState(false);
  const [confidenceFilter, setConfidenceFilter] = useState<ConfidenceFilter>({
    high: true,
    medium: true,
    low: true,
  });
  const [selectedFieldId, setSelectedFieldId] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingMode, setProcessingMode] = useState<ProcessingMode>(null);
  const [processingDetail, setProcessingDetail] = useState(DEFAULT_PROCESSING_MESSAGE);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [savedForms, setSavedForms] = useState<Array<{ id: string; name: string; createdAt: string }>>([]);
  const [activeSavedFormId, setActiveSavedFormId] = useState<string | null>(null);
  const [activeSavedFormName, setActiveSavedFormName] = useState<string | null>(null);
  const [deletingFormId, setDeletingFormId] = useState<string | null>(null);
  const [mappingSessionId, setMappingSessionId] = useState<string | null>(null);
  const [mappingInProgress, setMappingInProgress] = useState(false);
  const [mapSchemaInProgress, setMapSchemaInProgress] = useState(false);
  const [hasMappedSchema, setHasMappedSchema] = useState(false);
  const [renameInProgress, setRenameInProgress] = useState(false);
  const [hasRenamedFields, setHasRenamedFields] = useState(false);
  const [checkboxRules, setCheckboxRules] = useState<CheckboxRule[]>([]);
  const [schemaError, setSchemaError] = useState<string | null>(null);
  const [openAiError, setOpenAiError] = useState<string | null>(null);
  const [bannerNotice, setBannerNotice] = useState<BannerNotice | null>(null);
  const [dialogRequest, setDialogRequest] = useState<DialogRequest | null>(null);
  const [schemaId, setSchemaId] = useState<string | null>(null);
  const [pendingSchemaPayload, setPendingSchemaPayload] = useState<SchemaPayload | null>(null);
  const [dataSourceKind, setDataSourceKind] = useState<DataSourceKind>('none');
  const [dataSourceLabel, setDataSourceLabel] = useState<string | null>(null);
  const [schemaUploadInProgress, setSchemaUploadInProgress] = useState(false);
  const [dataColumns, setDataColumns] = useState<string[]>([]);
  const [dataRows, setDataRows] = useState<Array<Record<string, unknown>>>([]);
  const [identifierKey, setIdentifierKey] = useState<string | null>(null);
  const [showSearchFill, setShowSearchFill] = useState(false);
  const [searchFillSessionId, setSearchFillSessionId] = useState(0);
  const [sourceFile, setSourceFile] = useState<File | null>(null);
  const [sourceFileName, setSourceFileName] = useState<string | null>(null);
  const [saveInProgress, setSaveInProgress] = useState(false);
  const [downloadInProgress, setDownloadInProgress] = useState(false);
  const loadTokenRef = useRef(0);
  const dialogResolverRef = useRef<((value: any) => void) | null>(null);
  const authUserRef = useRef<User | null>(null);
  const savedFormsRetryRef = useRef(0);
  const savedFormsRetryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const csvInputRef = useRef<HTMLInputElement>(null);
  const excelInputRef = useRef<HTMLInputElement>(null);
  const txtInputRef = useRef<HTMLInputElement>(null);
  const fieldsRef = useRef<PdfField[]>([]);
  const historyRef = useRef<{ undo: PdfField[][]; redo: PdfField[][] }>({ undo: [], redo: [] });
  const pendingHistoryRef = useRef<PdfField[] | null>(null);
  const pendingAutoActionsRef = useRef<PendingAutoActions | null>(null);
  const [historyTick, setHistoryTick] = useState(0);
  const lastFieldVisibilityRef = useRef({ showFieldInfo, showFieldNames });
  const requiresEmailVerification = useMemo(
    () => Boolean(authUser && authSignInProvider === 'password' && !authUser.emailVerified),
    [authSignInProvider, authUser],
  );
  const verifiedUser = useMemo(
    () => (requiresEmailVerification ? null : authUser),
    [authUser, requiresEmailVerification],
  );
  const profileLimits = useMemo(
    () => userProfile?.limits ?? DEFAULT_PROFILE_LIMITS,
    [userProfile],
  );

  useEffect(() => {
    fieldsRef.current = fields;
  }, [fields]);

  useEffect(() => {
    if (!showFields) return;
    lastFieldVisibilityRef.current = { showFieldInfo, showFieldNames };
  }, [showFields, showFieldInfo, showFieldNames]);

  useEffect(() => {
    authUserRef.current = verifiedUser;
  }, [verifiedUser]);

  const clearSavedFormsRetry = useCallback(() => {
    if (savedFormsRetryTimerRef.current) {
      clearTimeout(savedFormsRetryTimerRef.current);
      savedFormsRetryTimerRef.current = null;
    }
    savedFormsRetryRef.current = 0;
  }, []);

  const refreshSavedForms = useCallback(
    async (options?: { allowRetry?: boolean }) => {
      const currentUser = authUserRef.current;
      if (!currentUser) return;
      try {
        const forms = await ApiService.getSavedForms({ suppressErrors: false });
        setSavedForms(forms || []);
        clearSavedFormsRetry();
      } catch (error) {
        if (!options?.allowRetry || !(error instanceof TypeError)) {
          debugLog('Failed to load saved forms', error);
          return;
        }
        const attempt = savedFormsRetryRef.current + 1;
        if (attempt > SAVED_FORMS_RETRY_LIMIT) {
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
    [clearSavedFormsRetry],
  );

  const loadUserProfile = useCallback(async () => {
    if (!authUserRef.current) return null;
    setProfileLoading(true);
    try {
      const profile = await ApiService.getProfile();
      setUserProfile(profile);
      return profile;
    } catch (error) {
      debugLog('Failed to load profile', error);
      setUserProfile(null);
      return null;
    } finally {
      setProfileLoading(false);
    }
  }, []);

  const syncAuthSession = useCallback(
    async (user: User | null, options?: { forceTokenRefresh?: boolean }) => {
      authUserRef.current = null;
      setAuthUser(user);
      setAuthSignInProvider(null);

      if (!user) {
        clearSavedFormsRetry();
        setSavedForms([]);
        setUserProfile(null);
        setShowProfile(false);
        return;
      }

      try {
        const tokenResult = await user.getIdTokenResult(options?.forceTokenRefresh ?? true);
        setAuthToken(tokenResult.token);
        const provider =
          tokenResult.signInProvider ??
          (user.providerData.length === 1 ? user.providerData[0]?.providerId ?? null : null);
        setAuthSignInProvider(provider);
        const needsVerification = provider === 'password' && !user.emailVerified;
        if (needsVerification) {
          clearSavedFormsRetry();
          setSavedForms([]);
          setUserProfile(null);
          setShowProfile(false);
          return;
        }
        authUserRef.current = user;
        await refreshSavedForms({ allowRetry: true });
        await loadUserProfile();
      } catch (error) {
        console.error('Failed to initialize session', error);
      }
    },
    [clearSavedFormsRetry, loadUserProfile, refreshSavedForms],
  );

  useEffect(() => {
    const unsubscribe = Auth.onAuthStateChanged(async (user) => {
      await syncAuthSession(user, { forceTokenRefresh: true });
      setAuthReady(true);
    });
    return () => {
      clearSavedFormsRetry();
      unsubscribe();
    };
  }, [clearSavedFormsRetry, syncAuthSession]);

  useEffect(() => {
    if (openAiError || schemaError) {
      setBannerNotice(null);
    }
  }, [openAiError, schemaError]);

  useEffect(() => {
    if (!bannerNotice?.autoDismissMs) return undefined;
    const timer = setTimeout(() => setBannerNotice(null), bannerNotice.autoDismissMs);
    return () => clearTimeout(timer);
  }, [bannerNotice]);

  useEffect(() => {
    if (!showProfile || !verifiedUser) return;
    void loadUserProfile();
  }, [loadUserProfile, showProfile, verifiedUser]);

  const pushFieldHistory = useCallback((snapshot: PdfField[]) => {
    const history = historyRef.current;
    history.undo = [...history.undo, snapshot].slice(-MAX_FIELD_HISTORY);
    history.redo = [];
    setHistoryTick((prev) => prev + 1);
  }, []);

  const resetFieldHistory = useCallback((nextFields: PdfField[] = []) => {
    historyRef.current.undo = [];
    historyRef.current.redo = [];
    pendingHistoryRef.current = null;
    fieldsRef.current = nextFields;
    setFields(nextFields);
    setHistoryTick((prev) => prev + 1);
  }, []);

  const clearPendingAutoActions = useCallback(() => {
    pendingAutoActionsRef.current = null;
  }, []);

  const updateFields = useCallback(
    (nextFields: PdfField[], options?: { trackHistory?: boolean }) => {
      const prev = fieldsRef.current;
      if (nextFields === prev) return;
      if (options?.trackHistory !== false) {
        pushFieldHistory(prev);
      }
      fieldsRef.current = nextFields;
      setFields(nextFields);
    },
    [pushFieldHistory],
  );

  const updateFieldsWith = useCallback(
    (updater: (prev: PdfField[]) => PdfField[], options?: { trackHistory?: boolean }) => {
      const prev = fieldsRef.current;
      const next = updater(prev);
      updateFields(next, options);
    },
    [updateFields],
  );

  const beginFieldHistory = useCallback(() => {
    if (!pendingHistoryRef.current) {
      pendingHistoryRef.current = fieldsRef.current;
    }
  }, []);

  const commitFieldHistory = useCallback(() => {
    const pending = pendingHistoryRef.current;
    if (!pending) return;
    pendingHistoryRef.current = null;
    if (pending === fieldsRef.current) return;
    pushFieldHistory(pending);
  }, [pushFieldHistory]);

  const handleUndo = useCallback(() => {
    const history = historyRef.current;
    if (!history.undo.length) return;
    const previous = history.undo[history.undo.length - 1];
    history.undo = history.undo.slice(0, -1);
    history.redo = [...history.redo, fieldsRef.current].slice(-MAX_FIELD_HISTORY);
    pendingHistoryRef.current = null;
    fieldsRef.current = previous;
    setFields(previous);
    setHistoryTick((prev) => prev + 1);
    setSelectedFieldId((currentId) =>
      currentId && previous.some((field) => field.id === currentId) ? currentId : null,
    );
  }, []);

  const handleRedo = useCallback(() => {
    const history = historyRef.current;
    if (!history.redo.length) return;
    const next = history.redo[history.redo.length - 1];
    history.redo = history.redo.slice(0, -1);
    history.undo = [...history.undo, fieldsRef.current].slice(-MAX_FIELD_HISTORY);
    pendingHistoryRef.current = null;
    fieldsRef.current = next;
    setFields(next);
    setHistoryTick((prev) => prev + 1);
    setSelectedFieldId((currentId) =>
      currentId && next.some((field) => field.id === currentId) ? currentId : null,
    );
  }, []);

  const clearWorkspace = useCallback(() => {
    setPdfDoc(null);
    setPageSizes({});
    setPageCount(0);
    setCurrentPage(1);
    setScale(1);
    setPendingPageJump(null);
    resetFieldHistory([]);
    setShowFields(true);
    setShowFieldNames(true);
    setShowFieldInfo(false);
    setConfidenceFilter({ high: true, medium: true, low: true });
    setSelectedFieldId(null);
    setProcessingMode(null);
    setMappingSessionId(null);
    setMappingInProgress(false);
    setHasMappedSchema(false);
    setCheckboxRules([]);
    setSchemaError(null);
    setSchemaId(null);
    setPendingSchemaPayload(null);
    setDataSourceKind('none');
    setDataSourceLabel(null);
    setSchemaUploadInProgress(false);
    setDataColumns([]);
    setDataRows([]);
    setIdentifierKey(null);
    setShowSearchFill(false);
    setSearchFillSessionId((prev) => prev + 1);
    setSourceFile(null);
    setSourceFileName(null);
    setSaveInProgress(false);
    setActiveSavedFormId(null);
    setActiveSavedFormName(null);
    setPendingDetectFile(null);
    setShowPipelineModal(false);
    setPipelineError(null);
    setUploadWantsRename(false);
    setUploadWantsMap(false);
    setDetectSessionId(null);
    setRenameInProgress(false);
    setHasRenamedFields(false);
    setOpenAiError(null);
    setBannerNotice(null);
    if (dialogResolverRef.current) {
      const fallback =
        dialogRequest?.kind === 'confirm'
          ? false
          : dialogRequest?.kind === 'prompt'
            ? null
            : null;
      dialogResolverRef.current(fallback);
    }
    dialogResolverRef.current = null;
    setDialogRequest(null);
  }, [dialogRequest, resetFieldHistory]);

  const resolveDialog = useCallback((value: any) => {
    const resolver = dialogResolverRef.current;
    dialogResolverRef.current = null;
    setDialogRequest(null);
    if (resolver) {
      resolver(value);
    }
  }, []);

  const requestConfirm = useCallback((options: ConfirmDialogOptions) => {
    return new Promise<boolean>((resolve) => {
      dialogResolverRef.current = resolve;
      setDialogRequest({ kind: 'confirm', ...options });
    });
  }, []);

  const requestPrompt = useCallback((options: PromptDialogOptions) => {
    return new Promise<string | null>((resolve) => {
      dialogResolverRef.current = resolve;
      setDialogRequest({ kind: 'prompt', ...options });
    });
  }, []);

  const handleSignOut = useCallback(async () => {
    await Auth.signOut();
    clearWorkspace();
    setSavedForms([]);
    setShowHomepage(true);
    setShowProfile(false);
  }, [clearWorkspace]);

  const handleNavigateHome = useCallback(() => {
    clearWorkspace();
    setLoadError(null);
    setShowHomepage(true);
  }, [clearWorkspace]);

  const handleOpenProfile = useCallback(() => {
    if (!verifiedUser) return;
    setShowProfile(true);
  }, [verifiedUser]);

  const handleCloseProfile = useCallback(() => {
    setShowProfile(false);
  }, []);

  const handleRefreshVerification = useCallback(async () => {
    const user = await Auth.refreshCurrentUser();
    await syncAuthSession(user, { forceTokenRefresh: true });
  }, [syncAuthSession]);

  const handleFillableUpload = useCallback(
    async (file: File) => {
      const loadToken = loadTokenRef.current + 1;
      loadTokenRef.current = loadToken;
      setShowSearchFill(false);
      setSearchFillSessionId((prev) => prev + 1);
      setProcessingMode('fillable');
      setIsProcessing(true);
      setLoadError(null);
      setShowHomepage(false);
      setMappingSessionId(crypto.randomUUID());
      setDetectSessionId(null);
      setHasRenamedFields(false);
      setHasMappedSchema(false);
      setCheckboxRules([]);
      setSchemaError(null);
      setOpenAiError(null);
      setSourceFile(file);
      setSourceFileName(file.name);
      setActiveSavedFormId(null);
      setActiveSavedFormName(null);
      try {
        const doc = await loadPdfFromFile(file);
        if (doc.numPages > profileLimits.fillableMaxPages) {
          if (loadTokenRef.current !== loadToken) return;
          clearWorkspace();
          setIsProcessing(false);
          setProcessingMode(null);
          setLoadError(
            `Fillable uploads are limited to ${profileLimits.fillableMaxPages} pages on your plan.`,
          );
          return;
        }
        const sizes = await loadPageSizes(doc);
        if (loadTokenRef.current !== loadToken) return;
        setPdfDoc(doc);
        setPageSizes(sizes);
        setPageCount(doc.numPages);
        setCurrentPage(1);
        setScale(1);
        setPendingPageJump(null);
        resetFieldHistory([]);
        setSelectedFieldId(null);
        setIsProcessing(false);
        setProcessingMode(null);

        void (async () => {
          let existingFields: PdfField[] = [];

          try {
            existingFields = await extractFieldsFromPdf(doc);
            debugLog('Extracted existing PDF fields', { total: existingFields.length });
          } catch (error) {
            debugLog('Failed to extract existing fields', error);
          }

          if (loadTokenRef.current !== loadToken) return;
          resetFieldHistory(existingFields);
          setSelectedFieldId(null);
          debugLog('Loaded fillable PDF', { name: file.name, pages: doc.numPages, fields: existingFields.length });
        })();
      } catch (error) {
        if (loadTokenRef.current !== loadToken) return;
        const message = error instanceof Error ? error.message : 'Unable to load PDF.';
        clearWorkspace();
        setIsProcessing(false);
        setProcessingMode(null);
        setLoadError(message);
        debugLog('Failed to load PDF', message);
      }
    },
    [clearWorkspace, profileLimits.fillableMaxPages, resetFieldHistory],
  );

  const handleSelectSavedForm = useCallback(
    async (formId: string) => {
      const loadToken = loadTokenRef.current + 1;
      loadTokenRef.current = loadToken;
      setShowSearchFill(false);
      setSearchFillSessionId((prev) => prev + 1);
      setProcessingMode('saved');
      setIsProcessing(true);
      setLoadError(null);
      setShowHomepage(false);
      setMappingSessionId(crypto.randomUUID());
      setDetectSessionId(null);
      setHasRenamedFields(false);
      setHasMappedSchema(false);
      setSchemaError(null);
      setOpenAiError(null);

      try {
        const savedMeta = await ApiService.loadSavedForm(formId);
        const blob = await ApiService.downloadSavedForm(formId);
        const name = savedMeta?.name || 'saved-form.pdf';
        const file = new File([blob], name, { type: 'application/pdf' });
        setSourceFile(file);
        setSourceFileName(name);
        const doc = await loadPdfFromFile(file);
        const sizes = await loadPageSizes(doc);
        if (loadTokenRef.current !== loadToken) return;
        setPdfDoc(doc);
        setPageSizes(sizes);
        setPageCount(doc.numPages);
        setCurrentPage(1);
        setScale(1);
        setPendingPageJump(null);
        resetFieldHistory([]);
        setSelectedFieldId(null);
        setIsProcessing(false);
        setProcessingMode(null);
        setActiveSavedFormId(formId);
        setActiveSavedFormName(savedMeta?.name || null);

        void (async () => {
          let existingFields: PdfField[] = [];

          try {
            existingFields = await extractFieldsFromPdf(doc);
            debugLog('Extracted saved form fields', { total: existingFields.length });
          } catch (error) {
            debugLog('Failed to extract saved form fields', error);
          }

          if (loadTokenRef.current !== loadToken) return;
          resetFieldHistory(existingFields);
          setSelectedFieldId(null);
          debugLog('Loaded saved form', { name, pages: doc.numPages, fields: existingFields.length });
        })();
      } catch (error) {
        if (loadTokenRef.current !== loadToken) return;
        const message = error instanceof Error ? error.message : 'Unable to load saved form.';
        clearWorkspace();
        setIsProcessing(false);
        setProcessingMode(null);
        setLoadError(message);
        debugLog('Failed to load saved form', message);
      }
    },
    [clearWorkspace, resetFieldHistory],
  );

  const handleSelectSavedFormFromProfile = useCallback(
    (formId: string) => {
      setShowProfile(false);
      void handleSelectSavedForm(formId);
    },
    [handleSelectSavedForm],
  );

  const handleDeleteSavedForm = useCallback(
    async (formId: string) => {
      const target = savedForms.find((form) => form.id === formId);
      const name = target?.name ? `"${target.name}"` : 'this saved form';
      const confirmDelete = await requestConfirm({
        title: 'Delete saved form?',
        message: `Delete ${name}? This removes it from your saved forms.`,
        confirmLabel: 'Delete',
        cancelLabel: 'Cancel',
        tone: 'danger',
      });
      if (!confirmDelete) return;

      setDeletingFormId(formId);
      try {
        await ApiService.deleteSavedForm(formId);
        setSavedForms((prev) => prev.filter((form) => form.id !== formId));
        if (formId === activeSavedFormId) {
          setActiveSavedFormId(null);
          setActiveSavedFormName(null);
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Failed to delete saved form.';
        setLoadError(message);
        debugLog('Failed to delete saved form', message);
      } finally {
        setDeletingFormId(null);
      }
    },
    [activeSavedFormId, requestConfirm, savedForms],
  );

  const handleSaveToProfile = useCallback(async () => {
    if (!pdfDoc) {
      setLoadError('No PDF is loaded to save.');
      return;
    }
    if (!verifiedUser) {
      setLoadError('Sign in to save this form to your profile.');
      return;
    }
    const maxSavedForms = profileLimits.savedFormsMax;
    const savedFormsLimitReached = savedForms.length >= maxSavedForms;
    if (!activeSavedFormId && savedFormsLimitReached) {
      setLoadError(`You have reached the saved forms limit (${maxSavedForms}). Delete a form to save another.`);
      return;
    }
    setLoadError(null);
    const defaultName = normaliseFormName(activeSavedFormName || sourceFileName || sourceFile?.name);
    const promptForName = async () => {
      const raw = await requestPrompt({
        title: 'Name this saved form',
        message: 'Enter a name to store this PDF in your saved forms list.',
        defaultValue: defaultName,
        placeholder: 'Saved form name',
        confirmLabel: 'Save',
        cancelLabel: 'Cancel',
        requireValue: true,
      });
      if (raw === null) return null;
      const trimmed = raw.trim();
      if (!trimmed) {
        setLoadError('A form name is required to save.');
        return null;
      }
      return normaliseFormName(trimmed);
    };

    let saveName = defaultName;
    let shouldOverwrite = false;
    if (activeSavedFormId) {
      const overwrite = await requestConfirm({
        title: 'Overwrite saved form?',
        message: 'This form is already saved. Overwrite it or save a new copy with a different name.',
        confirmLabel: 'Overwrite',
        cancelLabel: 'Save new copy',
        tone: 'danger',
      });
      if (overwrite) {
        shouldOverwrite = true;
      } else {
        if (savedFormsLimitReached) {
          setLoadError(`You have reached the saved forms limit (${maxSavedForms}). Delete a form to save another.`);
          return;
        }
        const nextName = await promptForName();
        if (!nextName) return;
        saveName = nextName;
      }
    } else {
      const nextName = await promptForName();
      if (!nextName) return;
      saveName = nextName;
    }

    const deleteAfterSaveId = shouldOverwrite ? activeSavedFormId : null;
    setSaveInProgress(true);
    try {
      let blob: Blob;
      if (sourceFile) {
        blob = sourceFile;
      } else {
        const data = await pdfDoc.getData();
        blob = new Blob([new Uint8Array(data)], { type: 'application/pdf' });
      }
      const fieldsForSave = prepareFieldsForMaterialize(fields);
      const generatedBlob = await ApiService.materializeFormPdf(blob, fieldsForSave);
      const payload = await ApiService.saveFormToProfile(generatedBlob, saveName, mappingSessionId || undefined);
      if (deleteAfterSaveId && payload?.id && payload.id !== deleteAfterSaveId) {
        await ApiService.deleteSavedForm(deleteAfterSaveId);
      }
      setActiveSavedFormId(payload?.id || null);
      setActiveSavedFormName(saveName);
      await refreshSavedForms();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to save form to profile.';
      setLoadError(message);
      debugLog('Failed to save form', message);
    } finally {
      setSaveInProgress(false);
    }
  }, [
    activeSavedFormId,
    activeSavedFormName,
    fields,
    mappingSessionId,
    pdfDoc,
    refreshSavedForms,
    requestConfirm,
    requestPrompt,
    sourceFile,
    sourceFileName,
    profileLimits.savedFormsMax,
    savedForms.length,
    verifiedUser,
  ]);

  const handleDownload = useCallback(async () => {
    if (!pdfDoc) {
      setLoadError('No PDF is loaded to download.');
      return;
    }
    if (!verifiedUser) {
      setLoadError('Sign in to download this form.');
      return;
    }
    setLoadError(null);
    setDownloadInProgress(true);
    try {
      let blob: Blob;
      if (sourceFile) {
        blob = sourceFile;
      } else {
        const data = await pdfDoc.getData();
        blob = new Blob([new Uint8Array(data)], { type: 'application/pdf' });
      }
      const generatedBlob = await ApiService.materializeFormPdf(blob, fields);
      const baseName = normaliseFormName(activeSavedFormName || sourceFileName || sourceFile?.name);
      const filename = `${baseName}-fillable.pdf`;
      const url = URL.createObjectURL(generatedBlob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to download form.';
      setLoadError(message);
      debugLog('Failed to download form', message);
    } finally {
      setDownloadInProgress(false);
    }
  }, [activeSavedFormName, fields, pdfDoc, sourceFile, sourceFileName, verifiedUser]);

  const applyFieldNameUpdates = useCallback((updatesByCurrentName: Map<string, FieldNameUpdate>) => {
    if (!updatesByCurrentName.size) return;
    updateFieldsWith((prev) => applyFieldNameUpdatesToList(prev, updatesByCurrentName));
  }, [updateFieldsWith]);

  const applyMappingResults = useCallback(
    (mappingResults?: any) => {
      if (!mappingResults) return;
      const mappings = mappingResults.mappings || [];
      const updates = new Map<string, FieldNameUpdate>();

      for (const mapping of mappings) {
        if (!mapping || !mapping.pdfField) continue;
        const currentName = mapping.originalPdfField || mapping.pdfField;
        const desiredName = mapping.pdfField;
        if (!currentName) continue;
        const mappingConfidence =
          parseConfidence(mapping.confidence) ?? deriveMappingConfidence(currentName, desiredName);
        updates.set(currentName, { newName: desiredName, mappingConfidence });
      }

      if (updates.size) {
        applyFieldNameUpdates(updates);
        debugLog('Applied AI mappings', { total: updates.size });
      }

      const rules = Array.isArray(mappingResults.checkboxRules) ? mappingResults.checkboxRules : [];
      setCheckboxRules(rules);
    },
    [applyFieldNameUpdates],
  );

  const buildTemplateFields = useCallback(
    (sourceFields: PdfField[]) =>
      sourceFields.map((field) => ({
        name: field.name,
        type: field.type,
        page: field.page,
        rect: field.rect,
        groupKey: field.groupKey,
        optionKey: field.optionKey,
        optionLabel: field.optionLabel,
        groupLabel: field.groupLabel,
      })),
    [],
  );

  const applyRenameResults = useCallback(
    (renamedFieldsPayload?: Array<Record<string, any>>): PdfField[] | null => {
      if (!Array.isArray(renamedFieldsPayload) || !renamedFieldsPayload.length) return null;
      const renamesByOriginal = new Map<string, Record<string, any>>();
      for (const entry of renamedFieldsPayload) {
        const original =
          entry.originalName || entry.original_name || entry.originalFieldName || entry.name;
        if (typeof original === 'string' && original.trim()) {
          renamesByOriginal.set(original, entry);
        }
      }

      if (!renamesByOriginal.size) return null;

      const updated: PdfField[] = [];
      for (const field of fieldsRef.current) {
        const rename = renamesByOriginal.get(field.name);
        if (!rename) continue;
        const renameConfidence = parseConfidence(rename.renameConfidence ?? rename.rename_confidence);
        const fieldConfidence = parseConfidence(
          rename.isItAfieldConfidence ?? rename.is_it_a_field_confidence,
        );
        const hasMappingConfidence =
          Object.prototype.hasOwnProperty.call(rename, 'mappingConfidence') ||
          Object.prototype.hasOwnProperty.call(rename, 'mapping_confidence');
        const mappingConfidence = parseConfidence(
          rename.mappingConfidence ?? rename.mapping_confidence,
        );
        const nextName = String(rename.name || rename.suggestedRename || field.name).trim() || field.name;
        updated.push({
          ...field,
          name: nextName,
          mappingConfidence: hasMappingConfidence ? mappingConfidence : field.mappingConfidence,
          renameConfidence: renameConfidence ?? field.renameConfidence,
          fieldConfidence: fieldConfidence ?? field.fieldConfidence,
          groupKey: rename.groupKey ?? field.groupKey,
          optionKey: rename.optionKey ?? field.optionKey,
          optionLabel: rename.optionLabel ?? field.optionLabel,
          groupLabel: rename.groupLabel ?? field.groupLabel,
        });
      }
      resetFieldHistory(updated);
      setSelectedFieldId(null);
      return updated;
    },
    [resetFieldHistory],
  );

  const applySchemaMappings = useCallback(
    async ({
      fieldsOverride,
      schemaIdOverride,
    }: { fieldsOverride?: PdfField[]; schemaIdOverride?: string | null } = {}): Promise<boolean> => {
      if (!verifiedUser) {
        setSchemaError(ALERT_MESSAGES.signInToRunSchemaMapping);
        return false;
      }
      clearPendingAutoActions();
      const activeSchemaId = schemaIdOverride ?? schemaId;
      if (!activeSchemaId) {
        setSchemaError(ALERT_MESSAGES.schemaRequiredForMapping);
        return false;
      }
      const activeFields = fieldsOverride ?? fieldsRef.current;
      if (!activeFields.length) {
        setSchemaError(ALERT_MESSAGES.noPdfFieldsToMap);
        return false;
      }

      setSchemaError(null);
      try {
        const mappingLoadToken = loadTokenRef.current;
        const templateFields = buildTemplateFields(activeFields);
        const mappingResult = await ApiService.mapSchema(
          activeSchemaId,
          templateFields,
          activeSavedFormId || undefined,
          detectSessionId || undefined,
        );
        if (loadTokenRef.current !== mappingLoadToken) {
          return false;
        }
        if (!mappingResult?.success) {
          throw new Error(mappingResult?.error || 'Mapping generation failed');
        }
        applyMappingResults(mappingResult.mappingResults);
        return true;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Schema mapping failed.';
      setSchemaError(message);
      debugLog('Schema mapping failed', message);
      return false;
    }
    },
    [
      activeSavedFormId,
      applyMappingResults,
      verifiedUser,
      buildTemplateFields,
      clearPendingAutoActions,
      detectSessionId,
      schemaId,
    ],
  );

  const handleMappingSuccess = useCallback(() => {
    setHasMappedSchema(true);
    setBannerNotice({
      tone: 'success',
      message: ALERT_MESSAGES.mappingDone,
      autoDismissMs: 5000,
    });
  }, []);

  const runOpenAiRename = useCallback(
    async ({
      confirm = true,
      allowDefer = false,
      sessionId,
      schemaId: renameSchemaId,
    }: {
      confirm?: boolean;
      allowDefer?: boolean;
      sessionId?: string | null;
      schemaId?: string | null;
    } = {}): Promise<PdfField[] | null> => {
      if (!verifiedUser) {
        setOpenAiError(ALERT_MESSAGES.signInToRunOpenAiRename);
        return null;
      }
      clearPendingAutoActions();
      const activeSessionId = sessionId || detectSessionId;
      if (!activeSessionId) {
        setOpenAiError(ALERT_MESSAGES.uploadPdfForRename);
        return null;
      }
      if (!fieldsRef.current.length) {
        if (allowDefer) {
          try {
            const statusPayload = await fetchDetectionStatus(activeSessionId);
            const status = String(statusPayload?.status || '').toLowerCase();
            if (status === 'queued' || status === 'running') {
              pendingAutoActionsRef.current = {
                loadToken: loadTokenRef.current,
                sessionId: activeSessionId,
                schemaId: renameSchemaId,
                autoRename: true,
                autoMap: Boolean(renameSchemaId),
              };
              setBannerNotice({
                tone: 'info',
                message: 'Detection is still running. Rename will start once fields are ready.',
                autoDismissMs: 8000,
              });
              return null;
            }
          } catch (error) {
            debugLog('Failed to fetch detection status for rename', error);
          }
        }
        setOpenAiError(ALERT_MESSAGES.noPdfFieldsToRename);
        return null;
      }
      if (confirm) {
        const ok = await requestConfirm({
          title: 'Send to OpenAI?',
          message:
            'This PDF and its field tags will be sent to OpenAI. No row data or field values are sent.',
          confirmLabel: 'Continue',
          cancelLabel: 'Cancel',
        });
        if (!ok) return null;
      }

      const hasSchemaForMap = Boolean(renameSchemaId);
      setOpenAiError(null);
      setMappingInProgress(true);
      setRenameInProgress(true);
      if (hasSchemaForMap) {
        setMapSchemaInProgress(true);
      }
      try {
        const renameLoadToken = loadTokenRef.current;
        const templateFields = buildTemplateFields(fieldsRef.current);
        const result = await ApiService.renameFields({
          sessionId: activeSessionId,
          schemaId: renameSchemaId || undefined,
          templateFields,
        });
        if (loadTokenRef.current !== renameLoadToken) {
          return null;
        }
        if (!result?.success) {
          throw new Error(result?.error || 'OpenAI rename failed.');
        }
        const updated = applyRenameResults(result.fields);
        if (!updated || updated.length === 0) {
          throw new Error('OpenAI rename returned no fields.');
        }
        setCheckboxRules(Array.isArray(result.checkboxRules) ? result.checkboxRules : []);
        setHasRenamedFields(true);
        return updated;
      } catch (error) {
        const message = error instanceof Error ? error.message : 'OpenAI rename failed.';
        setOpenAiError(message);
        debugLog('OpenAI rename failed', message);
        return null;
      } finally {
        setRenameInProgress(false);
        setMappingInProgress(false);
        if (hasSchemaForMap) {
          setMapSchemaInProgress(false);
        }
      }
    },
    [
      applyRenameResults,
      verifiedUser,
      buildTemplateFields,
      clearPendingAutoActions,
      detectSessionId,
      requestConfirm,
    ],
  );

  const persistSchemaPayload = useCallback(
    async (payload: SchemaPayload): Promise<string | null> => {
      if (!verifiedUser) return null;
      try {
        const created = await ApiService.createSchema(payload);
        const nextSchemaId = created.schemaId || null;
        setSchemaId(nextSchemaId);
        if (nextSchemaId) {
          setPendingSchemaPayload(null);
        }
        return nextSchemaId;
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Failed to store schema metadata.';
        setSchemaError(message);
        setSchemaId(null);
        return null;
      }
    },
    [verifiedUser],
  );

  const resolveSchemaForMapping = useCallback(
    async (mode: 'map' | 'renameAndMap'): Promise<string | null> => {
      if (!verifiedUser) {
        if (mode === 'renameAndMap') {
          setOpenAiError(ALERT_MESSAGES.signInToRunOpenAiRenameAndMap);
        } else {
          setSchemaError(ALERT_MESSAGES.signInToRunSchemaMapping);
        }
        return null;
      }
      if (dataSourceKind === 'none') {
        const message =
          mode === 'renameAndMap'
            ? ALERT_MESSAGES.chooseSchemaFileForRenameAndMap
            : ALERT_MESSAGES.chooseSchemaFileForMapping;
        setSchemaError(message);
        return null;
      }
      if (
        (dataSourceKind === 'csv' || dataSourceKind === 'excel' || dataSourceKind === 'txt') &&
        dataColumns.length === 0
      ) {
        setSchemaError(buildImportFileBeforeMapping(dataSourceKind));
        return null;
      }
      if (schemaId) {
        return schemaId;
      }
      if (!pendingSchemaPayload) {
        const message =
          mode === 'renameAndMap'
            ? ALERT_MESSAGES.chooseSchemaFileForRenameAndMap
            : ALERT_MESSAGES.chooseSchemaFileForMapping;
        setSchemaError(message);
        return null;
      }
      setSchemaUploadInProgress(true);
      try {
        return await persistSchemaPayload(pendingSchemaPayload);
      } finally {
        setSchemaUploadInProgress(false);
      }
    },
    [
      dataColumns.length,
      dataSourceKind,
      pendingSchemaPayload,
      persistSchemaPayload,
      schemaId,
      verifiedUser,
    ],
  );

  const confirmRemap = useCallback(async () => {
    if (!hasMappedSchema) return true;
    return requestConfirm({
      title: 'Remap fields?',
      message: 'A mapping already exists for this schema. Do you want to map again?',
      confirmLabel: 'Remap',
      cancelLabel: 'Cancel',
    });
  }, [hasMappedSchema, requestConfirm]);

  const handleMapSchema = useCallback(async () => {
    const resolvedSchemaId = await resolveSchemaForMapping('map');
    if (!resolvedSchemaId) return;
    const ok = await requestConfirm({
      title: 'Send to OpenAI?',
      message:
        'Your database field headers and PDF field tags will be sent to OpenAI. No row data or field values are sent.',
      confirmLabel: 'Continue',
      cancelLabel: 'Cancel',
    });
    if (!ok) return;
    const shouldRemap = await confirmRemap();
    if (!shouldRemap) return;

    setSchemaError(null);
    setOpenAiError(null);
    setMappingInProgress(true);
    setMapSchemaInProgress(true);
    try {
      const mapped = await applySchemaMappings({ schemaIdOverride: resolvedSchemaId });
      if (mapped) {
        handleMappingSuccess();
      }
    } finally {
      setMapSchemaInProgress(false);
      setMappingInProgress(false);
    }
  }, [
    applySchemaMappings,
    confirmRemap,
    handleMappingSuccess,
    requestConfirm,
    resolveSchemaForMapping,
  ]);

  const handleRename = useCallback(async () => {
    await runOpenAiRename({
      confirm: true,
    });
  }, [runOpenAiRename]);

  const handleRenameAndMap = useCallback(async () => {
    const resolvedSchemaId = await resolveSchemaForMapping('renameAndMap');
    if (!resolvedSchemaId) return;
    const ok = await requestConfirm({
      title: 'Send to OpenAI?',
      message:
        'This PDF and your database field headers will be sent to OpenAI. No row data or field values are sent.',
      confirmLabel: 'Continue',
      cancelLabel: 'Cancel',
    });
    if (!ok) return;
    const shouldRemap = await confirmRemap();
    if (!shouldRemap) return;

    setSchemaError(null);
    setOpenAiError(null);
    const renamed = await runOpenAiRename({
      confirm: false,
      schemaId: resolvedSchemaId,
    });
    if (!renamed) return;
    handleMappingSuccess();
  }, [
    confirmRemap,
    handleMappingSuccess,
    requestConfirm,
    resolveSchemaForMapping,
    runOpenAiRename,
  ]);

  const resumeDetectionPolling = useCallback(
    async (sessionId: string, loadToken: number) => {
      try {
        const payload = await pollDetectionStatus(sessionId, {
          timeoutMs: DETECTION_BACKGROUND_POLL_TIMEOUT_MS,
        });
        if (loadTokenRef.current !== loadToken) return;
        const status = String(payload?.status || '').toLowerCase();
        if (status === 'complete') {
          const nextFields = mapDetectionFields(payload);
          if (!nextFields.length) {
            setBannerNotice({
              tone: 'info',
              message: 'Detection finished but no fields were found.',
              autoDismissMs: 8000,
            });
            return;
          }
          const hasEdits = historyRef.current.undo.length > 0;
          if (hasEdits) {
            updateFields(nextFields);
          } else {
            resetFieldHistory(nextFields);
          }
          setSelectedFieldId(null);
          setHasRenamedFields(false);
          setHasMappedSchema(false);
          setCheckboxRules([]);
          setDetectSessionId(sessionId);
          setMappingSessionId(sessionId);
          const pendingAutoActions = pendingAutoActionsRef.current;
          if (
            pendingAutoActions &&
            pendingAutoActions.loadToken === loadToken &&
            pendingAutoActions.sessionId === sessionId
          ) {
            pendingAutoActionsRef.current = null;
            if (pendingAutoActions.autoRename && pendingAutoActions.autoMap) {
              const renamed = await runOpenAiRename({
                confirm: false,
                allowDefer: true,
                sessionId,
                schemaId: pendingAutoActions.schemaId,
              });
              if (renamed) {
                handleMappingSuccess();
              }
            } else if (pendingAutoActions.autoRename) {
              await runOpenAiRename({
                confirm: false,
                allowDefer: true,
                sessionId,
              });
            } else if (pendingAutoActions.autoMap) {
              if (!pendingAutoActions.schemaId) {
                setSchemaError('Upload a schema file before running mapping.');
              } else {
                const mapped = await applySchemaMappings({
                  schemaIdOverride: pendingAutoActions.schemaId,
                });
                if (mapped) {
                  handleMappingSuccess();
                }
              }
            }
          }
          setBannerNotice({
            tone: 'success',
            message: `Detection finished in the background (${nextFields.length} fields).`,
            autoDismissMs: 7000,
          });
          return;
        }
        if (status === 'failed') {
          const message = payload?.error || 'Detection failed on the backend.';
          setBannerNotice({
            tone: 'error',
            message: String(message),
            autoDismissMs: 8000,
          });
          return;
        }
        if (payload?.timedOut) {
          setBannerNotice({
            tone: 'info',
            message: 'Detection is still running on the backend. It may take a few more minutes.',
            autoDismissMs: 8000,
          });
        }
      } catch (error) {
        if (loadTokenRef.current !== loadToken) return;
        const message =
          error instanceof Error ? error.message : 'Detection failed on the backend.';
        setBannerNotice({
          tone: 'error',
          message,
          autoDismissMs: 8000,
        });
      }
    },
    [
      applySchemaMappings,
      handleMappingSuccess,
      resetFieldHistory,
      runOpenAiRename,
      setBannerNotice,
      setCheckboxRules,
      setDetectSessionId,
      setHasMappedSchema,
      setHasRenamedFields,
      setMappingSessionId,
      setSelectedFieldId,
      setSchemaError,
      updateFields,
    ],
  );

  const runDetectUpload = useCallback(
    async (
      file: File,
      options: { autoRename?: boolean; autoMap?: boolean; schemaIdOverride?: string | null } = {},
    ) => {
      const loadToken = loadTokenRef.current + 1;
      loadTokenRef.current = loadToken;
      pendingAutoActionsRef.current = null;
      setShowSearchFill(false);
      setSearchFillSessionId((prev) => prev + 1);

      setProcessingMode('detect');
      setIsProcessing(true);
      setProcessingDetail(DEFAULT_PROCESSING_MESSAGE);
      setLoadError(null);
      setShowHomepage(false);
      setMappingSessionId(null);
      setDetectSessionId(null);
      setHasRenamedFields(false);
      setHasMappedSchema(false);
      setCheckboxRules([]);
      setSchemaError(null);
      setOpenAiError(null);
      setSourceFile(file);
      setSourceFileName(file.name);
      setActiveSavedFormId(null);
      setActiveSavedFormName(null);
      try {
        const doc = await loadPdfFromFile(file);
        if (doc.numPages > profileLimits.detectMaxPages) {
          if (loadTokenRef.current !== loadToken) return;
          clearWorkspace();
          setIsProcessing(false);
          setProcessingMode(null);
          setLoadError(`Detection uploads are limited to ${profileLimits.detectMaxPages} pages on your plan.`);
          return;
        }
        const sizes = await loadPageSizes(doc);
        if (loadTokenRef.current !== loadToken) return;
        const activeSchemaId = options.schemaIdOverride ?? schemaId;

        let detectedFields: PdfField[] = [];
        let detectedSessionId: string | null = null;
        let detectionTimedOut = false;

        try {
          const detection = await detectFields(file, {
            pipeline: detectionPipeline,
            onStatus: (payload) => {
              if (loadTokenRef.current !== loadToken) return;
              const message = resolveDetectionStatusMessage(payload);
              if (message) {
                setProcessingDetail(message);
              }
            },
          });
          detectedSessionId = detection?.sessionId || null;
          detectionTimedOut = Boolean(detection?.timedOut);
          detectedFields = mapDetectionFields(detection);
          debugLog('Field detection returned', { total: detectedFields.length });
        } catch (error) {
          debugLog('Field detection failed', error);
        }

        if (!detectedFields.length) {
          try {
            detectedFields = await extractFieldsFromPdf(doc);
            debugLog('Fallback PDF field extraction returned', { total: detectedFields.length });
          } catch (error) {
            debugLog('Failed to extract existing fields', error);
          }
        }
        if (detectionTimedOut) {
          setBannerNotice({
            tone: 'info',
            message: 'Detection is still running on the backend. Using embedded form fields for now.',
            autoDismissMs: 8000,
          });
          if (detectedSessionId) {
            void resumeDetectionPolling(detectedSessionId, loadToken);
          }
        }

        if (loadTokenRef.current !== loadToken) return;
        setPdfDoc(doc);
        setPageSizes(sizes);
        setPageCount(doc.numPages);
        setCurrentPage(1);
        setScale(1);
        setPendingPageJump(null);
        resetFieldHistory(detectedFields);
        setSelectedFieldId(null);
        setIsProcessing(false);
        setProcessingMode(null);
        setDetectSessionId(detectedSessionId);
        if (detectedSessionId) {
          setMappingSessionId(detectedSessionId);
        }
        debugLog('Loaded PDF', { name: file.name, pages: doc.numPages, fields: detectedFields.length });

        if (loadTokenRef.current !== loadToken) return;
        if (!options.autoRename && !options.autoMap) return;

        if (detectionTimedOut && detectedSessionId) {
          pendingAutoActionsRef.current = {
            loadToken,
            sessionId: detectedSessionId,
            schemaId: activeSchemaId,
            autoRename: Boolean(options.autoRename),
            autoMap: Boolean(options.autoMap),
          };
          setBannerNotice({
            tone: 'info',
            message: 'Detection is still running. OpenAI actions will start once fields are ready.',
            autoDismissMs: 8000,
          });
          return;
        }
        if (!detectedFields.length) {
          setBannerNotice({
            tone: 'info',
            message: 'No fields detected. OpenAI actions were skipped.',
            autoDismissMs: 8000,
          });
          return;
        }

        if (options.autoRename && options.autoMap) {
          const renamed = await runOpenAiRename({
            confirm: false,
            allowDefer: true,
            sessionId: detectedSessionId,
            schemaId: activeSchemaId,
          });
          if (renamed) {
            handleMappingSuccess();
          }
          return;
        }
        if (options.autoRename) {
          await runOpenAiRename({
            confirm: false,
            allowDefer: true,
            sessionId: detectedSessionId,
          });
        }
        if (options.autoMap) {
          const mapped = await applySchemaMappings({ schemaIdOverride: activeSchemaId });
          if (mapped) {
            handleMappingSuccess();
          }
        }
      } catch (error) {
        if (loadTokenRef.current !== loadToken) return;
        const message = error instanceof Error ? error.message : 'Unable to load PDF.';
        clearWorkspace();
        setIsProcessing(false);
        setProcessingMode(null);
        setLoadError(message);
        debugLog('Failed to load PDF', message);
      }
    },
    [
      applySchemaMappings,
      clearWorkspace,
      handleMappingSuccess,
      profileLimits.detectMaxPages,
      resetFieldHistory,
      resumeDetectionPolling,
      runOpenAiRename,
      schemaId,
    ],
  );

  const handleDetectUpload = useCallback((file: File) => {
    setPendingDetectFile(file);
    setShowPipelineModal(true);
    setPipelineError(null);
    setUploadWantsRename(false);
    setUploadWantsMap(false);
  }, []);

  const handlePipelineCancel = useCallback(() => {
    setPendingDetectFile(null);
    setShowPipelineModal(false);
    setPipelineError(null);
  }, []);

  const handlePipelineConfirm = useCallback(async () => {
    if (!pendingDetectFile) return;
    const wantsRename = uploadWantsRename;
    const wantsMap = uploadWantsMap;
    let resolvedSchemaId = wantsMap ? schemaId : null;
    if (wantsMap) {
      if (schemaUploadInProgress) {
        setPipelineError('Schema file is still processing. Please wait.');
        return;
      }
      if (!resolvedSchemaId) {
        if (!pendingSchemaPayload) {
          setPipelineError('Upload a schema file before running mapping.');
          return;
        }
        if (!verifiedUser) {
          setPipelineError('Sign in to upload a schema file before running mapping.');
          return;
        }
        setSchemaUploadInProgress(true);
        try {
          resolvedSchemaId = await persistSchemaPayload(pendingSchemaPayload);
        } finally {
          setSchemaUploadInProgress(false);
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
    void runDetectUpload(file, {
      autoRename: wantsRename,
      autoMap: wantsMap,
      schemaIdOverride: wantsMap ? resolvedSchemaId : null,
    });
  }, [
    pendingDetectFile,
    pendingSchemaPayload,
    persistSchemaPayload,
    runDetectUpload,
    schemaId,
    schemaUploadInProgress,
    uploadWantsMap,
    uploadWantsRename,
    verifiedUser,
  ]);

  const handleClearDataSource = useCallback(() => {
    setSchemaError(null);
    setSchemaId(null);
    setPendingSchemaPayload(null);
    setDataSourceKind('none');
    setDataSourceLabel(null);
    setSchemaUploadInProgress(false);
    setDataColumns([]);
    setDataRows([]);
    setIdentifierKey(null);
    setHasMappedSchema(false);
  }, []);

  const handleChooseDataSource = useCallback(
    (kind: Exclude<DataSourceKind, 'none'>) => {
      setSchemaError(null);
      if (kind === 'csv') {
        csvInputRef.current?.click();
        return;
      }
      if (kind === 'excel') {
        excelInputRef.current?.click();
        return;
      }
      if (kind === 'txt') {
        txtInputRef.current?.click();
      }
    },
    [],
  );

  const applySchemaMetadata = useCallback(
    async ({
      kind,
      label,
      schema,
      rows = [],
      fileName,
      source,
    }: {
      kind: Exclude<DataSourceKind, 'none'>;
      label: string;
      schema: { fields: Array<{ name: string; type?: string }>; sampleCount: number };
      rows?: Array<Record<string, unknown>>;
      fileName: string;
      source: 'csv' | 'excel' | 'txt';
    }) => {
      const columns = schema.fields.map((field) => field.name);
      setDataSourceKind(kind);
      setDataSourceLabel(label);
      setDataColumns(columns);
      setDataRows(rows);
      setIdentifierKey(pickIdentifierKey(columns));
      setHasMappedSchema(false);
      setSchemaId(null);
      const payload: SchemaPayload = {
        name: fileName,
        fields: schema.fields,
        source,
        sampleCount: schema.sampleCount,
      };
      setPendingSchemaPayload(payload);
      if (!verifiedUser) {
        return;
      }
      await persistSchemaPayload(payload);
    },
    [persistSchemaPayload, verifiedUser],
  );

  const applyParsedDataSource = useCallback(
    async ({
      kind,
      label,
      columns,
      rows,
      fileName,
      source,
    }: {
      kind: Exclude<DataSourceKind, 'none'>;
      label: string;
      columns: string[];
      rows: Array<Record<string, unknown>>;
      fileName: string;
      source: 'csv' | 'excel';
    }) => {
      const schema = inferSchemaFromRows(columns, rows);
      await applySchemaMetadata({
        kind,
        label,
        schema,
        rows,
        fileName,
        source,
      });
    },
    [applySchemaMetadata],
  );

  const handleCsvFileSelected = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;

    setSchemaError(null);
    setMappingInProgress(true);
    setSchemaUploadInProgress(true);
    try {
      const text = await file.text();
      const parsed = parseCsv(text);
      if (!parsed.columns.length) {
        throw new Error('CSV file has no header row.');
      }
      await applyParsedDataSource({
        kind: 'csv',
        label: `CSV: ${file.name}`,
        columns: parsed.columns,
        rows: parsed.rows,
        fileName: file.name,
        source: 'csv',
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to import CSV file.';
      setSchemaError(message);
    } finally {
      setSchemaUploadInProgress(false);
      setMappingInProgress(false);
    }
  }, [applyParsedDataSource]);

  const handleExcelFileSelected = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;

    setSchemaError(null);
    setMappingInProgress(true);
    setSchemaUploadInProgress(true);
    try {
      const buffer = await file.arrayBuffer();
      const parsed = await parseExcel(buffer);
      if (!parsed.columns.length) {
        throw new Error('Excel sheet has no header row.');
      }
      await applyParsedDataSource({
        kind: 'excel',
        label: `Excel: ${file.name}${parsed.sheetName ? ` (${parsed.sheetName})` : ''}`,
        columns: parsed.columns,
        rows: parsed.rows,
        fileName: file.name,
        source: 'excel',
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to import Excel file.';
      setSchemaError(message);
    } finally {
      setSchemaUploadInProgress(false);
      setMappingInProgress(false);
    }
  }, [applyParsedDataSource]);

  const handleTxtFileSelected = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;

    setSchemaError(null);
    setMappingInProgress(true);
    setSchemaUploadInProgress(true);
    try {
      const text = await file.text();
      const schema = parseSchemaText(text);
      if (!schema.fields.length) {
        throw new Error('TXT schema file has no field names.');
      }
      await applySchemaMetadata({
        kind: 'txt',
        label: `TXT: ${file.name}`,
        schema,
        rows: [],
        fileName: file.name,
        source: 'txt',
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to import TXT schema file.';
      setSchemaError(message);
    } finally {
      setSchemaUploadInProgress(false);
      setMappingInProgress(false);
    }
  }, [applySchemaMetadata]);

  const handleSelectField = useCallback(
    (fieldId: string) => {
      setSelectedFieldId(fieldId);
      const field = fieldsRef.current.find((entry) => entry.id === fieldId);
      if (!field) return;
      if (field.page && field.page !== currentPage) {
        setCurrentPage(field.page);
      }
    },
    [currentPage],
  );

  const handlePageJump = useCallback((page: number) => {
    setCurrentPage(page);
    setPendingPageJump(page);
    setSelectedFieldId((prev) => {
      if (!prev) return prev;
      const field = fieldsRef.current.find((entry) => entry.id === prev);
      if (!field) return prev;
      return field.page === page ? prev : null;
    });
  }, []);

  const handlePageScroll = useCallback((page: number) => {
    setCurrentPage(page);
  }, []);

  const handlePageJumpComplete = useCallback(() => {
    setPendingPageJump(null);
  }, []);

  const handleUpdateField = useCallback((fieldId: string, updates: Partial<PdfField>) => {
    updateFieldsWith((prev) =>
      prev.map((field) => {
        if (field.id !== fieldId) return field;
        return {
          ...field,
          ...updates,
          rect: updates.rect ? { ...field.rect, ...updates.rect } : field.rect,
        };
      }),
    );
    debugLog('Updated field', fieldId, updates);
  }, [updateFieldsWith]);

  const handleUpdateFieldGeometry = useCallback(
    (fieldId: string, updates: Partial<PdfField>) => {
      updateFieldsWith(
        (prev) =>
          prev.map((field) => {
            if (field.id !== fieldId) return field;
            return {
              ...field,
              ...updates,
              rect: updates.rect ? { ...field.rect, ...updates.rect } : field.rect,
            };
          }),
        { trackHistory: false },
      );
    },
    [updateFieldsWith],
  );

  const handleDeleteField = useCallback((fieldId: string) => {
    updateFieldsWith((prev) => prev.filter((field) => field.id !== fieldId));
    setSelectedFieldId((prev) => (prev === fieldId ? null : prev));
    debugLog('Deleted field', fieldId);
  }, [updateFieldsWith]);

  const handleCreateField = useCallback(
    (type: FieldType) => {
      const pageSize = pageSizes[currentPage];
      if (!pageSize) return;
      const nextField = createField(type, currentPage, pageSize, fieldsRef.current);
      updateFieldsWith((prev) => [...prev, nextField]);
      setSelectedFieldId(nextField.id);
      debugLog('Created field', nextField);
    },
    [currentPage, pageSizes, updateFieldsWith],
  );

  const handleDismissBanner = useCallback(() => {
    if (openAiError || schemaError) {
      setSchemaError(null);
      setOpenAiError(null);
    }
    if (bannerNotice) {
      setBannerNotice(null);
    }
  }, [bannerNotice, openAiError, schemaError]);

  const handleFieldsChange = useCallback(
    (nextFields: PdfField[]) => {
      updateFields(nextFields);
    },
    [updateFields],
  );

  const hasFieldValues = useMemo(
    () =>
      fields.some((field) => {
        const value = field.value;
        if (value === null || value === undefined) return false;
        if (typeof value === 'string') return value.trim().length > 0;
        if (typeof value === 'boolean') return value;
        return true;
      }),
    [fields],
  );

  const handleClearFieldValues = useCallback(() => {
    updateFieldsWith((prev) => {
      let changed = false;
      const next = prev.map((field) => {
        const value = field.value;
        if (value === null || value === undefined) return field;
        if (typeof value === 'string' && value.trim().length === 0) return field;
        if (typeof value === 'boolean' && value === false) return field;
        changed = true;
        return { ...field, value: null };
      });
      return changed ? next : prev;
    });
  }, [updateFieldsWith]);

  const visibleFields = useMemo(
    () => fields.filter((field) => confidenceFilter[fieldConfidenceTierForField(field)]),
    [confidenceFilter, fields],
  );

  const canUndo = useMemo(() => historyRef.current.undo.length > 0, [historyTick]);
  const canRedo = useMemo(() => historyRef.current.redo.length > 0, [historyTick]);

  const handleConfidenceFilterChange = useCallback((tier: ConfidenceTier, enabled: boolean) => {
    setConfidenceFilter((prev) => ({
      ...prev,
      [tier]: enabled,
    }));
  }, []);

  const handleShowFieldsChange = useCallback((enabled: boolean) => {
    if (!enabled) {
      setShowFields(false);
      setShowFieldInfo(false);
      return;
    }
    setShowFields(true);
    const lastVisibility = lastFieldVisibilityRef.current;
    if (lastVisibility.showFieldInfo) {
      setShowFieldInfo(true);
      setShowFieldNames(false);
    } else {
      setShowFieldInfo(false);
      setShowFieldNames(lastVisibility.showFieldNames);
    }
  }, []);

  const handleShowFieldNamesChange = useCallback((enabled: boolean) => {
    setShowFieldNames(enabled);
    if (enabled) {
      setShowFieldInfo(false);
    }
  }, []);

  const handleShowFieldInfoChange = useCallback((enabled: boolean) => {
    setShowFieldInfo(enabled);
    if (enabled) {
      setShowFieldNames(false);
      setShowFields(true);
    }
  }, []);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (!pdfDoc || event.defaultPrevented) return;
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.isContentEditable ||
          target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.tagName === 'SELECT')
      ) {
        return;
      }
      const isMac = /Mac|iPhone|iPad|iPod/.test(navigator.platform);
      const modifier = isMac ? event.metaKey : event.ctrlKey;
      if (!modifier) return;
      const key = event.key.toLowerCase();
      if (key === 'z') {
        event.preventDefault();
        if (event.shiftKey) {
          handleRedo();
        } else {
          handleUndo();
        }
      } else if (key === 'x') {
        if (!selectedFieldId) return;
        event.preventDefault();
        handleDeleteField(selectedFieldId);
      } else if (key === 'y') {
        event.preventDefault();
        handleRedo();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleDeleteField, handleRedo, handleUndo, pdfDoc, selectedFieldId]);

  const userEmail = useMemo(() => verifiedUser?.email ?? undefined, [verifiedUser]);
  const hasDocument = !!pdfDoc;
  const savedFormsLimitReached = savedForms.length >= profileLimits.savedFormsMax;
  const canSaveToProfile =
    Boolean(pdfDoc && verifiedUser) && (!savedFormsLimitReached || Boolean(activeSavedFormId));
  const canDownload = Boolean(pdfDoc && verifiedUser);
  const canMapSchema = useMemo(() => {
    if (!verifiedUser) return false;
    if (!hasDocument || fields.length === 0) return false;
    if (dataSourceKind === 'csv' || dataSourceKind === 'excel' || dataSourceKind === 'txt') {
      return dataColumns.length > 0 && Boolean(schemaId || pendingSchemaPayload);
    }
    return false;
  }, [
    dataColumns.length,
    dataSourceKind,
    fields.length,
    hasDocument,
    pendingSchemaPayload,
    schemaId,
    verifiedUser,
  ]);
  const canRename = useMemo(() => {
    if (!verifiedUser) return false;
    if (!hasDocument || fields.length === 0) return false;
    if (!detectSessionId) return false;
    return true;
  }, [detectSessionId, fields.length, hasDocument, verifiedUser]);
  const canRenameAndMap = useMemo(() => {
    if (!canRename) return false;
    return canMapSchema;
  }, [canMapSchema, canRename]);
  const canSearchFill = useMemo(() => {
    if (!hasDocument) return false;
    if (dataSourceKind === 'csv' || dataSourceKind === 'excel') return dataRows.length > 0;
    return false;
  }, [dataRows.length, dataSourceKind, hasDocument]);
  const activeErrorMessage = openAiError ?? schemaError;
  const bannerAlert: BannerNotice | null = activeErrorMessage
    ? { tone: 'error', message: activeErrorMessage }
    : bannerNotice;
  const dialogContent = (() => {
    if (!dialogRequest) return null;
    if (dialogRequest.kind === 'confirm') {
      return (
        <ConfirmDialog
          open
          title={dialogRequest.title}
          description={dialogRequest.message}
          confirmLabel={dialogRequest.confirmLabel}
          cancelLabel={dialogRequest.cancelLabel}
          tone={dialogRequest.tone}
          onConfirm={() => resolveDialog(true)}
          onCancel={() => resolveDialog(false)}
        />
      );
    }
    if (dialogRequest.kind === 'prompt') {
      return (
        <PromptDialog
          open
          title={dialogRequest.title}
          description={dialogRequest.message}
          confirmLabel={dialogRequest.confirmLabel}
          cancelLabel={dialogRequest.cancelLabel}
          tone={dialogRequest.tone}
          defaultValue={dialogRequest.defaultValue}
          placeholder={dialogRequest.placeholder}
          requireValue={dialogRequest.requireValue}
          onSubmit={(value) => resolveDialog(value)}
          onCancel={() => resolveDialog(null)}
        />
      );
    }
    return null;
  })();
  const dataSourceInputs = (
    <>
      <input
        ref={csvInputRef}
        type="file"
        accept=".csv,text/csv"
        style={{ display: 'none' }}
        onChange={handleCsvFileSelected}
      />
      <input
        ref={excelInputRef}
        type="file"
        accept=".xlsx,.xls,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel"
        style={{ display: 'none' }}
        onChange={handleExcelFileSelected}
      />
      <input
        ref={txtInputRef}
        type="file"
        accept=".txt,text/plain"
        style={{ display: 'none' }}
        onChange={handleTxtFileSelected}
      />
    </>
  );
  const currentView = showHomepage
    ? 'homepage'
    : isProcessing
      ? 'processing'
    : hasDocument
      ? 'editor'
      : 'upload';
  const shouldShowProcessingAd = processingMode === 'detect' && Boolean(PROCESSING_AD_VIDEO_URL);

  useEffect(() => {
    if (currentView === 'editor') return;
    window.scrollTo({ top: 0, left: 0, behavior: 'auto' });
  }, [currentView]);

  if (!authReady) {
    return (
      <div className="auth-loading-screen">
        <div className="auth-loading-card">Loading workspace…</div>
      </div>
    );
  }

  if (requiresEmailVerification) {
    return (
      <VerifyEmailPage
        email={authUser?.email ?? null}
        onRefresh={handleRefreshVerification}
        onSignOut={handleSignOut}
      />
    );
  }

  if (showLogin) {
    return (
      <LoginPage
        onAuthenticated={() => setShowLogin(false)}
        onCancel={() => setShowLogin(false)}
      />
    );
  }

  if (showProfile && verifiedUser) {
    return (
      <ProfilePage
        email={userProfile?.email ?? verifiedUser.email}
        role={userProfile?.role ?? 'basic'}
        creditsRemaining={userProfile?.creditsRemaining ?? 0}
        isLoading={profileLoading}
        limits={profileLimits}
        savedForms={savedForms}
        onSelectSavedForm={handleSelectSavedFormFromProfile}
        onDeleteSavedForm={handleDeleteSavedForm}
        deletingFormId={deletingFormId}
        onClose={handleCloseProfile}
        onSignOut={handleSignOut}
      />
    );
  }

  if (currentView !== 'editor') {
    return (
      <div className="homepage-shell">
        {bannerAlert ? (
          <Alert
            tone={bannerAlert.tone}
            variant="banner"
            message={bannerAlert.message}
            onDismiss={handleDismissBanner}
          />
        ) : null}
        {dialogContent}
        <LegacyHeader
          currentView={currentView}
          onNavigateHome={handleNavigateHome}
          showBackButton={!showHomepage}
          userEmail={verifiedUser?.email ?? null}
          onOpenProfile={verifiedUser ? handleOpenProfile : undefined}
          onSignOut={verifiedUser ? handleSignOut : undefined}
          onSignIn={!verifiedUser ? () => setShowLogin(true) : undefined}
        />
        <main className="landing-main">
          {currentView === 'homepage' && (
            <Homepage onStartWorkflow={() => setShowHomepage(false)} />
          )}
          {currentView === 'upload' && (
            <div className="upload-layout">
              {showPipelineModal && (
                <div
                  className="pipeline-modal"
                  role="dialog"
                  aria-modal="true"
                  aria-labelledby="pipeline-modal-title"
                >
                  <div className="pipeline-modal__card">
                    <div className="pipeline-modal__header">
                      <h2 id="pipeline-modal-title" className="pipeline-modal__title">
                        Choose your detection pipeline
                      </h2>
                      {pendingDetectFile && (
                        <p className="pipeline-modal__subtitle">{pendingDetectFile.name}</p>
                      )}
                    </div>
                    <div className="pipeline-modal__section">
                      <span className="pipeline-modal__section-title">Detection pipeline</span>
                      <label className="pipeline-modal__choice">
                        <input
                          type="radio"
                          name="pipeline"
                          value="commonforms"
                          checked
                          disabled
                        />
                        CommonForms (FFDNet-L)
                      </label>
                    </div>
                    <div className="pipeline-modal__section">
                      <span className="pipeline-modal__section-title">OpenAI actions</span>
                      <p className="pipeline-modal__notice">
                        Rename sends PDF pages and detected field tags. Mapping sends schema header names and field
                        tags. If both are selected, OpenAI receives the PDF pages and schema headers to standardize
                        names. No row data or field values are sent.
                      </p>
                      <label className="pipeline-modal__choice">
                        <input
                          type="checkbox"
                          checked={uploadWantsRename}
                          onChange={(event) => setUploadWantsRename(event.target.checked)}
                        />
                        Rename fields with OpenAI
                      </label>
                      <label className="pipeline-modal__choice">
                        <input
                          type="checkbox"
                          checked={uploadWantsMap}
                          onChange={(event) => setUploadWantsMap(event.target.checked)}
                        />
                        Map to schema (CSV/Excel/TXT)
                      </label>
                      {uploadWantsRename || uploadWantsMap ? (
                        <p className="pipeline-modal__hint">
                          {uploadWantsRename && uploadWantsMap
                            ? 'OpenAI will receive the PDF pages, detected field tags, and your database field headers. No row data or field values are sent.'
                            : uploadWantsRename
                              ? 'OpenAI will receive the PDF pages and detected field tags. No row data or field values are sent.'
                              : 'OpenAI will receive your database field headers and detected field tags. No row data or field values are sent.'}
                        </p>
                      ) : null}
                      {uploadWantsMap ? (
                        <div className="pipeline-modal__schema-block">
                          <div className="pipeline-modal__source-row">
                            <button
                              type="button"
                              className="ui-button ui-button--ghost ui-button--compact"
                              onClick={() => handleChooseDataSource('csv')}
                            >
                              CSV
                            </button>
                            <button
                              type="button"
                              className="ui-button ui-button--ghost ui-button--compact"
                              onClick={() => handleChooseDataSource('excel')}
                            >
                              Excel
                            </button>
                            <button
                              type="button"
                              className="ui-button ui-button--ghost ui-button--compact"
                              onClick={() => handleChooseDataSource('txt')}
                            >
                              TXT
                            </button>
                          </div>
                          <span className="pipeline-modal__status pipeline-modal__status--center">
                            Schema file: {dataSourceLabel || 'None selected'}
                            {schemaUploadInProgress ? ' (processing)' : ''}
                          </span>
                        </div>
                      ) : null}
                    </div>
                    {pipelineError ? (
                      <div className="pipeline-modal__alert">
                        <Alert tone="error" variant="inline" size="sm" message={pipelineError} />
                      </div>
                    ) : null}
                    <div className="pipeline-modal__actions">
                      <button
                        className="ui-button ui-button--ghost"
                        type="button"
                        onClick={handlePipelineCancel}
                      >
                        Cancel
                      </button>
                      <button
                        className="ui-button ui-button--primary"
                        type="button"
                        onClick={handlePipelineConfirm}
                        disabled={!pendingDetectFile || (uploadWantsMap && schemaUploadInProgress)}
                      >
                        Continue
                      </button>
                    </div>
                  </div>
                </div>
              )}
              <div className="upload-primary-grid">
                <UploadComponent
                  variant="detect"
                  title="Upload PDF for Field Detection"
                  subtitle="Drag and drop your PDF file here, or"
                  onFileUpload={handleDetectUpload}
                  onValidationError={(message) => setLoadError(message)}
                />
                <UploadComponent
                  variant="fillable"
                  title="Upload Fillable PDF Template"
                  subtitle="Open your existing fillable PDF directly in the editor"
                  onFileUpload={handleFillableUpload}
                  onValidationError={(message) => setLoadError(message)}
                />
              </div>
              {verifiedUser && (
                <section className="saved-forms-section" aria-label="Open saved form">
                  <h2 className="saved-forms-title">Open Saved Form:</h2>
                  <UploadComponent
                    variant="saved"
                    title=""
                    subtitle=""
                    savedForms={savedForms}
                    onSelectSavedForm={handleSelectSavedForm}
                    onDeleteSavedForm={handleDeleteSavedForm}
                    deletingFormId={deletingFormId}
                  />
                </section>
              )}
              {loadError ? (
                <div className="upload-alert">
                  <Alert tone="error" variant="inline" message={loadError} />
                </div>
              ) : null}
            </div>
          )}
          {currentView === 'processing' && (
            <div className="processing-indicator">
              <div className="spinner"></div>
              <h3>Preparing your form…</h3>
              <p>{processingDetail}</p>
              {shouldShowProcessingAd ? (
                <div className="processing-ad" aria-live="polite">
                  <video
                    className="processing-ad__video"
                    src={PROCESSING_AD_VIDEO_URL}
                    poster={PROCESSING_AD_POSTER_URL || undefined}
                    autoPlay
                    muted
                    loop
                    playsInline
                    preload="auto"
                  />
                  <p className="processing-ad__note">
                    This short video runs while field detection finishes on the backend. It helps
                    cover hosting so the tool can stay free.
                  </p>
                </div>
              ) : null}
            </div>
          )}
        </main>
        {dataSourceInputs}
      </div>
    );
  }

  return (
    <div className="app">
      {bannerAlert ? (
        <Alert
          tone={bannerAlert.tone}
          variant="banner"
          message={bannerAlert.message}
          onDismiss={handleDismissBanner}
        />
      ) : null}
      {dialogContent}
      <HeaderBar
        pageCount={pageCount}
        currentPage={currentPage}
        scale={scale}
        onScaleChange={setScale}
        onNavigateHome={handleNavigateHome}
        mappingInProgress={mappingInProgress}
        mapSchemaInProgress={mapSchemaInProgress}
        hasMappedSchema={hasMappedSchema}
        renameInProgress={renameInProgress}
        hasRenamedFields={hasRenamedFields}
        dataSourceKind={dataSourceKind}
        dataSourceLabel={dataSourceLabel}
        onChooseDataSource={handleChooseDataSource}
        onClearDataSource={handleClearDataSource}
        onRename={handleRename}
        onRenameAndMap={handleRenameAndMap}
        onMapSchema={handleMapSchema}
        canMapSchema={canMapSchema}
        canRename={canRename}
        canRenameAndMap={canRenameAndMap}
        onOpenSearchFill={canSearchFill ? () => setShowSearchFill(true) : undefined}
        canSearchFill={canSearchFill}
        onDownload={handleDownload}
        onSaveToProfile={handleSaveToProfile}
        downloadInProgress={downloadInProgress}
        saveInProgress={saveInProgress}
        canDownload={canDownload}
        canSave={canSaveToProfile}
        userEmail={userEmail}
        onOpenProfile={verifiedUser ? handleOpenProfile : undefined}
        onSignIn={!verifiedUser ? () => setShowLogin(true) : undefined}
        onSignOut={verifiedUser ? handleSignOut : undefined}
      />
      <div className="app-shell">
        <FieldListPanel
          fields={visibleFields}
          selectedFieldId={selectedFieldId}
          currentPage={currentPage}
          pageCount={pageCount}
          showFields={showFields}
          showFieldNames={showFieldNames}
          showFieldInfo={showFieldInfo}
          onShowFieldsChange={handleShowFieldsChange}
          onShowFieldNamesChange={handleShowFieldNamesChange}
          onShowFieldInfoChange={handleShowFieldInfoChange}
          canClearInputs={hasFieldValues}
          onClearInputs={handleClearFieldValues}
          confidenceFilter={confidenceFilter}
          onConfidenceFilterChange={handleConfidenceFilterChange}
          onSelectField={handleSelectField}
          onPageChange={handlePageJump}
        />
        <main className="workspace">
          {loadError ? (
            <div className="viewer viewer--empty">
              <div className="viewer__placeholder viewer__placeholder--error">
                <h2>Unable to load PDF</h2>
                <Alert tone="error" variant="inline" message={loadError} />
              </div>
            </div>
          ) : (
            <PdfViewer
              pdfDoc={pdfDoc}
              pageNumber={currentPage}
              scale={scale}
              pageSizes={pageSizes}
              fields={visibleFields}
              showFields={showFields}
              showFieldNames={showFieldNames}
              showFieldInfo={showFieldInfo}
              selectedFieldId={selectedFieldId}
              onSelectField={handleSelectField}
              onUpdateField={handleUpdateField}
              onUpdateFieldGeometry={handleUpdateFieldGeometry}
              onBeginFieldChange={beginFieldHistory}
              onCommitFieldChange={commitFieldHistory}
              onPageChange={handlePageScroll}
              pendingPageJump={pendingPageJump}
              onPageJumpComplete={handlePageJumpComplete}
            />
          )}
        </main>
        <FieldInspectorPanel
          fields={fields}
          selectedFieldId={selectedFieldId}
          currentPage={currentPage}
          onUpdateField={handleUpdateField}
          onDeleteField={handleDeleteField}
          onCreateField={handleCreateField}
          canUndo={canUndo}
          canRedo={canRedo}
          onUndo={handleUndo}
          onRedo={handleRedo}
        />
      </div>
      {showSearchFill ? (
        <SearchFillModal
          open={showSearchFill}
          onClose={() => setShowSearchFill(false)}
          sessionId={searchFillSessionId}
          dataSourceKind={dataSourceKind}
          dataSourceLabel={dataSourceLabel}
          columns={dataColumns}
          identifierKey={identifierKey}
          rows={dataRows}
          fields={fields}
          checkboxRules={checkboxRules}
          onFieldsChange={handleFieldsChange}
          onClearFields={handleClearFieldValues}
          onAfterFill={() => {
            setShowFieldInfo(true);
            setShowFieldNames(false);
            setShowFields(true);
          }}
          onError={(message) => setSchemaError(message)}
        />
      ) : null}
      {dataSourceInputs}
    </div>
  );
}

export default App;
