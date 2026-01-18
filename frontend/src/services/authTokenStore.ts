/**
 * Simple in-memory store for the latest Firebase ID token.
 */

type TokenListener = (token: string | null) => void;

let currentToken: string | null = null;
const listeners = new Set<TokenListener>();

/**
 * Return the cached auth token.
 */
export function getAuthToken(): string | null {
  return currentToken;
}

/**
 * Update the token and notify listeners.
 */
export function setAuthToken(token: string | null): void {
  currentToken = token;
  for (const listener of listeners) {
    try {
      listener(token);
    } catch (err) {
      console.error('[authTokenStore] listener error', err);
    }
  }
}

/**
 * Register a listener for token changes.
 */
export function onTokenChanged(listener: TokenListener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
