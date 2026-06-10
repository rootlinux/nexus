import type {
  AuthenticationResponseJSON,
  PublicKeyCredentialCreationOptionsJSON,
  PublicKeyCredentialRequestOptionsJSON,
  RegistrationResponseJSON,
} from '@simplewebauthn/browser'

import axios from 'axios';
import { getApiBaseUrl } from './env';
import { bootstrapSessionData, clearSessionState, getAccessToken, getCookieSessionHeaders, setAccessToken } from './session';
import type {
  SessionListResponse,
  EmailTokenCompletionResponse,
  FeedbackReportPayload,
  InviteStatus,
  LoginResponse,
  NeutralActionResponse,
  PendingEmailVerificationResponse,
  PushSubscriptionUpsertPayload,
  PushSubscriptionsResponse,
  PushSubscriptionRecord,
  WebAuthnCredential,
} from '../types';
import { isMFARequired } from '../types';

const API_BASE = getApiBaseUrl();
export const API_BASE_URL = `${API_BASE}/api`;

const api = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
  withCredentials: true,
});

const authBypassApi = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
  withCredentials: true,
});

function getLoginFailureMessage(status?: number) {
  if (status === 401) {
    return 'Invalid username or password.'
  }

  if (status === 429) {
    return 'Too many attempts. Please try again shortly.'
  }

  return null
}

let isRefreshing = false;
let failedQueue: Array<{
  resolve: (value: unknown) => void;
  reject: (reason?: unknown) => void;
}> = [];

const processQueue = (error: Error | null, token: string | null = null) => {
  failedQueue.forEach((prom) => {
    if (error) {
      prom.reject(error);
    } else {
      prom.resolve(token);
    }
  });
  failedQueue = [];
};

const clearTokens = () => {
  clearSessionState();
};

// Request interceptor - add token to headers
api.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Response interceptor - handle 401 with token refresh
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;

    // If error is 401 and we haven't tried to refresh yet
    if (
      error.response?.status === 401 &&
      !originalRequest._retry &&
      !String(originalRequest.url || '').includes('/api/auth/refresh') &&
      !originalRequest.headers?.['X-Skip-Auth-Refresh']
    ) {
      if (isRefreshing) {
        // If already refreshing, queue this request
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        })
          .then((token) => {
            originalRequest.headers.Authorization = `Bearer ${token}`;
            return api(originalRequest);
          })
          .catch((err) => Promise.reject(err));
      }

      originalRequest._retry = true;
      isRefreshing = true;

      try {
        const session = await bootstrapSessionData();
        if (!session.accessToken) {
          throw new Error('No refresh token available');
        }

        processQueue(null, session.accessToken);
        originalRequest.headers.Authorization = `Bearer ${session.accessToken}`;
        return api(originalRequest);
      } catch (refreshError) {
        processQueue(refreshError as Error, null);
        try {
          await authBypassApi.post('/api/auth/logout', {}, {
            headers: {
              ...getCookieSessionHeaders(),
              'X-Skip-Auth-Refresh': 'true',
            },
          });
        } catch {
          // Ignore cleanup errors
        }
        clearTokens();
        // Redirect to auth page
        if (typeof window !== 'undefined') {
          window.location.href = '/auth';
        }
        return Promise.reject(refreshError);
      } finally {
        isRefreshing = false;
      }
    }

    return Promise.reject(error);
  }
);

// Auth API functions

/**
 * Login with username/password.
 *
 * Returns:
 *  - Token (200) when login is complete (no MFA, or MFA not set up)
 *  - MFARequiredResponse (202) when the user has WebAuthn keys registered
 */
export const login = async (username: string, password: string): Promise<LoginResponse> => {
  try {
    const response = await authBypassApi.post('/api/auth/login', { username, password }, {
      headers: getCookieSessionHeaders(),
    });
    const data = response.data as LoginResponse;
    if (!isMFARequired(data)) {
      setAccessToken(data.access_token);
    }
    return data;
  } catch (error) {
    if (axios.isAxiosError(error)) {
      const message = getLoginFailureMessage(error.response?.status)
      if (message) {
        throw new Error(message)
      }

      const backendDetail =
        typeof error.response?.data?.detail === 'string'
          ? error.response.data.detail
          : null

      if (backendDetail) {
        throw new Error(backendDetail)
      }

      if (!error.response) {
        throw new Error('Unable to reach the server. Please try again.')
      }

      throw new Error('Sign in could not be completed. Please try again.')
    }

    throw error instanceof Error
      ? error
      : new Error('Sign in could not be completed. Please try again.')
  }
};

