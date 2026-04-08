import { useCallback, useMemo, useRef, useState } from 'react';
import type { User } from 'firebase/auth';
import type {
  BannerNotice,
  CheckboxRule,
  ConfirmDialogOptions,
  PdfField,
  RadioGroupSuggestion,
  TextTransformRule,
} from '../types';
import { ALERT_MESSAGES } from '../utils/alertMessages';
import { resolveIdentifierKey } from '../utils/dataSource';
import { buildTemplateFields } from '../utils/fields';
import { debugLog } from '../utils/debug';
import {
  applyMappingPayloadToFields,
  applyRenamePayloadToFields,
  deriveCombinedRadioGroupSuggestions,
} from '../utils/openAiFields';
import { resolveSourcePdfSha256 } from '../utils/pdfFingerprint';
import { ApiService, type UserProfile } from '../services/api';
import { ApiError } from '../services/apiConfig';
import { fetchDetectionStatus } from '../services/detectionApi';
import type { PendingAutoActions } from '../types';

export interface UseOpenAiPipelineDeps {
  verifiedUser: User | null;
  fieldsRef: React.MutableRefObject<PdfField[]>;
  loadTokenRef: React.MutableRefObject<number>;
  detectSessionId: string | null;
  setDetectSessionId: (sessionId: string | null) => void;
  setMappingSessionId: (sessionId: string | null) => void;
  activeSavedFormId: string | null;
  pageCount: number;
  dataColumns: string[];
  schemaId: string | null;
  pendingAutoActionsRef: React.MutableRefObject<PendingAutoActions | null>;
  setBannerNotice: (notice: BannerNotice | null) => void;
  requestConfirm: (options: ConfirmDialogOptions) => Promise<boolean | null>;
  resolveSourcePdfBytes: () => Promise<Uint8Array>;
  loadUserProfile: () => Promise<UserProfile | null>;
  resetFieldHistory: (fields?: PdfField[]) => void;
  updateFieldsWith: (updater: (prev: PdfField[]) => PdfField[], options?: { trackHistory?: boolean }) => void;
  setIdentifierKey: (key: string | null) => void;
  onBeforeOpenAiAction?: (action: 'rename' | 'map' | 'rename_remap', sessionId: string | null) => Promise<void> | void;
  // For computed canRename/canMapSchema
  hasDocument: boolean;
  fieldsCount: number;
  dataSourceKind: string;
  hasSchemaOrPending: boolean;
}

function fieldHasMeaningfulValue(field: PdfField): boolean {
  const value = field.value;
  if (value === null || value === undefined) return false;
  if (typeof value === 'string') return value.trim().length > 0;
  if (typeof value === 'boolean') return value;
  return true;
}

function clearFieldValuesForTemplateChange(fields: PdfField[]): {
  fields: PdfField[];
  clearedValues: boolean;
} {
  let nextFields: PdfField[] | null = null;
  for (let index = 0; index < fields.length; index += 1) {
    const field = fields[index];
    if (!fieldHasMeaningfulValue(field)) continue;
    if (!nextFields) nextFields = [...fields];
    nextFields[index] = { ...field, value: null };
  }
  return {
    fields: nextFields ?? fields,
    clearedValues: nextFields !== null,
  };
}

