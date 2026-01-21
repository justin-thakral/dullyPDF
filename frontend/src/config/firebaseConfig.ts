/**
 * Firebase web configuration loaded from Vite environment variables.
 * Required in all modes to avoid implicit fallback config in production.
 */

const env = import.meta.env;

/**
 * Read a required Vite env value or throw.
 */
const readRequiredEnv = (key: string) => {
  const raw = env?.[key];
  if (typeof raw !== 'string' || !raw.trim()) {
    throw new Error(`Missing ${key}. Set it in your Vite env file.`);
  }
  return raw.trim();
};

export const firebaseConfig = {
  apiKey: readRequiredEnv('VITE_FIREBASE_API_KEY'),
  authDomain: readRequiredEnv('VITE_FIREBASE_AUTH_DOMAIN'),
  projectId: readRequiredEnv('VITE_FIREBASE_PROJECT_ID'),
  appId: readRequiredEnv('VITE_FIREBASE_APP_ID'),
  storageBucket: readRequiredEnv('VITE_FIREBASE_STORAGE_BUCKET'),
  messagingSenderId: readRequiredEnv('VITE_FIREBASE_MESSAGING_SENDER_ID'),
};
