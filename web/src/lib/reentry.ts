'use client';

import type { ArrivalKind } from './arrival';
import type { Notification } from '../types';

export type ReentryConversationSource =
  | 'feed'
  | 'profile'
  | 'notifications'
  | 'search'
  | 'discovery'
  | 'bookmarks'
  | 'reply'
  | 'quote';

export interface RecentConversationState {
  postId: number;
  authorUsername: string;
  authorDisplayName?: string | null;
  snippet: string;
  source: ReentryConversationSource;
  lastViewedAt: number;
}

export interface ReturningSessionState {
  userId: number;
  username: string;
  firstSeenAt: number;
  previousSeenAt: number | null;
  lastSeenAt: number;
  currentSessionStartedAt: number;
  sessionCount: number;
  recentConversation: RecentConversationState | null;
  dismissedSessionStartedAt: number | null;
}

const RETURNING_SESSION_KEY = 'nexus_returning_session_state';
const RETURNING_SESSION_USER_KEY = 'nexus_returning_session_user';
const RETURNING_SESSION_MAX_AGE_MS = 1000 * 60 * 60 * 24 * 30;
const RETURNING_SESSION_MIN_GAP_MS = 1000 * 60 * 60 * 6;
const RECENT_CONVERSATION_MAX_AGE_MS = 1000 * 60 * 60 * 24 * 7;
const NOTIFICATION_REENTRY_MAX_AGE_MS = 1000 * 60 * 60 * 24 * 7;
const RECENT_CONVERSATION_MIN_SNIPPET_CHARS = 24;
const EMPTY_CONVERSATION_SNIPPET = 'Conversation without text';

function isBrowser() {
  return typeof window !== 'undefined';
}

function isExpired(state: ReturningSessionState) {
  return Date.now() - state.lastSeenAt > RETURNING_SESSION_MAX_AGE_MS;
}

function normalizeSnippet(snippet: string) {
  const trimmed = snippet.trim().replace(/\s+/g, ' ');
  if (!trimmed) {
    return EMPTY_CONVERSATION_SNIPPET;
  }

  return trimmed.length > 180 ? `${trimmed.slice(0, 177)}...` : trimmed;
}

function isMeaningfulSnippet(snippet: string) {
  const normalized = normalizeSnippet(snippet);
  return (
    normalized !== EMPTY_CONVERSATION_SNIPPET &&
    normalized.length >= RECENT_CONVERSATION_MIN_SNIPPET_CHARS
  );
}

function isRecentConversationFresh(conversation: RecentConversationState | null) {
  return Boolean(conversation && Date.now() - conversation.lastViewedAt <= RECENT_CONVERSATION_MAX_AGE_MS);
}

function getPreviousGapMs(state: ReturningSessionState | null) {
  if (!state?.previousSeenAt) {
    return null;
  }

  return Math.max(0, state.currentSessionStartedAt - state.previousSeenAt);
}

function notificationTimestampMs(notification: Notification) {
  const timestamp = Date.parse(notification.created_at);
  return Number.isNaN(timestamp) ? null : timestamp;
}

export function notificationPrimaryPost(notification: Notification) {
  switch (notification.notification_type) {
    case 'reply':
    case 'quote':
    case 'mention':
      return notification.source_post || notification.post;
    case 'like':
    case 'repost':
      return notification.post || notification.source_post;
    case 'follow':
      return null;
  }
}

export function getNotificationReentryFocus(notification: Notification) {
  if (notification.notification_type === 'quote') {
    return 'quote';
  }

  if (notification.notification_type === 'reply' || notification.notification_type === 'mention') {
    return 'reply';
  }

  return 'conversation';
}

export function getNotificationReentrySource(notification: Notification): ReentryConversationSource {
  const focus = getNotificationReentryFocus(notification);
  return focus === 'quote' || focus === 'reply' ? focus : 'notifications';
}

export function isNotificationReentryCandidate(notification: Notification) {
  const primaryPost = notificationPrimaryPost(notification);
  const timestamp = notificationTimestampMs(notification);

  if (
    (notification.notification_type !== 'reply' &&
      notification.notification_type !== 'quote' &&
      notification.notification_type !== 'mention') ||
    !primaryPost?.id ||
    primaryPost.is_available === false ||
    !timestamp
  ) {
    return false;
  }

  if (Date.now() - timestamp > NOTIFICATION_REENTRY_MAX_AGE_MS) {
    return false;
  }

  return Boolean(
    primaryPost.content_snippet && isMeaningfulSnippet(primaryPost.content_snippet)
  );
}