export const register = async (
  username: string,
  email: string,
  password: string,
  inviteCode: string,
  displayName?: string,
  requestKey?: string
): Promise<PendingEmailVerificationResponse> => {
  try {
    const normalizedRequestKey = typeof requestKey === 'string' ? requestKey.trim() : ''
    const headers = {
      ...getCookieSessionHeaders(),
      ...(normalizedRequestKey ? { 'X-Signup-Request-Key': normalizedRequestKey } : {}),
    }

    const response = await authBypassApi.post('/api/auth/register', {
      username,
      display_name: displayName,
      email,
      password,
      invite_code: inviteCode,
    }, {
      headers,
    });
    clearSessionState();
    return response.data as PendingEmailVerificationResponse;
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 409) {
      throw new Error('Registration is already in progress. Please wait a moment and try again.')
    }
    throw error
  }
};

export const logout = async () => {
  try {
    await authBypassApi.post('/api/auth/logout', {}, {
      headers: getCookieSessionHeaders(),
    });
  } catch {
    // Ignore logout errors
  }
  clearTokens();
  if (typeof window !== 'undefined') {
    window.location.assign('/auth');
  }
};

export const getMe = async () => {
  const response = await api.get('/api/auth/me');
  return response.data;
};

export const requestEmailVerification = async (email: string) => {
  const response = await authBypassApi.post('/api/auth/verify-email/request', { email });
  return response.data as NeutralActionResponse;
};

export const completeEmailVerification = async (token: string) => {
  const response = await authBypassApi.post('/api/auth/verify-email/complete', { token });
  return response.data as EmailTokenCompletionResponse;
};

export const listSessions = async () => {
  const response = await api.get('/api/auth/sessions');
  return response.data as SessionListResponse;
};

export const revokeSession = async (sessionId: number) => {
  const response = await api.post(`/api/auth/sessions/${sessionId}/revoke`);
  return response.data as { revoked_session_id: number };
};

export const revokeOtherSessions = async (currentPassword: string) => {
  const response = await api.post('/api/auth/sessions/revoke-others', {
    current_password: currentPassword,
  });
  return response.data as { revoked_session_count: number };
};

export const requestEmailChange = async (newEmail: string, currentPassword: string) => {
  const response = await api.post('/api/auth/email-change/request', {
    new_email: newEmail,
    current_password: currentPassword,
  });
  return response.data as NeutralActionResponse;
};

export const submitFeedbackReport = async (payload: FeedbackReportPayload, attachment?: File | null) => {
  if (!attachment) {
    const response = await api.post('/api/feedback/report', payload)
    return response.data as NeutralActionResponse
  }

  const formData = new FormData()
  Object.entries(payload).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      formData.append(key, String(value))
    }
  })
  formData.append('attachment', attachment)

  const response = await api.post('/api/feedback/report', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return response.data as NeutralActionResponse
}

export const completeEmailChange = async (token: string) => {
  const response = await authBypassApi.post('/api/auth/email-change/complete', { token }, {
    headers: getCookieSessionHeaders(),
  });
  clearSessionState();
  return response.data as EmailTokenCompletionResponse;
};

export const requestPasswordReset = async (email: string) => {
  const response = await authBypassApi.post('/api/auth/password-reset/request', { email });
  return response.data as NeutralActionResponse;
};

export const completePasswordReset = async (token: string, newPassword: string) => {
  await authBypassApi.post('/api/auth/password-reset/complete', { token, new_password: newPassword });
};

export const getFeed = async (cursor?: number | null, limit = 20) => {
  const response = await api.get('/api/posts/feed', { params: { cursor, limit } });
  return response.data;
};

export const createPost = async (data: {
  content?: string;
  media_url?: string | null;
  parent_id?: number | null;
  repost_of_id?: number | null;
  quoted_post_id?: number | null;
}) => {
  const response = await api.post('/api/posts', data);
  return response.data;
};

