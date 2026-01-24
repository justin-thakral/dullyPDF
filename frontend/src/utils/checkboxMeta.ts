import type { PdfField } from '../types';
import { normaliseDataKey } from './dataSource';

export type CheckboxMeta = {
  groupKey: string;
  optionKey: string;
  optionLabel?: string;
};

const CHECKBOX_BOOLEAN_OPTIONS = new Set([
  'yes',
  'no',
  'true',
  'false',
  'y',
  'n',
  't',
  'f',
  'on',
  'off',
  'checked',
  'unchecked',
]);

function resolveCheckboxBaseName(field: PdfField): string {
  const normalizedName = normaliseDataKey(field.name || '');
  if (!normalizedName) return '';
  if (normalizedName.startsWith('i_')) return normalizedName.slice(2);
  if (normalizedName.startsWith('checkbox_')) return normalizedName.replace(/^checkbox_/, '');
  return normalizedName;
}

/**
 * Resolve checkbox group/option keys from metadata or naming.
 */
export function computeCheckboxMeta(fields: PdfField[], rowKeys: string[]): Map<string, CheckboxMeta> {
  const metaById = new Map<string, CheckboxMeta>();
  const prefixCounts = new Map<string, number>();
  const normalizedKeys = rowKeys.map((key) => normaliseDataKey(key)).filter(Boolean);
  const rowKeySet = new Set(normalizedKeys);
  const rowKeySetStripped = new Set(
    normalizedKeys.map((key) => {
      if (key.startsWith('i_')) return key.slice(2);
      if (key.startsWith('checkbox_')) return key.replace(/^checkbox_/, '');
      return key;
    }),
  );
  const candidates: Array<{
    field: PdfField;
    base: string;
    tokens: string[];
    optionLabel?: string;
  }> = [];

  for (const field of fields) {
    if (field.type !== 'checkbox') continue;
    const optionLabel = typeof field.optionLabel === 'string' ? field.optionLabel : undefined;
    const storedGroup = field.groupKey ? normaliseDataKey(field.groupKey) : '';
    const storedOption = field.optionKey ? normaliseDataKey(field.optionKey) : '';
    if (storedGroup && storedOption) {
      metaById.set(field.id, { groupKey: storedGroup, optionKey: storedOption, optionLabel });
    }

    const base = resolveCheckboxBaseName(field);
    if (!base) continue;
    const tokens = base.split('_').filter(Boolean);
    candidates.push({ field, base, tokens, optionLabel });
    if (tokens.length < 2) continue;
    for (let i = 1; i < tokens.length; i += 1) {
      const prefix = tokens.slice(0, i).join('_');
      prefixCounts.set(prefix, (prefixCounts.get(prefix) ?? 0) + 1);
    }
  }

  // Build checkbox group hints using shared name prefixes to keep multi-word options intact.
  // Complexity: O(n * s^2) over checkbox fields, where s is avg segment count per name.
  const findRowKeyPrefix = (tokens: string[]) => {
    for (let i = tokens.length - 1; i >= 1; i -= 1) {
      const prefix = tokens.slice(0, i).join('_');
      if (rowKeySet.has(prefix) || rowKeySetStripped.has(prefix)) {
        return { prefix, index: i };
      }
    }
    return null;
  };

  for (const { field, base, tokens, optionLabel } of candidates) {
    if (metaById.has(field.id)) continue;
    if (!base) continue;
    const optionFromLabel = optionLabel ? normaliseDataKey(optionLabel) : '';
    if (optionFromLabel && base.endsWith(`_${optionFromLabel}`)) {
      metaById.set(field.id, {
        groupKey: base.slice(0, -(optionFromLabel.length + 1)),
        optionKey: optionFromLabel,
        optionLabel,
      });
      continue;
    }

    if (tokens.length < 2) {
      metaById.set(field.id, { groupKey: base, optionKey: 'yes', optionLabel });
      continue;
    }

    const rowKeyPrefix = findRowKeyPrefix(tokens);
    if (rowKeyPrefix) {
      metaById.set(field.id, {
        groupKey: rowKeyPrefix.prefix,
        optionKey: tokens.slice(rowKeyPrefix.index).join('_'),
        optionLabel,
      });
      continue;
    }

    let chosenPrefix = '';
    for (let i = tokens.length - 1; i >= 1; i -= 1) {
      const prefix = tokens.slice(0, i).join('_');
      if ((prefixCounts.get(prefix) ?? 0) >= 2) {
        chosenPrefix = prefix;
        break;
      }
    }

    if (chosenPrefix) {
      metaById.set(field.id, {
        groupKey: chosenPrefix,
        optionKey: tokens.slice(chosenPrefix.split('_').length).join('_'),
        optionLabel,
      });
      continue;
    }

    const lastToken = tokens[tokens.length - 1];
    if (CHECKBOX_BOOLEAN_OPTIONS.has(lastToken)) {
      metaById.set(field.id, {
        groupKey: tokens.slice(0, -1).join('_'),
        optionKey: lastToken,
        optionLabel,
      });
      continue;
    }

    metaById.set(field.id, { groupKey: base, optionKey: 'yes', optionLabel });
  }

  return metaById;
}
