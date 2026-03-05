import { useCallback, useMemo, useState } from 'react';
import type { User } from 'firebase/auth';
import type {
  BannerNotice,
  CheckboxHint,
  CheckboxRule,
  ConfirmDialogOptions,
  FieldNameUpdate,
  NameQueue,
  PdfField,
  TextTransformRule,
} from '../types';
import { deriveMappingConfidence, parseConfidence } from '../utils/confidence';
import { normaliseDataKey } from '../utils/dataSource';
import { computeCheckboxMeta, type CheckboxMeta } from '../utils/checkboxMeta';
import { applyFieldNameUpdatesToList, enqueueByName, takeNextByName } from '../utils/fieldUpdates';
import { ALERT_MESSAGES } from '../utils/alertMessages';
import { resolveIdentifierKey } from '../utils/dataSource';
import { buildTemplateFields } from '../utils/fields';
import { debugLog } from '../utils/debug';
import { ApiService } from '../services/api';
import { ApiError } from '../services/apiConfig';
import { fetchDetectionStatus } from '../services/detectionApi';
import type { PendingAutoActions } from '../types';

export interface UseOpenAiPipelineDeps {
  verifiedUser: User | null;
  fieldsRef: React.MutableRefObject<PdfField[]>;
  loadTokenRef: React.MutableRefObject<number>;
  detectSessionId: string | null;
  activeSavedFormId: string | null;
  dataColumns: string[];
  schemaId: string | null;
  pendingAutoActionsRef: React.MutableRefObject<PendingAutoActions | null>;
  setBannerNotice: (notice: BannerNotice | null) => void;
  requestConfirm: (options: ConfirmDialogOptions) => Promise<boolean>;
  loadUserProfile: () => Promise<any>;
  resetFieldHistory: (fields?: PdfField[]) => void;
  updateFieldsWith: (updater: (prev: PdfField[]) => PdfField[], options?: { trackHistory?: boolean }) => void;
  setIdentifierKey: (key: string | null) => void;
  // For computed canRename/canMapSchema
  hasDocument: boolean;
  fieldsCount: number;
  dataSourceKind: string;
  hasSchemaOrPending: boolean;
}

