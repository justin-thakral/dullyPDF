/**
 * Field name update queue logic for rename and mapping operations.
 */
import type { FieldNameUpdate, NameQueue, PdfField } from '../types';
import type { CheckboxMeta } from './checkboxMeta';
import { parseConfidence } from './confidence';
import { ensureUniqueFieldName } from './fields';

export function enqueueByName<T>(queue: Map<string, NameQueue<T>>, key: string, entry: T) {
  const bucket = queue.get(key);
  if (bucket) {
    bucket.entries.push(entry);
    return;
  }
  queue.set(key, { entries: [entry], index: 0 });
}

export function takeNextByName<T>(queue: Map<string, NameQueue<T>>, key: string): T | null {
  const bucket = queue.get(key);
  if (!bucket || bucket.index >= bucket.entries.length) return null;
  const entry = bucket.entries[bucket.index];
  bucket.index += 1;
  return entry ?? null;
}

/**
 * Apply rename updates while enforcing unique field names.
 */
export function applyFieldNameUpdatesToList(
  fields: PdfField[],
  updatesByCurrentName: Map<string, NameQueue<FieldNameUpdate>>,
  checkboxMetaById?: Map<string, CheckboxMeta>,
): PdfField[] {
  if (!updatesByCurrentName.size) return fields;
  const existingNames = new Set(fields.map((field) => field.name));
  return fields.map((field) => {
    const update = takeNextByName(updatesByCurrentName, field.name);
    if (!update) return field;

    let next = field;
    const nextMappingConfidence = parseConfidence(update.mappingConfidence);
    if (nextMappingConfidence !== undefined && nextMappingConfidence !== field.mappingConfidence) {
      next = { ...next, mappingConfidence: nextMappingConfidence };
    }
    const checkboxMeta = checkboxMetaById?.get(field.id);
    if (
      field.type === 'checkbox' &&
      checkboxMeta &&
      (!field.groupKey || !field.optionKey)
    ) {
      const nextOptionLabel = checkboxMeta.optionLabel ?? field.optionLabel;
      if (
        next.groupKey !== checkboxMeta.groupKey ||
        next.optionKey !== checkboxMeta.optionKey ||
        next.optionLabel !== nextOptionLabel
      ) {
        next = {
          ...next,
          groupKey: checkboxMeta.groupKey,
          optionKey: checkboxMeta.optionKey,
          optionLabel: nextOptionLabel,
        };
      }
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
