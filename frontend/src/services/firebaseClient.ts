/**
 * Firebase client initialization for the frontend.
 */
import { initializeApp, getApps, getApp } from 'firebase/app';
import { getAuth } from 'firebase/auth';
import { firebaseConfig } from '../config/firebaseConfig';

/**
 * Initializes Firebase exactly once and exports a shared Auth instance.
 * Components/services should import from here instead of calling
 * initializeApp in multiple places.
 */
const app = getApps().length ? getApp() : initializeApp(firebaseConfig);

export const firebaseApp = app;
export const firebaseAuth = getAuth(app);
