/**
 * Firebase web configuration loaded from Vite environment variables.
 * Falls back to the default Identity Platform project values so local
 * development works even if no .env file is present.
 */

const fallbackConfig = {
  apiKey: 'AIzaSyCu1G3q_WcCafGChYf942k89o234WTbMBA',
  authDomain: 'dullypdf.firebaseapp.com',
  projectId: 'dullypdf',
  appId: '1:916039292611:web:16b9c77a2f3de56c9fb476',
  storageBucket: 'dullypdf.firebasestorage.app',
  messagingSenderId: '916039292611',
};

const readEnv = (key: string, fallback: string) => {
  const raw = (import.meta as any)?.env?.[key];
  if (typeof raw !== 'string') return fallback;
  const trimmed = raw.trim();
  return trimmed.length ? trimmed : fallback;
};

export const firebaseConfig = {
  apiKey: readEnv('VITE_FIREBASE_API_KEY', fallbackConfig.apiKey),
  authDomain: readEnv('VITE_FIREBASE_AUTH_DOMAIN', fallbackConfig.authDomain),
  projectId: readEnv('VITE_FIREBASE_PROJECT_ID', fallbackConfig.projectId),
  appId: readEnv('VITE_FIREBASE_APP_ID', fallbackConfig.appId),
  storageBucket: readEnv('VITE_FIREBASE_STORAGE_BUCKET', fallbackConfig.storageBucket),
  messagingSenderId: readEnv('VITE_FIREBASE_MESSAGING_SENDER_ID', fallbackConfig.messagingSenderId),
};
