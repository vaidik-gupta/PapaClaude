import type { Credentials } from './types';

const STORAGE_KEY = 'papaclaude.creds';

let current: Credentials | null = null;

export function loadCredentials(): Credentials | null {
  if (current) return current;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) current = JSON.parse(raw) as Credentials;
  } catch {
    current = null;
  }
  return current;
}

export function setCredentials(creds: Credentials): void {
  current = creds;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(creds));
  } catch {
    // ignore storage failures (private mode, etc.)
  }
}

export function clearCredentials(): void {
  current = null;
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}

export function getCredentials(): Credentials | null {
  return loadCredentials();
}

export function authHeaders(): Record<string, string> {
  const creds = getCredentials();
  if (!creds) return {};
  return {
    'X-User-Name': creds.userName,
    'X-User-Key': creds.userKey,
  };
}
