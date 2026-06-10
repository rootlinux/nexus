export type InviteStatus = 'active' | 'used' | 'expired' | 'inactive';

// User types
export interface User {
  id: number;
  username: string;
  display_name?: string | null;
  email: string;
  email_verified?: boolean;
  email_verified_at?: string | null;
  avatar_url: string | null;
  cover_url?: string | null;
  bio: string | null;
  location?: string | null;
  website?: string | null;
  created_at: string;
  is_active: boolean;
  is_admin: boolean;
  admin_role?: 'super_admin' | 'invite_admin' | 'moderator' | 'support_admin' | null;
  status?: 'active' | 'frozen' | 'suspended' | 'banned';
  status_reason?: string | null;
  status_changed_at?: string | null;
  status_changed_by_user_id?: number | null;
  // Profile fields
  followers_count?: number;
  following_count?: number;
  posts_count?: number;
  replies_count?: number;
  reposts_count?: number;
  is_following?: boolean;
  is_blocked_by_me?: boolean;
  has_blocked_me?: boolean;
  is_access_limited?: boolean;
  inviter?: {
    id: number;
    username: string;
    display_name?: string | null;
    avatar_url?: string | null;
  } | null;
  assigned_invite?: {
    id: number;
    code: string;
    internal_note?: string | null;
    status: InviteStatus;
    expires_at?: string | null;
    used_at?: string | null;
    invited_user_id?: number | null;
    invited_username?: string | null;
  } | null;
}

export interface UserCreate {
  username: string;
  display_name: string;
  email: string;
  password: string;
  invite_code: string;
}

export interface UserLogin {
  username: string;
  password: string;
}

// Auth types
export interface Token {
  access_token: string;
  refresh_token?: string | null;
  token_type: string;
  user?: User | null;
}

export interface PendingEmailVerificationResponse {
  status: 'pending_email_verification';
  message: string;
  email: string;
  masked_email: string;
}

export interface NeutralActionResponse {
  message: string;
}

export interface FeedbackReportPayload {
  title: string;
  description: string;
  current_path?: string;
  username?: string;
  device_info?: string;
  contact_email?: string;
  current_url?: string;
  user_agent?: string;
  standalone_mode?: boolean;
  occurred_at?: string;
  app_version?: string;
}

// WebAuthn / FIDO2 types
export interface MFARequiredResponse {
  mfa_required: true;
  mfa_session_token: string;
}

export interface WebAuthnCredential {
  id: number;
  name: string;
  created_at: string;
  last_used_at: string | null;
}

export type LoginResponse = Token | MFARequiredResponse;

export function isMFARequired(data: LoginResponse): data is MFARequiredResponse {
  return (data as MFARequiredResponse).mfa_required === true;
}

export interface EmailTokenCompletionResponse {
  status: 'verified' | 'already_verified';
  message: string;
}

export interface SessionRead {
  id: number;
  is_current: boolean;
  created_at: string;
  last_used_at?: string | null;
  expires_at: string;
  device_label?: string | null;
}

export interface SessionListResponse {
  sessions: SessionRead[];
}

// Post types
export interface PostBase {
  content: string;
  media_url?: string;
}

export interface PostCreate extends PostBase {
  parent_id?: number;
  repost_of_id?: number;
  quoted_post_id?: number;
}

export interface Post extends PostBase {
  id: number;
  user_id: number;
  parent_id: number | null;
  repost_of_id: number | null;
  quoted_post_id: number | null;
  is_repost: boolean;
  is_quote: boolean;
  likes_count: number;
  replies_count: number;
  reposts_count: number;
  created_at: string;
  is_liked_by_me: boolean;
  is_bookmarked: boolean;
  is_bookmarked_by_me?: boolean;
  has_reposted?: boolean;
  moderation_status?: 'visible' | 'hidden' | 'deleted';
  moderation_reason?: string | null;
  moderated_at?: string | null;
  moderated_by_user_id?: number | null;
  feed_reason?: string | null;
  author: User;
  original_post: Post | null;
  parent_post: Post | null;
  quoted_post: Post | null;
  quoted_post_unavailable?: boolean;
  quoted_post_placeholder?: string | null;
}

