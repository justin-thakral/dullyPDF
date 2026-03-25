import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { User } from 'firebase/auth';
import { flushSync } from 'react-dom';
import type {
  BannerNotice,
  CheckboxRule,
  TextTransformRule,
} from '../types';
import type {
  CreditPricingConfig,
  ProfileLimits,
  TemplateGroupSummary,
} from '../services/api';
import { ApiService } from '../services/api';
import { ApiError } from '../services/apiConfig';
import { detectFields } from '../services/detectionApi';
import { mapDetectionFields } from '../utils/detection';
import {
  estimateCreditsForPageCounts,
  resolveClientCreditPricing,
  resolveOpenAiCreditOperation,
  summarizeDetectPageCounts,
} from '../utils/creditPricing';
import {
  buildTemplateFields,
  normaliseFormName,
  prepareFieldsForMaterialize,
} from '../utils/fields';
import {
  applyMappingPayloadToFields,
  applyRenamePayloadToFields,
} from '../utils/openAiFields';
import { debugLog } from '../utils/debug';
import { extractFieldsFromPdf, loadPdfFromFile } from '../utils/pdf';

const PDF_PAGE_COUNT_TIMEOUT_MS = 15000;

type GroupUploadProfileSnapshot = {
  role?: string | null;
  availableCredits?: number | null;
  creditsRemaining?: number | null;
  creditPricing?: CreditPricingConfig | null;
} | null;

export type GroupUploadItemStatus =
  | 'loading'
  | 'ready'
  | 'processing'
  | 'saved'
  | 'failed';

export type GroupUploadItem = {
  id: string;
  file: File;
  name: string;
  pageCount: number | null;
  error: string | null;
  status: GroupUploadItemStatus;
  detail: string | null;
  savedFormId: string | null;
};

type UseGroupUploadModalDeps = {
  verifiedUser: User | null;
  userProfile?: GroupUploadProfileSnapshot;
  loadUserProfile: () => Promise<any>;
  profileLimits: Pick<ProfileLimits, 'detectMaxPages' | 'savedFormsMax'>;
  savedFormsCount: number;
  dataColumns: string[];
  schemaId: string | null;
  schemaUploadInProgress: boolean;
  pendingSchemaPayload: any;
  persistSchemaPayload: (payload: any) => Promise<string | null>;
  setSchemaUploadInProgress: (value: boolean) => void;
  createGroup: (
    payload: { name: string; templateIds: string[] },
    options?: { signal?: AbortSignal },
  ) => Promise<TemplateGroupSummary>;
  openGroup: (groupId: string) => Promise<boolean> | boolean;
  refreshSavedForms: (opts?: { allowRetry?: boolean; throwOnError?: boolean }) => Promise<unknown>;
  refreshProfile?: () => Promise<unknown> | void;
  setBannerNotice: (notice: BannerNotice | null) => void;
};

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
};

type GroupUploadDetectionOutcome = {
  cancelled: boolean;
  error: unknown | null;
  payload: any | null;
};

function createDeferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

