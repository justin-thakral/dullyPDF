/**
 * UI labels and options for field types and editor create tools.
 */
import type { CreateTool, FieldType } from '../types';

// Order matters for dropdown display.
export const FIELD_TYPES: FieldType[] = ['text', 'date', 'signature', 'checkbox', 'radio'];
export const CREATE_TOOLS: CreateTool[] = ['text', 'date', 'signature', 'checkbox', 'radio', 'quick-radio'];

export function fieldTypeLabel(type: FieldType) {
  switch (type) {
    case 'text':
      return 'Text';
    case 'date':
      return 'Date';
    case 'signature':
      return 'Signature';
    case 'checkbox':
      return 'Checkbox';
    case 'radio':
      return 'Radio';
    default:
      return 'Field';
  }
}

export function createToolLabel(type: CreateTool) {
  if (type === 'quick-radio') {
    return 'Quick Radio';
  }
  return fieldTypeLabel(type);
}
