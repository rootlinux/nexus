'use client';

export type ArrivalKind = 'login' | 'signup';

export interface AuthArrivalState {
  kind: ArrivalKind;
  userId: number;
  username: string;
  displayName?: string | null;
  createdAt: number;
  inviter?: {
    username: string;
    displayName?: string | null;
  } | null;
}

const ARRIVAL_STATE_KEY = 'auth_arrival_state';

function isBrowser() {
  return typeof window !== 'undefined';
}

export function readArrivalState(): AuthArrivalState | null {
  if (!isBrowser()) {
    return null;
  }

  const raw = window.sessionStorage.getItem(ARRIVAL_STATE_KEY);
  if (!raw) {
    return null;
  }

  try {
    return JSON.parse(raw) as AuthArrivalState;
  } catch {
    window.sessionStorage.removeItem(ARRIVAL_STATE_KEY);
    return null;
  }
}

export function writeArrivalState(state: AuthArrivalState | null) {
  if (!isBrowser()) {
    return;
  }

  if (!state) {
    window.sessionStorage.removeItem(ARRIVAL_STATE_KEY);
    return;
  }

  window.sessionStorage.setItem(ARRIVAL_STATE_KEY, JSON.stringify(state));
}

export function clearArrivalState() {
  writeArrivalState(null);
}
