import { useCallback, useEffect, useMemo, useState } from 'react';

import type { WorkspaceSessionDiagnostic } from '../types';
import { fetchDetectionStatus } from '../services/detectionApi';
import { debugLog, isUiDebugEnabled } from '../utils/debug';
import {
  createPendingSessionDiagnostic,
  resolveSessionDiagnostic,
} from '../utils/sessionDiagnostics';

export interface UseWorkspaceSessionDiagnosticDeps {
  detectSessionId: string | null;
  pageCount: number;
  activeSavedFormId: string | null;
  activeSavedFormName: string | null;
  sourceFileName: string | null;
}

/**
 * Resolve and cache the active backend session metadata used by the dev-only
 * header badge and the pre-Rename/Map console trace.
 */
export function useWorkspaceSessionDiagnostic(deps: UseWorkspaceSessionDiagnosticDeps) {
  const [resolvedSessionDiagnostic, setResolvedSessionDiagnostic] = useState<WorkspaceSessionDiagnostic | null>(null);
  const debugEnabled = isUiDebugEnabled();
  const activeSessionId = debugEnabled ? deps.detectSessionId : null;
  const pendingSessionDiagnostic = useMemo(
    () => (
      activeSessionId
        ? createPendingSessionDiagnostic(activeSessionId, deps.pageCount > 0 ? deps.pageCount : null)
        : null
    ),
    [activeSessionId, deps.pageCount],
  );

  const resolveWorkspaceSessionDiagnostic = useCallback(
    async (sessionId: string): Promise<WorkspaceSessionDiagnostic> => {
      const fallbackPageCount = deps.pageCount > 0 ? deps.pageCount : null;
      const pendingDiagnostic = createPendingSessionDiagnostic(sessionId, fallbackPageCount);
      try {
        const payload = await fetchDetectionStatus(sessionId);
        return resolveSessionDiagnostic(sessionId, payload, { fallbackPageCount });
      } catch (error) {
        debugLog('Failed to refresh workspace session diagnostic', { sessionId, error });
        return pendingDiagnostic;
      }
    },
    [deps.pageCount],
  );

  const onBeforeOpenAiAction = useCallback(
    async (action: 'rename' | 'map' | 'rename_remap', sessionId: string | null) => {
      if (!isUiDebugEnabled()) return;
      const diagnostic = sessionId
        ? await resolveWorkspaceSessionDiagnostic(sessionId)
        : null;
      if (sessionId && deps.detectSessionId === sessionId) {
        setResolvedSessionDiagnostic(diagnostic);
      }
      debugLog('OpenAI workspace session diagnostic', {
        action,
        sessionId: diagnostic?.sessionId ?? sessionId ?? null,
        sourcePdf: diagnostic?.sourcePdf ?? null,
        sourcePdfResolved: diagnostic?.sourcePdfResolved ?? false,
        pageCount: diagnostic?.pageCount ?? (deps.pageCount > 0 ? deps.pageCount : null),
        status: diagnostic?.status ?? null,
        activeSavedFormId: deps.activeSavedFormId,
        activeSavedFormName: deps.activeSavedFormName ?? null,
        sourceFileName: deps.sourceFileName ?? null,
      });
    },
    [
      deps.activeSavedFormId,
      deps.activeSavedFormName,
      deps.detectSessionId,
      deps.pageCount,
      deps.sourceFileName,
      resolveWorkspaceSessionDiagnostic,
    ],
  );

  useEffect(() => {
    if (!activeSessionId) {
      return;
    }

    let cancelled = false;
    void (async () => {
      const diagnostic = await resolveWorkspaceSessionDiagnostic(activeSessionId);
      if (cancelled) return;
      setResolvedSessionDiagnostic((current) =>
        current?.sessionId && current.sessionId !== activeSessionId ? current : diagnostic,
      );
    })();

    return () => {
      cancelled = true;
    };
  }, [activeSessionId, resolveWorkspaceSessionDiagnostic]);

  const sessionDiagnostic = activeSessionId
    ? (
      resolvedSessionDiagnostic?.sessionId === activeSessionId
        ? resolvedSessionDiagnostic
        : pendingSessionDiagnostic
    )
    : null;

  return {
    sessionDiagnostic,
    onBeforeOpenAiAction,
  };
}
