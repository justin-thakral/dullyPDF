/** Shared type definitions for the frontend. */
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
   * Confidence of the schema mapping/rename suggestion (0..1).
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
  /**
   * Checkbox grouping metadata used for schema mapping and search/fill rules.
   */
  groupKey?: string;
  optionKey?: string;
  optionLabel?: string;
  groupLabel?: string;
};

export type CheckboxRule = {
  databaseField: string;
  groupKey: string;
  operation: 'yes_no' | 'enum' | 'list' | 'presence';
  trueOption?: string;
  falseOption?: string;
  valueMap?: Record<string, string>;
  confidence?: number;
  reasoning?: string;
};

// Cached page dimensions for rendering and clamping.
export type PageSize = {
  width: number;
  height: number;
};
