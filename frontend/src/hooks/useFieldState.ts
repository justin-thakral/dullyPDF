import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ConfidenceFilter, ConfidenceTier, FieldType, PageSize, PdfField } from '../types';
import { fieldConfidenceTierForField } from '../utils/confidence';
import { createField } from '../utils/fields';
import { debugLog } from '../utils/debug';

function mergeFieldUpdates(field: PdfField, updates: Partial<PdfField>): PdfField {
  return {
    ...field,
    ...updates,
    rect: updates.rect ? { ...field.rect, ...updates.rect } : field.rect,
  };
}

function hasFieldChanges(field: PdfField, updates: Partial<PdfField>): boolean {
  for (const [key, value] of Object.entries(updates) as [keyof PdfField, PdfField[keyof PdfField]][]) {
    if (key === 'rect') {
      if (!value) continue;
      const rectUpdates = value as Partial<PdfField['rect']>;
      for (const [rectKey, rectValue] of Object.entries(rectUpdates) as [keyof PdfField['rect'], number][]) {
        if (field.rect[rectKey] !== rectValue) {
          return true;
        }
      }
      continue;
    }
    if (field[key] !== value) {
      return true;
    }
  }
  return false;
}

function updateSingleField(
  fields: PdfField[],
  fieldId: string,
  updates: Partial<PdfField>,
): PdfField[] {
  const index = fields.findIndex((field) => field.id === fieldId);
  if (index === -1) return fields;
  const current = fields[index];
  if (!hasFieldChanges(current, updates)) return fields;
  const nextField = mergeFieldUpdates(current, updates);
  const next = [...fields];
  next[index] = nextField;
  return next;
}

function deleteFieldsByIds(fields: PdfField[], fieldIds: Iterable<string>): PdfField[] {
  const deleteIds = new Set(fieldIds);
  if (deleteIds.size === 0) return fields;
  const next = fields.filter((field) => !deleteIds.has(field.id));
  return next.length === fields.length ? fields : next;
}

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

  useEffect(() => {
    if (!showFields) return;
    lastFieldVisibilityRef.current = { showFieldInfo, showFieldNames };
  }, [showFieldInfo, showFieldNames, showFields]);

  const handleUpdateField = useCallback((fieldId: string, updates: Partial<PdfField>) => {
    updateFieldsWith((prev) => updateSingleField(prev, fieldId, updates));
    debugLog('Updated field', fieldId, updates);
  }, [updateFieldsWith]);

  const handleUpdateFieldDraft = useCallback(
    (fieldId: string, updates: Partial<PdfField>) => {
      updateFieldsWith(
        (prev) => updateSingleField(prev, fieldId, updates),
        { trackHistory: false },
      );
      debugLog('Updated field (draft)', fieldId, updates);
    },
    [updateFieldsWith],
  );

  const handleUpdateFieldGeometry = useCallback(
    (fieldId: string, updates: Partial<PdfField>) => {
      updateFieldsWith(
        (prev) => updateSingleField(prev, fieldId, updates),
        { trackHistory: false },
      );
    },
    [updateFieldsWith],
  );

  const handleDeleteField = useCallback((fieldId: string) => {
    updateFieldsWith((prev) => deleteFieldsByIds(prev, [fieldId]));
    setSelectedFieldId((prev) => (prev === fieldId ? null : prev));
    debugLog('Deleted field', fieldId);
  }, [updateFieldsWith]);

  const handleDeleteAllFields = useCallback(() => {
    updateFieldsWith((prev) => deleteFieldsByIds(prev, prev.map((field) => field.id)));
    setSelectedFieldId(null);
    debugLog('Deleted all fields');
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
      let next: PdfField[] | null = null;
      for (let index = 0; index < prev.length; index += 1) {
        const field = prev[index];
        const value = field.value;
        if (value === null || value === undefined) continue;
        if (typeof value === 'string' && value.trim().length === 0) continue;
        if (typeof value === 'boolean' && value === false) continue;
        if (!next) next = [...prev];
        next[index] = { ...field, value: null };
      }
      return next ?? prev;
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
    handleDeleteAllFields,
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
