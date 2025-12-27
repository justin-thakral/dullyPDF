import type { FieldType } from '../types';

export const FIELD_TYPES: FieldType[] = ['text', 'date', 'signature', 'checkbox'];

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
    default:
      return 'Field';
  }
}
