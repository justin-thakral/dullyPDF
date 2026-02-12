import { useCallback, useMemo, useRef, useState } from 'react';
import type { ConfidenceFilter, ConfidenceTier, FieldType, PageSize, PdfField } from '../types';
import { fieldConfidenceTierForField } from '../utils/confidence';
import { createField } from '../utils/fields';
import { debugLog } from '../utils/debug';

export function useFieldState(
  fieldsRef: React.MutableRefObject<PdfField[]>,
  fields: PdfField[],
  updateFields: (next: PdfField[], options?: { trackHistory?: boolean }) => void,
  updateFieldsWith: (updater: (prev: PdfField[]) => PdfField[], options?: { trackHistory?: boolean }) => void,
) {
  const [showFields, setShowFields] = useState(true);
  const [showFieldNames, setShowFieldNames] = useState(true);
  const [showFieldInfo, setShowFieldInfo] = useState(false);
  const [confidenceFilter, setConfidenceFilter] = useState<ConfidenceFilter>({
    high: true,
    medium: true,
    low: true,
  });
  const [selectedFieldId, setSelectedFieldId] = useState<string | null>(null);
  const lastFieldVisibilityRef = useRef({ showFieldInfo, showFieldNames });

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

  const handleUpdateFieldDraft = useCallback(
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
      debugLog('Updated field (draft)', fieldId, updates);
    },
    [updateFieldsWith],
  );

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
    (type: FieldType, currentPage: number, pageSizes: Record<number, PageSize>) => {
      const pageSize = pageSizes[currentPage];
      if (!pageSize) return;
      const nextField = createField(type, currentPage, pageSize, fieldsRef.current);
      updateFieldsWith((prev) => [...prev, nextField]);
      setSelectedFieldId(nextField.id);
      debugLog('Created field', nextField);
    },
    [fieldsRef, updateFieldsWith],
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

  const visibleFields = useMemo(
    () => fields.filter((field) => confidenceFilter[fieldConfidenceTierForField(field)]),
    [confidenceFilter, fields],
  );

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

  const reset = useCallback(() => {
    setShowFields(true);
    setShowFieldNames(true);
    setShowFieldInfo(false);
    setConfidenceFilter({ high: true, medium: true, low: true });
    setSelectedFieldId(null);
  }, []);

  const handleFieldsChange = useCallback(
    (nextFields: PdfField[]) => {
      updateFields(nextFields);
    },
    [updateFields],
  );

  return {
    showFields,
    setShowFields,
    showFieldNames,
    setShowFieldNames,
    showFieldInfo,
    setShowFieldInfo,
    confidenceFilter,
    setConfidenceFilter,
    selectedFieldId,
    setSelectedFieldId,
    lastFieldVisibilityRef,
    visibleFields,
    hasFieldValues,
    handleUpdateField,
    handleUpdateFieldDraft,
    handleUpdateFieldGeometry,
    handleDeleteField,
    handleCreateField,
    handleClearFieldValues,
    handleConfidenceFilterChange,
    handleShowFieldsChange,
    handleShowFieldNamesChange,
    handleShowFieldInfoChange,
    handleFieldsChange,
    reset,
  };
}