export function useOpenAiPipeline(deps: UseOpenAiPipelineDeps) {
  const [renameInProgress, setRenameInProgress] = useState(false);
  const [hasRenamedFields, setHasRenamedFields] = useState(false);
  const [mappingInProgress, setMappingInProgress] = useState(false);
  const [mapSchemaInProgress, setMapSchemaInProgress] = useState(false);
  const [hasMappedSchema, setHasMappedSchema] = useState(false);
  const [openAiError, setOpenAiError] = useState<string | null>(null);
  const [checkboxRules, setCheckboxRules] = useState<CheckboxRule[]>([]);
  const [radioGroupSuggestions, setRadioGroupSuggestions] = useState<RadioGroupSuggestion[]>([]);
  const [textTransformRules, setTextTransformRules] = useState<TextTransformRule[]>([]);
  const templateInputsClearedRef = useRef(false);

  const resolveCreditExhaustionMessage = useCallback(async (): Promise<string> => {
    try {
      const profile = await deps.loadUserProfile();
      const role = String(profile?.role || '').toLowerCase();
      if (role === 'pro') {
        return 'OpenAI credits exhausted. Buy a 500-credit refill from your profile to continue.';
      }
      return 'OpenAI credits exhausted. Upgrade to Pro from your profile to continue.';
    } catch {
      return 'OpenAI credits exhausted. Check your profile to continue.';
    }
  }, [deps]);

  const clearPendingAutoActions = useCallback(() => {
    deps.pendingAutoActionsRef.current = null;
  }, [deps.pendingAutoActionsRef]);

  const resetTemplateInputsClearedFlag = useCallback(() => {
    templateInputsClearedRef.current = false;
  }, []);

  const noteTemplateInputsCleared = useCallback((clearedValues: boolean) => {
    if (clearedValues) {
      templateInputsClearedRef.current = true;
    }
  }, []);

  const consumeTemplateInputsClearedMessage = useCallback((baseMessage: string): string => {
    if (!templateInputsClearedRef.current) {
      return baseMessage;
    }
    templateInputsClearedRef.current = false;
    return `${baseMessage} ${ALERT_MESSAGES.templateInputsCleared}`;
  }, []);

  const resolveActiveSourcePdfSha256 = useCallback(async (): Promise<string> => {
    return resolveSourcePdfSha256(deps.resolveSourcePdfBytes, {
      onError: (error) => {
        debugLog('Failed to resolve active PDF fingerprint for OpenAI action', error);
      },
    });
  }, [deps.resolveSourcePdfBytes]);

  const ensureTemplateSessionId = useCallback(async (): Promise<string | null> => {
    if (deps.detectSessionId) {
      return deps.detectSessionId;
    }
    if (!deps.activeSavedFormId) {
      return null;
    }
    const activeFields = deps.fieldsRef.current;
    if (!activeFields.length) {
      return null;
    }
    const sessionPayload = await ApiService.createSavedFormSession(deps.activeSavedFormId, {
      fields: buildTemplateFields(activeFields),
      pageCount: deps.pageCount || undefined,
    });
    deps.setDetectSessionId(sessionPayload.sessionId);
    deps.setMappingSessionId(sessionPayload.sessionId);
    return sessionPayload.sessionId;
  }, [deps]);

  const applyMappingResults = useCallback(
    (mappingResults?: Record<string, unknown> | null) => {
      if (!mappingResults) return;
      const mapped = applyMappingPayloadToFields(
        deps.fieldsRef.current,
        mappingResults,
        deps.dataColumns,
      );
      const clearedTemplateInputs = clearFieldValuesForTemplateChange(mapped.fields);
      noteTemplateInputsCleared(clearedTemplateInputs.clearedValues);
      if (clearedTemplateInputs.fields !== deps.fieldsRef.current) {
        deps.resetFieldHistory(clearedTemplateInputs.fields);
        debugLog('Applied AI mappings', {
          total: clearedTemplateInputs.fields.length,
          clearedValues: clearedTemplateInputs.clearedValues,
        });
      }
      setCheckboxRules(mapped.checkboxRules);
      setRadioGroupSuggestions(mapped.radioGroupSuggestions);
      setTextTransformRules(mapped.textTransformRules);
      const resolvedIdentifier = resolveIdentifierKey(
        mappingResults.identifierKey || mappingResults.identifier_key,
        deps.dataColumns,
      );
      if (resolvedIdentifier) {
        deps.setIdentifierKey(resolvedIdentifier);
      }
    },
    [deps, noteTemplateInputsCleared],
  );

  const applyRenameResults = useCallback(
    (renamedFieldsPayload?: Array<Record<string, unknown>>): PdfField[] | null => {
      const updated = applyRenamePayloadToFields(deps.fieldsRef.current, renamedFieldsPayload);
      if (!updated || updated.length === 0) return null;
      const clearedTemplateInputs = clearFieldValuesForTemplateChange(updated);
      noteTemplateInputsCleared(clearedTemplateInputs.clearedValues);
      deps.resetFieldHistory(clearedTemplateInputs.fields);
      return clearedTemplateInputs.fields;
    },
    [deps, noteTemplateInputsCleared],
  );

  const applySchemaMappings = useCallback(
    async ({
      fieldsOverride,
      schemaIdOverride,
      sessionIdOverride,
    }: {
      fieldsOverride?: PdfField[];
      schemaIdOverride?: string | null;
      sessionIdOverride?: string | null;
    } = {}): Promise<boolean> => {
      if (!deps.verifiedUser) {
        setOpenAiError(ALERT_MESSAGES.signInToRunSchemaMapping);
        return false;
      }
      clearPendingAutoActions();
      const activeSchemaId = schemaIdOverride ?? deps.schemaId;
      if (!activeSchemaId) {
        setOpenAiError(ALERT_MESSAGES.schemaRequiredForMapping);
        return false;
      }
      const activeFields = fieldsOverride ?? deps.fieldsRef.current;
      if (!activeFields.length) {
        setOpenAiError(ALERT_MESSAGES.noPdfFieldsToMap);
        return false;
      }
      let activeSessionId = sessionIdOverride ?? deps.detectSessionId;
      if (!activeSessionId && deps.activeSavedFormId) {
        try {
          activeSessionId = await ensureTemplateSessionId();
        } catch (error) {
          const message = error instanceof Error ? error.message : 'Failed to prepare this saved form for schema mapping.';
          setOpenAiError(message);
          debugLog('Failed to prepare saved form mapping session', message);
          return false;
        }
      }
      if (!activeSessionId && !deps.activeSavedFormId) {
        setOpenAiError('Template session is not ready yet. Try again in a moment.');
        return false;
      }

      setOpenAiError(null);
      setMappingInProgress(true);
      setMapSchemaInProgress(true);
      try {
        const mappingLoadToken = deps.loadTokenRef.current;
        const templateFields = buildTemplateFields(activeFields);
        const sourcePdfSha256 = await resolveActiveSourcePdfSha256();
        try {
          await deps.onBeforeOpenAiAction?.('map', activeSessionId);
        } catch (error) {
          debugLog('Failed to capture map session diagnostic', error);
        }
        const mappingResult = await ApiService.mapSchema(
          activeSchemaId,
          templateFields,
          deps.activeSavedFormId || undefined,
          activeSessionId || undefined,
          undefined,
          sourcePdfSha256,
        );
        if (deps.loadTokenRef.current !== mappingLoadToken) return false;
        if (!mappingResult?.success) {
          throw new Error(mappingResult?.error || 'Mapping generation failed');
        }
        applyMappingResults(mappingResult.mappingResults);
        void deps.loadUserProfile();
        return true;
      } catch (error) {
        let message = error instanceof Error ? error.message : 'Schema mapping failed.';
        if (error instanceof ApiError && error.status === 402) {
          message = await resolveCreditExhaustionMessage();
        }
        setOpenAiError(message);
        debugLog('Schema mapping failed', message);
        return false;
      } finally {
        setMapSchemaInProgress(false);
        setMappingInProgress(false);
      }
    },
    [applyMappingResults, clearPendingAutoActions, deps, ensureTemplateSessionId, resolveActiveSourcePdfSha256, resolveCreditExhaustionMessage],
  );

  const handleMappingSuccess = useCallback(() => {
    setHasMappedSchema(true);
    deps.setBannerNotice({
      tone: 'success',
      message: consumeTemplateInputsClearedMessage(ALERT_MESSAGES.mappingDone),
      autoDismissMs: 5000,
    });
  }, [consumeTemplateInputsClearedMessage, deps]);

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
      if (!deps.verifiedUser) {
        setOpenAiError(ALERT_MESSAGES.signInToRunOpenAiRename);
        return null;
      }
      clearPendingAutoActions();
      let activeSessionId = sessionId || deps.detectSessionId;
      if (!activeSessionId && deps.activeSavedFormId && deps.fieldsRef.current.length) {
        try {
          activeSessionId = await ensureTemplateSessionId();
        } catch (error) {
          const message = error instanceof Error ? error.message : 'Failed to prepare this saved form for rename.';
          setOpenAiError(message);
          debugLog('Failed to prepare saved form rename session', message);
          return null;
        }
      }
      if (!activeSessionId) {
        setOpenAiError(ALERT_MESSAGES.uploadPdfForRename);
        return null;
      }
      if (!deps.fieldsRef.current.length) {
        if (allowDefer) {
          try {
            const statusPayload = await fetchDetectionStatus(activeSessionId);
            const status = String(statusPayload?.status || '').toLowerCase();
            if (status === 'queued' || status === 'running') {
              deps.pendingAutoActionsRef.current = {
                loadToken: deps.loadTokenRef.current,
                sessionId: activeSessionId,
                schemaId: renameSchemaId ?? null,
                autoRename: true,
                autoMap: Boolean(renameSchemaId),
              };
              deps.setBannerNotice({
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
      const hasSchemaForMap = Boolean(renameSchemaId);
      if (confirm) {
        const baseMessage =
          'OpenAI will receive PDF page content and field tags. Row data and field input values are not sent.';
        const renameOnlyWarning =
          '\n\nRename-only standardizes names but does not align fields to database columns. ' +
          'For reliable checkbox and schema fill behavior, run Map or Rename + Map.';
        const ok = await deps.requestConfirm({
          title: 'Send to OpenAI?',
          message: hasSchemaForMap ? baseMessage : baseMessage + renameOnlyWarning,
          confirmLabel: 'Continue',
          cancelLabel: 'Cancel',
        });
        if (!ok) return null;
      }
      setOpenAiError(null);
      resetTemplateInputsClearedFlag();
      setMappingInProgress(true);
      setRenameInProgress(true);
      if (hasSchemaForMap) setMapSchemaInProgress(true);
      try {
        const renameLoadToken = deps.loadTokenRef.current;
        const templateFields = buildTemplateFields(deps.fieldsRef.current);
        const sourcePdfSha256 = await resolveActiveSourcePdfSha256();
        try {
          await deps.onBeforeOpenAiAction?.('rename', activeSessionId);
        } catch (error) {
          debugLog('Failed to capture rename session diagnostic', error);
        }
        const result = await ApiService.renameFields({
          sessionId: activeSessionId,
          schemaId: renameSchemaId || undefined,
          sourcePdfSha256,
          templateFields,
        });
        if (deps.loadTokenRef.current !== renameLoadToken) return null;
        if (!result?.success) throw new Error(result?.error || 'OpenAI rename failed.');
        const updated = applyRenameResults(result.fields);
        if (!updated || updated.length === 0) throw new Error('OpenAI rename returned no fields.');
        const rules = Array.isArray(result.checkboxRules) ? result.checkboxRules : [];
        setCheckboxRules(rules);
        setRadioGroupSuggestions(deriveCombinedRadioGroupSuggestions(updated, [], rules));
        setTextTransformRules([]);
        if (!hasSchemaForMap) {
          deps.setBannerNotice({
            tone: 'info',
            message: consumeTemplateInputsClearedMessage(
              'Rename only standardizes field names. Complex checkbox groups and any checkbox columns that do not already match the field names may not fill.',
            ),
            autoDismissMs: 9000,
          });
        }
        setHasRenamedFields(true);
        void deps.loadUserProfile();
        return updated;
      } catch (error) {
        let message = error instanceof Error ? error.message : 'OpenAI rename failed.';
        if (error instanceof ApiError && error.status === 402) {
          message = await resolveCreditExhaustionMessage();
        }
        setOpenAiError(message);
        debugLog('OpenAI rename failed', message);
        return null;
      } finally {
        setRenameInProgress(false);
        setMappingInProgress(false);
        if (hasSchemaForMap) setMapSchemaInProgress(false);
      }
    },
    [applyRenameResults, clearPendingAutoActions, consumeTemplateInputsClearedMessage, deps, ensureTemplateSessionId, resetTemplateInputsClearedFlag, resolveActiveSourcePdfSha256, resolveCreditExhaustionMessage],
  );

  const runOpenAiRenameAndRemap = useCallback(
    async ({
      confirm = true,
      allowDefer = false,
      sessionId,
      schemaId: combinedSchemaId,
    }: {
      confirm?: boolean;
      allowDefer?: boolean;
      sessionId?: string | null;
      schemaId?: string | null;
    } = {}): Promise<PdfField[] | null> => {
      if (!deps.verifiedUser) {
        setOpenAiError(ALERT_MESSAGES.signInToRunOpenAiRename);
        return null;
      }
      clearPendingAutoActions();
      const activeSchemaId = combinedSchemaId ?? deps.schemaId;
      if (!activeSchemaId) {
        setOpenAiError(ALERT_MESSAGES.schemaRequiredForMapping);
        return null;
      }
      let activeSessionId = sessionId || deps.detectSessionId;
      if (!activeSessionId && deps.activeSavedFormId && deps.fieldsRef.current.length) {
        try {
          activeSessionId = await ensureTemplateSessionId();
        } catch (error) {
          const message = error instanceof Error ? error.message : 'Failed to prepare this saved form for Rename + Remap.';
          setOpenAiError(message);
          debugLog('Failed to prepare saved form Rename + Remap session', message);
          return null;
        }
      }
      if (!activeSessionId) {
        setOpenAiError(ALERT_MESSAGES.uploadPdfForRename);
        return null;
      }
      if (!deps.fieldsRef.current.length) {
        if (allowDefer) {
          try {
            const statusPayload = await fetchDetectionStatus(activeSessionId);
            const status = String(statusPayload?.status || '').toLowerCase();
            if (status === 'queued' || status === 'running') {
              deps.pendingAutoActionsRef.current = {
                loadToken: deps.loadTokenRef.current,
                sessionId: activeSessionId,
                schemaId: activeSchemaId,
                autoRename: true,
                autoMap: true,
              };
              deps.setBannerNotice({
                tone: 'info',
                message: 'Detection is still running. Rename + Remap will start once fields are ready.',
                autoDismissMs: 8000,
              });
              return null;
            }
          } catch (error) {
            debugLog('Failed to fetch detection status for Rename + Remap', error);
          }
        }
        setOpenAiError(ALERT_MESSAGES.noPdfFieldsToRename);
        return null;
      }
      if (confirm) {
        const ok = await deps.requestConfirm({
          title: 'Send to OpenAI?',
          message: 'This PDF and your database field headers will be sent to OpenAI. No row data or field values are sent.',
          confirmLabel: 'Continue',
          cancelLabel: 'Cancel',
        });
        if (!ok) return null;
      }

      setOpenAiError(null);
      resetTemplateInputsClearedFlag();
      setMappingInProgress(true);
      setRenameInProgress(true);
      setMapSchemaInProgress(true);
      try {
        const renameLoadToken = deps.loadTokenRef.current;
        const templateFields = buildTemplateFields(deps.fieldsRef.current);
        const sourcePdfSha256 = await resolveActiveSourcePdfSha256();
        try {
          await deps.onBeforeOpenAiAction?.('rename_remap', activeSessionId);
        } catch (error) {
          debugLog('Failed to capture Rename + Remap session diagnostic', error);
        }
        const result = await ApiService.renameAndRemap({
          sessionId: activeSessionId,
          schemaId: activeSchemaId,
          sourcePdfSha256,
          templateFields,
        });
        if (deps.loadTokenRef.current !== renameLoadToken) return null;
        if (!result?.success) throw new Error(result?.error || 'Rename + Remap failed.');
        if (!result?.mappingResults || typeof result.mappingResults !== 'object') {
          throw new Error('Rename + Remap returned no mapping results.');
        }
        const updated = applyRenameResults(result.fields);
        if (!updated || updated.length === 0) throw new Error('Rename + Remap returned no fields.');
        applyMappingResults(result.mappingResults);
        setHasRenamedFields(true);
        handleMappingSuccess();
        void deps.loadUserProfile();
        return deps.fieldsRef.current;
      } catch (error) {
        let message = error instanceof Error ? error.message : 'Rename + Remap failed.';
        if (error instanceof ApiError && error.status === 402) {
          message = await resolveCreditExhaustionMessage();
        }
        setOpenAiError(message);
        debugLog('Rename + Remap failed', message);
        return null;
      } finally {
        setMapSchemaInProgress(false);
        setRenameInProgress(false);
        setMappingInProgress(false);
      }
    },
    [
      applyMappingResults,
      applyRenameResults,
      clearPendingAutoActions,
      deps,
      ensureTemplateSessionId,
      handleMappingSuccess,
      resetTemplateInputsClearedFlag,
      resolveActiveSourcePdfSha256,
      resolveCreditExhaustionMessage,
    ],
  );

  const confirmRemap = useCallback(async () => {
    if (!hasMappedSchema) return true;
    return deps.requestConfirm({
      title: 'Remap fields?',
      message: 'A mapping already exists for this schema. Do you want to map again?',
      confirmLabel: 'Remap',
      cancelLabel: 'Cancel',
    });
  }, [hasMappedSchema, deps]);

  const handleMapSchema = useCallback(
    async (resolveSchemaForMapping: (mode: 'map') => Promise<string | null>) => {
      const resolvedSchemaId = await resolveSchemaForMapping('map');
      if (!resolvedSchemaId) return;
      const ok = await deps.requestConfirm({
        title: 'Send to OpenAI?',
        message: 'Your database field headers and PDF field tags will be sent to OpenAI. No row data or field values are sent.',
        confirmLabel: 'Continue',
        cancelLabel: 'Cancel',
      });
      if (!ok) return;
      const shouldRemap = await confirmRemap();
      if (!shouldRemap) return;
      setOpenAiError(null);
      resetTemplateInputsClearedFlag();
      const mapped = await applySchemaMappings({ schemaIdOverride: resolvedSchemaId });
      if (mapped) handleMappingSuccess();
    },
    [applySchemaMappings, confirmRemap, handleMappingSuccess, resetTemplateInputsClearedFlag, deps],
  );

  const handleRename = useCallback(async () => {
    await runOpenAiRename({ confirm: true });
  }, [runOpenAiRename]);

  const handleRenameAndMap = useCallback(
    async (resolveSchemaForMapping: (mode: 'renameAndMap') => Promise<string | null>) => {
      const resolvedSchemaId = await resolveSchemaForMapping('renameAndMap');
      if (!resolvedSchemaId) return;
      const ok = await deps.requestConfirm({
        title: 'Send to OpenAI?',
        message: 'This PDF and your database field headers will be sent to OpenAI. No row data or field values are sent.',
        confirmLabel: 'Continue',
        cancelLabel: 'Cancel',
      });
      if (!ok) return;
      const shouldRemap = await confirmRemap();
      if (!shouldRemap) return;
      setOpenAiError(null);
      await runOpenAiRenameAndRemap({ confirm: false, schemaId: resolvedSchemaId });
    },
    [confirmRemap, runOpenAiRenameAndRemap, deps],
  );

  // ── Computed capability flags ──────────────────────────────────────
  const renameDisabledReason = useMemo(() => {
    if (renameInProgress) return 'Rename is already running.';
    if (mapSchemaInProgress) return 'Mapping is already running.';
    if (mappingInProgress) return 'Please wait for the current workspace task to finish.';
    if (!deps.verifiedUser) return 'Sign in to run Rename.';
    if (!deps.hasDocument) return 'Upload a PDF first.';
    if (deps.fieldsCount === 0) return 'Detect fields or add at least one field before Rename.';
    if (!deps.detectSessionId && !deps.activeSavedFormId) {
      return 'Template session is still initializing. Try again in a moment.';
    }
    return null;
  }, [
    deps.activeSavedFormId,
    deps.detectSessionId,
    deps.fieldsCount,
    deps.hasDocument,
    deps.verifiedUser,
    mapSchemaInProgress,
    mappingInProgress,
    renameInProgress,
  ]);

  const mapSchemaDisabledReason = useMemo(() => {
    if (mapSchemaInProgress) return 'Mapping is already running.';
    if (renameInProgress) return 'Rename is already running.';
    if (mappingInProgress) return 'Please wait for the current workspace task to finish.';
    if (!deps.verifiedUser) return 'Sign in to run Map Schema.';
    if (!deps.hasDocument) return 'Upload a PDF first.';
    if (deps.fieldsCount === 0) return 'Detect fields or add at least one field before mapping.';
    if (!deps.detectSessionId && !deps.activeSavedFormId) {
      return 'Template session is still initializing. Try again in a moment.';
    }
    if (
      deps.dataSourceKind !== 'csv' &&
      deps.dataSourceKind !== 'sql' &&
      deps.dataSourceKind !== 'excel' &&
      deps.dataSourceKind !== 'json' &&
      deps.dataSourceKind !== 'txt'
    ) {
      return 'Connect a CSV, SQL, Excel, JSON, or TXT schema source first.';
    }
    if (deps.dataColumns.length === 0) {
      return 'Upload schema headers before mapping.';
    }
    if (!deps.hasSchemaOrPending) {
      return 'Schema metadata is required before mapping.';
    }
    return null;
  }, [
    deps.activeSavedFormId,
    deps.dataColumns.length,
    deps.dataSourceKind,
    deps.detectSessionId,
    deps.fieldsCount,
    deps.hasDocument,
    deps.hasSchemaOrPending,
    deps.verifiedUser,
    mapSchemaInProgress,
    mappingInProgress,
    renameInProgress,
  ]);

  const renameAndMapDisabledReason = useMemo(() => {
    if (renameDisabledReason) return renameDisabledReason;
    if (mapSchemaDisabledReason) return mapSchemaDisabledReason;
    return null;
  }, [mapSchemaDisabledReason, renameDisabledReason]);

  const canRename = useMemo(() => !renameDisabledReason, [renameDisabledReason]);
  const canMapSchema = useMemo(() => !mapSchemaDisabledReason, [mapSchemaDisabledReason]);
  const canRenameAndMap = useMemo(() => !renameAndMapDisabledReason, [renameAndMapDisabledReason]);

  const reset = useCallback(() => {
    setMappingInProgress(false);
    setMapSchemaInProgress(false);
    setHasMappedSchema(false);
    setCheckboxRules([]);
    setRadioGroupSuggestions([]);
    setTextTransformRules([]);
    setRenameInProgress(false);
    setHasRenamedFields(false);
    setOpenAiError(null);
    resetTemplateInputsClearedFlag();
  }, [resetTemplateInputsClearedFlag]);

  return {
    renameInProgress, setRenameInProgress,
    hasRenamedFields, setHasRenamedFields,
    mappingInProgress, setMappingInProgress,
    mapSchemaInProgress,
    hasMappedSchema, setHasMappedSchema,
    openAiError, setOpenAiError,
    checkboxRules, setCheckboxRules,
    radioGroupSuggestions, setRadioGroupSuggestions,
    textTransformRules, setTextTransformRules,
    clearPendingAutoActions,
    applyMappingResults,
    applyRenameResults,
    applySchemaMappings,
    handleMappingSuccess,
    runOpenAiRename,
    runOpenAiRenameAndRemap,
    handleMapSchema,
    handleRename,
    handleRenameAndMap,
    canRename,
    canMapSchema,
    canRenameAndMap,
    renameDisabledReason,
    mapSchemaDisabledReason,
    renameAndMapDisabledReason,
    reset,
  };
}
