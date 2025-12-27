// Supported field categories used by the editor and overlay styling.
export type FieldType = 'text' | 'checkbox' | 'signature' | 'date';

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
};

// Cached page dimensions for rendering and clamping.
export type PageSize = {
  width: number;
  height: number;
};
