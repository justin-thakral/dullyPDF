import { deleteUser, signInWithCustomToken, signOut } from 'firebase/auth';
import { firebaseAuth } from '../services/firebaseClient';

export async function signInWithCustomTokenForPlaywright(customToken: string): Promise<{
  uid: string;
  email: string | null;
  emailVerified: boolean;
  providerId: string | null;
}> {
  const credential = await signInWithCustomToken(firebaseAuth, customToken);
  const tokenResult = await credential.user.getIdTokenResult(true);
  return {
    uid: credential.user.uid,
    email: credential.user.email,
    emailVerified: credential.user.emailVerified,
    providerId: tokenResult.signInProvider ?? null,
  };
}

export async function signOutForPlaywright(): Promise<void> {
  await signOut(firebaseAuth);
}

export async function deleteCurrentUserForPlaywright(): Promise<boolean> {
  const user = firebaseAuth.currentUser;
  if (!user) return false;
  await deleteUser(user);
  return true;
}
