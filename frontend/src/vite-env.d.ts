/// <reference types="vite/client" />

// Shared SEO route data is kept in a plain ESM module so the frontend runtime and
// build-time Node scripts can consume the same source without a TS compile step.
declare module '*.mjs';
