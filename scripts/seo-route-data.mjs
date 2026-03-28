/**
 * Build-time bridge for shared public SEO route data.
 *
 * `frontend/src/config/publicRouteSeoData.mjs` is the source of truth for
 * public route metadata used by both the React runtime and the static build
 * scripts. Keep this file as a thin re-export so existing script imports do
 * not need to change.
 */

export * from '../frontend/src/config/publicRouteSeoData.mjs';
