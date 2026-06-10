'use client';

import { getApiBaseUrl } from './env';
import type { User } from '../types';

const API_BASE = getApiBaseUrl();
// X-Session-Transport tells the backend which credential mechanism this client
// is using. When set to 'cookie', the server knows the refresh token arrives
// via an HTTP-only cookie (browser flow) rather than a Bearer token in the
// Authorization header (mobile / non-browser flow). This lets the server apply
// the correct extraction path and Set-Cookie response behaviour without having
// to sniff the request body or rely on Content-Type.
const COOKIE_SESSION_HEADER = 'X-Session-Transport';
const COOKIE_SESSION_VALUE = 'cookie';

type AccessTokenListener = (token: string | null) => void;

const listeners = new Set<AccessTokenListener>();

let accessTokenCache: string | null = null;
let bootstrapPromise: Promise<SessionBootstrapResult> | null = null;

export interface SessionBootstrapResult {
  accessToken: string | null;
  user: User | null;
}

function isBrowser() {
  return typeof window !== 'undefined';
}

function readStoredAccessToken(): string | null {
  return accessTokenCache;
}

function writeStoredAccessToken(token: string | null) {
  accessTokenCache = token;
}

function notifyListeners(token: string | null) {
  listeners.forEach((listener) => listener(token));
}

export function getAccessToken(): string | null {
  if (accessTokenCache !== null) {
    return accessTokenCache;
  }

  accessTokenCache = readStoredAccessToken();
  return accessTokenCache;
}

export function setAccessToken(token: string | null) {
  accessTokenCache = token;
  writeStoredAccessToken(token);
  notifyListeners(token);
}

export function clearSessionState() {
  setAccessToken(null);
}

export function subscribeToAccessToken(listener: AccessTokenListener) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

async function requestSessionRefresh(): Promise<SessionBootstrapResult> {
  const response = await fetch(`${API_BASE}/api/auth/refresh`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      [COOKIE_SESSION_HEADER]: COOKIE_SESSION_VALUE,
    },
    body: JSON.stringify({}),
  });

  if (!response.ok) {
    clearSessionState();
    return { accessToken: null, user: null };
  }

  const data = (await response.json()) as { access_token?: string; user?: User | null };
  const nextAccessToken = typeof data.access_token === 'string' ? data.access_token : null;
  setAccessToken(nextAccessToken);
  return {
    accessToken: nextAccessToken,
    user: data.user ?? null,
  };
}

export async function refreshSession(): Promise<string | null> {
  const result = await bootstrapSessionData();
  return result.accessToken;
}

export async function bootstrapSession(): Promise<string | null> {
  const result = await bootstrapSessionData();
  return result.accessToken;
}

export async function bootstrapSessionData(): Promise<SessionBootstrapResult> {
  if (!isBrowser()) {
    return { accessToken: null, user: null };
  }

  if (!bootstrapPromise) {
    bootstrapPromise = requestSessionRefresh().finally(() => {
      bootstrapPromise = null;
    });
  }

  return bootstrapPromise;
}

export function getCookieSessionHeaders(): Record<string, string> {
  return {
    [COOKIE_SESSION_HEADER]: COOKIE_SESSION_VALUE,
  };
}