export function readReturningSessionState(): ReturningSessionState | null {
  if (!isBrowser()) {
    return null;
  }

  const raw = window.localStorage.getItem(RETURNING_SESSION_KEY);
  if (!raw) {
    return null;
  }

  try {
    const parsed = JSON.parse(raw) as ReturningSessionState;
    if (isExpired(parsed)) {
      window.localStorage.removeItem(RETURNING_SESSION_KEY);
      return null;
    }
    return parsed;
  } catch {
    window.localStorage.removeItem(RETURNING_SESSION_KEY);
    return null;
  }
}

export function writeReturningSessionState(state: ReturningSessionState | null) {
  if (!isBrowser()) {
    return;
  }

  if (!state) {
    window.localStorage.removeItem(RETURNING_SESSION_KEY);
    return;
  }

  window.localStorage.setItem(RETURNING_SESSION_KEY, JSON.stringify(state));
}

export function clearReturningSessionState() {
  if (!isBrowser()) {
    return;
  }

  window.localStorage.removeItem(RETURNING_SESSION_KEY);
  window.sessionStorage.removeItem(RETURNING_SESSION_USER_KEY);
}

export function syncReturningSessionState(params: {
  userId: number;
  username: string;
  arrivalKind?: ArrivalKind | null;
}) {
  if (!isBrowser()) {
    return null;
  }

  const now = Date.now();
  const existing = readReturningSessionState();
  const shouldStartFresh = params.arrivalKind === 'signup';

  let nextState: ReturningSessionState =
    shouldStartFresh || !existing || existing.userId !== params.userId
      ? {
          userId: params.userId,
          username: params.username,
          firstSeenAt: now,
          previousSeenAt: null,
          lastSeenAt: now,
          currentSessionStartedAt: now,
          sessionCount: 0,
          recentConversation: null,
          dismissedSessionStartedAt: null,
        }
      : {
          ...existing,
          username: params.username,
          previousSeenAt: existing.lastSeenAt,
          lastSeenAt: now,
        };

  const currentSessionUserId = window.sessionStorage.getItem(RETURNING_SESSION_USER_KEY);
  if (currentSessionUserId !== String(params.userId)) {
    nextState = {
      ...nextState,
      sessionCount: nextState.sessionCount + 1,
      currentSessionStartedAt: now,
      dismissedSessionStartedAt: null,
    };
    window.sessionStorage.setItem(RETURNING_SESSION_USER_KEY, String(params.userId));
  }

  writeReturningSessionState(nextState);
  return nextState;
}

export function saveRecentConversation(params: {
  postId: number;
  authorUsername: string;
  authorDisplayName?: string | null;
  snippet: string;
  source: ReentryConversationSource;
}) {
  const existing = readReturningSessionState();
  if (!existing) {
    return existing;
  }

  const normalizedSnippet = normalizeSnippet(params.snippet);
  const currentRecentConversation = getRecentConversation(existing);
  const isSameConversation = currentRecentConversation?.postId === params.postId;

  if (!isMeaningfulSnippet(normalizedSnippet) && !isSameConversation) {
    return existing;
  }

  const nextState = {
    ...existing,
    lastSeenAt: Date.now(),
    recentConversation: {
      postId: params.postId,
      authorUsername: params.authorUsername,
      authorDisplayName: params.authorDisplayName,
      snippet: normalizedSnippet,
      source: params.source,
      lastViewedAt: Date.now(),
    },
  };

  writeReturningSessionState(nextState);
  return nextState;
}

export function dismissReturningSession(state: ReturningSessionState | null) {
  if (!state) {
    return state;
  }

  const nextState = {
    ...state,
    dismissedSessionStartedAt: state.currentSessionStartedAt,
    lastSeenAt: Date.now(),
  };

  writeReturningSessionState(nextState);
  return nextState;
}

export function isReturningSessionEligible(state: ReturningSessionState | null) {
  const gapMs = getPreviousGapMs(state);
  return Boolean(
    state &&
      state.sessionCount > 1 &&
      state.previousSeenAt &&
      gapMs !== null &&
      gapMs >= RETURNING_SESSION_MIN_GAP_MS
  );
}

export function isReturningSessionDismissed(state: ReturningSessionState | null) {
  return Boolean(
    state &&
      state.dismissedSessionStartedAt &&
      state.dismissedSessionStartedAt === state.currentSessionStartedAt
  );
}

export function getRecentConversation(state: ReturningSessionState | null) {
  if (!state?.recentConversation || !isRecentConversationFresh(state.recentConversation)) {
    return null;
  }

  if (!isMeaningfulSnippet(state.recentConversation.snippet)) {
    return null;
  }

  return state.recentConversation;
}

export function getReturningSessionHoursAway(state: ReturningSessionState | null) {
  const gapMs = getPreviousGapMs(state);
  if (gapMs === null) {
    return null;
  }

  return Math.max(1, Math.round(gapMs / (1000 * 60 * 60)));
}
