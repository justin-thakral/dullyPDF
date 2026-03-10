import { useCallback, useRef, useState } from 'react';
import type { PdfField } from '../types';
import { MAX_FIELD_HISTORY } from '../config/appConstants';

export function useFieldHistory() {
  const fieldsRef = useRef<PdfField[]>([]);
  const historyRef = useRef<{ undo: PdfField[][]; redo: PdfField[][] }>({ undo: [], redo: [] });
  const pendingHistoryRef = useRef<PdfField[] | null>(null);
  const [fields, setFields] = useState<PdfField[]>([]);
  const [historyTick, setHistoryTick] = useState(0);

  const pushSnapshot = (stack: PdfField[][], snapshot: PdfField[]) => {
    stack.push(snapshot);
    if (stack.length > MAX_FIELD_HISTORY) {
      stack.shift();
    }
  };

  const pushFieldHistory = useCallback((snapshot: PdfField[]) => {
    const history = historyRef.current;
    pushSnapshot(history.undo, snapshot);
    history.redo.length = 0;
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

  const handleUndo = useCallback(
    (onSelectionUpdate: (updater: (currentId: string | null) => string | null) => void) => {
      commitFieldHistory();
      const history = historyRef.current;
      if (!history.undo.length) return;
      const previous = history.undo[history.undo.length - 1];
      history.undo.pop();
      pushSnapshot(history.redo, fieldsRef.current);
      pendingHistoryRef.current = null;
      fieldsRef.current = previous;
      setFields(previous);
      setHistoryTick((prev) => prev + 1);
      onSelectionUpdate((currentId) =>
        currentId && previous.some((field) => field.id === currentId) ? currentId : null,
      );
    },
    [commitFieldHistory],
  );

  const handleRedo = useCallback(
    (onSelectionUpdate: (updater: (currentId: string | null) => string | null) => void) => {
      commitFieldHistory();
      const history = historyRef.current;
      if (!history.redo.length) return;
      const next = history.redo[history.redo.length - 1];
      history.redo.pop();
      pushSnapshot(history.undo, fieldsRef.current);
      pendingHistoryRef.current = null;
      fieldsRef.current = next;
      setFields(next);
      setHistoryTick((prev) => prev + 1);
      onSelectionUpdate((currentId) =>
        currentId && next.some((field) => field.id === currentId) ? currentId : null,
      );
    },
    [commitFieldHistory],
  );

  const reset = useCallback(() => {
    resetFieldHistory([]);
  }, [resetFieldHistory]);

  const restoreState = useCallback(
    (
      nextFields: PdfField[],
      history?: {
        undo?: PdfField[][];
        redo?: PdfField[][];
      } | null,
    ) => {
      historyRef.current.undo = Array.isArray(history?.undo) ? history.undo : [];
      historyRef.current.redo = Array.isArray(history?.redo) ? history.redo : [];
      pendingHistoryRef.current = null;
      fieldsRef.current = nextFields;
      setFields(nextFields);
      setHistoryTick((prev) => prev + 1);
    },
    [],
  );

  const canUndo = historyRef.current.undo.length > 0;
  const canRedo = historyRef.current.redo.length > 0;
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  void historyTick; // Force re-render dependency for canUndo/canRedo

  return {
    fields,
    setFields,
    fieldsRef,
    historyRef,
    updateFields,
    updateFieldsWith,
    resetFieldHistory,
    pushFieldHistory,
    beginFieldHistory,
    commitFieldHistory,
    handleUndo,
    handleRedo,
    canUndo,
    canRedo,
    historyTick,
    restoreState,
    reset,
  };
}