export const uploadPostImage = async (file: File) => {
  const formData = new FormData();
  formData.append('file', file);
  try {
    const response = await api.post('/api/posts/upload-image', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return response.data as { url: string };
  } catch (error) {
    if (
      typeof error === 'object' &&
      error !== null &&
      'response' in error &&
      typeof (error as { response?: unknown }).response === 'object' &&
      (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail &&
      typeof (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail === 'string'
    ) {
      throw new Error((error as { response?: { data?: { detail?: string } } }).response?.data?.detail || 'Failed to upload image');
    }
    throw error;
  }
};

export const likePost = async (postId: number) => {
  const response = await api.post(`/api/posts/${postId}/like`);
  return response.data;
};

export const unlikePost = async (postId: number) => {
  const response = await api.post(`/api/posts/${postId}/like`);
  return response.data;
};

export const getProfile = async (username: string) => {
  const response = await api.get(`/api/users/${username}`);
  return response.data;
};

export const getUserPosts = async (username: string, skip = 0, limit = 20) => {
  const response = await api.get(`/api/users/${username}/posts`, { params: { skip, limit } });
  return response.data;
};

export const getUserTimeline = async (
  username: string,
  view: 'posts' | 'replies' | 'media' | 'likes' | 'reposts',
  skip = 0,
  limit = 20
) => {
  const response = await api.get(`/api/users/${username}/posts`, { params: { skip, limit, view } });
  return response.data;
};

export const toggleFollow = async (username: string) => {
  const response = await api.post(`/api/users/${username}/follow`);
  return response.data;
};

export const toggleBlock = async (username: string) => {
  const response = await api.post(`/api/users/${username}/block`);
  return response.data as { is_blocked: boolean };
};

export const updateMyProfile = async (data: {
  display_name?: string | null
  bio?: string | null
  location?: string | null
  website?: string | null
}) => {
  const response = await api.patch('/api/users/me/profile', data);
  return response.data;
};

export const uploadMyAvatar = async (file: File) => {
  const formData = new FormData();
  formData.append('file', file);
  const response = await api.post('/api/users/me/avatar', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data;
};

export const uploadMyCover = async (file: File) => {
  const formData = new FormData();
  formData.append('file', file);
  const response = await api.post('/api/users/me/cover', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data;
};

export const changeMyPassword = async (currentPassword: string, newPassword: string) => {
  await api.post('/api/users/me/password', {
    current_password: currentPassword,
    new_password: newPassword,
  });
  clearSessionState();
};

export const getFollowers = async (username: string, skip = 0, limit = 20) => {
  const response = await api.get(`/api/users/${username}/followers`, { params: { skip, limit } });
  return response.data;
};

export const getFollowing = async (username: string, skip = 0, limit = 20) => {
  const response = await api.get(`/api/users/${username}/following`, { params: { skip, limit } });
  return response.data;
};

export const getSuggestions = async (limit = 5) => {
  const response = await api.get('/api/users/suggestions', { params: { limit } });
  return response.data;
};

export const getExploreFeed = async (mode: 'for_you' | 'trending', limit = 12) => {
  const response = await api.get('/api/posts/explore', { params: { mode, limit } });
  return response.data;
};

export const getTrendingPosts = async (limit = 5) => {
  const response = await api.get('/api/posts/trending', { params: { limit } });
  return response.data;
};

// Discover page API functions
export interface DiscoverUser {
  id: number;
  username: string;
  display_name: string | null;
  avatar_url: string | null;
  mutual_count: number;
  score: number;
}

export interface DiscoverUsersResponse {
  users: DiscoverUser[];
}

export const getDiscoverUsers = async (limit = 12): Promise<DiscoverUsersResponse> => {
  try {
    const response = await api.get('/api/discover/users', { params: { limit } });
    return response.data as DiscoverUsersResponse;
  } catch {
    // Fall back to existing suggestions endpoint until /api/discover/users is deployed
    const response = await api.get('/api/users/suggestions', { params: { limit } });
    const data = response.data as { users: Array<{ id: number; username: string; display_name?: string | null; avatar_url?: string | null; score: number; reason: string }> };
    return {
      users: (data.users || []).map((u) => ({
        id: u.id,
        username: u.username,
        display_name: u.display_name ?? null,
        avatar_url: u.avatar_url ?? null,
        mutual_count: 0,
        score: u.score,
      })),
    };
  }
};

export const getDiscoverPosts = async (limit = 15): Promise<import('../types').DiscoveryFeedResponse> => {
  try {
    const response = await api.get('/api/discover/posts', { params: { limit } });
    const data = response.data;
    // Backend may return DiscoverPostsResponse {posts, total, ...} instead of DiscoveryFeedResponse {items, mode, ...}
    // Fall through to the explore endpoint if the expected shape is missing
    if (!data || !Array.isArray(data.items)) {
      throw new Error('unexpected_shape');
    }
    return data as import('../types').DiscoveryFeedResponse;
  } catch {
    const response = await api.get('/api/posts/explore', { params: { mode: 'trending', limit } });
    return response.data as import('../types').DiscoveryFeedResponse;
  }
};

export const repostPost = async (postId: number) => {
  const response = await api.post(`/api/posts/${postId}/repost`);
  return response.data;
};

export const toggleBookmarkPost = async (postId: number) => {
  const response = await api.post(`/api/posts/${postId}/bookmark`);
  return response.data;
};

function getDeletePostFailureMessage(status?: number) {
  if (status === 401) {
    return 'Your session expired. Sign in again and try once more.'
  }

  if (status === 403) {
    return 'You can only delete your own posts.'
  }

  if (status === 404) {
    return 'This post is no longer available.'
  }

  return 'Could not delete this post right now.'
}

export const deletePostById = async (postId: number) => {
  try {
    await api.delete(`/api/posts/${postId}`)
  } catch (error) {
    if (axios.isAxiosError(error)) {
      throw new Error(getDeletePostFailureMessage(error.response?.status))
    }

    throw new Error(getDeletePostFailureMessage())
  }
};

export const adminDeletePost = async (postId: number, reason?: string) => {
  try {
    await api.post(`/api/admin/posts/${postId}/delete`, { reason: reason || 'Platform kurallarını ihlal ettiği gerekçesiyle kaldırıldı.' })
  } catch (error) {
    if (axios.isAxiosError(error)) {
      if (error.response?.status === 404) {
        throw new Error('Post not found.')
      }
      throw new Error(error.response?.data?.detail || 'Could not delete this post.')
    }
    throw new Error('Could not delete this post.')
  }
};

export const reportPost = async (postId: number, reason?: string) => {
  try {
    await api.post(`/api/posts/${postId}/report`, { reason })
  } catch (error) {
    if (axios.isAxiosError(error)) {
      if (error.response?.status === 404) {
        throw new Error('Post not found.')
      }
      if (error.response?.status === 403) {
        throw new Error('You cannot report your own post.')
      }
      throw new Error(error.response?.data?.detail || 'Could not submit report.')
    }
    throw new Error('Could not submit report.')
  }
};

export const reportUser = async (username: string, reason?: string) => {
  try {
    await api.post(`/api/users/${username}/report`, { reason })
  } catch (error) {
    if (axios.isAxiosError(error)) {
      if (error.response?.status === 404) {
        throw new Error('User not found.')
      }
      if (error.response?.status === 403) {
        throw new Error('You cannot report yourself.')
      }
      throw new Error(error.response?.data?.detail || 'Could not submit report.')
    }
    throw new Error('Could not submit report.')
  }
};

export interface AuditLogEntry {
  id: number
  actor_user_id: string
  actor_role: string | null
  action: string
  target_type: string
  target_id: string
  reason: string | null
  request_id: string | null
  ip_address: string | null
  session_id: string | null
  success: boolean
  created_at: string
}

export const getAuditLogs = async (skip = 0, limit = 50): Promise<{ items: AuditLogEntry[]; total: number }> => {
  const response = await api.get('/api/admin/audit-logs', { params: { skip, limit } })
  return response.data
};

export const getBookmarks = async (cursor?: number | null, limit = 20) => {
  const response = await api.get('/api/bookmarks', { params: { cursor, limit } });
  return response.data;
};

export const searchUsers = async (query: string) => {
  const response = await api.get('/api/users/search', { params: { q: query } });
  return response.data;
};

export const searchEverything = async (query: string, type: 'top' | 'latest' | 'people' = 'top') => {
  const response = await api.get('/api/search', { params: { q: query, type } });
  return response.data;
};

export const getPost = async (postId: number) => {
  const response = await api.get(`/api/posts/${postId}`);
  return response.data;
};

export const getPostReplies = async (
  postId: number,
  page = 1,
  limit = 20,
  order: 'asc' | 'desc' = 'desc'
) => {
  const response = await api.get(`/api/posts/${postId}/replies`, { params: { page, limit, order } });
  return response.data;
};

export const createReply = async (postId: number, content: string) => {
  const response = await api.post(`/api/posts/${postId}/replies`, { content });
  return response.data;
};

export const getNotifications = async (
  tab: 'all' | 'mentions' = 'all',
  cursor?: number | null,
  limit = 20
) => {
  const response = await api.get('/api/notifications', { params: { tab, cursor, limit } });
  return response.data;
};

export const markNotificationRead = async (notificationId: number) => {
  const response = await api.post(`/api/notifications/${notificationId}/read`);
  return response.data;
};

export const markAllNotificationsRead = async () => {
  const response = await api.post('/api/notifications/read-all');
  return response.data;
};

export const getNotificationSettings = async () => {
  const response = await api.get('/api/notifications/settings');
  return response.data;
};

export const updateNotificationSettings = async (data: Record<string, boolean>) => {
  const response = await api.patch('/api/notifications/settings', data);
  return response.data;
};

export const getPushSubscriptions = async () => {
  const response = await api.get('/api/notifications/push-subscriptions');
  return response.data as PushSubscriptionsResponse;
};

export const upsertPushSubscription = async (data: PushSubscriptionUpsertPayload) => {
  const response = await api.put('/api/notifications/push-subscriptions', data);
  return response.data as { subscription: PushSubscriptionRecord };
};

export const deletePushSubscription = async (endpoint: string) => {
  const response = await api.delete('/api/notifications/push-subscriptions', {
    data: { endpoint },
  });
  return response.data as { deleted_count: number };
};

export const testPushNotification = async (payload?: { title?: string; body?: string; url?: string }) => {
  const response = await api.post('/api/notifications/push-subscriptions/test-send', payload || {});
  return response.data as { sent_count: number; failed_count: number; total_active: number };
};

export const getMeWithToken = async (token: string) => {
  const response = await api.get('/api/auth/me', {
    headers: { Authorization: `Bearer ${token}` }
  });
  return response.data;
};

export const authFetch = async (input: string, init: RequestInit = {}): Promise<Response> => {
  const headers = new Headers(init.headers || {});
  const token = getAccessToken();

  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const response = await fetch(input, {
    ...init,
    credentials: 'include',
    headers,
  });

  if (response.status !== 401) {
    return response;
  }

  const session = await bootstrapSessionData();
  if (!session.accessToken) {
    return response;
  }

  const retryHeaders = new Headers(init.headers || {});
  retryHeaders.set('Authorization', `Bearer ${session.accessToken}`);

  return fetch(input, {
    ...init,
    credentials: 'include',
    headers: retryHeaders,
  });
};

// Invite API functions
export interface InviteValidateResponse {
  valid: boolean;
  message?: string;
  expires_at?: string;
}

export interface InviteCreateRequest {
  internal_note?: string | null;
  assigned_to_username?: string | null;
  expires_days?: number | null;
}

export interface InviteCode {
  id: number;
  code: string;
  created_by_id: number;
  generated_by_user_id?: number | null;
  campaign_id?: number | null;
  internal_note: string | null;
  assigned_to_user_id: number | null;
  assigned_to_username: string | null;
  current_uses: number;
  used_by_user_id: number | null;
  used_at: string | null;
  expires_at: string | null;
  is_active: boolean;
  created_at: string;
}

export interface MyInvite {
  id: number;
  code: string;
  status: InviteStatus;
  created_at: string;
  expires_at?: string | null;
  used_at?: string | null;
  invited_username?: string | null;
  remaining_uses: number;
  campaign_id?: number | null;
  campaign_slug?: string | null;
  campaign_name?: string | null;
}

export interface InviteCampaign {
  id: number;
  name: string;
  slug: string;
  public_label?: string | null;
  description?: string | null;
  is_active: boolean;
  active_from?: string | null;
  expires_at?: string | null;
  max_uses_total?: number | null;
  per_user_invite_allowance: number;
  generated_count: number;
  consumed_count: number;
  remaining_generation_capacity?: number | null;
  user_generated_count?: number | null;
  user_remaining_allowance?: number | null;
}

export interface CampaignInviteGenerateResponse {
  invite_id: number;
  code: string;
  campaign_id: number;
  campaign_slug: string;
  expires_at?: string | null;
  user_generated_count: number;
  user_remaining_allowance: number;
}

export interface AdminInviteCampaign extends InviteCampaign {
  internal_note?: string | null;
  created_by_user_id?: number | null;
  updated_by_user_id?: number | null;
  created_at: string;
  updated_at: string;
}

export interface AdminInviteCampaignDetail extends AdminInviteCampaign {
  invites: Array<{
    id: number;
    code: string;
    generated_by_user_id?: number | null;
    generated_by_username?: string | null;
    used_by_user_id?: number | null;
    used_by_username?: string | null;
    created_at: string;
    used_at?: string | null;
    expires_at?: string | null;
    is_active: boolean;
  }>;
  registrations: Array<{
    id: number;
    username: string;
    display_name?: string | null;
    created_at: string;
    invited_by_user_id?: number | null;
  }>;
}

export interface AdminInviteCampaignPayload {
  name: string;
  slug: string;
  internal_note?: string | null;
  public_label?: string | null;
  description?: string | null;
  is_active: boolean;
  active_from?: string | null;
  expires_at?: string | null;
  max_uses_total?: number | null;
  per_user_invite_allowance: number;
}

export const validateInvite = async (code: string): Promise<InviteValidateResponse> => {
  const response = await api.post('/api/invite/validate', { code });
  return response.data;
};

export const createInvite = async (data: InviteCreateRequest): Promise<InviteCode> => {
  const response = await api.post('/api/invite/create', data);
  return response.data;
};

export const getMyInvites = async (): Promise<{ invites: MyInvite[] }> => {
  const response = await api.get('/api/invites/me');
  return response.data;
};

export const getInviteCampaigns = async (): Promise<{ items: InviteCampaign[] }> => {
  const response = await api.get('/api/invites/campaigns');
  return response.data;
};

export const generateCampaignInvite = async (campaignId: number): Promise<CampaignInviteGenerateResponse> => {
  const response = await api.post(`/api/invites/campaigns/${campaignId}/generate`);
  return response.data;
};

export const listAdminInviteCampaigns = async (): Promise<AdminInviteCampaign[]> => {
  const response = await api.get('/api/admin/invite-campaigns');
  return response.data;
};

export const getAdminInviteCampaign = async (campaignId: number): Promise<AdminInviteCampaignDetail> => {
  const response = await api.get(`/api/admin/invite-campaigns/${campaignId}`);
  return response.data;
};

export const createAdminInviteCampaign = async (payload: AdminInviteCampaignPayload): Promise<AdminInviteCampaign> => {
  const response = await api.post('/api/admin/invite-campaigns', payload);
  return response.data;
};

export const updateAdminInviteCampaign = async (
  campaignId: number,
  payload: Partial<AdminInviteCampaignPayload>,
): Promise<AdminInviteCampaign> => {
  const response = await api.patch(`/api/admin/invite-campaigns/${campaignId}`, payload);
  return response.data;
};

// DM API functions
export interface Message {
  id: number;
  content: string;
  created_at: string;
  sender?: {
    id: number;
    username: string;
    display_name?: string | null;
    avatar_url?: string | null;
  };
}

export interface Conversation {
  user: {
    id: number;
    username: string;
    display_name?: string | null;
    avatar_url: string | null;
  };
  last_message: string | null;
  unread_count: number;
  updated_at?: string | null;
}

export const getConversations = async (): Promise<Conversation[]> => {
  const response = await api.get('/api/dm/conversations');
  return response.data?.conversations || response.data || [];
};

export const getMessages = async (username: string, page = 1, limit = 50): Promise<{ messages: Message[]; total: number; has_more: boolean }> => {
  const response = await api.get(`/api/dm/conversations/${username}/messages`, { params: { page, limit } });
  return response.data;
};

export const getMessagesDirect = async (username: string, page = 1, limit = 50): Promise<Message[]> => {
  const response = await api.get(`/api/dm/conversations/${username}/messages`, { params: { page, limit } });
  return response.data.messages;
};

export const sendMessage = async (username: string, content: string): Promise<Message> => {
  const response = await api.post(`/api/dm/conversations/${username}`, { content });
  return response.data;
};

// Export api instance for direct use (default export for backward compatibility)
export { api };
export default api;

// ---------------------------------------------------------------------------
// WebAuthn / FIDO2 API functions
// ---------------------------------------------------------------------------

/** Begin registration – returns options to pass to startRegistration() */
export const webauthnRegisterBegin = async (
  name: string,
  currentPassword: string,
): Promise<PublicKeyCredentialCreationOptionsJSON> => {
  const response = await api.post('/api/webauthn/register/begin', {
    name,
    current_password: currentPassword,
  });
  return response.data.options as PublicKeyCredentialCreationOptionsJSON;
};

/** Complete registration – send attestation response back to server */
export const webauthnRegisterComplete = async (
  credential: RegistrationResponseJSON,
  name: string,
): Promise<WebAuthnCredential> => {
  const response = await api.post('/api/webauthn/register/complete', { credential, name });
  return response.data as WebAuthnCredential;
};

/** Begin authentication – requires the short-lived mfa_session_token */
export const webauthnAuthBegin = async (
  mfaSessionToken: string,
): Promise<PublicKeyCredentialRequestOptionsJSON> => {
  const response = await authBypassApi.post('/api/webauthn/auth/begin', {
    mfa_session_token: mfaSessionToken,
  });
  return response.data.options as PublicKeyCredentialRequestOptionsJSON;
};

/** Complete authentication – verifies assertion and returns a full Token */
export const webauthnAuthComplete = async (
  mfaSessionToken: string,
  credential: AuthenticationResponseJSON,
): Promise<import('../types').Token> => {
  const response = await authBypassApi.post(
    '/api/webauthn/auth/complete',
    { mfa_session_token: mfaSessionToken, credential },
    { headers: getCookieSessionHeaders() },
  );
  const data = response.data as import('../types').Token;
  setAccessToken(data.access_token);
  return data;
};

/** List the current user's registered security keys */
export const listWebAuthnCredentials = async (): Promise<WebAuthnCredential[]> => {
  const response = await api.get('/api/webauthn/credentials');
  return response.data as WebAuthnCredential[];
};

/** Delete a registered security key by its DB id */
export const deleteWebAuthnCredential = async (
  credentialId: number | string,
  currentPassword: string
): Promise<void> => {
  await api.delete(`/api/webauthn/credentials/${credentialId}`, {
    data: { current_password: currentPassword },
  });
};

// =============================================================================
// WAITLIST API
// =============================================================================

export interface WaitlistApplicationPayload {
  full_name: string;
  contact: string;
  preferred_username?: string;
  reason: string;
  referral_source?: string;
  social_url?: string;
}

export interface WaitlistApplicationResponse {
  id: number;
  full_name: string;
  contact: string;
  preferred_username: string | null;
  reason: string;
  referral_source: string | null;
  social_url: string | null;
  status: string;
  admin_notes: string | null;
  invite_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface WaitlistApplicationListResponse {
  applications: WaitlistApplicationResponse[];
  total: number;
  limit: number;
  offset: number;
}

export interface WaitlistInviteResponse {
  id: number;
  code: string;
  internal_note: string | null;
  created_by_id: number;
  expires_at: string | null;
  is_active: boolean;
  created_at: string;
}

export const submitWaitlistApplication = async (
  payload: WaitlistApplicationPayload
): Promise<WaitlistApplicationResponse> => {
  const response = await authBypassApi.post('/api/waitlist', payload);
  return response.data as WaitlistApplicationResponse;
};

export const listWaitlistApplications = async (params?: {
  status?: string;
  search?: string;
  page?: number;
  limit?: number;
}): Promise<WaitlistApplicationListResponse> => {
  const searchParams = new URLSearchParams();
  if (params?.status) searchParams.set('status', params.status);
  if (params?.search) searchParams.set('search', params.search);
  if (params?.page) searchParams.set('page', String(params.page));
  if (params?.limit) searchParams.set('limit', String(params.limit));
  const response = await api.get(`/api/admin/waitlist?${searchParams.toString()}`);
  return response.data as WaitlistApplicationListResponse;
};

export const updateWaitlistApplication = async (
  applicationId: number,
  payload: { status?: string; admin_notes?: string }
): Promise<WaitlistApplicationResponse> => {
  const response = await api.patch(`/api/admin/waitlist/${applicationId}`, payload);
  return response.data as WaitlistApplicationResponse;
};

export const createWaitlistInvite = async (
  applicationId: number
): Promise<WaitlistInviteResponse> => {
  const response = await api.post(`/api/admin/waitlist/${applicationId}/invite`);
  return response.data as WaitlistInviteResponse;
};

export const getWaitlistInvite = async (
  applicationId: number
): Promise<WaitlistInviteResponse> => {
  const response = await api.get(`/api/admin/waitlist/${applicationId}/invite`);
  return response.data as WaitlistInviteResponse;
};
