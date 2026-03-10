import {
  DEFAULT_PROCESSING_MESSAGE,
  DETECT_PROCESSING_TITLE,
  FILLABLE_TEMPLATE_PROCESSING_MESSAGE,
  FILLABLE_TEMPLATE_PROCESSING_TITLE,
  SAVED_FORM_PROCESSING_MESSAGE,
  SAVED_FORM_PROCESSING_TITLE,
  SAVED_GROUP_PROCESSING_MESSAGE,
  SAVED_GROUP_PROCESSING_TITLE,
} from '../config/appConstants';

export type ProcessingVariant = 'detect' | 'fillable' | 'saved-form' | 'saved-group';

type ProcessingCopy = {
  heading: string;
  detail: string;
};

const PROCESSING_COPY: Record<ProcessingVariant, ProcessingCopy> = {
  detect: {
    heading: DETECT_PROCESSING_TITLE,
    detail: DEFAULT_PROCESSING_MESSAGE,
  },
  fillable: {
    heading: FILLABLE_TEMPLATE_PROCESSING_TITLE,
    detail: FILLABLE_TEMPLATE_PROCESSING_MESSAGE,
  },
  'saved-form': {
    heading: SAVED_FORM_PROCESSING_TITLE,
    detail: SAVED_FORM_PROCESSING_MESSAGE,
  },
  'saved-group': {
    heading: SAVED_GROUP_PROCESSING_TITLE,
    detail: SAVED_GROUP_PROCESSING_MESSAGE,
  },
};

export function resolveProcessingCopy(variant: ProcessingVariant): ProcessingCopy {
  return PROCESSING_COPY[variant];
}
