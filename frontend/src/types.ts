// Supported field categories used by the editor and overlay styling.
export type FieldType = 'text' | 'checkbox' | 'signature' | 'date';

export type ConfidenceTier = 'high' | 'medium' | 'low';

export type ConfidenceFilter = Record<ConfidenceTier, boolean>;

// Geometry is expressed in PDF points with a top-left origin.
export type FieldRect = {
  x: number;
  y: number;
  width: number;
  height: number;
};

// Client-side representation of a form field, kept in memory until export is implemented.
export type PdfField = {
  id: string;
  name: string;
  type: FieldType;
  page: number;
  rect: FieldRect;
  /**
   * Confidence that this is a real field (0..1). Populated by detection.
   * When OpenAI rename runs, this should represent "isItAfieldConfidence" if present.
   */
  fieldConfidence?: number;
  /**
   * Confidence of the DB mapping/rename suggestion (0..1). Populated by Map DB / .txt mapping.
   */
  mappingConfidence?: number;
  /**
   * Confidence of the OpenAI rename suggestion (0..1).
   */
  renameConfidence?: number;
  /**
   * Optional field value to inject when generating a filled PDF.
   */
  value?: string | number | boolean | null;
};

// Cached page dimensions for rendering and clamping.
export type PageSize = {
  width: number;
  height: number;
};
