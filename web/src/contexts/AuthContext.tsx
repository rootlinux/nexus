'use client';

import type { AuthenticationResponseJSON } from '@simplewebauthn/browser';
import React, { createContext, useContext, useState, useEffect, ReactNode, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { PendingEmailVerificationResponse, User, Token, isMFARequired } from '../types';
import { login as apiLogin, register as apiRegister, getMe, logout as apiLogout, webauthnAuthComplete, webauthnAuthBegin } from '../lib/api';
import { AuthArrivalState, clearArrivalState as clearStoredArrivalState, readArrivalState, writeArrivalState } from '../lib/arrival';
import { ActivationAction, ActivationSurface, MemberActivationState, isMemberActivationActive, markActivationActionCompleted, markActivationSurfaceVisited, readMemberActivationState, syncMemberActivationState, writeMemberActivationState } from '../lib/activation';
import { RecentConversationState, ReturningSessionState, clearReturningSessionState, dismissReturningSession, readReturningSessionState, saveRecentConversation as persistRecentConversation, syncReturningSessionState } from '../lib/reentry';
import { bootstrapSession, bootstrapSessionData, clearSessionState, getAccessToken, subscribeToAccessToken } from '../lib/session';

interface AuthContextType {
  user: User | null;
  token: string | null;
  isLoading: boolean;
  arrivalState: AuthArrivalState | null;
  memberActivationState: MemberActivationState | null;
  returningSessionState: ReturningSessionState | null;
  /** Non-null when the backend returned 202 mfa_required after password login. */
  pendingMfaToken: string | null;
  login: (username: string, password: string) => Promise<void>;
  /**
   * Called by WebAuthnPrompt after the browser authenticator succeeds.
   * Sends the assertion to the backend and completes the login session.
   */
  completeMfaLogin: (credential: AuthenticationResponseJSON) => Promise<void>;
  /** Cancel the pending MFA step and return to the login form. */
  cancelMfaLogin: () => void;
  register: (username: string, displayName: string, email: string, password: string, inviteCode: string) => Promise<PendingEmailVerificationResponse>;
  logout: () => Promise<void>;
  refreshToken: () => Promise<boolean>;
  clearArrivalState: () => void;
  markActivationSurface: (surface: ActivationSurface) => void;
  completeActivationAction: (action: ActivationAction) => void;
  dismissReturningSessionCue: () => void;
  saveRecentConversation: (conversation: Omit<RecentConversationState, 'lastViewedAt'>) => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(getAccessToken());
  const [isLoading, setIsLoading] = useState(true);
  const [pendingMfaToken, setPendingMfaToken] = useState<string | null>(null);
  const [arrivalState, setArrivalState] = useState<AuthArrivalState | null>(readArrivalState());
  const [memberActivationState, setMemberActivationState] = useState<MemberActivationState | null>(readMemberActivationState());
  const [returningSessionState, setReturningSessionState] = useState<ReturningSessionState | null>(readReturningSessionState());

  const persistArrivalState = useCallback((nextArrivalState: AuthArrivalState | null) => {
    setArrivalState(nextArrivalState);
    writeArrivalState(nextArrivalState);
  }, []);

  const persistMemberActivationState = useCallback((nextActivationState: MemberActivationState | null) => {
    setMemberActivationState(nextActivationState);
    writeMemberActivationState(nextActivationState);
  }, []);

  const persistReturningSessionState = useCallback((nextReturningSessionState: ReturningSessionState | null) => {
    setReturningSessionState(nextReturningSessionState);
  }, []);

  const resetClientAuthState = useCallback(() => {
    setUser(null);
    setToken(null);
    setPendingMfaToken(null);
    persistArrivalState(null);
    persistMemberActivationState(null);
    persistReturningSessionState(null);
    clearSessionState();
    clearStoredArrivalState();
    clearReturningSessionState();
  }, [persistArrivalState, persistMemberActivationState, persistReturningSessionState]);

  useEffect(() => {
    const unsubscribe = subscribeToAccessToken((nextToken) => {
      setToken(nextToken);
    });

    const bootstrap = async () => {
      try {
        const session = await bootstrapSessionData();
        if (!session.accessToken) {
          resetClientAuthState();
          return;
        }

        const userData: User = session.user ?? await getMe();
        setUser(userData);
        persistMemberActivationState(syncMemberActivationState({
          userId: userData.id,
          username: userData.username,
          arrivalKind: null,
        }));
        persistReturningSessionState(syncReturningSessionState({
          userId: userData.id,
          username: userData.username,
          arrivalKind: null,
        }));
      } catch {
        resetClientAuthState();
      } finally {
        setIsLoading(false);
      }
    };

    void bootstrap();

    return unsubscribe;
  }, [persistMemberActivationState, persistReturningSessionState, resetClientAuthState]);

  const refreshToken = useCallback(async (): Promise<boolean> => {
    try {
      const session = await bootstrapSessionData();
      if (!session.accessToken) {
        resetClientAuthState();
        return false;
      }

      const userData: User = session.user ?? await getMe();
      setUser(userData);
      persistMemberActivationState(syncMemberActivationState({
        userId: userData.id,
        username: userData.username,
        arrivalKind: null,
      }));
      persistReturningSessionState(syncReturningSessionState({
        userId: userData.id,
        username: userData.username,
        arrivalKind: null,
      }));
      return true;
    } catch (error) {
      console.error('Token refresh failed:', error);
      resetClientAuthState();
      return false;
    }
  }, [persistMemberActivationState, persistReturningSessionState, resetClientAuthState]);

  const _finaliseLogin = useCallback(async (userData: User) => {
    setUser(userData);
    persistArrivalState({
      kind: 'login',
      userId: userData.id,
      username: userData.username,
      displayName: userData.display_name,
      createdAt: Date.now(),
      inviter: userData.inviter
        ? {
            username: userData.inviter.username,
            displayName: userData.inviter.display_name,
          }
        : null,
    });
    persistMemberActivationState(syncMemberActivationState({
      userId: userData.id,
      username: userData.username,
      arrivalKind: 'login',
    }));
    persistReturningSessionState(syncReturningSessionState({
      userId: userData.id,
      username: userData.username,
      arrivalKind: 'login',
    }));
    router.push('/');
  }, [persistArrivalState, persistMemberActivationState, persistReturningSessionState, router]);

  const login = useCallback(async (username: string, password: string) => {
    const data = await apiLogin(username, password);

    if (isMFARequired(data)) {
      // Password verified — now the user must tap their security key
      setPendingMfaToken(data.mfa_session_token);
      return;
    }

    setToken(data.access_token);
    const userData: User = data.user ?? await getMe();
    await _finaliseLogin(userData);
  }, [_finaliseLogin]);

  const completeMfaLogin = useCallback(async (credential: AuthenticationResponseJSON) => {
    if (!pendingMfaToken) return;

    const tokenData: Token = await webauthnAuthComplete(pendingMfaToken, credential);
    setPendingMfaToken(null);
    setToken(tokenData.access_token);
    const userData: User = await getMe();
    await _finaliseLogin(userData);
  }, [pendingMfaToken, _finaliseLogin]);

  const cancelMfaLogin = useCallback(() => {
    setPendingMfaToken(null);
  }, []);

  const register = useCallback(async (username: string, displayName: string, email: string, password: string, inviteCode: string) => {
    resetClientAuthState();
    return await apiRegister(username, email, password, inviteCode, displayName);
  }, [resetClientAuthState]);

  const logout = useCallback(async () => {
    resetClientAuthState();
    await apiLogout();
  }, [resetClientAuthState]);

  const clearArrivalState = useCallback(() => {
    persistArrivalState(null);
  }, [persistArrivalState]);

  const markActivationSurface = useCallback((surface: ActivationSurface) => {
    setMemberActivationState((prev) => {
      if (!prev || !isMemberActivationActive(prev) || prev.visitedSurfaces.includes(surface)) {
        return prev;
      }

      return markActivationSurfaceVisited(surface);
    });
  }, []);

  const completeActivationAction = useCallback((action: ActivationAction) => {
    setMemberActivationState((prev) => {
      if (!prev || !isMemberActivationActive(prev) || prev.completedActions.includes(action)) {
        return prev;
      }

      return markActivationActionCompleted(action);
    });
  }, []);

  const dismissReturningSessionCue = useCallback(() => {
    setReturningSessionState((prev) => dismissReturningSession(prev));
  }, []);

  const saveRecentConversation = useCallback((conversation: Omit<RecentConversationState, 'lastViewedAt'>) => {
    setReturningSessionState((prev) => {
      if (!prev) {
        return prev;
      }

      return persistRecentConversation(conversation) ?? prev;
    });
  }, []);

  return (
    <AuthContext.Provider value={{ user, token, isLoading, arrivalState, memberActivationState, returningSessionState, pendingMfaToken, login, completeMfaLogin, cancelMfaLogin, register, logout, refreshToken, clearArrivalState, markActivationSurface, completeActivationAction, dismissReturningSessionCue, saveRecentConversation }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
