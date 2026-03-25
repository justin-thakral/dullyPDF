import type {
  CheckboxRule,
  NameQueue,
  PdfField,
  RadioGroupSuggestion,
  TextTransformRule,
} from '../types';
import { computeCheckboxMeta } from './checkboxMeta';
import {
  applyFieldNameUpdatesToList,
  enqueueByName,
  takeNextByName,
} from './fieldUpdates';
import { deriveMappingConfidence, parseConfidence } from './confidence';

export function applyRenamePayloadToFields(
  fields: PdfField[],
  renamedFieldsPayload?: Array<Record<string, any>>,
): PdfField[] | null {
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
  for (const field of fields) {
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
  return updated;
}

type MappingApplicationResult = {
  fields: PdfField[];
  checkboxRules: CheckboxRule[];
  radioGroupSuggestions: RadioGroupSuggestion[];
  textTransformRules: TextTransformRule[];
};

export function applyMappingPayloadToFields(
  fields: PdfField[],
  mappingResults?: Record<string, any> | null,
  dataColumns: string[] = [],
): MappingApplicationResult {
  const mappings = Array.isArray(mappingResults?.mappings) ? mappingResults.mappings : [];
  const updates = new Map<string, NameQueue<Record<string, any>>>();
  const checkboxMetaById = computeCheckboxMeta(fields, dataColumns);

  for (const mapping of mappings) {
    if (!mapping || !mapping.pdfField) continue;
    const currentName = mapping.originalPdfField || mapping.pdfField;
    const desiredName = mapping.pdfField;
    if (!currentName) continue;
    const mappingConfidence =
      parseConfidence(mapping.confidence) ??
      deriveMappingConfidence(String(currentName), String(desiredName));
    enqueueByName(updates, String(currentName), {
      newName: String(desiredName),
      mappingConfidence,
    });
  }

  const nextFields = updates.size
    ? applyFieldNameUpdatesToList(fields, updates, checkboxMetaById)
    : fields;
  const fillRules = mappingResults?.fillRules && typeof mappingResults.fillRules === 'object'
    ? mappingResults.fillRules
    : null;

  const checkboxRules = Array.isArray(fillRules?.checkboxRules)
    ? (fillRules.checkboxRules as CheckboxRule[])
    : Array.isArray(mappingResults?.checkboxRules)
      ? (mappingResults.checkboxRules as CheckboxRule[])
      : [];
  const radioGroupSuggestions = Array.isArray(mappingResults?.radioGroupSuggestions)
    ? (mappingResults.radioGroupSuggestions as RadioGroupSuggestion[])
    : [];
  const textTransformRules = Array.isArray(fillRules?.textTransformRules)
    ? (fillRules.textTransformRules as TextTransformRule[])
    : Array.isArray((fillRules as Record<string, unknown> | null)?.templateRules)
      ? ((fillRules as Record<string, unknown>).templateRules as TextTransformRule[])
      : Array.isArray(mappingResults?.textTransformRules)
        ? (mappingResults.textTransformRules as TextTransformRule[])
        : Array.isArray((mappingResults as Record<string, unknown> | null)?.templateRules)
          ? ((mappingResults as Record<string, unknown>).templateRules as TextTransformRule[])
          : [];

  return {
    fields: nextFields,
    checkboxRules,
    radioGroupSuggestions,
    textTransformRules,
  };
}