export interface PostList {
  posts: Post[];
  total: number;
  page: number;
  limit: number;
  has_more: boolean;
}

export interface LikeResponse {
  liked: boolean;
  likes_count: number;
}

export interface RepostResponse {
  reposted: boolean;
  reposts_count: number;
}

export interface FeedResponse {
  posts: Post[];
  next_cursor: number | null;
  has_more: boolean;
}

export interface DiscoveryAuthorSummary {
  id: number;
  username: string;
  display_name?: string | null;
  avatar_url?: string | null;
}

export interface DiscoveryEngagement {
  likes: number;
  replies: number;
  reposts: number;
}

export interface DiscoveryPostEntry {
  rank: number;
  score: number;
  post_id: number;
  created_at: string;
  author: DiscoveryAuthorSummary;
  content_preview: string;
  has_media: boolean;
  media_url?: string | null;
  engagement: DiscoveryEngagement;
  category_label?: string | null;
  discovery_reason?: string | null;
  post: Post;
}

export interface DiscoveryFeedResponse {
  mode: 'for_you' | 'trending';
  window_hours: number;
  items: DiscoveryPostEntry[];
}

export interface Notification {
  id: number;
  notification_type: 'like' | 'repost' | 'quote' | 'follow' | 'reply' | 'mention';
  created_at: string;
  read_at: string | null;
  is_unread: boolean;
  actor: {
    id: number;
    username: string;
    display_name?: string | null;
    avatar_url?: string | null;
  };
  post: {
    id: number | null;
    content_snippet?: string | null;
    author_username?: string | null;
    author_display_name?: string | null;
    is_quote: boolean;
    is_reply: boolean;
    is_available: boolean;
    unavailable_reason?: string | null;
  } | null;
  source_post: {
    id: number | null;
    content_snippet?: string | null;
    author_username?: string | null;
    author_display_name?: string | null;
    is_quote: boolean;
    is_reply: boolean;
    is_available: boolean;
    unavailable_reason?: string | null;
  } | null;
}

export interface NotificationListResponse {
  notifications: Notification[];
  total: number;
  next_cursor: number | null;
  has_more: boolean;
}

export interface NotificationSettings {
  push_likes: boolean;
  push_replies: boolean;
  push_reposts: boolean;
  push_mentions: boolean;
  push_follows: boolean;
  email_likes: boolean;
  email_replies: boolean;
  email_reposts: boolean;
  email_mentions: boolean;
  email_follows: boolean;
}

export interface PushSubscriptionRecord {
  id: number;
  endpoint: string;
  p256dh: string;
  user_agent?: string | null;
  last_seen_at: string;
  last_success_at?: string | null;
  last_failure_at?: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface PushSubscriptionsResponse {
  subscriptions: PushSubscriptionRecord[];
  push_configured: boolean;
  vapid_public_key?: string | null;
}

export interface PushSubscriptionUpsertPayload {
  endpoint: string;
  keys: {
    p256dh: string;
    auth: string;
  };
  user_agent?: string | null;
}

export interface SuggestedUser extends User {
  score: number;
  reason: string;
}

export interface SuggestionsList {
  users: SuggestedUser[];
}

export interface SearchUserResult {
  id: number;
  username: string;
  display_name?: string | null;
  avatar_url?: string | null;
}

export type SearchTab = 'top' | 'latest' | 'people';

export interface SearchUserProfile {
  id: number;
  username: string;
  display_name?: string | null;
  avatar_url?: string | null;
  bio?: string | null;
  created_at: string;
  is_following?: boolean;
  followers_count?: number;
  following_count?: number;
  posts_count?: number;
  replies_count?: number;
  reposts_count?: number;
}

export interface SearchResponse {
  query: string;
  type: SearchTab;
  posts: Post[];
  users: SearchUserProfile[];
}

// API Error
export interface ApiError {
  detail: string;
}

export interface MyInvite {
  code: string;
  status: InviteStatus;
  created_at: string;
  expires_at?: string | null;
  used_at?: string | null;
  invited_username?: string | null;
  remaining_uses: number;
}