function buildUploadItemId(): string {
  const cryptoApi =
    typeof globalThis !== 'undefined' && typeof globalThis.crypto !== 'undefined'
      ? globalThis.crypto
      : undefined;
  if (cryptoApi && typeof cryptoApi.randomUUID === 'function') {
    return cryptoApi.randomUUID();
  }
  return `group_upload_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

function resolveRemainingCredits(profile?: GroupUploadProfileSnapshot): number | null {
  if (!profile) return null;
  if (typeof profile.availableCredits === 'number') return profile.availableCredits;
  if (typeof profile.creditsRemaining === 'number') return profile.creditsRemaining;
  return null;
}

function isPdfFile(file: File): boolean {
  const name = file.name.toLowerCase();
  return (
    file.type === 'application/pdf' ||
    file.type === 'application/octet-stream' ||
    file.type === '' ||
    name.endsWith('.pdf')
  );
}

async function resolvePdfPageCount(
  file: File,
  options: { signal?: AbortSignal } = {},
): Promise<number> {
  const payload = await ApiService.getPdfPageCount(file, {
    signal: options.signal,
    timeoutMs: PDF_PAGE_COUNT_TIMEOUT_MS,
  });
  return Math.max(1, Number(payload?.pageCount) || 1);
}

function resolveQueueDetailLabel(wantsRename: boolean, wantsMap: boolean): string {
  if (wantsRename && wantsMap) return 'Detected. Waiting for Rename + Map…';
  if (wantsRename) return 'Detected. Waiting for rename…';
  if (wantsMap) return 'Detected. Waiting for mapping…';
  return 'Detected. Waiting to save…';
}

function resolveStopMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  return fallback;
}

function isAbortError(error: unknown): boolean {
  if (error instanceof DOMException && error.name === 'AbortError') {
    return true;
  }
  if (error instanceof Error) {
    return error.name === 'AbortError' || error.message.toLowerCase().includes('aborted');
  }
  return false;
}

function shouldStopRemaining(error: unknown, message: string): boolean {
  return (
    (error instanceof ApiError && (error.status === 402 || error.status === 403)) ||
    message.toLowerCase().includes('credits exhausted') ||
    message.toLowerCase().includes('saved form limit')
  );
}

function isDetectionStillRunning(payload: any): boolean {
  const status = String(payload?.status || '').toLowerCase();
  return Boolean(payload?.timedOut) || status === 'queued' || status === 'running';
}

export function useGroupUploadModal(deps: UseGroupUploadModalDeps) {
  const [open, setOpen] = useState(false);
  const [groupName, setGroupName] = useState('');
  const [items, setItems] = useState<GroupUploadItem[]>([]);
  const [wantsRename, setWantsRename] = useState(false);
  const [wantsMap, setWantsMap] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [progressLabel, setProgressLabel] = useState('Create PDF Group');
  const activeRequestAbortControllersRef = useRef<Set<AbortController>>(new Set());
  const cancelRequestedRef = useRef(false);
  const dismissRequestedRef = useRef(false);
  const mountedRef = useRef(true);

  const trackAbortController = useCallback((controller: AbortController) => {
    activeRequestAbortControllersRef.current.add(controller);
    return controller;
  }, []);

  const releaseAbortController = useCallback((controller: AbortController) => {
    activeRequestAbortControllersRef.current.delete(controller);
  }, []);

  const abortInFlightRequests = useCallback(() => {
    for (const controller of activeRequestAbortControllersRef.current) {
      controller.abort();
    }
    activeRequestAbortControllersRef.current.clear();
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    cancelRequestedRef.current = false;

    return () => {
      mountedRef.current = false;
      cancelRequestedRef.current = true;
      abortInFlightRequests();
    };
  }, [abortInFlightRequests]);

  const pricing = useMemo(
    () => resolveClientCreditPricing(deps.userProfile?.creditPricing),
    [deps.userProfile?.creditPricing],
  );
  const operation = useMemo(
    () => resolveOpenAiCreditOperation(wantsRename, wantsMap),
    [wantsMap, wantsRename],
  );
  const resolvedPageCounts = useMemo(
    () => items.map((item) => item.pageCount).filter((pageCount): pageCount is number => typeof pageCount === 'number'),
    [items],
  );
  const pageSummary = useMemo(
    () => summarizeDetectPageCounts(resolvedPageCounts, deps.profileLimits.detectMaxPages),
    [deps.profileLimits.detectMaxPages, resolvedPageCounts],
  );
  const creditEstimate = useMemo(() => {
    if (!operation || resolvedPageCounts.length === 0) return null;
    return estimateCreditsForPageCounts(operation, resolvedPageCounts, pricing);
  }, [operation, pricing, resolvedPageCounts]);
  const creditsRemaining = useMemo(
    () => resolveRemainingCredits(deps.userProfile),
    [deps.userProfile],
  );
  const hasPendingPageCounts = useMemo(
    () => items.some((item) => item.status === 'loading'),
    [items],
  );
  const hasFileErrors = useMemo(
    () => items.some((item) => Boolean(item.error)),
    [items],
  );

  const setItemState = useCallback((itemId: string, next: Partial<GroupUploadItem>) => {
    if (!mountedRef.current) return;
    setItems((prev) => prev.map((entry) => (
      entry.id === itemId ? { ...entry, ...next } : entry
    )));
  }, []);

  const reset = useCallback(() => {
    cancelRequestedRef.current = false;
    dismissRequestedRef.current = false;
    abortInFlightRequests();
    setGroupName('');
    setItems([]);
    setWantsRename(false);
    setWantsMap(false);
    setProcessing(false);
    setLocalError(null);
    setProgressLabel('Create PDF Group');
  }, [abortInFlightRequests]);

  const openDialog = useCallback(() => {
    if (processing) {
      setOpen(true);
      return;
    }
    reset();
    setOpen(true);
  }, [processing, reset]);

  const closeDialog = useCallback(() => {
    if (!processing) {
      setOpen(false);
      reset();
      return;
    }
    const confirmed = typeof globalThis.confirm === 'function'
      ? globalThis.confirm(
        'Closing now will stop the pending group upload. Any templates that are already saved will stay in your account. Continue?',
      )
      : true;
    if (!confirmed) return;
    cancelRequestedRef.current = true;
    dismissRequestedRef.current = true;
    abortInFlightRequests();
    setOpen(false);
    setLocalError(null);
    deps.setBannerNotice({
      tone: 'info',
      message: 'Stopping the pending group upload. Templates already saved will stay in your account.',
      autoDismissMs: 7000,
    });
  }, [abortInFlightRequests, deps, processing, reset]);

  const addFiles = useCallback(async (incomingFiles: File[] | FileList | null | undefined) => {
    const nextFiles = Array.from(incomingFiles || []);
    if (!nextFiles.length) return;
    setLocalError(null);
    const nextItems = nextFiles.map((file) => {
      let error: string | null = null;
      if (!isPdfFile(file)) {
        error = 'Only PDF files are supported.';
      } else if (file.size > 50 * 1024 * 1024) {
        error = 'PDF files must be smaller than 50MB.';
      }
      return {
        id: buildUploadItemId(),
        file,
        name: file.name,
        pageCount: null,
        error,
        status: error ? 'failed' : 'loading',
        detail: error ? error : 'Counting pages…',
        savedFormId: null,
      } satisfies GroupUploadItem;
    });

    flushSync(() => {
      setItems((prev) => [...prev, ...nextItems]);
      setGroupName((prev) => {
        if (prev.trim().length > 0) return prev;
        const firstValid = nextItems.find((item) => !item.error);
        if (!firstValid) return prev;
        return `${normaliseFormName(firstValid.file.name)} Group`;
      });
    });

    await Promise.all(nextItems.map(async (item) => {
      if (item.error) return;
      const controller = trackAbortController(new AbortController());
      try {
        const pageCount = await resolvePdfPageCount(item.file, {
          signal: controller.signal,
        });
        setItemState(item.id, {
          pageCount,
          status: 'ready',
          detail: `${pageCount} page${pageCount === 1 ? '' : 's'}`,
        });
      } catch (error) {
        if (isAbortError(error)) {
          return;
        }
        const message = resolveStopMessage(error, 'Unable to read PDF pages.');
        setItemState(item.id, {
          error: message,
          status: 'failed',
          detail: message,
        });
      } finally {
        releaseAbortController(controller);
      }
    }));
  }, [releaseAbortController, setItemState, trackAbortController]);

  const removeFile = useCallback((itemId: string) => {
    if (processing) return;
    setItems((prev) => prev.filter((item) => item.id !== itemId));
  }, [processing]);

  const confirm = useCallback(async () => {
    if (processing) return;
    if (!deps.verifiedUser) {
      setLocalError('Sign in to create a PDF group.');
      return;
    }

    const trimmedGroupName = groupName.trim();
    if (!trimmedGroupName) {
      setLocalError('Group name is required.');
      return;
    }

    if (items.length === 0) {
      setLocalError('Add at least one PDF to create a group.');
      return;
    }

    if (hasPendingPageCounts) {
      setLocalError('Page counting is still running. Please wait.');
      return;
    }

    if (hasFileErrors) {
      setLocalError('Remove invalid PDFs before creating the group.');
      return;
    }

    if (!pageSummary.withinLimit) {
      setLocalError(
        `Each PDF in this group must be ${deps.profileLimits.detectMaxPages} pages or fewer on your plan.`,
      );
      return;
    }

    const readyItems = items.filter((item) => item.status === 'ready' && !item.error);
    if (readyItems.length === 0) {
      setLocalError('Add at least one valid PDF to create a group.');
      return;
    }

    if (deps.savedFormsCount + readyItems.length > deps.profileLimits.savedFormsMax) {
      setLocalError(
        `This upload would exceed your saved form limit (${deps.profileLimits.savedFormsMax} max).`,
      );
      return;
    }

    cancelRequestedRef.current = false;
    dismissRequestedRef.current = false;
    setProcessing(true);
    setLocalError(null);
    const successIds: string[] = [];
    const failures: Array<{ name: string; message: string }> = [];
    let shouldResetAtEnd = false;

    try {
      let resolvedSchemaId = wantsMap ? deps.schemaId : null;
      if (wantsMap) {
        if (deps.schemaUploadInProgress) {
          setLocalError('Schema file is still processing. Please wait.');
          return;
        }
        if (!resolvedSchemaId) {
          if (!deps.pendingSchemaPayload) {
            setLocalError('Upload a schema file before running mapping.');
            return;
          }
          setProgressLabel('Preparing schema…');
          deps.setSchemaUploadInProgress(true);
          try {
            resolvedSchemaId = await deps.persistSchemaPayload(deps.pendingSchemaPayload);
          } finally {
            deps.setSchemaUploadInProgress(false);
          }
          if (cancelRequestedRef.current) {
            shouldResetAtEnd = dismissRequestedRef.current;
            return;
          }
          if (!resolvedSchemaId) {
            setLocalError('Failed to store schema metadata. Please re-upload your schema file.');
            return;
          }
        }
      }

      if (operation) {
        setProgressLabel('Checking credits…');
        const profile = await deps.loadUserProfile();
        if (cancelRequestedRef.current) {
          shouldResetAtEnd = dismissRequestedRef.current;
          return;
        }
        if (!profile) {
          setLocalError('Unable to check OpenAI credits. Try signing out and signing in again.');
          return;
        }
        const role = String(profile.role || '').toLowerCase();
        if (role !== 'god') {
          const requiredCredits = estimateCreditsForPageCounts(
            operation,
            readyItems.map((item) => item.pageCount || 1),
            profile.creditPricing,
          ).totalCredits;
          const remaining = resolveRemainingCredits(profile);
          if ((remaining ?? 0) < requiredCredits) {
            if (role === 'pro') {
              setLocalError(
                `OpenAI credits exhausted. Remaining=${remaining ?? 0}, required=${requiredCredits}. Purchase a 500-credit refill from your profile to continue.`,
              );
            } else {
              setLocalError(
                `OpenAI credits exhausted. Remaining=${remaining ?? 0}, required=${requiredCredits}. Upgrade to Pro from your profile to continue.`,
              );
            }
            return;
          }
        }
      }

      if (cancelRequestedRef.current) {
        shouldResetAtEnd = dismissRequestedRef.current;
        return;
      }

      const queuedDetail = resolveQueueDetailLabel(wantsRename, wantsMap);
      const detectionSlots = readyItems.map(() => createDeferred<GroupUploadDetectionOutcome>());

      const processDetectedItem = async (
        item: GroupUploadItem,
        detectionPayload: any,
      ): Promise<{ cancelled: boolean; savedFormId: string | null }> => {
        const controller = trackAbortController(new AbortController());
        try {
          let sessionId = typeof detectionPayload?.sessionId === 'string'
            ? detectionPayload.sessionId
            : null;
          let fields = mapDetectionFields(detectionPayload);

          if (!fields.length || !sessionId) {
            setItemState(item.id, { detail: 'Reading embedded fields…' });
            const pdfDoc = await loadPdfFromFile(item.file);
            try {
              if (!fields.length) {
                fields = await extractFieldsFromPdf(pdfDoc);
              }
            } finally {
              if (typeof pdfDoc.destroy === 'function') {
                void pdfDoc.destroy().catch(() => {});
              }
            }
          }

          if (!fields.length) {
            throw new Error('No fields were found in this PDF.');
          }

          if (cancelRequestedRef.current) {
            return { cancelled: true, savedFormId: null };
          }

          if (!sessionId) {
            setItemState(item.id, { detail: 'Creating template session…' });
            const sessionPayload = await ApiService.createTemplateSession(item.file, {
              fields: buildTemplateFields(fields),
              pageCount: item.pageCount || undefined,
            }, {
              signal: controller.signal,
            });
            sessionId = sessionPayload.sessionId;
          }

          if (cancelRequestedRef.current) {
            return { cancelled: true, savedFormId: null };
          }

          let nextFields = fields;
          let checkboxRules: CheckboxRule[] = [];
          let textTransformRules: TextTransformRule[] = [];

          if (wantsRename && wantsMap) {
            setItemState(item.id, { detail: 'Running Rename + Map…' });
            const renameResult = await ApiService.renameFields({
              sessionId,
              schemaId: resolvedSchemaId || undefined,
              templateFields: buildTemplateFields(nextFields),
            }, {
              signal: controller.signal,
            });
            const renamedFields = applyRenamePayloadToFields(
              nextFields,
              Array.isArray(renameResult?.fields) ? renameResult.fields : undefined,
            );
            if (!renameResult?.success || !renamedFields || renamedFields.length === 0) {
              throw new Error(renameResult?.error || 'Rename + Map returned no updated fields.');
            }
            nextFields = renamedFields;
            checkboxRules = Array.isArray(renameResult?.checkboxRules) ? renameResult.checkboxRules : [];
          } else if (wantsRename) {
            setItemState(item.id, { detail: 'Renaming fields…' });
            const renameResult = await ApiService.renameFields({
              sessionId,
              templateFields: buildTemplateFields(nextFields),
            }, {
              signal: controller.signal,
            });
            const renamedFields = applyRenamePayloadToFields(
              nextFields,
              Array.isArray(renameResult?.fields) ? renameResult.fields : undefined,
            );
            if (!renameResult?.success || !renamedFields || renamedFields.length === 0) {
              throw new Error(renameResult?.error || 'Rename returned no updated fields.');
            }
            nextFields = renamedFields;
            checkboxRules = Array.isArray(renameResult?.checkboxRules) ? renameResult.checkboxRules : [];
          } else if (wantsMap) {
            setItemState(item.id, { detail: 'Mapping schema…' });
            const mappingResult = await ApiService.mapSchema(
              resolvedSchemaId || '',
              buildTemplateFields(nextFields),
              undefined,
              sessionId,
              {
                signal: controller.signal,
              },
            );
            if (!mappingResult?.success) {
              throw new Error(mappingResult?.error || 'Schema mapping failed.');
            }
            const mapped = applyMappingPayloadToFields(
              nextFields,
              mappingResult.mappingResults,
              deps.dataColumns,
            );
            nextFields = mapped.fields;
            checkboxRules = mapped.checkboxRules;
            textTransformRules = mapped.textTransformRules;
          }

          if (cancelRequestedRef.current) {
            return { cancelled: true, savedFormId: null };
          }

          setItemState(item.id, { detail: 'Saving template…' });
          const materializedBlob = await ApiService.materializeFormPdf(
            item.file,
            prepareFieldsForMaterialize(nextFields),
            {
              signal: controller.signal,
            },
          );

          if (cancelRequestedRef.current) {
            return { cancelled: true, savedFormId: null };
          }

          const savePayload = await ApiService.saveFormToProfile(
            materializedBlob,
            normaliseFormName(item.file.name),
            sessionId,
            undefined,
            checkboxRules,
            textTransformRules,
            undefined,
            {
              signal: controller.signal,
            },
          );
          setItemState(item.id, {
            savedFormId: savePayload.id,
            status: 'saved',
            error: null,
            detail: 'Saved to your templates.',
          });
          return { cancelled: false, savedFormId: savePayload.id };
        } finally {
          releaseAbortController(controller);
        }
      };

      const producerPromise = (async () => {
        for (let index = 0; index < readyItems.length; index += 1) {
          if (cancelRequestedRef.current) {
            for (let remaining = index; remaining < readyItems.length; remaining += 1) {
              detectionSlots[remaining].resolve({ cancelled: true, error: null, payload: null });
            }
            return;
          }
          const item = readyItems[index];
          setProgressLabel(`Detecting ${index + 1}/${readyItems.length}`);
          setItemState(item.id, { status: 'processing', error: null, detail: 'Detecting fields…' });
          const controller = trackAbortController(new AbortController());
          try {
            const payload = await detectFields(item.file, {
              pipeline: 'commonforms',
              prewarmRename: wantsRename,
              prewarmRemap: wantsMap,
              signal: controller.signal,
            });
            detectionSlots[index].resolve({ cancelled: false, error: null, payload });
            if (!cancelRequestedRef.current) {
              setItemState(item.id, { status: 'processing', error: null, detail: queuedDetail });
            }
          } catch (error) {
            const cancelled = cancelRequestedRef.current && isAbortError(error);
            detectionSlots[index].resolve({
              cancelled,
              error: cancelled ? null : error,
              payload: null,
            });
          } finally {
            releaseAbortController(controller);
          }
        }
      })();

      for (let index = 0; index < readyItems.length; index += 1) {
        const item = readyItems[index];
        const outcome = await detectionSlots[index].promise;

        if (outcome.cancelled) {
          if (!dismissRequestedRef.current) {
            setItemState(item.id, {
              status: 'failed',
              error: null,
              detail: 'Stopped before saving.',
            });
          }
          continue;
        }

        if (outcome.error) {
          const message = resolveStopMessage(outcome.error, 'Failed to process this PDF.');
          failures.push({ name: item.name, message });
          setItemState(item.id, {
            status: 'failed',
            error: message,
            detail: message,
          });
          debugLog('Failed to process grouped PDF upload item', { name: item.name, error: message });
          if (shouldStopRemaining(outcome.error, message)) {
            cancelRequestedRef.current = true;
            abortInFlightRequests();
          }
          continue;
        }

        if (isDetectionStillRunning(outcome.payload)) {
          const message = 'Detection is still running on the backend. Retry this PDF after it finishes.';
          failures.push({ name: item.name, message });
          setItemState(item.id, {
            status: 'failed',
            error: message,
            detail: message,
          });
          debugLog('Grouped PDF detection timed out before completion', { name: item.name, payload: outcome.payload });
          continue;
        }

        if (cancelRequestedRef.current) {
          setItemState(item.id, {
            status: 'failed',
            error: null,
            detail: 'Stopped before saving.',
          });
          continue;
        }

        setProgressLabel(`Processing ${index + 1}/${readyItems.length}`);
        try {
          const result = await processDetectedItem(item, outcome.payload);
          if (result.cancelled) {
            setItemState(item.id, {
              status: 'failed',
              error: null,
              detail: 'Stopped before saving.',
            });
            continue;
          }
          if (result.savedFormId) {
            successIds.push(result.savedFormId);
          }
        } catch (error) {
          if (cancelRequestedRef.current && isAbortError(error)) {
            setItemState(item.id, {
              status: 'failed',
              error: null,
              detail: 'Stopped before saving.',
            });
            continue;
          }
          const message = resolveStopMessage(error, 'Failed to process this PDF.');
          failures.push({ name: item.name, message });
          setItemState(item.id, {
            status: 'failed',
            error: message,
            detail: message,
          });
          debugLog('Failed to process grouped PDF upload item', { name: item.name, error: message });
          if (shouldStopRemaining(error, message)) {
            cancelRequestedRef.current = true;
            abortInFlightRequests();
          }
        }
      }

      await producerPromise;

      if (!successIds.length) {
        shouldResetAtEnd = dismissRequestedRef.current;
        const message = cancelRequestedRef.current
          ? 'Stopped PDF group upload before any templates were saved.'
          : failures[0]?.message || 'No PDFs were saved.';
        if (!dismissRequestedRef.current) {
          setLocalError(message);
        }
        deps.setBannerNotice({
          tone: cancelRequestedRef.current ? 'info' : 'error',
          message,
          autoDismissMs: 9000,
        });
        return;
      }

      setProgressLabel('Creating group…');
      const refreshResults = await Promise.allSettled([
        deps.refreshSavedForms(),
        Promise.resolve().then(() => deps.refreshProfile?.()),
      ]);
      for (const result of refreshResults) {
        if (result.status === 'rejected') {
          debugLog('Failed to refresh workspace state after grouped upload', result.reason);
        }
      }
      const groupCreateController = trackAbortController(new AbortController());
      let nextGroup: TemplateGroupSummary;
      try {
        nextGroup = await deps.createGroup({
          name: trimmedGroupName,
          templateIds: successIds,
        }, {
          signal: groupCreateController.signal,
        });
      } finally {
        releaseAbortController(groupCreateController);
      }
      if (!dismissRequestedRef.current) {
        await deps.openGroup(nextGroup.id);
        setOpen(false);
      }

      shouldResetAtEnd = true;
      if (cancelRequestedRef.current) {
        deps.setBannerNotice({
          tone: 'warning',
          message: `Stopped group "${trimmedGroupName}" after ${successIds.length} saved template${successIds.length === 1 ? '' : 's'}.`,
          autoDismissMs: 10000,
        });
      } else if (failures.length === 0) {
        deps.setBannerNotice({
          tone: 'success',
          message: `Created group "${trimmedGroupName}" with ${successIds.length} template${successIds.length === 1 ? '' : 's'}.`,
          autoDismissMs: 7000,
        });
      } else {
        deps.setBannerNotice({
          tone: 'warning',
          message: `Created group "${trimmedGroupName}" with ${successIds.length} saved template${successIds.length === 1 ? '' : 's'} and ${failures.length} failure${failures.length === 1 ? '' : 's'}.`,
          autoDismissMs: 10000,
        });
      }
    } catch (error) {
      if (cancelRequestedRef.current && dismissRequestedRef.current) {
        shouldResetAtEnd = true;
        return;
      }
      const message = successIds.length > 0
        ? `Saved ${successIds.length} template${successIds.length === 1 ? '' : 's'}, but failed to create group "${trimmedGroupName}". The saved templates remain in your account without a group.`
        : resolveStopMessage(error, 'Failed to create the PDF group.');
      shouldResetAtEnd = dismissRequestedRef.current;
      if (!dismissRequestedRef.current) {
        setLocalError(message);
      }
      deps.setBannerNotice({
        tone: successIds.length > 0 ? 'warning' : 'error',
        message,
        autoDismissMs: 9000,
      });
    } finally {
      if (shouldResetAtEnd) {
        reset();
        if (!dismissRequestedRef.current) {
          setOpen(false);
        }
      } else {
        setProcessing(false);
        setProgressLabel('Create PDF Group');
      }
    }
  }, [
    deps,
    groupName,
    hasFileErrors,
    hasPendingPageCounts,
    items,
    operation,
    pageSummary.withinLimit,
    processing,
    reset,
    abortInFlightRequests,
    releaseAbortController,
    setItemState,
    trackAbortController,
    wantsMap,
    wantsRename,
  ]);

  return {
    open,
    groupName,
    setGroupName,
    items,
    wantsRename,
    setWantsRename,
    wantsMap,
    setWantsMap,
    processing,
    localError,
    progressLabel,
    pageSummary,
    creditEstimate,
    creditsRemaining,
    openDialog,
    closeDialog,
    addFiles,
    removeFile,
    confirm,
    reset,
  };
}
