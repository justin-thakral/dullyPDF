/**
 * Simple in-memory store for the latest Firebase ID token so API calls can
 * attach Authorization headers without each caller fetching tokens manually.
 */

type TokenListener = (token: string | null) => void;

let currentToken: string | null = null;
const listeners = new Set<TokenListener>();

export function getAuthToken(): string | null {
  return currentToken;
}

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

export function onTokenChanged(listener: TokenListener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
