'use client';

import type { ArrivalKind } from './arrival';

export type ActivationSurface = 'home' | 'explore' | 'search' | 'profile';
export type ActivationAction = 'opened_thread' | 'ran_search' | 'tuned_profile';
export type ActivationStage = 'first_session' | 'second_session' | 'settled';

export interface MemberActivationState {
  userId: number;
  username: string;
  startedAt: number;
  lastSeenAt: number;
  sessionCount: number;
  visitedSurfaces: ActivationSurface[];
  completedActions: ActivationAction[];
}

const ACTIVATION_STATE_KEY = 'member_activation_state';
const ACTIVATION_SESSION_KEY = 'member_activation_session_user';
const ACTIVATION_MAX_SESSIONS = 2;
const ACTIVATION_MAX_AGE_MS = 1000 * 60 * 60 * 24 * 14;

function isBrowser() {
  return typeof window !== 'undefined';
}

function normalizeActivationState(value: MemberActivationState): MemberActivationState {
  return {
    ...value,
    visitedSurfaces: Array.isArray(value.visitedSurfaces)
      ? Array.from(new Set(value.visitedSurfaces.filter((surface) => surface)))
      : [],
    completedActions: Array.isArray(value.completedActions)
      ? Array.from(new Set(value.completedActions.filter((action) => action)))
      : [],
  };
}

function hasCompletedChecklist(state: MemberActivationState) {
  return ['opened_thread', 'ran_search', 'tuned_profile'].every((action) => state.completedActions.includes(action as ActivationAction));
}

export function readMemberActivationState(): MemberActivationState | null {
  if (!isBrowser()) {
    return null;
  }

  const raw = window.localStorage.getItem(ACTIVATION_STATE_KEY);
  if (!raw) {
    return null;
  }

  try {
    return normalizeActivationState(JSON.parse(raw) as MemberActivationState);
  } catch {
    window.localStorage.removeItem(ACTIVATION_STATE_KEY);
    return null;
  }
}

export function writeMemberActivationState(state: MemberActivationState | null) {
  if (!isBrowser()) {
    return;
  }

  if (!state) {
    window.localStorage.removeItem(ACTIVATION_STATE_KEY);
    return;
  }

  window.localStorage.setItem(ACTIVATION_STATE_KEY, JSON.stringify(normalizeActivationState(state)));
}

function isExpired(state: MemberActivationState) {
  return Date.now() - state.startedAt > ACTIVATION_MAX_AGE_MS;
}

export function isMemberActivationActive(state: MemberActivationState | null) {
  if (!state) {
    return false;
  }

  if (isExpired(state)) {
    return false;
  }

  if (hasCompletedChecklist(state)) {
    return false;
  }

  return state.sessionCount <= ACTIVATION_MAX_SESSIONS;
}

export function getActivationStage(state: MemberActivationState | null): ActivationStage {
  if (!state || !isMemberActivationActive(state)) {
    return 'settled';
  }

  return state.sessionCount <= 1 ? 'first_session' : 'second_session';
}

export function syncMemberActivationState(params: {
  userId: number;
  username: string;
  arrivalKind?: ArrivalKind | null;
}) {
  if (!isBrowser()) {
    return null;
  }

  const now = Date.now();
  const shouldStartFresh = params.arrivalKind === 'signup';
  const existing = readMemberActivationState();

  let nextState: MemberActivationState | null = null;

  if (shouldStartFresh) {
    nextState = {
      userId: params.userId,
      username: params.username,
      startedAt: now,
      lastSeenAt: now,
      sessionCount: 0,
      visitedSurfaces: [],
      completedActions: [],
    };
  } else if (existing && existing.userId === params.userId && !isExpired(existing)) {
    nextState = {
      ...existing,
      username: params.username,
      lastSeenAt: now,
    };
  }

  if (!nextState) {
    return null;
  }

  const currentSessionUserId = window.sessionStorage.getItem(ACTIVATION_SESSION_KEY);
  if (currentSessionUserId !== String(params.userId)) {
    nextState.sessionCount += 1;
    window.sessionStorage.setItem(ACTIVATION_SESSION_KEY, String(params.userId));
  }

  writeMemberActivationState(nextState);
  return nextState;
}

export function markActivationSurfaceVisited(surface: ActivationSurface) {
  const existing = readMemberActivationState();
  if (!existing || !isMemberActivationActive(existing)) {
    return existing;
  }

  if (existing.visitedSurfaces.includes(surface)) {
    return existing;
  }

  const nextState = {
    ...existing,
    visitedSurfaces: [...existing.visitedSurfaces, surface],
    lastSeenAt: Date.now(),
  };

  writeMemberActivationState(nextState);
  return nextState;
}

export function markActivationActionCompleted(action: ActivationAction) {
  const existing = readMemberActivationState();
  if (!existing || !isMemberActivationActive(existing)) {
    return existing;
  }

  if (existing.completedActions.includes(action)) {
    return existing;
  }

  const nextState = {
    ...existing,
    completedActions: [...existing.completedActions, action],
    lastSeenAt: Date.now(),
  };

  writeMemberActivationState(nextState);
  return nextState;
}