export function useOpenAiPipeline(deps: UseOpenAiPipelineDeps) {
  const [renameInProgress, setRenameInProgress] = useState(false);
  const [hasRenamedFields, setHasRenamedFields] = useState(false);
  const [mappingInProgress, setMappingInProgress] = useState(false);
  const [mapSchemaInProgress, setMapSchemaInProgress] = useState(false);
  const [hasMappedSchema, setHasMappedSchema] = useState(false);
  const [openAiError, setOpenAiError] = useState<string | null>(null);
  const [checkboxRules, setCheckboxRules] = useState<CheckboxRule[]>([]);
  const [checkboxHints, setCheckboxHints] = useState<CheckboxHint[]>([]);
  const [textTransformRules, setTextTransformRules] = useState<TextTransformRule[]>([]);

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

  const applyFieldNameUpdates = useCallback(
    (
      updatesByCurrentName: Map<string, NameQueue<FieldNameUpdate>>,
      checkboxMetaById?: Map<string, CheckboxMeta>,
    ) => {
      if (!updatesByCurrentName.size) return;
      deps.updateFieldsWith((prev) => applyFieldNameUpdatesToList(prev, updatesByCurrentName, checkboxMetaById));
    },
    [deps.updateFieldsWith],
  );

  const applyMappingResults = useCallback(
    (mappingResults?: any) => {
      if (!mappingResults) return;
      const mappings = mappingResults.mappings || [];
      const updates = new Map<string, NameQueue<FieldNameUpdate>>();
      const normalizedColumns = deps.dataColumns.map((column) => normaliseDataKey(column)).filter(Boolean);
      const checkboxMetaById = computeCheckboxMeta(deps.fieldsRef.current, normalizedColumns);

      for (const mapping of mappings) {
        if (!mapping || !mapping.pdfField) continue;
        const currentName = mapping.originalPdfField || mapping.pdfField;
        const desiredName = mapping.pdfField;
        if (!currentName) continue;
        const mappingConfidence =
          parseConfidence(mapping.confidence) ?? deriveMappingConfidence(currentName, desiredName);
        enqueueByName(updates, currentName, { newName: desiredName, mappingConfidence });
      }

      if (updates.size) {
        applyFieldNameUpdates(updates, checkboxMetaById);
        debugLog('Applied AI mappings', { total: updates.size });
      }

      const fillRules = mappingResults.fillRules && typeof mappingResults.fillRules === 'object'
        ? mappingResults.fillRules
        : null;

      const rules = Array.isArray(fillRules?.checkboxRules)
        ? (fillRules.checkboxRules as CheckboxRule[])
        : Array.isArray(mappingResults.checkboxRules)
          ? (mappingResults.checkboxRules as CheckboxRule[])
          : [];
      setCheckboxRules(rules);
      const hints = Array.isArray(fillRules?.checkboxHints)
        ? (fillRules.checkboxHints as CheckboxHint[])
        : Array.isArray(mappingResults.checkboxHints)
          ? (mappingResults.checkboxHints as CheckboxHint[])
          : [];
      setCheckboxHints(hints);
      const textRules = Array.isArray(fillRules?.textTransformRules)
        ? (fillRules.textTransformRules as TextTransformRule[])
        : Array.isArray((fillRules as Record<string, unknown> | null)?.templateRules)
          ? ((fillRules as Record<string, unknown>).templateRules as TextTransformRule[])
        : Array.isArray(mappingResults.textTransformRules)
          ? (mappingResults.textTransformRules as TextTransformRule[])
          : Array.isArray((mappingResults as Record<string, unknown> | null)?.templateRules)
            ? ((mappingResults as Record<string, unknown>).templateRules as TextTransformRule[])
          : [];
      setTextTransformRules(textRules);
      const resolvedIdentifier = resolveIdentifierKey(
        mappingResults.identifierKey || mappingResults.identifier_key,
        deps.dataColumns,
      );
      if (resolvedIdentifier) {
        deps.setIdentifierKey(resolvedIdentifier);
      }
    },
    [applyFieldNameUpdates, deps],
  );

  const applyRenameResults = useCallback(
    (renamedFieldsPayload?: Array<Record<string, any>>): PdfField[] | null => {
      if (!Array.isArray(renamedFieldsPayload) || !renamedFieldsPayload.length) return null;
      const renamesByOriginal = new Map<string, NameQueue<Record<string, any>>>();
      for (const entry of renamedFieldsPayload) {
        const original =
          entry.originalName || entry.original_name || entry.originalFieldName || entry.name;
        if (typeof original === 'string' && original.trim()) {
          enqueueByName(renamesByOriginal, original.trim(), entry);
        }
      }
      if (!renamesByOriginal.size) return null;

      const updated: PdfField[] = [];
      for (const field of deps.fieldsRef.current) {
        const rename = takeNextByName(renamesByOriginal, field.name);
        if (!rename) {
          updated.push(field);
          continue;
        }
        const renameConfidence = parseConfidence(rename.renameConfidence ?? rename.rename_confidence);
        const fieldConfidence = parseConfidence(rename.isItAfieldConfidence ?? rename.is_it_a_field_confidence);
        const hasMappingConf =
          Object.prototype.hasOwnProperty.call(rename, 'mappingConfidence') ||
          Object.prototype.hasOwnProperty.call(rename, 'mapping_confidence');
        const mappingConfidence = parseConfidence(rename.mappingConfidence ?? rename.mapping_confidence);
        const nextName = String(rename.name || rename.suggestedRename || field.name).trim() || field.name;
        updated.push({
          ...field,
          name: nextName,
          mappingConfidence: hasMappingConf ? mappingConfidence : field.mappingConfidence,
          renameConfidence: renameConfidence ?? field.renameConfidence,
          fieldConfidence: fieldConfidence ?? field.fieldConfidence,
          groupKey: rename.groupKey ?? field.groupKey,
          optionKey: rename.optionKey ?? field.optionKey,
          optionLabel: rename.optionLabel ?? field.optionLabel,
          groupLabel: rename.groupLabel ?? field.groupLabel,
        });
      }
      deps.resetFieldHistory(updated);
      return updated;
    },
    [deps],
  );

  const applySchemaMappings = useCallback(
    async ({
      fieldsOverride,
      schemaIdOverride,
    }: { fieldsOverride?: PdfField[]; schemaIdOverride?: string | null } = {}): Promise<boolean> => {
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
      if (!deps.detectSessionId && !deps.activeSavedFormId) {
        setOpenAiError('Template session is not ready yet. Try again in a moment.');
        return false;
      }

      setOpenAiError(null);
      try {
        const mappingLoadToken = deps.loadTokenRef.current;
        const templateFields = buildTemplateFields(activeFields);
        const mappingResult = await ApiService.mapSchema(
          activeSchemaId,
          templateFields,
          deps.activeSavedFormId || undefined,
          deps.detectSessionId || undefined,
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
      }
    },
    [applyMappingResults, clearPendingAutoActions, deps, resolveCreditExhaustionMessage],
  );

  const handleMappingSuccess = useCallback(() => {
    setHasMappedSchema(true);
    deps.setBannerNotice({
      tone: 'success',
      message: ALERT_MESSAGES.mappingDone,
      autoDismissMs: 5000,
    });
  }, [deps]);

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
      const activeSessionId = sessionId || deps.detectSessionId;
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
      setMappingInProgress(true);
      setRenameInProgress(true);
      if (hasSchemaForMap) setMapSchemaInProgress(true);
      try {
        const renameLoadToken = deps.loadTokenRef.current;
        const templateFields = buildTemplateFields(deps.fieldsRef.current);
        const result = await ApiService.renameFields({
          sessionId: activeSessionId,
          schemaId: renameSchemaId || undefined,
          templateFields,
        });
        if (deps.loadTokenRef.current !== renameLoadToken) return null;
        if (!result?.success) throw new Error(result?.error || 'OpenAI rename failed.');
        const updated = applyRenameResults(result.fields);
        if (!updated || updated.length === 0) throw new Error('OpenAI rename returned no fields.');
        setCheckboxRules(Array.isArray(result.checkboxRules) ? result.checkboxRules : []);
        // Rename responses currently include rules but not hints; clear hints unless
        // a future backend version explicitly returns them.
        setCheckboxHints(Array.isArray((result as { checkboxHints?: CheckboxHint[] }).checkboxHints) ? (result as { checkboxHints?: CheckboxHint[] }).checkboxHints ?? [] : []);
        setTextTransformRules([]);
        if (!hasSchemaForMap) {
          deps.setBannerNotice({
            tone: 'info',
            message: 'Rename only standardizes field names. Complex checkbox groups and any checkbox columns that do not already match the field names may not fill.',
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
    [applyRenameResults, clearPendingAutoActions, deps, resolveCreditExhaustionMessage],
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
      setMappingInProgress(true);
      setMapSchemaInProgress(true);
      try {
        const mapped = await applySchemaMappings({ schemaIdOverride: resolvedSchemaId });
        if (mapped) handleMappingSuccess();
      } finally {
        setMapSchemaInProgress(false);
        setMappingInProgress(false);
      }
    },
    [applySchemaMappings, confirmRemap, handleMappingSuccess, deps],
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
      const renamed = await runOpenAiRename({ confirm: false, schemaId: resolvedSchemaId });
      if (!renamed) return;
      handleMappingSuccess();
    },
    [confirmRemap, handleMappingSuccess, runOpenAiRename, deps],
  );

  // ── Computed capability flags ──────────────────────────────────────
  const renameDisabledReason = useMemo(() => {
    if (renameInProgress) return 'Rename is already running.';
    if (mappingInProgress || mapSchemaInProgress) return 'Another OpenAI action is already running.';
    if (!deps.verifiedUser) return 'Sign in to run Rename.';
    if (!deps.hasDocument) return 'Upload a PDF first.';
    if (deps.fieldsCount === 0) return 'Detect fields or add at least one field before Rename.';
    if (!deps.detectSessionId) return 'Template session is still initializing. Try again in a moment.';
    return null;
  }, [
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
    if (mappingInProgress || renameInProgress) return 'Another OpenAI action is already running.';
    if (!deps.verifiedUser) return 'Sign in to run Map Schema.';
    if (!deps.hasDocument) return 'Upload a PDF first.';
    if (deps.fieldsCount === 0) return 'Detect fields or add at least one field before mapping.';
    if (!deps.detectSessionId && !deps.activeSavedFormId) {
      return 'Template session is still initializing. Try again in a moment.';
    }
    if (
      deps.dataSourceKind !== 'csv' &&
      deps.dataSourceKind !== 'excel' &&
      deps.dataSourceKind !== 'json' &&
      deps.dataSourceKind !== 'txt'
    ) {
      return 'Connect a CSV, Excel, JSON, or TXT schema source first.';
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
    setHasMappedSchema(false);
    setCheckboxRules([]);
    setCheckboxHints([]);
    setTextTransformRules([]);
    setRenameInProgress(false);
    setHasRenamedFields(false);
    setOpenAiError(null);
  }, []);

  return {
    renameInProgress, setRenameInProgress,
    hasRenamedFields, setHasRenamedFields,
    mappingInProgress, setMappingInProgress,
    mapSchemaInProgress,
    hasMappedSchema, setHasMappedSchema,
    openAiError, setOpenAiError,
    checkboxRules, setCheckboxRules,
    checkboxHints, setCheckboxHints,
    textTransformRules, setTextTransformRules,
    clearPendingAutoActions,
    applyMappingResults,
    applyRenameResults,
    applySchemaMappings,
    handleMappingSuccess,
    runOpenAiRename,
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
