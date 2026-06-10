'use client'

import type { FormEvent } from 'react'
import { useCallback, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import StaffManagementPanel from '../../components/admin/StaffManagementPanel'
import WaitlistAdminPanel from '../../components/admin/WaitlistAdminPanel'
import Layout from '../../components/Layout'
import {
  API_BASE_URL,
  authFetch,
  createAdminInviteCampaign,
  createInvite,
  getAdminInviteCampaign,
  getAuditLogs,
  listAdminInviteCampaigns,
  logout,
  updateAdminInviteCampaign,
  type AdminInviteCampaign,
  type AdminInviteCampaignDetail,
  type AdminInviteCampaignPayload,
  type AuditLogEntry,
  type InviteCreateRequest,
} from '../../lib/api'
import { useAuth } from '../../contexts/AuthContext'
import { resolveMediaUrl } from '../../lib/media'
import { getProfileHref } from '../../lib/routes'
import { tokens } from '../../styles/tokens'

type UserStatus = 'active' | 'frozen' | 'suspended' | 'banned'
type InviteStatus = 'active' | 'used' | 'expired' | 'inactive'
type AdminTab = 'users' | 'invites' | 'campaigns' | 'moderation' | 'moderators' | 'waitlist' | 'audit'
type ModerationAction = 'freeze' | 'unfreeze' | 'ban' | 'unban' | 'suspend' | 'unsuspend'
type SensitiveAdminAction = 'forcePasswordReset' | 'revokeSessions'
type PostModerationAction = 'hide' | 'unhide' | 'delete'
type ModerationDetectionStatus = 'clean' | 'suspicious' | 'blocked'
type ModerationReviewStatus = 'open' | 'resolved' | 'dismissed'
type ModerationQueueAction = 'approve' | 'hide_post' | 'delete_post' | 'freeze_user' | 'suspend_user' | 'ban_user' | 'dismiss_signal'

interface UserSummary {
  id: number
  username: string
  display_name: string | null
  email: string | null
  status: UserStatus
  is_active: boolean
  is_admin: boolean
  admin_role?: string | null
  created_at: string
  banned_at: string | null
  ban_reason: string | null
  banned_by_user_id: number | null
  status_reason?: string | null
  status_changed_at?: string | null
  status_changed_by_user_id?: number | null
  invited_by_user_id?: number | null
  invited_by_username?: string | null
  invite_id_used: number | null
  invite_code_used?: string | null
}

interface UserInviteTrace {
  id: number
  code: string
  internal_note: string | null
  created_by_id: number | null
  created_by_username: string | null
  assigned_to_user_id: number | null
  assigned_to_username: string | null
  current_uses: number
  used_by_user_id: number | null
  used_at: string | null
  expires_at: string | null
  is_active: boolean
  can_reveal_code?: boolean
}

interface UserDetail extends UserSummary {
  must_change_password: boolean
  active_refresh_session_count?: number
  available_sensitive_actions?: {
    can_force_password_reset: boolean
    can_revoke_sessions: boolean
  }
  banned_by_user: {
    id: number
    username: string
  } | null
  invite_used: UserInviteTrace | null
  invite_lineage?: {
    invited_by_user_id: number | null
    invited_by_username: string | null
    invite_used_id: number | null
    invite_created_by_user_id: number | null
    invite_created_by_username: string | null
    invite_assigned_to_username: string | null
  }
  recent_posts?: AdminPost[]
  moderation_history?: ModerationHistoryEntry[]
}

interface InviteSummary {
  id: number
  code: string
  internal_note: string | null
  created_by_id: number | null
  created_by_username: string | null
  assigned_to_user_id: number | null
  assigned_to_username: string | null
  current_uses: number
  used: boolean
  used_by_user_id: number | null
  used_by_username: string | null
  used_at: string | null
  expires_at: string | null
  is_active: boolean
  created_at: string
  can_reveal_code?: boolean
}

interface InviteRegisteredUser {
  id: number
  username: string
  display_name: string | null
  email: string | null
  status: UserStatus
  created_at: string
}

interface InviteDetail extends InviteSummary {
  registered_users: InviteRegisteredUser[]
}

interface CampaignFormState {
  name: string
  slug: string
  internal_note: string
  public_label: string
  description: string
  is_active: boolean
  active_from: string
  expires_at: string
  max_uses_total: string
  per_user_invite_allowance: string
}

interface AdminPost {
  id: number
  user_id: number
  content: string
  media_url?: string | null
  created_at: string
  parent_id?: number | null
  repost_of_id?: number | null
  is_repost: boolean
  likes_count: number
  replies_count: number
  reposts_count: number
  is_liked_by_me?: boolean
  has_reposted?: boolean
  moderation_status?: 'visible' | 'hidden' | 'deleted'
  moderation_reason?: string | null
  author: {
    id?: number
    username: string
    display_name?: string | null
  }
  original_post?: AdminPost | null
}

interface ModerationHistoryEntry {
  id: number
  action: string
  target_type?: string | null
  target_id?: string | null
  reason?: string | null
  success: boolean
  created_at: string
}

interface AdminSearchResults {
  users: UserSummary[]
  invites: InviteSummary[]
  posts: Array<{
    id: number
    content_preview: string
    created_at: string
    author_username: string | null
    is_repost: boolean
    repost_of_id: number | null
    parent_id: number | null
  }>
}

interface PostModerationDetail {
  post: AdminPost
  author: {
    id: number
    username: string
    display_name: string | null
  } | null
  parent_post: AdminPost | null
  original_post: AdminPost | null
  recent_replies: AdminPost[]
  recent_reposts: AdminPost[]
  moderation_history: ModerationHistoryEntry[]
}

interface ModerationActorSummary {
  id: number
  username: string
  display_name: string | null
  status: UserStatus
}

interface ModerationQueueItem {
  id: number
  user_id: number
  post_id: number | null
  dm_message_id: number | null
  surface_type: string
  detection_status: ModerationDetectionStatus
  review_status: ModerationReviewStatus
  reason_codes: string[]
  reason_summary: string
  risk_score: number
  content_preview: string | null
  media_url: string | null
  created_at: string
  resolved_at: string | null
  resolved_by_user_id: number | null
  resolution_action: string | null
  resolution_note: string | null
  is_media_signal?: boolean
  has_media_preview?: boolean
  actor_user: ModerationActorSummary | null
}

interface ModerationQueueDetail extends ModerationQueueItem {
  media_signal_counts?: {
    window_days: number
    recent_suspicious_media_signals: number
    recent_blocked_media_signals: number
  }
  media_preview_url?: string | null
  resolved_by_user: { id: number; username: string } | null
  target_post: AdminPost | null
  target_dm_message: {
    id: number
    content: string
    created_at: string
    sender: { id: number; username: string } | null
    receiver: { id: number; username: string } | null
  } | null
  available_actions: ModerationQueueAction[]
  audit_history: ModerationHistoryEntry[]
}

interface ModerationDashboard {
  open_suspicious_count: number
  blocked_items_count: number
  newest_unresolved_items: ModerationQueueItem[]
}

interface AdminCapabilityState {
  can_read_users: boolean
  can_manage_users: boolean
  can_suspend_users: boolean
  can_ban_users: boolean
  can_read_invites: boolean
  can_create_invites: boolean
  can_assign_invites: boolean
  can_reveal_invite_codes: boolean
  can_manage_campaigns: boolean
  can_view_moderation_queue: boolean
  can_moderate_posts: boolean
  can_manage_moderators: boolean
  can_read_waitlist: boolean
  can_manage_waitlist: boolean
  can_read_audit_log: boolean
}

interface AdminSessionState {
  user_id: number
  role: 'super_admin' | 'admin' | 'moderator'
  permissions: {
    can_create_invites: boolean
    invite_quota_monthly: number | null
    can_view_moderation_queue: boolean
    can_moderate_posts: boolean
    can_manage_invites: boolean
    can_manage_users: boolean
    can_suspend_users: boolean
    can_ban_users: boolean
    can_manage_moderators: boolean
    can_reset_passwords: boolean
    can_revoke_sessions: boolean
    can_create_wave_campaigns: boolean
    can_read_waitlist: boolean
    can_manage_waitlist: boolean
  }
  capabilities: AdminCapabilityState
}

interface ConfirmState {
  action: ModerationAction | SensitiveAdminAction
  user: UserSummary
}

interface SensitiveActionResult {
  kind: SensitiveAdminAction
  token?: string
  expiresAt?: string
  username: string
}

const PAGE_SIZE = 50

const normalizeErrorMessage = (error: unknown): string => {
  if (typeof error === 'string') return error

  if (error && typeof error === 'object') {
    const errorRecord = error as {
      response?: { data?: { detail?: unknown; message?: unknown } }
      detail?: unknown
      message?: unknown
    }

    if (errorRecord.response?.data?.detail) return normalizeErrorMessage(errorRecord.response.data.detail)
    if (errorRecord.response?.data?.message) return normalizeErrorMessage(errorRecord.response.data.message)
    if (errorRecord.detail) return normalizeErrorMessage(errorRecord.detail)
    if (errorRecord.message) return normalizeErrorMessage(errorRecord.message)
  }

  if (error instanceof Error) return error.message

  return 'Failed to create invite'
}

export default function AdminPage() {
  const router = useRouter()
  const { token, user, isLoading: isAuthLoading } = useAuth()

  const [isPageLoading, setIsPageLoading] = useState(true)
  const [isAuthorized, setIsAuthorized] = useState(false)
  const [adminSession, setAdminSession] = useState<AdminSessionState | null>(null)
  const [adminSessionError, setAdminSessionError] = useState('')
  const [activeTab, setActiveTab] = useState<AdminTab>('users')

  const [successMessage, setSuccessMessage] = useState('')
  const [actionError, setActionError] = useState('')
  const [confirmState, setConfirmState] = useState<ConfirmState | null>(null)
  const [sensitiveActionResult, setSensitiveActionResult] = useState<SensitiveActionResult | null>(null)
  const [actionReason, setActionReason] = useState('')
  const [isSubmittingAction, setIsSubmittingAction] = useState(false)
  const [globalSearch, setGlobalSearch] = useState('')
  const [globalSearchResults, setGlobalSearchResults] = useState<AdminSearchResults>({ users: [], invites: [], posts: [] })
  const [isSearchingGlobal, setIsSearchingGlobal] = useState(false)
  const [globalSearchError, setGlobalSearchError] = useState('')

  const [selectedPostId, setSelectedPostId] = useState<number | null>(null)
  const [selectedPost, setSelectedPost] = useState<PostModerationDetail | null>(null)
  const [isLoadingPostDetail, setIsLoadingPostDetail] = useState(false)
  const [postDetailError, setPostDetailError] = useState('')
  const [postModerationReason, setPostModerationReason] = useState('')
  const [isSubmittingPostAction, setIsSubmittingPostAction] = useState(false)

  const [users, setUsers] = useState<UserSummary[]>([])
  const [isLoadingUsers, setIsLoadingUsers] = useState(false)
  const [usersError, setUsersError] = useState('')
  const [userSearch, setUserSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | UserStatus>('all')
  const [userTotalCount, setUserTotalCount] = useState(0)
  const [userPage, setUserPage] = useState(0)
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null)
  const [selectedUser, setSelectedUser] = useState<UserDetail | null>(null)
  const [isLoadingUserDetail, setIsLoadingUserDetail] = useState(false)
  const [userDetailError, setUserDetailError] = useState('')

  const [invites, setInvites] = useState<InviteSummary[]>([])
  const [isLoadingInvites, setIsLoadingInvites] = useState(false)
  const [invitesError, setInvitesError] = useState('')
  const [inviteSearch, setInviteSearch] = useState('')
  const [inviteTotalCount, setInviteTotalCount] = useState(0)
  const [invitePage, setInvitePage] = useState(0)
  const [selectedInviteId, setSelectedInviteId] = useState<number | null>(null)
  const [selectedInvite, setSelectedInvite] = useState<InviteDetail | null>(null)
  const [isLoadingInviteDetail, setIsLoadingInviteDetail] = useState(false)
  const [inviteDetailError, setInviteDetailError] = useState('')
  const [revealedInviteCode, setRevealedInviteCode] = useState<string | null>(null)
  const [isRevealingInviteCode, setIsRevealingInviteCode] = useState(false)
  const [inviteCopyFeedback, setInviteCopyFeedback] = useState('')
  const [campaigns, setCampaigns] = useState<AdminInviteCampaign[]>([])
  const [isLoadingCampaigns, setIsLoadingCampaigns] = useState(false)
  const [campaignsError, setCampaignsError] = useState('')
  const [selectedCampaignId, setSelectedCampaignId] = useState<number | null>(null)
  const [selectedCampaign, setSelectedCampaign] = useState<AdminInviteCampaignDetail | null>(null)
  const [isLoadingCampaignDetail, setIsLoadingCampaignDetail] = useState(false)
  const [campaignDetailError, setCampaignDetailError] = useState('')
  const [isSubmittingCampaign, setIsSubmittingCampaign] = useState(false)
  const [campaignFormError, setCampaignFormError] = useState('')
  const [campaignForm, setCampaignForm] = useState<CampaignFormState>({
    name: '',
    slug: '',
    internal_note: '',
    public_label: '',
    description: '',
    is_active: false,
    active_from: '',
    expires_at: '',
    max_uses_total: '',
    per_user_invite_allowance: '1',
  })
  const [internalNote, setInternalNote] = useState('')
  const [assignedUsername, setAssignedUsername] = useState('')
  const [expiresDays, setExpiresDays] = useState('')
  const [isCreatingInvite, setIsCreatingInvite] = useState(false)
  const [inviteCreateError, setInviteCreateError] = useState('')

  const [moderationDashboard, setModerationDashboard] = useState<ModerationDashboard | null>(null)
  const [moderationQueue, setModerationQueue] = useState<ModerationQueueItem[]>([])
  const [moderationFilter, setModerationFilter] = useState<'all' | 'open' | 'resolved' | 'dismissed'>('open')
  const [selectedModerationSignalId, setSelectedModerationSignalId] = useState<number | null>(null)
  const [selectedModerationSignal, setSelectedModerationSignal] = useState<ModerationQueueDetail | null>(null)
  const [moderationSurfaceFilter, setModerationSurfaceFilter] = useState<'all' | string>('all')
  const [isLoadingModerationQueue, setIsLoadingModerationQueue] = useState(false)
  const [isLoadingModerationDetail, setIsLoadingModerationDetail] = useState(false)
  const [moderationQueueError, setModerationQueueError] = useState('')
  const [moderationDetailError, setModerationDetailError] = useState('')
  const [moderationActionNote, setModerationActionNote] = useState('')
  const [isSubmittingModerationSignalAction, setIsSubmittingModerationSignalAction] = useState(false)

  const [auditLogs, setAuditLogs] = useState<AuditLogEntry[]>([])
  const [auditLogsTotal, setAuditLogsTotal] = useState(0)
  const [auditLogsPage, setAuditLogsPage] = useState(0)
  const [isLoadingAuditLogs, setIsLoadingAuditLogs] = useState(false)
  const [auditLogsError, setAuditLogsError] = useState('')

  useEffect(() => {
    if (isAuthLoading) return

    const resolveAdminSession = async () => {
      if (!token) {
        await logout()
        return
      }

      if (!user?.is_admin) {
        router.push('/')
        return
      }

      setIsPageLoading(true)
      setAdminSessionError('')

      try {
        const response = await authFetch(`${API_BASE_URL}/admin/session`)
        if (response.status === 401) {
          await logout()
          return
        }
        if (!response.ok) {
          const errorData = await response.json().catch(() => null)
          throw new Error(normalizeErrorMessage(errorData?.detail || errorData?.message || 'Failed to load admin session'))
        }

        const data = (await response.json()) as AdminSessionState
        setAdminSession(data)
        setIsAuthorized(true)
      } catch (error: unknown) {
        setAdminSession(null)
        setIsAuthorized(false)
        setAdminSessionError(normalizeErrorMessage(error))
      } finally {
        setIsPageLoading(false)
      }
    }

    void resolveAdminSession()
  }, [isAuthLoading, logout, router, token, user])

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return '-'
    return new Date(dateStr).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  }

  const formatDateTime = (dateStr: string | null) => {
    if (!dateStr) return '-'
    return new Date(dateStr).toLocaleString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  const maskInviteCode = (code: string | null | undefined) => {
    if (!code) return '-'
    if (code.includes('*')) return code
    if (code.length <= 4) return '*'.repeat(code.length)
    if (code.length <= 8) return `${code.slice(0, 2)}${'*'.repeat(code.length - 4)}${code.slice(-2)}`
    return `${code.slice(0, 4)}${'*'.repeat(code.length - 8)}${code.slice(-4)}`
  }

  const getUserStatusBadge = (status: UserStatus) => {
    switch (status) {
      case 'active':
        return { backgroundColor: 'transparent', border: '1px solid #2a3a2a', color: '#6a9a6a' }
      case 'banned':
        return { backgroundColor: 'transparent', border: '1px solid #3a2a2a', color: '#9a6a6a' }
      case 'frozen':
        return { backgroundColor: 'transparent', border: '1px solid #2a2a3a', color: '#6a6a9a' }
      case 'suspended':
        return { backgroundColor: 'transparent', border: '1px solid #3a3a2a', color: '#9a9a6a' }
    }
  }

  const getInviteStatus = (invite: Pick<InviteSummary, 'is_active' | 'expires_at' | 'current_uses' | 'used_at'>) => {
    const hasExpired = Boolean(invite.expires_at && new Date(invite.expires_at) < new Date())
    const isUsed = invite.current_uses >= 1 || Boolean(invite.used_at)

    if (isUsed) {
      return {
        label: 'used' as InviteStatus,
        backgroundColor: 'transparent',
        border: '1px solid #242424',
        color: '#555',
      }
    }

    if (hasExpired) {
      return {
        label: 'expired' as InviteStatus,
        backgroundColor: 'transparent',
        border: '1px solid #3a2a2a',
        color: '#9a6a6a',
      }
    }

    if (!invite.is_active) {
      return {
        label: 'inactive' as InviteStatus,
        backgroundColor: 'transparent',
        border: '1px solid #242424',
        color: '#404040',
      }
    }

    return {
      label: 'active' as InviteStatus,
      backgroundColor: 'transparent',
      border: '1px solid #2a3a2a',
      color: '#6a9a6a',
    }
  }

  const getDetectionBadge = (status: ModerationDetectionStatus) => {
    switch (status) {
      case 'blocked':
        return { backgroundColor: 'transparent', border: '1px solid #3a2a2a', color: '#9a6a6a' }
      case 'suspicious':
        return { backgroundColor: 'transparent', border: '1px solid #3a3a2a', color: '#9a9a6a' }
      default:
        return { backgroundColor: 'transparent', border: '1px solid #2a3a2a', color: '#6a9a6a' }
    }
  }

  const getReviewBadge = (status: ModerationReviewStatus) => {
    switch (status) {
      case 'dismissed':
        return { backgroundColor: 'transparent', border: '1px solid #242424', color: '#555' }
      case 'resolved':
        return { backgroundColor: 'transparent', border: '1px solid #2a3a2a', color: '#6a9a6a' }
      default:
        return { backgroundColor: 'transparent', border: '1px solid #242424', color: '#404040' }
    }
  }

  const visibleTabs: AdminTab[] = [
    'users',
    ...(adminSession?.capabilities.can_read_invites || adminSession?.capabilities.can_create_invites ? ['invites' as const] : []),
    ...(adminSession?.capabilities.can_manage_campaigns ? ['campaigns' as const] : []),
    ...(adminSession?.capabilities.can_view_moderation_queue ? ['moderation' as const] : []),
    ...(adminSession?.capabilities.can_manage_moderators ? ['moderators' as const] : []),
    ...(adminSession?.capabilities.can_read_waitlist || adminSession?.capabilities.can_manage_waitlist ? ['waitlist' as const] : []),
    ...(adminSession?.capabilities.can_read_audit_log ? ['audit' as const] : []),
  ]

  useEffect(() => {
    if (!visibleTabs.includes(activeTab)) {
      setActiveTab(visibleTabs[0] ?? 'users')
    }
  }, [activeTab, visibleTabs])

  const fetchJson = useCallback(async <T,>(url: string): Promise<T> => {
    if (!token) {
      throw new Error('Missing auth token')
    }

    const response = await authFetch(url)

    if (response.status === 401) {
      await logout()
      throw new Error('Session expired')
    }

    if (!response.ok) {
      const errorData = await response.json().catch(() => null)
      throw new Error(errorData?.detail || 'Request failed')
    }

    return response.json() as Promise<T>
  }, [token])

  useEffect(() => {
    if (!isAuthorized || !token) return

    const query = globalSearch.trim()
    if (query.length < 2) {
      setGlobalSearchResults({ users: [], invites: [], posts: [] })
      setGlobalSearchError('')
      return
    }

    let cancelled = false
    const timeoutId = window.setTimeout(() => {
      const run = async () => {
        setIsSearchingGlobal(true)
        setGlobalSearchError('')

        try {
          const params = new URLSearchParams({ q: query })
          const results = await fetchJson<AdminSearchResults>(`${API_BASE_URL}/admin/search?${params.toString()}`)
          if (!cancelled) {
            setGlobalSearchResults(results)
          }
        } catch (error: unknown) {
          if (!cancelled) {
            setGlobalSearchError(error instanceof Error ? error.message : 'Search failed')
            setGlobalSearchResults({ users: [], invites: [], posts: [] })
          }
        } finally {
          if (!cancelled) {
            setIsSearchingGlobal(false)
          }
        }
      }

      void run()
    }, 250)

    return () => {
      cancelled = true
      window.clearTimeout(timeoutId)
    }
  }, [fetchJson, globalSearch, isAuthorized, token])

  const loadUsersPage = useCallback(async (page: number, filter: 'all' | UserStatus = statusFilter) => {
    const params = new URLSearchParams({
      skip: String(page * PAGE_SIZE),
      limit: String(PAGE_SIZE),
    })

    if (filter !== 'all') {
      params.append('status_filter', filter)
    }

    const countParams = new URLSearchParams()
    if (filter !== 'all') {
      countParams.append('status_filter', filter)
    }

    const countUrl = countParams.toString()
      ? `${API_BASE_URL}/admin/users/count?${countParams.toString()}`
      : `${API_BASE_URL}/admin/users/count`

    const [listData, countData] = await Promise.all([
      fetchJson<UserSummary[]>(`${API_BASE_URL}/admin/users?${params.toString()}`),
      fetchJson<{ count: number }>(countUrl),
    ])

    setUsers(listData)
    setUserTotalCount(countData.count ?? 0)
  }, [fetchJson, statusFilter])

  const loadInvitesPage = useCallback(async (page: number) => {
    const params = new URLSearchParams({
      skip: String(page * PAGE_SIZE),
      limit: String(PAGE_SIZE),
    })

    const [listData, countData] = await Promise.all([
      fetchJson<InviteSummary[]>(`${API_BASE_URL}/admin/invites?${params.toString()}`),
      fetchJson<{ count: number }>(`${API_BASE_URL}/admin/invites/count`),
    ])

    setInvites(listData)
    setInviteTotalCount(countData.count ?? 0)
  }, [fetchJson])

  const loadCampaigns = useCallback(async () => {
    const data = await listAdminInviteCampaigns()
    setCampaigns(data)
  }, [])

  const openCampaignDetail = useCallback(async (campaignId: number) => {
    setSelectedCampaignId(campaignId)
    setIsLoadingCampaignDetail(true)
    setCampaignDetailError('')

    try {
      const data = await getAdminInviteCampaign(campaignId)
      setSelectedCampaign(data)
    } catch (error: unknown) {
      setSelectedCampaign(null)
      setCampaignDetailError(error instanceof Error ? error.message : 'Failed to load campaign detail')
    } finally {
      setIsLoadingCampaignDetail(false)
    }
  }, [])

  const loadModerationDashboard = useCallback(async () => {
    const data = await fetchJson<ModerationDashboard>(`${API_BASE_URL}/admin/moderation/dashboard`)
    setModerationDashboard(data)
  }, [fetchJson])

  const loadModerationQueue = useCallback(async () => {
    const params = new URLSearchParams()
    if (moderationFilter !== 'all') {
      params.append('review_status', moderationFilter)
    }
    if (moderationSurfaceFilter !== 'all') {
      params.append('surface_type', moderationSurfaceFilter)
    }
    params.append('limit', '100')

    const data = await fetchJson<ModerationQueueItem[]>(`${API_BASE_URL}/admin/moderation/queue?${params.toString()}`)
    setModerationQueue(data)
  }, [fetchJson, moderationFilter, moderationSurfaceFilter])

  useEffect(() => {
    if (!isAuthorized || !token || activeTab !== 'users') return

    let isCancelled = false

    const run = async () => {
      setIsLoadingUsers(true)
      setUsersError('')

      try {
        await loadUsersPage(userPage)
      } catch (error: unknown) {
        if (!isCancelled) {
          setUsers([])
          setUserTotalCount(0)
          setUsersError(error instanceof Error ? error.message : 'Failed to load users')
        }
      } finally {
        if (!isCancelled) {
          setIsLoadingUsers(false)
        }
      }
    }

    void run()

    return () => {
      isCancelled = true
    }
  }, [activeTab, isAuthorized, loadUsersPage, token, userPage])

  useEffect(() => {
    if (!isAuthorized || !token || activeTab !== 'invites') return

    let isCancelled = false

    const run = async () => {
      setIsLoadingInvites(true)
      setInvitesError('')

      try {
        await loadInvitesPage(invitePage)
      } catch (error: unknown) {
        if (!isCancelled) {
          setInvites([])
          setInviteTotalCount(0)
          setInvitesError(error instanceof Error ? error.message : 'Failed to load invites')
        }
      } finally {
        if (!isCancelled) {
          setIsLoadingInvites(false)
        }
      }
    }

    void run()

    return () => {
      isCancelled = true
    }
  }, [activeTab, invitePage, isAuthorized, loadInvitesPage, token])

  useEffect(() => {
    if (!isAuthorized || !token || activeTab !== 'moderation') return

    let isCancelled = false

    const run = async () => {
      setIsLoadingModerationQueue(true)
      setModerationQueueError('')

      try {
        await Promise.all([loadModerationDashboard(), loadModerationQueue()])
      } catch (error: unknown) {
        if (!isCancelled) {
          setModerationQueue([])
          setModerationQueueError(error instanceof Error ? error.message : 'Failed to load moderation queue')
        }
      } finally {
        if (!isCancelled) {
          setIsLoadingModerationQueue(false)
        }
      }
    }

    void run()

    return () => {
      isCancelled = true
    }
  }, [activeTab, isAuthorized, loadModerationDashboard, loadModerationQueue, token])

  useEffect(() => {
    if (!isAuthorized || !token || activeTab !== 'campaigns') return

    let isCancelled = false

    const run = async () => {
      setIsLoadingCampaigns(true)
      setCampaignsError('')

      try {
        const data = await listAdminInviteCampaigns()
        if (!isCancelled) {
          setCampaigns(data)
        }
      } catch (error: unknown) {
        if (!isCancelled) {
          setCampaigns([])
          setCampaignsError(error instanceof Error ? error.message : 'Failed to load invite campaigns')
        }
      } finally {
        if (!isCancelled) {
          setIsLoadingCampaigns(false)
        }
      }
    }

    void run()

    return () => {
      isCancelled = true
    }
  }, [activeTab, isAuthorized, token])

  useEffect(() => {
    if (!isAuthorized || !token || activeTab !== 'audit') return

    let isCancelled = false

    const run = async () => {
      setIsLoadingAuditLogs(true)
      setAuditLogsError('')

      try {
        const data = await getAuditLogs(auditLogsPage * PAGE_SIZE, PAGE_SIZE)
        if (!isCancelled) {
          setAuditLogs((prev) => auditLogsPage === 0 ? data.items : [...prev, ...data.items])
          setAuditLogsTotal(data.total)
        }
      } catch (error: unknown) {
        if (!isCancelled) {
          setAuditLogsError(error instanceof Error ? error.message : 'Failed to load audit logs')
        }
      } finally {
        if (!isCancelled) {
          setIsLoadingAuditLogs(false)
        }
      }
    }

    void run()

    return () => {
      isCancelled = true
    }
  }, [activeTab, auditLogsPage, isAuthorized, token])

  useEffect(() => {
    if (!selectedUserId) return
    if (users.some((user) => user.id === selectedUserId)) return

    setSelectedUserId(null)
    setSelectedUser(null)
    setUserDetailError('')
  }, [selectedUserId, users])

  useEffect(() => {
    if (!selectedInviteId) return
    if (invites.some((invite) => invite.id === selectedInviteId)) return

    setSelectedInviteId(null)
    setSelectedInvite(null)
    setInviteDetailError('')
  }, [invites, selectedInviteId])

  useEffect(() => {
    if (!selectedCampaignId) return
    if (campaigns.some((campaign) => campaign.id === selectedCampaignId)) return

    setSelectedCampaignId(null)
    setSelectedCampaign(null)
    setCampaignDetailError('')
  }, [campaigns, selectedCampaignId])

  useEffect(() => {
    if (!selectedModerationSignalId) return
    if (moderationQueue.some((signal) => signal.id === selectedModerationSignalId)) return

    setSelectedModerationSignalId(null)
    setSelectedModerationSignal(null)
    setModerationDetailError('')
  }, [moderationQueue, selectedModerationSignalId])

  useEffect(() => {
    if (!selectedInviteId || typeof document === 'undefined') return

    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    return () => {
      document.body.style.overflow = previousOverflow
    }
  }, [selectedInviteId])

  const openUserDetail = async (userId: number) => {
    setSelectedUserId(userId)
    setIsLoadingUserDetail(true)
    setUserDetailError('')

    try {
      const detailData = await fetchJson<UserDetail>(`${API_BASE_URL}/admin/users/${userId}`)
      setRevealedInviteCode(null)
      setSensitiveActionResult((current) => (current?.username === detailData.username ? current : null))
      setSelectedUser(detailData)
    } catch (error: unknown) {
      setSelectedUser(null)
      setUserDetailError(error instanceof Error ? error.message : 'Failed to load user detail')
    } finally {
      setIsLoadingUserDetail(false)
    }
  }

  const openInviteDetail = async (inviteId: number) => {
    setSelectedInviteId(inviteId)
    setIsLoadingInviteDetail(true)
    setInviteDetailError('')

    try {
      const detailData = await fetchJson<InviteDetail>(`${API_BASE_URL}/admin/invites/${inviteId}`)
      setRevealedInviteCode(null)
      setSelectedInvite(detailData)
    } catch (error: unknown) {
      setSelectedInvite(null)
      setInviteDetailError(error instanceof Error ? error.message : 'Failed to load invite detail')
    } finally {
      setIsLoadingInviteDetail(false)
    }
  }

  const openPostDetail = async (postId: number) => {
    setSelectedPostId(postId)
    setIsLoadingPostDetail(true)
    setPostDetailError('')
    setPostModerationReason('')

    try {
      const detailData = await fetchJson<PostModerationDetail>(`${API_BASE_URL}/admin/posts/${postId}`)
      setSelectedPost(detailData)
    } catch (error: unknown) {
      setSelectedPost(null)
      setPostDetailError(error instanceof Error ? error.message : 'Failed to load post detail')
    } finally {
      setIsLoadingPostDetail(false)
    }
  }

  const openModerationSignalDetail = async (signalId: number) => {
    setSelectedModerationSignalId(signalId)
    setIsLoadingModerationDetail(true)
    setModerationDetailError('')
    setModerationActionNote('')

    try {
      const detailData = await fetchJson<ModerationQueueDetail>(`${API_BASE_URL}/admin/moderation/queue/${signalId}`)
      setSelectedModerationSignal(detailData)
    } catch (error: unknown) {
      setSelectedModerationSignal(null)
      setModerationDetailError(error instanceof Error ? error.message : 'Failed to load moderation signal')
    } finally {
      setIsLoadingModerationDetail(false)
    }
  }

  const openInviteFromUserDetail = async (inviteId: number) => {
    setActiveTab('invites')
    setSuccessMessage('')
    setActionError('')
    await openInviteDetail(inviteId)
  }

  const openUserFromInviteDetail = async (userId: number) => {
    setActiveTab('users')
    setSuccessMessage('')
    setActionError('')
    await openUserDetail(userId)
  }

  const closeUserDetail = () => {
    setSelectedUserId(null)
    setSelectedUser(null)
    setSensitiveActionResult(null)
    setUserDetailError('')
  }

  const closeInviteDetail = () => {
    setSelectedInviteId(null)
    setSelectedInvite(null)
    setInviteDetailError('')
    setRevealedInviteCode(null)
    setInviteCopyFeedback('')
  }

  const closePostDetail = () => {
    setSelectedPostId(null)
    setSelectedPost(null)
    setPostDetailError('')
    setPostModerationReason('')
  }

  const closeModerationSignalDetail = () => {
    setSelectedModerationSignalId(null)
    setSelectedModerationSignal(null)
    setModerationDetailError('')
    setModerationActionNote('')
  }

  const submitPostModeration = async (action: PostModerationAction) => {
    if (!selectedPostId || !token || !postModerationReason.trim()) {
      setPostDetailError('A moderation reason is required.')
      return
    }

    setIsSubmittingPostAction(true)
    setPostDetailError('')

    try {
      const response = await authFetch(`${API_BASE_URL}/admin/posts/${selectedPostId}/${action}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ reason: postModerationReason.trim() }),
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => null)
        throw new Error(errorData?.detail || `Failed to ${action} post`)
      }

      setSuccessMessage(
        action === 'hide' ? 'Post hidden successfully.' : action === 'unhide' ? 'Post unhidden successfully.' : 'Post deleted successfully.'
      )

      await openPostDetail(selectedPostId)

      if (selectedUserId) {
        await refreshSelectedUserIfOpen(selectedUserId)
      }
    } catch (error: unknown) {
      setPostDetailError(error instanceof Error ? error.message : 'Post moderation failed')
    } finally {
      setIsSubmittingPostAction(false)
    }
  }

  const submitModerationSignalAction = async (action: ModerationQueueAction) => {
    if (!selectedModerationSignalId || !token) return

    setIsSubmittingModerationSignalAction(true)
    setModerationDetailError('')

    try {
      const response = await authFetch(`${API_BASE_URL}/admin/moderation/queue/${selectedModerationSignalId}/action`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ action, note: moderationActionNote.trim() || null }),
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => null)
        throw new Error(errorData?.detail || 'Failed to resolve moderation signal')
      }

      setSuccessMessage('Moderation queue updated successfully.')
      await Promise.all([
        openModerationSignalDetail(selectedModerationSignalId),
        loadModerationDashboard(),
        loadModerationQueue(),
      ])

      if (selectedUserId && selectedModerationSignal?.user_id === selectedUserId) {
        await refreshSelectedUserIfOpen(selectedUserId)
      }
      if (selectedPostId && selectedModerationSignal?.post_id === selectedPostId) {
        await openPostDetail(selectedPostId)
      }
    } catch (error: unknown) {
      setModerationDetailError(error instanceof Error ? error.message : 'Moderation queue action failed')
    } finally {
      setIsSubmittingModerationSignalAction(false)
    }
  }

  const revealSelectedInviteCode = async () => {
    if (!selectedInviteId || !token) return

    setIsRevealingInviteCode(true)
    setInviteDetailError('')
    setInviteCopyFeedback('')

    try {
      const response = await authFetch(`${API_BASE_URL}/admin/invites/${selectedInviteId}/reveal`, {
        method: 'POST',
      })

      if (response.status === 401) {
        await logout()
        return
      }

      if (!response.ok) {
        const errorData = await response.json().catch(() => null)
        throw new Error(errorData?.detail || 'Failed to reveal invite code')
      }

      const data = (await response.json()) as { code: string }
      setRevealedInviteCode(data.code)
    } catch (error: unknown) {
      setInviteDetailError(error instanceof Error ? error.message : 'Failed to reveal invite code')
    } finally {
      setIsRevealingInviteCode(false)
    }
  }

  const copyRevealedInviteCode = async () => {
    if (!revealedInviteCode) return

    try {
      await navigator.clipboard.writeText(revealedInviteCode)
      setInviteCopyFeedback('Copied')
      window.setTimeout(() => {
        setInviteCopyFeedback((current) => (current === 'Copied' ? '' : current))
      }, 1500)
    } catch {
      setInviteDetailError('Failed to copy invite code')
    }
  }

  const openConfirmModal = (action: ModerationAction, user: UserSummary) => {
    setActionError('')
    setSuccessMessage('')
    setActionReason('')
    setConfirmState({ action, user })
  }

  const openSensitiveActionModal = (action: SensitiveAdminAction, user: UserSummary) => {
    setActionError('')
    setSuccessMessage('')
    setActionReason('')
    setConfirmState({ action, user })
  }

  const closeConfirmModal = () => {
    if (isSubmittingAction) return
    setConfirmState(null)
    setActionReason('')
  }

  const getActionConfig = (action: ModerationAction | SensitiveAdminAction) => {
    switch (action) {
      case 'ban':
        return {
          title: 'Ban user',
          buttonLabel: 'Ban user',
          endpoint: 'ban',
          requiresReason: true,
          message: 'This will block the user from accessing the platform.',
        }
      case 'freeze':
        return {
          title: 'Freeze user',
          buttonLabel: 'Freeze user',
          endpoint: 'freeze',
          requiresReason: true,
          message: 'This will stop the user from posting or interacting while keeping the account visible.',
        }
      case 'unfreeze':
        return {
          title: 'Unfreeze user',
          buttonLabel: 'Unfreeze user',
          endpoint: 'unfreeze',
          requiresReason: true,
          message: 'This will restore posting and interaction capabilities.',
        }
      case 'unban':
        return {
          title: 'Unban user',
          buttonLabel: 'Unban user',
          endpoint: 'unban',
          requiresReason: true,
          message: 'This will restore the user to active status.',
        }
      case 'suspend':
        return {
          title: 'Suspend user',
          buttonLabel: 'Suspend user',
          endpoint: 'suspend',
          requiresReason: true,
          message: 'This will mark the user as suspended until you lift it.',
        }
      case 'unsuspend':
        return {
          title: 'Lift suspension',
          buttonLabel: 'Unsuspend user',
          endpoint: 'unsuspend',
          requiresReason: true,
          message: 'This will restore the user to active status.',
        }
      case 'forcePasswordReset':
        return {
          title: 'Force password reset',
          buttonLabel: 'Issue reset token',
          endpoint: 'force-password-reset',
          requiresReason: true,
          message: 'This issues a short-lived one-time reset token and marks the account as requiring a password change.',
        }
      case 'revokeSessions':
        return {
          title: 'Revoke all sessions',
          buttonLabel: 'Revoke sessions',
          endpoint: 'revoke-sessions',
          requiresReason: true,
          message: 'This immediately revokes every active refresh-backed session for the selected account.',
        }
    }
  }

  const refreshSelectedUserIfOpen = async (userId: number) => {
    if (selectedUserId === userId) {
      await openUserDetail(userId)
    }
  }

  const submitModerationAction = async () => {
    if (!token || !confirmState) return

    const config = getActionConfig(confirmState.action)
    if (config.requiresReason && !actionReason.trim()) {
      setActionError('A moderation reason is required.')
      return
    }

    setIsSubmittingAction(true)
    setActionError('')

    try {
      const response = await authFetch(
        `${API_BASE_URL}/admin/users/${confirmState.user.id}/${config.endpoint}`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ reason: actionReason.trim() }),
        }
      )

      if (!response.ok) {
        const errorData = await response.json().catch(() => null)
        throw new Error(errorData?.detail || `Failed to ${confirmState.action} user`)
      }

      const responseData = await response.json().catch(() => null)
      if (confirmState.action === 'forcePasswordReset' && responseData?.reset_token) {
        setSensitiveActionResult({
          kind: 'forcePasswordReset',
          token: responseData.reset_token,
          expiresAt: responseData.expires_at,
          username: confirmState.user.username,
        })
        setSuccessMessage(`Reset token issued for ${confirmState.user.username}.`)
      } else if (confirmState.action === 'revokeSessions') {
        setSensitiveActionResult({
          kind: 'revokeSessions',
          username: confirmState.user.username,
        })
        setSuccessMessage(`${confirmState.user.username} sessions revoked successfully.`)
      } else {
        setSensitiveActionResult(null)
        setSuccessMessage(`${confirmState.user.username} updated successfully.`)
      }
      setConfirmState(null)
      setActionReason('')

      if (activeTab === 'users') {
        await loadUsersPage(userPage)
      }
      await refreshSelectedUserIfOpen(confirmState.user.id)
    } catch (error: unknown) {
      setActionError(error instanceof Error ? error.message : 'Moderation action failed')
    } finally {
      setIsSubmittingAction(false)
    }
  }

  const submitInviteCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!token) return

    setIsCreatingInvite(true)
    setInviteCreateError('')
    setSuccessMessage('')
    setActionError('')

    try {
      const payload: InviteCreateRequest = {
        internal_note: internalNote.trim() || null,
        assigned_to_username: adminSession?.capabilities.can_assign_invites ? assignedUsername.trim() || null : null,
        expires_days: expiresDays.trim() ? Number(expiresDays) : null,
      }

      const expiresDaysValue = payload.expires_days
      if (expiresDaysValue != null && (!Number.isInteger(expiresDaysValue) || expiresDaysValue < 1)) {
        throw new Error('Expiration must be a whole number of days.')
      }

      const createdInvite = await createInvite(payload)

      setInternalNote('')
      setAssignedUsername('')
      setExpiresDays('')
      setInvitePage(0)
      setSuccessMessage('Invite created successfully.')
      await loadInvitesPage(0)
      await openInviteDetail(createdInvite.id)
    } catch (error: unknown) {
      setInviteCreateError(normalizeErrorMessage(error))
    } finally {
      setIsCreatingInvite(false)
    }
  }

  const buildCampaignPayload = (): AdminInviteCampaignPayload => {
    const allowance = Number(campaignForm.per_user_invite_allowance)
    if (!Number.isInteger(allowance) || allowance < 1) {
      throw new Error('Per-user allowance must be a whole number greater than zero.')
    }

    const maxUses = campaignForm.max_uses_total.trim() ? Number(campaignForm.max_uses_total) : null
    if (maxUses != null && (!Number.isInteger(maxUses) || maxUses < 1)) {
      throw new Error('Maximum total uses must be a whole number greater than zero.')
    }

    return {
      name: campaignForm.name.trim(),
      slug: campaignForm.slug.trim(),
      internal_note: campaignForm.internal_note.trim() || null,
      public_label: campaignForm.public_label.trim() || null,
      description: campaignForm.description.trim() || null,
      is_active: campaignForm.is_active,
      active_from: campaignForm.active_from || null,
      expires_at: campaignForm.expires_at || null,
      max_uses_total: maxUses,
      per_user_invite_allowance: allowance,
    }
  }

  const resetCampaignForm = () => {
    setCampaignForm({
      name: '',
      slug: '',
      internal_note: '',
      public_label: '',
      description: '',
      is_active: false,
      active_from: '',
      expires_at: '',
      max_uses_total: '',
      per_user_invite_allowance: '1',
    })
  }

  const populateCampaignForm = (campaign: AdminInviteCampaign) => {
    setCampaignForm({
      name: campaign.name,
      slug: campaign.slug,
      internal_note: campaign.internal_note || '',
      public_label: campaign.public_label || '',
      description: campaign.description || '',
      is_active: campaign.is_active,
      active_from: campaign.active_from ? campaign.active_from.slice(0, 16) : '',
      expires_at: campaign.expires_at ? campaign.expires_at.slice(0, 16) : '',
      max_uses_total: campaign.max_uses_total != null ? String(campaign.max_uses_total) : '',
      per_user_invite_allowance: String(campaign.per_user_invite_allowance),
    })
  }

  const submitCampaignCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setIsSubmittingCampaign(true)
    setCampaignFormError('')
    setSuccessMessage('')

    try {
      const created = await createAdminInviteCampaign(buildCampaignPayload())
      await loadCampaigns()
      setSelectedCampaignId(created.id)
      await openCampaignDetail(created.id)
      setSuccessMessage('Campaign created successfully.')
      resetCampaignForm()
    } catch (error: unknown) {
      setCampaignFormError(error instanceof Error ? error.message : 'Failed to create campaign')
    } finally {
      setIsSubmittingCampaign(false)
    }
  }

  const submitCampaignUpdate = async () => {
    if (!selectedCampaignId) return
    setIsSubmittingCampaign(true)
    setCampaignFormError('')
    setSuccessMessage('')

    try {
      await updateAdminInviteCampaign(selectedCampaignId, buildCampaignPayload())
      await loadCampaigns()
      await openCampaignDetail(selectedCampaignId)
      setSuccessMessage('Campaign updated successfully.')
    } catch (error: unknown) {
      setCampaignFormError(error instanceof Error ? error.message : 'Failed to update campaign')
    } finally {
      setIsSubmittingCampaign(false)
    }
  }

  const filteredUsers = users.filter((user) => {
    if (!userSearch.trim()) return true

    const query = userSearch.toLowerCase()
    return (
      user.username.toLowerCase().includes(query) ||
      (user.display_name || '').toLowerCase().includes(query) ||
      (user.email || '').toLowerCase().includes(query)
    )
  })

  const filteredInvites = invites.filter((invite) => {
    if (!inviteSearch.trim()) return true

    const query = inviteSearch.toLowerCase()
    return (
      invite.code.toLowerCase().includes(query) ||
      (invite.created_by_username || '').toLowerCase().includes(query) ||
      (invite.assigned_to_username || '').toLowerCase().includes(query) ||
      (invite.internal_note || '').toLowerCase().includes(query) ||
      (invite.used_by_username || '').toLowerCase().includes(query)
    )
  })

  const totalUserPages = Math.max(1, Math.ceil(userTotalCount / PAGE_SIZE))
  const totalInvitePages = Math.max(1, Math.ceil(inviteTotalCount / PAGE_SIZE))
  const selectedUserSummary = users.find((user) => user.id === selectedUserId) || null
  const selectedInviteSummary = invites.find((invite) => invite.id === selectedInviteId) || null

  const renderRowActions = (user: UserSummary) => {
    const actions: Array<{ label: string; action: ModerationAction; danger?: boolean }> = []

    if (adminSession?.capabilities.can_ban_users && user.status === 'banned') {
      actions.push({ label: 'Unban', action: 'unban' })
    } else if (adminSession?.capabilities.can_ban_users) {
      actions.push({ label: 'Ban', action: 'ban', danger: true })
    }

    if (adminSession?.capabilities.can_suspend_users && user.status === 'suspended') {
      actions.push({ label: 'Unsuspend', action: 'unsuspend' })
    } else if (adminSession?.capabilities.can_suspend_users && user.status !== 'banned') {
      actions.push({ label: 'Suspend', action: 'suspend' })
    }

    if (adminSession?.capabilities.can_manage_users && user.status === 'frozen') {
      actions.push({ label: 'Unfreeze', action: 'unfreeze' })
    } else if (adminSession?.capabilities.can_manage_users && user.status === 'active') {
      actions.push({ label: 'Freeze', action: 'freeze' })
    }

    if (actions.length === 0) {
      return <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>No user actions available in this session.</span>
    }

    return (
      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
        {actions.map(({ label, action, danger }) => (
          <button
            key={action}
            onClick={(event) => {
              event.stopPropagation()
              openConfirmModal(action, user)
            }}
            style={{
              backgroundColor: 'transparent',
              border: danger ? '1px solid #3a2a2a' : '1px solid #242424',
              color: danger ? '#9a6a6a' : '#555',
              borderRadius: tokens.radius.full,
              padding: '6px 12px',
              fontSize: tokens.font.sm,
              cursor: 'pointer',
            }}
          >
            {label}
          </button>
        ))}
      </div>
    )
  }

  const renderAdminPostSummary = (post: AdminPost, label?: string) => {
    const displayPost = post.original_post || post
    const mediaUrl = resolveMediaUrl(displayPost.media_url)

    return (
      <div
        key={`${label || 'post'}-${post.id}`}
        style={{
          padding: '12px',
          borderRadius: tokens.radius.md,
          backgroundColor: tokens.colors.bg,
          border: `1px solid ${tokens.colors.border}`,
          display: 'grid',
          gap: '6px',
        }}
      >
        {label && <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.xs }}>{label}</span>}
        {post.is_repost && (
          <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.xs }}>
            @{post.author.username} reposted
          </span>
        )}
        <div style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.sm }}>
          <strong>@{displayPost.author.username}</strong> · {formatDateTime(post.created_at)}
        </div>
        <div style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.sm, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
          {displayPost.content || '[No text content]'}
        </div>
        {mediaUrl && (
          <img
            src={mediaUrl}
            alt="Post media"
            style={{ width: '100%', maxHeight: '280px', objectFit: 'cover', borderRadius: tokens.radius.md, border: `1px solid ${tokens.colors.border}` }}
          />
        )}
        {displayPost.moderation_status && displayPost.moderation_status !== 'visible' && (
          <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.xs, textTransform: 'capitalize' }}>
            Status: {displayPost.moderation_status}
          </div>
        )}
        <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.xs }}>
          {displayPost.likes_count} likes · {displayPost.replies_count} replies · {displayPost.reposts_count} reposts
        </div>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <button
            onClick={() => void openPostDetail(post.id)}
            style={{
              backgroundColor: tokens.colors.surfaceElevated,
              border: `1px solid ${tokens.colors.border}`,
              color: tokens.colors.textPrimary,
              borderRadius: tokens.radius.full,
              padding: '6px 10px',
              fontSize: tokens.font.sm,
              cursor: 'pointer',
            }}
          >
            Moderate post
          </button>
          <button
            onClick={() => router.push(getProfileHref(displayPost.author.username))}
            style={{
              background: 'none',
              border: 'none',
              color: tokens.colors.accent,
              padding: 0,
              cursor: 'pointer',
              fontSize: tokens.font.sm,
            }}
          >
            Open profile
          </button>
        </div>
      </div>
    )
  }

  const formatSurfaceLabel = (surfaceType: string) =>
    surfaceType
      .split('_')
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(' ')

  const tabButtonStyle = (tab: AdminTab) => ({
    padding: '6px 16px',
    borderRadius: '8px',
    border: '1px solid #242424',
    backgroundColor: activeTab === tab ? '#1c1c1c' : 'transparent',
    color: activeTab === tab ? '#f0f0f0' : '#555',
    fontSize: tokens.font.sm,
    cursor: 'pointer',
  })

  const pageContent = (
    <div className="admin-page">
      <header className="admin-page-header" style={{ padding: '16px 24px', borderBottom: '1px solid #1c1c1c' }}>
        <div style={{ fontSize: '18px', fontWeight: 500, color: '#f0f0f0' }}>Admin</div>
        <div style={{ color: '#555', fontSize: '13px', marginTop: '4px' }}>
          Moderation, invite controls, and account review on the live admin surface.
        </div>
      </header>
      <div className="admin-page-body" style={{ padding: '16px' }}>

      <section
        style={{
          marginBottom: '16px',
          padding: '16px 20px',
          backgroundColor: '#141414',
          borderRadius: '10px',
          border: '1px solid #242424',
          display: 'grid',
          gap: '12px',
        }}
      >
        <div>
          <div style={{ margin: '0 0 6px 0', color: '#404040', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            Global search
          </div>
          <p style={{ margin: 0, color: tokens.colors.textSecondary, fontSize: '13px' }}>
            Search users, invites, and posts from one place. Results open the existing detail views.
          </p>
        </div>
        <input
          type="text"
          value={globalSearch}
          onChange={(event) => setGlobalSearch(event.target.value)}
          placeholder="Search username, email, invite note, code suffix, or post text"
          style={{
            padding: '10px 12px',
            border: '1px solid #242424',
            borderRadius: '8px',
            backgroundColor: '#0a0a0a',
            color: tokens.colors.textPrimary,
            fontSize: tokens.font.sm,
            outline: 'none',
          }}
        />
        {globalSearchError && (
          <div style={{ color: tokens.colors.danger, fontSize: tokens.font.sm }}>{globalSearchError}</div>
        )}
        {globalSearch.trim().length >= 2 && (
          <div style={{ display: 'grid', gap: '12px' }}>
            {isSearchingGlobal ? (
              <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>Searching…</div>
            ) : (
              <>
                <div style={{ display: 'grid', gap: '8px' }}>
                  <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>Users</span>
                  {globalSearchResults.users.length === 0 ? (
                    <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>No users found.</span>
                  ) : (
                    globalSearchResults.users.map((user) => (
                      <button
                        key={`search-user-${user.id}`}
                        onClick={() => void openUserDetail(user.id)}
                        style={{
                          textAlign: 'left',
                          padding: '10px 12px',
                          borderRadius: tokens.radius.md,
                          border: `1px solid ${tokens.colors.border}`,
                          backgroundColor: tokens.colors.bg,
                          color: tokens.colors.textPrimary,
                          cursor: 'pointer',
                        }}
                      >
                        @{user.username} {user.display_name ? `· ${user.display_name}` : ''} {user.email ? `· ${user.email}` : ''}
                      </button>
                    ))
                  )}
                </div>
                <div style={{ display: 'grid', gap: '8px' }}>
                  <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>Invites</span>
                  {globalSearchResults.invites.length === 0 ? (
                    <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>No invites found.</span>
                  ) : (
                    globalSearchResults.invites.map((invite) => (
                      <button
                        key={`search-invite-${invite.id}`}
                        onClick={() => void openInviteDetail(invite.id)}
                        style={{
                          textAlign: 'left',
                          padding: '10px 12px',
                          borderRadius: tokens.radius.md,
                          border: `1px solid ${tokens.colors.border}`,
                          backgroundColor: tokens.colors.bg,
                          color: tokens.colors.textPrimary,
                          cursor: 'pointer',
                        }}
                      >
                        {invite.code} · {invite.internal_note || 'No note'} · created by {invite.created_by_username || '-'}
                      </button>
                    ))
                  )}
                </div>
                <div style={{ display: 'grid', gap: '8px' }}>
                  <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>Posts</span>
                  {globalSearchResults.posts.length === 0 ? (
                    <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>No posts found.</span>
                  ) : (
                    globalSearchResults.posts.map((post) => (
                      <button
                        key={`search-post-${post.id}`}
                        onClick={() => void openPostDetail(post.id)}
                        style={{
                          textAlign: 'left',
                          padding: '10px 12px',
                          borderRadius: tokens.radius.md,
                          border: `1px solid ${tokens.colors.border}`,
                          backgroundColor: tokens.colors.bg,
                          color: tokens.colors.textPrimary,
                          cursor: 'pointer',
                        }}
                      >
                        @{post.author_username || 'unknown'} · {post.content_preview || '[No text content]'}
                      </button>
                    ))
                  )}
                </div>
              </>
            )}
          </div>
        )}
      </section>

      <div className="admin-tab-row" style={{ display: 'flex', gap: '10px', marginBottom: '16px', flexWrap: 'wrap' }}>
        {visibleTabs.includes('users') && (
          <button onClick={() => setActiveTab('users')} style={tabButtonStyle('users')}>
            Users
          </button>
        )}
        {visibleTabs.includes('moderation') && (
          <button onClick={() => setActiveTab('moderation')} style={tabButtonStyle('moderation')}>
            Moderation Queue
          </button>
        )}
        {visibleTabs.includes('invites') && (
          <button onClick={() => setActiveTab('invites')} style={tabButtonStyle('invites')}>
            Invites
          </button>
        )}
        {visibleTabs.includes('campaigns') && (
          <button onClick={() => setActiveTab('campaigns')} style={tabButtonStyle('campaigns')}>
            Campaigns
          </button>
        )}
        {visibleTabs.includes('moderators') && (
          <button onClick={() => setActiveTab('moderators')} style={tabButtonStyle('moderators')}>
            Moderators
          </button>
        )}
        {visibleTabs.includes('waitlist') && (
          <button onClick={() => setActiveTab('waitlist')} style={tabButtonStyle('waitlist')}>
            Waitlist
          </button>
        )}
        {visibleTabs.includes('audit') && (
          <button onClick={() => setActiveTab('audit')} style={tabButtonStyle('audit')}>
            Audit Log
          </button>
        )}
      </div>

      {successMessage && (
        <div
          style={{
            marginBottom: '16px',
            padding: '12px',
            backgroundColor: 'rgba(0, 186, 124, 0.1)',
            border: `1px solid ${tokens.colors.success}`,
            borderRadius: tokens.radius.md,
            color: tokens.colors.success,
            fontSize: tokens.font.sm,
          }}
        >
          {successMessage}
        </div>
      )}

      {actionError && !confirmState && (
        <div
          style={{
            marginBottom: '16px',
            padding: '12px',
            backgroundColor: 'rgba(244, 33, 46, 0.1)',
            border: `1px solid ${tokens.colors.danger}`,
            borderRadius: tokens.radius.md,
            color: tokens.colors.danger,
            fontSize: tokens.font.sm,
          }}
        >
          {actionError}
        </div>
      )}

      {activeTab === 'users' ? (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '16px', alignItems: 'flex-start' }}>
          <section
            style={{
              flex: '2 1 720px',
              backgroundColor: tokens.colors.surface,
              borderRadius: tokens.radius.lg,
              border: '1px solid #242424',
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                padding: '20px',
                borderBottom: '1px solid #1c1c1c',
                display: 'flex',
                justifyContent: 'space-between',
                gap: '12px',
                flexWrap: 'wrap',
                alignItems: 'end',
              }}
            >
              <div>
                <h2
                  style={{
                    fontSize: tokens.font.lg,
                    fontWeight: Number(tokens.font.weightSemibold),
                    color: tokens.colors.textPrimary,
                    marginBottom: '6px',
                  }}
                >
                  Users Management
                </h2>
                <p style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm, margin: 0 }}>
                  {userTotalCount} users across the current moderation filter.
                </p>
              </div>

              <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
                <input
                  type="text"
                  value={userSearch}
                  onChange={(event) => setUserSearch(event.target.value)}
                  placeholder="Search username, display name, email"
                  style={{
                    width: '280px',
                    maxWidth: '100%',
                    padding: '10px 12px',
                    border: '1px solid #242424',
                    borderRadius: '8px',
                    backgroundColor: '#0a0a0a',
                    color: tokens.colors.textPrimary,
                    fontSize: tokens.font.sm,
                    outline: 'none',
                  }}
                />

                <select
                  value={statusFilter}
                  onChange={(event) => {
                    setStatusFilter(event.target.value as 'all' | UserStatus)
                    setUserPage(0)
                  }}
                  style={{
                    padding: '10px 12px',
                    border: '1px solid #242424',
                    borderRadius: '8px',
                    backgroundColor: '#141414',
                    color: tokens.colors.textPrimary,
                    fontSize: tokens.font.sm,
                    outline: 'none',
                  }}
                >
                  <option value="all">All statuses</option>
                  <option value="active">Active</option>
                  <option value="frozen">Frozen</option>
                  <option value="suspended">Suspended</option>
                  <option value="banned">Banned</option>
                </select>
              </div>
            </div>

            {isLoadingUsers ? (
              <div style={{ padding: '32px 20px', color: tokens.colors.textSecondary }}>Loading users…</div>
            ) : usersError ? (
              <div style={{ padding: '32px 20px', color: tokens.colors.danger }}>{usersError}</div>
            ) : filteredUsers.length === 0 ? (
              <div style={{ padding: '32px 20px', color: tokens.colors.textSecondary }}>
                {users.length === 0 ? 'No users found for this filter.' : 'No users match this search.'}
              </div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ backgroundColor: 'transparent' }}>
                      {['Username', 'Display Name', 'Email', 'Status', 'Joined', 'Invited By', 'Actions'].map((heading) => (
                        <th
                          key={heading}
                          style={{
                            padding: '12px 16px',
                            textAlign: 'left',
                            fontSize: '11px',
                            fontWeight: 400,
                            textTransform: 'uppercase' as const,
                            letterSpacing: '0.06em',
                            color: '#404040',
                            borderBottom: '1px solid #1c1c1c',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {heading}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {filteredUsers.map((user) => {
                      const badge = getUserStatusBadge(user.status)
                      const isSelected = user.id === selectedUserId

                      return (
                        <tr
                          key={user.id}
                          onClick={() => void openUserDetail(user.id)}
                          style={{
                            borderBottom: '1px solid #1c1c1c',
                            backgroundColor: isSelected ? '#0f0f0f' : 'transparent',
                            cursor: 'pointer',
                          }}
                        >
                          <td style={{ padding: '16px', color: tokens.colors.textPrimary, fontSize: tokens.font.sm }}>
                            {user.username}
                          </td>
                          <td style={{ padding: '16px', color: tokens.colors.textPrimary, fontSize: tokens.font.sm }}>
                            {user.display_name || '-'}
                          </td>
                          <td style={{ padding: '16px', color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                            {user.email || '-'}
                          </td>
                          <td style={{ padding: '16px' }}>
                            <span
                              style={{
                                ...badge,
                                padding: '4px 8px',
                                borderRadius: tokens.radius.full,
                                fontSize: tokens.font.sm,
                                textTransform: 'capitalize',
                              }}
                            >
                              {user.status}
                            </span>
                          </td>
                          <td style={{ padding: '16px', color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                            {formatDate(user.created_at)}
                          </td>
                          <td style={{ padding: '16px', color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                            {user.invited_by_username || '-'}
                          </td>
                          <td style={{ padding: '16px' }}>{renderRowActions(user)}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}

            <div
              style={{
                padding: '16px 20px',
                borderTop: '1px solid #1c1c1c',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                gap: '12px',
                flexWrap: 'wrap',
              }}
            >
              <p style={{ margin: 0, color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                Page {Math.min(userPage + 1, totalUserPages)} of {totalUserPages}
              </p>

              <div style={{ display: 'flex', gap: '8px' }}>
                <button
                  onClick={() => setUserPage((page) => Math.max(0, page - 1))}
                  disabled={userPage === 0 || isLoadingUsers}
                  style={{
                    padding: '8px 14px',
                    borderRadius: tokens.radius.full,
                    border: '1px solid #242424',
                    backgroundColor: 'transparent',
                    color: '#555',
                    opacity: userPage === 0 || isLoadingUsers ? 0.5 : 1,
                    cursor: userPage === 0 || isLoadingUsers ? 'default' : 'pointer',
                  }}
                >
                  Previous
                </button>
                <button
                  onClick={() => setUserPage((page) => (page + 1 < totalUserPages ? page + 1 : page))}
                  disabled={userPage + 1 >= totalUserPages || isLoadingUsers}
                  style={{
                    padding: '8px 14px',
                    borderRadius: tokens.radius.full,
                    border: '1px solid #242424',
                    backgroundColor: 'transparent',
                    color: '#555',
                    opacity: userPage + 1 >= totalUserPages || isLoadingUsers ? 0.5 : 1,
                    cursor: userPage + 1 >= totalUserPages || isLoadingUsers ? 'default' : 'pointer',
                  }}
                >
                  Next
                </button>
              </div>
            </div>
          </section>

          {selectedUserId && (
            <aside
              style={{
                flex: '1 1 320px',
                backgroundColor: tokens.colors.surface,
                borderRadius: tokens.radius.lg,
                border: '1px solid #242424',
                overflow: 'hidden',
              }}
            >
              <div
                style={{
                  padding: '20px',
                  borderBottom: '1px solid #1c1c1c',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  gap: '12px',
                }}
              >
                <div>
                  <h2
                    style={{
                      fontSize: tokens.font.lg,
                      fontWeight: Number(tokens.font.weightSemibold),
                      color: tokens.colors.textPrimary,
                      marginBottom: '6px',
                    }}
                  >
                    User Detail
                  </h2>
                  <p style={{ margin: 0, color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                    {selectedUserSummary?.username || 'Selected user'}
                  </p>
                </div>

                <button
                  onClick={closeUserDetail}
                  style={{
                    background: 'none',
                    border: 'none',
                    color: tokens.colors.textSecondary,
                    cursor: 'pointer',
                    fontSize: tokens.font.sm,
                  }}
                >
                  Close
                </button>
              </div>

              {isLoadingUserDetail ? (
                <div style={{ padding: '20px', color: tokens.colors.textSecondary }}>
                  Loading user detail...
                </div>
              ) : userDetailError ? (
                <div style={{ padding: '20px', color: tokens.colors.danger }}>{userDetailError}</div>
              ) : selectedUser ? (
                <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '18px' }}>
                  <div style={{ display: 'grid', gap: '12px' }}>
                    {[
                      ['Username', selectedUser.username],
                      ['Display name', selectedUser.display_name || '-'],
                      ['Status', selectedUser.status],
                      ['Password reset required', selectedUser.must_change_password ? 'Yes' : 'No'],
                      ['Active sessions', String(selectedUser.active_refresh_session_count ?? 0)],
                      ['Current moderation reason', selectedUser.status_reason || selectedUser.ban_reason || '-'],
                      ['Invited by', selectedUser.invited_by_username || '-'],
                      ['Invite used', selectedUser.invite_code_used || '-'],
                      ['Joined', formatDateTime(selectedUser.created_at)],
                    ].map(([label, value]) => (
                      <div key={label} style={{ display: 'grid', gap: '4px' }}>
                        <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>{label}</span>
                        <span
                          style={{
                            color: label === 'Status' ? getUserStatusBadge(selectedUser.status).color : tokens.colors.textPrimary,
                            fontSize: tokens.font.sm,
                            textTransform: label === 'Status' ? 'capitalize' : 'none',
                          }}
                        >
                          {value}
                        </span>
                      </div>
                    ))}
                  </div>

                  {(selectedUser.available_sensitive_actions?.can_force_password_reset ||
                    selectedUser.available_sensitive_actions?.can_revoke_sessions) && (
                    <div
                      style={{
                        padding: '14px',
                        borderRadius: tokens.radius.md,
                        backgroundColor: tokens.colors.bg,
                        border: `1px solid ${tokens.colors.border}`,
                        display: 'grid',
                        gap: '12px',
                      }}
                    >
                      <div style={{ display: 'grid', gap: '4px' }}>
                        <span style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.sm }}>Sensitive account actions</span>
                        <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.xs }}>
                          High-risk actions require explicit confirmation and are fully audited.
                        </span>
                      </div>
                      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                        {selectedUser.available_sensitive_actions?.can_force_password_reset && (
                          <button
                            onClick={() => openSensitiveActionModal('forcePasswordReset', selectedUser)}
                            style={{
                              padding: '8px 12px',
                              borderRadius: tokens.radius.full,
                              border: `1px solid ${tokens.colors.border}`,
                              backgroundColor: 'transparent',
                              color: tokens.colors.textPrimary,
                              cursor: 'pointer',
                              fontSize: tokens.font.sm,
                            }}
                          >
                            Force password reset
                          </button>
                        )}
                        {selectedUser.available_sensitive_actions?.can_revoke_sessions && (
                          <button
                            onClick={() => openSensitiveActionModal('revokeSessions', selectedUser)}
                            style={{
                              padding: '8px 12px',
                              borderRadius: tokens.radius.full,
                              border: `1px solid ${tokens.colors.border}`,
                              backgroundColor: 'transparent',
                              color: tokens.colors.textPrimary,
                              cursor: 'pointer',
                              fontSize: tokens.font.sm,
                            }}
                          >
                            Revoke all sessions
                          </button>
                        )}
                      </div>
                      {sensitiveActionResult?.username === selectedUser.username && (
                        <div
                          style={{
                            padding: '12px',
                            borderRadius: tokens.radius.md,
                            border: `1px solid ${tokens.colors.border}`,
                            backgroundColor: tokens.colors.surface,
                            display: 'grid',
                            gap: '6px',
                          }}
                        >
                          <span style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.sm }}>
                            {sensitiveActionResult.kind === 'forcePasswordReset' ? 'Reset token issued' : 'Sessions revoked'}
                          </span>
                          {sensitiveActionResult.kind === 'forcePasswordReset' && sensitiveActionResult.token && (
                            <>
                              <code
                                style={{
                                  padding: '10px 12px',
                                  borderRadius: tokens.radius.md,
                                  backgroundColor: tokens.colors.bg,
                                  border: `1px solid ${tokens.colors.border}`,
                                  color: tokens.colors.textPrimary,
                                  fontSize: tokens.font.sm,
                                  wordBreak: 'break-all',
                                }}
                              >
                                {sensitiveActionResult.token}
                              </code>
                              <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.xs }}>
                                Visible only in this session. Expires {formatDateTime(sensitiveActionResult.expiresAt || null)}.
                              </span>
                            </>
                          )}
                        </div>
                      )}
                    </div>
                  )}

                  <div style={{ display: 'grid', gap: '6px' }}>
                    <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                      Invite used
                    </span>
                    {selectedUser.invite_used ? (
                      <div
                        style={{
                          padding: '12px',
                          borderRadius: tokens.radius.md,
                          backgroundColor: tokens.colors.bg,
                          border: `1px solid ${tokens.colors.border}`,
                          display: 'grid',
                          gap: '6px',
                        }}
                      >
                        <button
                          onClick={() => void openInviteFromUserDetail(selectedUser.invite_used!.id)}
                          style={{
                            background: 'none',
                            border: 'none',
                            color: tokens.colors.accent,
                            cursor: 'pointer',
                            padding: 0,
                            textAlign: 'left',
                            fontSize: tokens.font.sm,
                          }}
                        >
                          {selectedUser.invite_used.code}
                        </button>
                        <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                          Internal note: {selectedUser.invite_used.internal_note || '-'}
                        </span>
                        <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                          Assigned to: {selectedUser.invite_used.assigned_to_username || '-'}
                        </span>
                        <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                          Created by: {selectedUser.invite_used.created_by_username || '-'}
                        </span>
                        <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                          Status: {getInviteStatus(selectedUser.invite_used).label}
                        </span>
                      </div>
                    ) : (
                      <span style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.sm }}>-</span>
                    )}
                  </div>

                  {selectedUser.banned_by_user && (
                    <div style={{ display: 'grid', gap: '4px' }}>
                      <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                        Moderated by
                      </span>
                      <span style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.sm }}>
                        {selectedUser.banned_by_user.username}
                      </span>
                    </div>
                  )}

                  {selectedUser.invite_lineage && (
                    <div style={{ display: 'grid', gap: '6px' }}>
                      <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                        Invite lineage
                      </span>
                      <div style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.sm }}>
                        Invited by: {selectedUser.invite_lineage.invited_by_username || '-'}
                      </div>
                      <div style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.sm }}>
                        Invite creator: {selectedUser.invite_lineage.invite_created_by_username || '-'}
                      </div>
                      <div style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.sm }}>
                        Invite assigned to: {selectedUser.invite_lineage.invite_assigned_to_username || '-'}
                      </div>
                    </div>
                  )}

                  <div style={{ display: 'grid', gap: '8px' }}>
                    <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>Moderation controls</span>
                    {renderRowActions(selectedUser)}
                  </div>

                  <div style={{ display: 'grid', gap: '8px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', alignItems: 'center' }}>
                      <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>Recent posts</span>
                    </div>
                    {selectedUser.recent_posts && selectedUser.recent_posts.length > 0 ? (
                      selectedUser.recent_posts.map((post) => renderAdminPostSummary(post))
                    ) : (
                      <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>No recent posts.</span>
                    )}
                  </div>

                  <div style={{ display: 'grid', gap: '8px' }}>
                    <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>Moderation history</span>
                    {selectedUser.moderation_history && selectedUser.moderation_history.length > 0 ? (
                      selectedUser.moderation_history.map((entry) => (
                        <div
                          key={`user-history-${entry.id}`}
                          style={{
                            padding: '10px 12px',
                            borderRadius: tokens.radius.md,
                            backgroundColor: tokens.colors.bg,
                            border: `1px solid ${tokens.colors.border}`,
                            display: 'grid',
                            gap: '4px',
                          }}
                        >
                          <span style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.sm }}>{entry.action}</span>
                          <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.xs }}>
                            {formatDateTime(entry.created_at)} {entry.reason ? `· ${entry.reason}` : ''}
                          </span>
                        </div>
                      ))
                    ) : (
                      <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>No moderation history yet.</span>
                    )}
                  </div>

                </div>
              ) : (
                <div style={{ padding: '20px', color: tokens.colors.textSecondary }}>
                  Select a user to inspect moderation and invite details.
                </div>
              )}
            </aside>
          )}
        </div>
      ) : activeTab === 'invites' ? (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '16px', alignItems: 'flex-start' }}>
          <section
            style={{
              flex: '2 1 720px',
              backgroundColor: tokens.colors.surface,
              borderRadius: tokens.radius.lg,
              border: '1px solid #242424',
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                padding: '20px',
                borderBottom: '1px solid #1c1c1c',
                display: 'flex',
                justifyContent: 'space-between',
                gap: '12px',
                flexWrap: 'wrap',
                alignItems: 'end',
              }}
            >
              <div>
                <h2
                  style={{
                    fontSize: tokens.font.lg,
                    fontWeight: Number(tokens.font.weightSemibold),
                    color: tokens.colors.textPrimary,
                    marginBottom: '6px',
                  }}
                >
                  Invite Management
                </h2>
                <p style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm, margin: 0 }}>
                  {inviteTotalCount} invites across the current filter.
                </p>
              </div>

              <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
                <input
                  type="text"
                  value={inviteSearch}
                  onChange={(event) => setInviteSearch(event.target.value)}
                  placeholder="Search code, note, creator, or used by"
                  style={{
                    width: '280px',
                    maxWidth: '100%',
                    padding: '10px 12px',
                    border: '1px solid #242424',
                    borderRadius: '8px',
                    backgroundColor: '#0a0a0a',
                    color: tokens.colors.textPrimary,
                    fontSize: tokens.font.sm,
                    outline: 'none',
                  }}
                />
              </div>
            </div>

            {adminSession?.capabilities.can_create_invites ? (
              <form
                onSubmit={submitInviteCreate}
                style={{
                  padding: '20px',
                  borderBottom: '1px solid #1c1c1c',
                  backgroundColor: '#141414',
                  borderRadius: '10px',
                  display: 'grid',
                  gap: '12px',
                }}
              >
                <div>
                  <h3
                    style={{
                      margin: '0 0 6px 0',
                      color: tokens.colors.textPrimary,
                      fontSize: tokens.font.md,
                      fontWeight: Number(tokens.font.weightSemibold),
                    }}
                  >
                    Create Invite
                  </h3>
                  <p style={{ margin: 0, color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                    Each invite is single-use. Add an optional internal note and optional expiration.
                  </p>
                </div>

                <input
                  type="text"
                  value={internalNote}
                  onChange={(event) => setInternalNote(event.target.value)}
                  placeholder="Internal admin note"
                  maxLength={255}
                  style={{
                    padding: '10px 12px',
                    border: '1px solid #242424',
                    borderRadius: '8px',
                    backgroundColor: '#0a0a0a',
                    color: tokens.colors.textPrimary,
                    fontSize: tokens.font.sm,
                    outline: 'none',
                  }}
                />

                {adminSession.capabilities.can_assign_invites ? (
                  <input
                    type="text"
                    value={assignedUsername}
                    onChange={(event) => setAssignedUsername(event.target.value)}
                    placeholder="Assign to existing username (optional)"
                    maxLength={50}
                    style={{
                      padding: '10px 12px',
                      border: '1px solid #242424',
                      borderRadius: '8px',
                      backgroundColor: '#0a0a0a',
                      color: tokens.colors.textPrimary,
                      fontSize: tokens.font.sm,
                      outline: 'none',
                    }}
                  />
                ) : (
                  <p style={{ margin: 0, color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                    This session can create invites but cannot assign them to a specific existing account.
                  </p>
                )}

                <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'center' }}>
                  <input
                    type="number"
                    min="1"
                    step="1"
                    value={expiresDays}
                    onChange={(event) => setExpiresDays(event.target.value)}
                    placeholder="Expires in days"
                    style={{
                      width: '180px',
                      padding: '10px 12px',
                      border: '1px solid #242424',
                      borderRadius: '8px',
                      backgroundColor: '#0a0a0a',
                      color: tokens.colors.textPrimary,
                      fontSize: tokens.font.sm,
                      outline: 'none',
                    }}
                  />

                  <button
                    type="submit"
                    disabled={isCreatingInvite}
                    style={{
                      padding: '10px 16px',
                      borderRadius: tokens.radius.full,
                      border: '1px solid #242424',
                      backgroundColor: 'transparent',
                      color: '#888',
                      fontSize: tokens.font.sm,
                      cursor: isCreatingInvite ? 'default' : 'pointer',
                      opacity: isCreatingInvite ? 0.6 : 1,
                    }}
                  >
                    {isCreatingInvite ? 'Creating...' : 'Create invite'}
                  </button>
                </div>

                {inviteCreateError && (
                  <p style={{ margin: 0, color: tokens.colors.danger, fontSize: tokens.font.sm }}>
                    {inviteCreateError}
                  </p>
                )}
              </form>
            ) : (
              <div
                style={{
                  padding: '20px',
                  borderBottom: '1px solid #1c1c1c',
                  backgroundColor: '#141414',
                  color: tokens.colors.textSecondary,
                  fontSize: tokens.font.sm,
                }}
              >
                This admin session can review invites but cannot create new ones.
              </div>
            )}

            {isLoadingInvites ? (
              <div style={{ padding: '32px 20px', color: tokens.colors.textSecondary }}>Loading invites…</div>
            ) : invitesError ? (
              <div style={{ padding: '32px 20px', color: tokens.colors.danger }}>{invitesError}</div>
            ) : filteredInvites.length === 0 ? (
              <div style={{ padding: '32px 20px', color: tokens.colors.textSecondary }}>
                {invites.length === 0 ? 'No invites found for this filter.' : 'No invites match this search.'}
              </div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ backgroundColor: 'transparent' }}>
                      {['Code', 'Internal Label', 'Created By', 'Assigned To', 'Created At', 'Used', 'Used By', 'Expiration', 'Status'].map((heading) => (
                        <th
                          key={heading}
                          style={{
                            padding: '12px 16px',
                            textAlign: 'left',
                            fontSize: '11px',
                            fontWeight: 400,
                            textTransform: 'uppercase' as const,
                            letterSpacing: '0.06em',
                            color: '#404040',
                            borderBottom: '1px solid #1c1c1c',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {heading}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {filteredInvites.map((invite) => {
                      const statusBadge = getInviteStatus(invite)
                      const isSelected = invite.id === selectedInviteId

                      return (
                        <tr
                          key={invite.id}
                          onClick={() => void openInviteDetail(invite.id)}
                          style={{
                            borderBottom: '1px solid #1c1c1c',
                            backgroundColor: isSelected ? '#0f0f0f' : 'transparent',
                            cursor: 'pointer',
                          }}
                        >
                          <td style={{ padding: '16px', color: tokens.colors.textPrimary, fontSize: tokens.font.sm }}>
                            <code>{maskInviteCode(invite.code)}</code>
                          </td>
                          <td style={{ padding: '16px', color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                            {invite.internal_note || '-'}
                          </td>
                          <td style={{ padding: '16px', color: tokens.colors.textPrimary, fontSize: tokens.font.sm }}>
                            {invite.created_by_username || '-'}
                          </td>
                          <td style={{ padding: '16px', color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                            {invite.assigned_to_username || '-'}
                          </td>
                          <td style={{ padding: '16px', color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                            {formatDate(invite.created_at)}
                          </td>
                          <td style={{ padding: '16px', color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                            {invite.used ? 'Used' : 'Unused'}
                          </td>
                          <td style={{ padding: '16px', color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                            {invite.used_by_username || '-'}
                          </td>
                          <td style={{ padding: '16px', color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                            {formatDate(invite.expires_at)}
                          </td>
                          <td style={{ padding: '16px' }}>
                            <span
                              style={{
                                backgroundColor: statusBadge.backgroundColor,
                                border: statusBadge.border,
                                color: statusBadge.color,
                                padding: '4px 8px',
                                borderRadius: tokens.radius.full,
                                fontSize: tokens.font.sm,
                                textTransform: 'capitalize',
                              }}
                            >
                              {statusBadge.label}
                            </span>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}

            <div
              style={{
                padding: '16px 20px',
                borderTop: '1px solid #1c1c1c',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                gap: '12px',
                flexWrap: 'wrap',
              }}
            >
              <p style={{ margin: 0, color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                Page {Math.min(invitePage + 1, totalInvitePages)} of {totalInvitePages}
              </p>

              <div style={{ display: 'flex', gap: '8px' }}>
                <button
                  onClick={() => setInvitePage((page) => Math.max(0, page - 1))}
                  disabled={invitePage === 0 || isLoadingInvites}
                  style={{
                    padding: '8px 14px',
                    borderRadius: tokens.radius.full,
                    border: '1px solid #242424',
                    backgroundColor: 'transparent',
                    color: '#555',
                    opacity: invitePage === 0 || isLoadingInvites ? 0.5 : 1,
                    cursor: invitePage === 0 || isLoadingInvites ? 'default' : 'pointer',
                  }}
                >
                  Previous
                </button>
                <button
                  onClick={() => setInvitePage((page) => (page + 1 < totalInvitePages ? page + 1 : page))}
                  disabled={invitePage + 1 >= totalInvitePages || isLoadingInvites}
                  style={{
                    padding: '8px 14px',
                    borderRadius: tokens.radius.full,
                    border: '1px solid #242424',
                    backgroundColor: 'transparent',
                    color: '#555',
                    opacity: invitePage + 1 >= totalInvitePages || isLoadingInvites ? 0.5 : 1,
                    cursor: invitePage + 1 >= totalInvitePages || isLoadingInvites ? 'default' : 'pointer',
                  }}
                >
                  Next
                </button>
              </div>
            </div>
          </section>

        </div>
      ) : activeTab === 'campaigns' ? (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '16px', alignItems: 'flex-start' }}>
          <section
            style={{
              flex: '2 1 720px',
              backgroundColor: tokens.colors.surface,
              borderRadius: tokens.radius.lg,
              border: '1px solid #242424',
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                padding: '20px',
                borderBottom: '1px solid #1c1c1c',
                display: 'flex',
                justifyContent: 'space-between',
                gap: '12px',
                flexWrap: 'wrap',
                alignItems: 'end',
              }}
            >
              <div>
                <h2
                  style={{
                    fontSize: tokens.font.lg,
                    fontWeight: Number(tokens.font.weightSemibold),
                    color: tokens.colors.textPrimary,
                    marginBottom: '6px',
                  }}
                >
                  Invite campaigns
                </h2>
                <p style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm, margin: 0 }}>
                  Campaign windows, per-user allowances, and invite lineage.
                </p>
              </div>
            </div>

            <form
              onSubmit={submitCampaignCreate}
              style={{
                padding: '20px',
                borderBottom: '1px solid #1c1c1c',
                backgroundColor: '#141414',
                display: 'grid',
                gap: '12px',
              }}
            >
              <div style={{ display: 'grid', gap: '12px', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }}>
                <input
                  type="text"
                  value={campaignForm.name}
                  onChange={(event) => setCampaignForm((current) => ({ ...current, name: event.target.value }))}
                  placeholder="Campaign name"
                  style={{ padding: '10px 12px', border: '1px solid #242424', borderRadius: '8px', backgroundColor: '#0a0a0a', color: tokens.colors.textPrimary, fontSize: tokens.font.sm, outline: 'none' }}
                />
                <input
                  type="text"
                  value={campaignForm.slug}
                  onChange={(event) => setCampaignForm((current) => ({ ...current, slug: event.target.value }))}
                  placeholder="campaign-slug"
                  style={{ padding: '10px 12px', border: '1px solid #242424', borderRadius: '8px', backgroundColor: '#0a0a0a', color: tokens.colors.textPrimary, fontSize: tokens.font.sm, outline: 'none' }}
                />
                <input
                  type="text"
                  value={campaignForm.public_label}
                  onChange={(event) => setCampaignForm((current) => ({ ...current, public_label: event.target.value }))}
                  placeholder="Public label"
                  style={{ padding: '10px 12px', border: '1px solid #242424', borderRadius: '8px', backgroundColor: '#0a0a0a', color: tokens.colors.textPrimary, fontSize: tokens.font.sm, outline: 'none' }}
                />
                <input
                  type="text"
                  value={campaignForm.internal_note}
                  onChange={(event) => setCampaignForm((current) => ({ ...current, internal_note: event.target.value }))}
                  placeholder="Internal note"
                  style={{ padding: '10px 12px', border: '1px solid #242424', borderRadius: '8px', backgroundColor: '#0a0a0a', color: tokens.colors.textPrimary, fontSize: tokens.font.sm, outline: 'none' }}
                />
                <input
                  type="datetime-local"
                  value={campaignForm.active_from}
                  onChange={(event) => setCampaignForm((current) => ({ ...current, active_from: event.target.value }))}
                  style={{ padding: '10px 12px', border: '1px solid #242424', borderRadius: '8px', backgroundColor: '#0a0a0a', color: tokens.colors.textPrimary, fontSize: tokens.font.sm, outline: 'none' }}
                />
                <input
                  type="datetime-local"
                  value={campaignForm.expires_at}
                  onChange={(event) => setCampaignForm((current) => ({ ...current, expires_at: event.target.value }))}
                  style={{ padding: '10px 12px', border: '1px solid #242424', borderRadius: '8px', backgroundColor: '#0a0a0a', color: tokens.colors.textPrimary, fontSize: tokens.font.sm, outline: 'none' }}
                />
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={campaignForm.max_uses_total}
                  onChange={(event) => setCampaignForm((current) => ({ ...current, max_uses_total: event.target.value }))}
                  placeholder="Maximum total invites"
                  style={{ padding: '10px 12px', border: '1px solid #242424', borderRadius: '8px', backgroundColor: '#0a0a0a', color: tokens.colors.textPrimary, fontSize: tokens.font.sm, outline: 'none' }}
                />
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={campaignForm.per_user_invite_allowance}
                  onChange={(event) => setCampaignForm((current) => ({ ...current, per_user_invite_allowance: event.target.value }))}
                  placeholder="Per-user allowance"
                  style={{ padding: '10px 12px', border: '1px solid #242424', borderRadius: '8px', backgroundColor: '#0a0a0a', color: tokens.colors.textPrimary, fontSize: tokens.font.sm, outline: 'none' }}
                />
              </div>

              <textarea
                value={campaignForm.description}
                onChange={(event) => setCampaignForm((current) => ({ ...current, description: event.target.value }))}
                placeholder="Description"
                rows={3}
                style={{ padding: '10px 12px', border: '1px solid #242424', borderRadius: '8px', backgroundColor: '#0a0a0a', color: tokens.colors.textPrimary, fontSize: tokens.font.sm, outline: 'none', resize: 'vertical' }}
              />

              <label style={{ display: 'inline-flex', gap: '8px', alignItems: 'center', color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                <input
                  type="checkbox"
                  checked={campaignForm.is_active}
                  onChange={(event) => setCampaignForm((current) => ({ ...current, is_active: event.target.checked }))}
                />
                Start active
              </label>

              <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                <button type="submit" disabled={isSubmittingCampaign} style={{ padding: '10px 16px', borderRadius: tokens.radius.full, border: '1px solid #242424', backgroundColor: 'transparent', color: '#888', fontSize: tokens.font.sm, cursor: isSubmittingCampaign ? 'default' : 'pointer', opacity: isSubmittingCampaign ? 0.6 : 1 }}>
                  {isSubmittingCampaign ? 'Saving…' : 'Create campaign'}
                </button>
                {selectedCampaignId ? (
                  <button type="button" onClick={() => void submitCampaignUpdate()} disabled={isSubmittingCampaign} style={{ padding: '10px 16px', borderRadius: tokens.radius.full, border: '1px solid #242424', backgroundColor: 'transparent', color: '#888', fontSize: tokens.font.sm, cursor: isSubmittingCampaign ? 'default' : 'pointer', opacity: isSubmittingCampaign ? 0.6 : 1 }}>
                    Save campaign changes
                  </button>
                ) : null}
                <button type="button" onClick={resetCampaignForm} style={{ padding: '10px 16px', borderRadius: tokens.radius.full, border: '1px solid #242424', backgroundColor: 'transparent', color: '#888', fontSize: tokens.font.sm, cursor: 'pointer' }}>
                  Reset form
                </button>
              </div>

              {campaignFormError ? (
                <p style={{ margin: 0, color: tokens.colors.danger, fontSize: tokens.font.sm }}>{campaignFormError}</p>
              ) : null}
            </form>

            {isLoadingCampaigns ? (
              <div style={{ padding: '32px 20px', color: tokens.colors.textSecondary }}>Loading campaigns…</div>
            ) : campaignsError ? (
              <div style={{ padding: '32px 20px', color: tokens.colors.danger }}>{campaignsError}</div>
            ) : campaigns.length === 0 ? (
              <div style={{ padding: '32px 20px', color: tokens.colors.textSecondary }}>No invite campaigns yet.</div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr>
                      {['Name', 'Slug', 'Window', 'Allowance', 'Generated', 'Consumed', 'Status'].map((heading) => (
                        <th key={heading} style={{ padding: '12px 16px', textAlign: 'left', fontSize: '11px', fontWeight: 400, textTransform: 'uppercase', letterSpacing: '0.06em', color: '#404040', borderBottom: '1px solid #1c1c1c', whiteSpace: 'nowrap' }}>
                          {heading}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {campaigns.map((campaign) => (
                      <tr
                        key={campaign.id}
                        onClick={() => {
                          populateCampaignForm(campaign)
                          void openCampaignDetail(campaign.id)
                        }}
                        style={{ borderBottom: '1px solid #1c1c1c', backgroundColor: campaign.id === selectedCampaignId ? '#0f0f0f' : 'transparent', cursor: 'pointer' }}
                      >
                        <td style={{ padding: '16px', color: tokens.colors.textPrimary, fontSize: tokens.font.sm }}>{campaign.name}</td>
                        <td style={{ padding: '16px', color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>{campaign.slug}</td>
                        <td style={{ padding: '16px', color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>{campaign.expires_at ? formatDate(campaign.expires_at) : 'Open-ended'}</td>
                        <td style={{ padding: '16px', color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>{campaign.per_user_invite_allowance}</td>
                        <td style={{ padding: '16px', color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>{campaign.generated_count}</td>
                        <td style={{ padding: '16px', color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>{campaign.consumed_count}</td>
                        <td style={{ padding: '16px', color: campaign.is_active ? tokens.colors.success : tokens.colors.textSecondary, fontSize: tokens.font.sm }}>{campaign.is_active ? 'Active' : 'Inactive'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <aside
            style={{
              flex: '1 1 320px',
              minWidth: '300px',
              backgroundColor: tokens.colors.surface,
              borderRadius: tokens.radius.lg,
              border: '1px solid #242424',
              overflow: 'hidden',
            }}
          >
            <div style={{ padding: '20px', borderBottom: '1px solid #1c1c1c' }}>
              <h3 style={{ margin: 0, color: tokens.colors.textPrimary, fontSize: tokens.font.md, fontWeight: Number(tokens.font.weightSemibold) }}>
                Campaign detail
              </h3>
            </div>
            {isLoadingCampaignDetail ? (
              <div style={{ padding: '20px', color: tokens.colors.textSecondary }}>Loading campaign details…</div>
            ) : campaignDetailError ? (
              <div style={{ padding: '20px', color: tokens.colors.danger }}>{campaignDetailError}</div>
            ) : selectedCampaign ? (
              <div style={{ padding: '20px', display: 'grid', gap: '14px' }}>
                <div>
                  <div style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.md, fontWeight: Number(tokens.font.weightSemibold) }}>
                    {selectedCampaign.name}
                  </div>
                  <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm, marginTop: '4px' }}>
                    /{selectedCampaign.slug}
                  </div>
                </div>
                <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm, lineHeight: 1.6 }}>
                  {selectedCampaign.description || 'No description'}
                </div>
                <div style={{ display: 'grid', gap: '6px', color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                  <div>Generated: {selectedCampaign.generated_count}</div>
                  <div>Consumed: {selectedCampaign.consumed_count}</div>
                  <div>Remaining capacity: {selectedCampaign.remaining_generation_capacity ?? 'Unlimited'}</div>
                </div>
                <div>
                  <div style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.sm, marginBottom: '8px' }}>Latest invites</div>
                  <div style={{ display: 'grid', gap: '8px' }}>
                    {selectedCampaign.invites.slice(0, 5).map((invite) => (
                      <div key={invite.id} style={{ padding: '10px 12px', border: '1px solid #242424', borderRadius: '8px', color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                        <div>{invite.code}</div>
                        <div style={{ marginTop: '4px' }}>Generator: {invite.generated_by_username || '-'}</div>
                        <div>Used by: {invite.used_by_username || '-'}</div>
                      </div>
                    ))}
                  </div>
                </div>
                <div>
                  <div style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.sm, marginBottom: '8px' }}>Registrations</div>
                  <div style={{ display: 'grid', gap: '8px' }}>
                    {selectedCampaign.registrations.slice(0, 5).map((registration) => (
                      <div key={registration.id} style={{ padding: '10px 12px', border: '1px solid #242424', borderRadius: '8px', color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                        @{registration.username}
                      </div>
                    ))}
                    {selectedCampaign.registrations.length === 0 ? (
                      <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>No registrations yet.</div>
                    ) : null}
                  </div>
                </div>
              </div>
            ) : (
              <div style={{ padding: '20px', color: tokens.colors.textSecondary }}>Select a campaign to inspect invite lineage and registrations.</div>
            )}
          </aside>
        </div>
      ) : activeTab === 'moderation' ? (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '16px', alignItems: 'flex-start' }}>
          <section
            style={{
              flex: '2 1 760px',
              backgroundColor: tokens.colors.surface,
              borderRadius: tokens.radius.lg,
              border: '1px solid #242424',
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                padding: '20px',
                borderBottom: '1px solid #1c1c1c',
                display: 'grid',
                gap: '14px',
              }}
            >
              <div>
                <h2
                  style={{
                    fontSize: tokens.font.lg,
                    fontWeight: Number(tokens.font.weightSemibold),
                    color: tokens.colors.textPrimary,
                    marginBottom: '6px',
                  }}
                >
                  Moderation Review Queue
                </h2>
                <p style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm, margin: 0 }}>
                  Suspicious and blocked runtime signals land here for manual review and audited action.
                </p>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px' }}>
                <div style={{ padding: '16px 20px', borderRadius: '10px', backgroundColor: '#141414', border: '1px solid #242424' }}>
                  <div style={{ color: '#555', fontSize: '12px', marginBottom: '4px' }}>Open suspicious</div>
                  <div style={{ color: '#f0f0f0', fontSize: '24px', fontWeight: 500 }}>
                    {moderationDashboard?.open_suspicious_count ?? '-'}
                  </div>
                </div>
                <div style={{ padding: '16px 20px', borderRadius: '10px', backgroundColor: '#141414', border: '1px solid #242424' }}>
                  <div style={{ color: '#555', fontSize: '12px', marginBottom: '4px' }}>Blocked items</div>
                  <div style={{ color: '#f0f0f0', fontSize: '24px', fontWeight: 500 }}>
                    {moderationDashboard?.blocked_items_count ?? '-'}
                  </div>
                </div>
              </div>

              <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
                <select
                  value={moderationFilter}
                  onChange={(event) => setModerationFilter(event.target.value as 'all' | 'open' | 'resolved' | 'dismissed')}
                  style={{
                    padding: '10px 12px',
                    border: '1px solid #242424',
                    borderRadius: '8px',
                    backgroundColor: '#141414',
                    color: tokens.colors.textPrimary,
                    fontSize: tokens.font.sm,
                    outline: 'none',
                  }}
                >
                  <option value="open">Open only</option>
                  <option value="resolved">Resolved only</option>
                  <option value="dismissed">Dismissed only</option>
                  <option value="all">All review states</option>
                </select>

                <select
                  value={moderationSurfaceFilter}
                  onChange={(event) => setModerationSurfaceFilter(event.target.value)}
                  style={{
                    padding: '10px 12px',
                    border: '1px solid #242424',
                    borderRadius: '8px',
                    backgroundColor: '#141414',
                    color: tokens.colors.textPrimary,
                    fontSize: tokens.font.sm,
                    outline: 'none',
                  }}
                >
                  <option value="all">All surfaces</option>
                  <option value="profile_avatar">Profile avatar</option>
                  <option value="profile_cover">Profile cover</option>
                  <option value="profile_display_name">Display name</option>
                  <option value="profile_bio">Profile bio</option>
                  <option value="post_text">Post text</option>
                  <option value="post_media">Post media</option>
                  <option value="dm_text">DM text</option>
                  <option value="dm_media">DM media</option>
                </select>
              </div>
            </div>

            {isLoadingModerationQueue ? (
              <div style={{ padding: '32px 20px', color: tokens.colors.textSecondary }}>Loading moderation queue...</div>
            ) : moderationQueueError ? (
              <div style={{ padding: '32px 20px', color: tokens.colors.danger }}>{moderationQueueError}</div>
            ) : moderationQueue.length === 0 ? (
              <div style={{ padding: '32px 20px', color: '#404040', textAlign: 'center' }}>No moderation items match the current filters.</div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ backgroundColor: 'transparent' }}>
                      {['Queue ID', 'Surface', 'Actor', 'Detection', 'Review', 'Risk', 'Reason', 'Created'].map((heading) => (
                        <th
                          key={heading}
                          style={{
                            padding: '12px 16px',
                            textAlign: 'left',
                            fontSize: '11px',
                            fontWeight: 400,
                            textTransform: 'uppercase' as const,
                            letterSpacing: '0.06em',
                            color: '#404040',
                            borderBottom: '1px solid #1c1c1c',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {heading}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {moderationQueue.map((signal) => {
                      const detectionBadge = getDetectionBadge(signal.detection_status)
                      const reviewBadge = getReviewBadge(signal.review_status)
                      const isSelected = signal.id === selectedModerationSignalId

                      return (
                        <tr
                          key={signal.id}
                          onClick={() => void openModerationSignalDetail(signal.id)}
                          style={{
                            borderBottom: '1px solid #1c1c1c',
                            backgroundColor: isSelected ? '#0f0f0f' : 'transparent',
                            cursor: 'pointer',
                          }}
                        >
                          <td style={{ padding: '16px', color: tokens.colors.textPrimary, fontSize: tokens.font.sm }}>#{signal.id}</td>
                          <td style={{ padding: '16px', color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>{formatSurfaceLabel(signal.surface_type)}</td>
                          <td style={{ padding: '16px', color: tokens.colors.textPrimary, fontSize: tokens.font.sm }}>
                            <div style={{ display: 'grid', gap: '4px' }}>
                              <span>@{signal.actor_user?.username || 'unknown'}</span>
                              {signal.is_media_signal ? (
                                <span style={{ color: signal.has_media_preview ? tokens.colors.accent : tokens.colors.textSecondary, fontSize: tokens.font.xs }}>
                                  {signal.has_media_preview ? 'Media preview available' : 'No media preview'}
                                </span>
                              ) : null}
                            </div>
                          </td>
                          <td style={{ padding: '16px' }}>
                            <span style={{ backgroundColor: detectionBadge.backgroundColor, border: detectionBadge.border, color: detectionBadge.color, padding: '4px 8px', borderRadius: tokens.radius.full, fontSize: tokens.font.sm, textTransform: 'capitalize' }}>
                              {signal.detection_status}
                            </span>
                          </td>
                          <td style={{ padding: '16px' }}>
                            <span style={{ backgroundColor: reviewBadge.backgroundColor, border: reviewBadge.border, color: reviewBadge.color, padding: '4px 8px', borderRadius: tokens.radius.full, fontSize: tokens.font.sm, textTransform: 'capitalize' }}>
                              {signal.review_status}
                            </span>
                          </td>
                          <td style={{ padding: '16px', color: tokens.colors.textPrimary, fontSize: tokens.font.sm }}>{signal.risk_score}</td>
                          <td style={{ padding: '16px', color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>{signal.reason_summary}</td>
                          <td style={{ padding: '16px', color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>{formatDateTime(signal.created_at)}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <aside
            style={{
              flex: '1 1 320px',
              minWidth: '300px',
              backgroundColor: tokens.colors.surface,
              borderRadius: tokens.radius.lg,
              border: '1px solid #242424',
              overflow: 'hidden',
            }}
          >
            <div style={{ padding: '20px', borderBottom: '1px solid #1c1c1c' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'start' }}>
                <div>
                  <h3 style={{ fontSize: tokens.font.md, fontWeight: Number(tokens.font.weightSemibold), color: tokens.colors.textPrimary, marginBottom: '6px' }}>
                    Queue Detail
                  </h3>
                  <p style={{ margin: 0, color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                    Inspect flagged content and apply audited moderation actions.
                  </p>
                </div>
                {selectedModerationSignal && (
                  <button
                    onClick={closeModerationSignalDetail}
                    style={{ background: 'none', border: 'none', color: tokens.colors.textSecondary, cursor: 'pointer', fontSize: tokens.font.sm, padding: 0 }}
                  >
                    Clear
                  </button>
                )}
              </div>
            </div>

            {isLoadingModerationDetail ? (
              <div style={{ padding: '20px', color: tokens.colors.textSecondary }}>Loading queue detail...</div>
            ) : moderationDetailError ? (
              <div style={{ padding: '20px', color: tokens.colors.danger }}>{moderationDetailError}</div>
            ) : selectedModerationSignal ? (
              <div style={{ padding: '20px', display: 'grid', gap: '16px' }}>
                <div style={{ display: 'grid', gap: '8px' }}>
                  <div style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.base, fontWeight: Number(tokens.font.weightSemibold) }}>
                    #{selectedModerationSignal.id} · {formatSurfaceLabel(selectedModerationSignal.surface_type)}
                  </div>
                  <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                    Actor: {selectedModerationSignal.actor_user ? (
                      <button
                        onClick={() => void openUserDetail(selectedModerationSignal.actor_user!.id)}
                        style={{ background: 'none', border: 'none', color: tokens.colors.accent, cursor: 'pointer', padding: 0 }}
                      >
                        @{selectedModerationSignal.actor_user.username}
                      </button>
                    ) : 'Unknown'}
                  </div>
                  <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                    Risk {selectedModerationSignal.risk_score} · {formatDateTime(selectedModerationSignal.created_at)}
                  </div>
                </div>

                <div style={{ display: 'grid', gap: '10px', padding: '12px', borderRadius: tokens.radius.md, backgroundColor: tokens.colors.bg, border: `1px solid ${tokens.colors.border}` }}>
                  <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>Reason summary</span>
                  <span style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.sm }}>{selectedModerationSignal.reason_summary}</span>
                  {selectedModerationSignal.reason_codes.length > 0 && (
                    <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.xs }}>
                      Codes: {selectedModerationSignal.reason_codes.join(', ')}
                    </span>
                  )}
                </div>

                {selectedModerationSignal.media_signal_counts ? (
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '10px' }}>
                    <div style={{ padding: '12px', borderRadius: tokens.radius.md, backgroundColor: tokens.colors.bg, border: `1px solid ${tokens.colors.border}` }}>
                      <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.xs, marginBottom: '4px' }}>
                        Suspicious media in last {selectedModerationSignal.media_signal_counts.window_days} days
                      </div>
                      <div style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.lg, fontWeight: Number(tokens.font.weightBold) }}>
                        {selectedModerationSignal.media_signal_counts.recent_suspicious_media_signals}
                      </div>
                    </div>
                    <div style={{ padding: '12px', borderRadius: tokens.radius.md, backgroundColor: tokens.colors.bg, border: `1px solid ${tokens.colors.border}` }}>
                      <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.xs, marginBottom: '4px' }}>
                        Blocked media in last {selectedModerationSignal.media_signal_counts.window_days} days
                      </div>
                      <div style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.lg, fontWeight: Number(tokens.font.weightBold) }}>
                        {selectedModerationSignal.media_signal_counts.recent_blocked_media_signals}
                      </div>
                    </div>
                  </div>
                ) : null}

                {selectedModerationSignal.content_preview && (
                  <div style={{ display: 'grid', gap: '8px' }}>
                    <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                      {selectedModerationSignal.is_media_signal ? 'Upload metadata' : 'Text preview'}
                    </span>
                    <div style={{ padding: '12px', borderRadius: tokens.radius.md, backgroundColor: tokens.colors.bg, border: `1px solid ${tokens.colors.border}`, color: tokens.colors.textPrimary, fontSize: tokens.font.sm, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                      {selectedModerationSignal.content_preview}
                    </div>
                  </div>
                )}

                {selectedModerationSignal.media_preview_url && (
                  <div style={{ display: 'grid', gap: '8px' }}>
                    <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                      Media preview {selectedModerationSignal.review_status === 'open' ? '(review copy)' : ''}
                    </span>
                    <img
                      src={resolveMediaUrl(selectedModerationSignal.media_preview_url) || undefined}
                      alt="Flagged media"
                      style={{ width: '100%', borderRadius: tokens.radius.md, border: `1px solid ${tokens.colors.border}` }}
                    />
                  </div>
                )}

                {selectedModerationSignal.target_post && renderAdminPostSummary(selectedModerationSignal.target_post, 'Related post')}

                {selectedModerationSignal.target_dm_message && (
                  <div style={{ display: 'grid', gap: '8px' }}>
                    <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>Related DM</span>
                    <div style={{ padding: '12px', borderRadius: tokens.radius.md, backgroundColor: tokens.colors.bg, border: `1px solid ${tokens.colors.border}`, display: 'grid', gap: '6px' }}>
                      <span style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.sm }}>
                        @{selectedModerationSignal.target_dm_message.sender?.username || 'unknown'} to @{selectedModerationSignal.target_dm_message.receiver?.username || 'unknown'}
                      </span>
                      <span style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.sm, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                        {selectedModerationSignal.target_dm_message.content}
                      </span>
                    </div>
                  </div>
                )}

                <div style={{ display: 'grid', gap: '8px' }}>
                  <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>Resolution note</span>
                  <textarea
                    value={moderationActionNote}
                    onChange={(event) => setModerationActionNote(event.target.value)}
                    placeholder="Optional note for audit trail"
                    rows={3}
                    style={{
                      width: '100%',
                      boxSizing: 'border-box',
                      padding: '12px',
                      border: `1px solid ${tokens.colors.border}`,
                      borderRadius: tokens.radius.md,
                      backgroundColor: tokens.colors.bg,
                      color: tokens.colors.textPrimary,
                      fontSize: tokens.font.sm,
                      resize: 'vertical',
                    }}
                  />
                </div>

                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                  <button
                    onClick={() => void submitModerationSignalAction('approve')}
                    disabled={isSubmittingModerationSignalAction || selectedModerationSignal.review_status !== 'open'}
                    style={{ padding: '8px 14px', borderRadius: tokens.radius.full, border: '1px solid #242424', backgroundColor: 'transparent', color: '#555', cursor: 'pointer', opacity: isSubmittingModerationSignalAction || selectedModerationSignal.review_status !== 'open' ? 0.6 : 1 }}
                  >
                    Clear
                  </button>
                  {selectedModerationSignal.post_id && (
                    <>
                      <button
                        onClick={() => void submitModerationSignalAction('hide_post')}
                        disabled={isSubmittingModerationSignalAction || selectedModerationSignal.review_status !== 'open'}
                        style={{ padding: '8px 14px', borderRadius: tokens.radius.full, border: '1px solid #242424', backgroundColor: 'transparent', color: '#555', cursor: 'pointer', opacity: isSubmittingModerationSignalAction || selectedModerationSignal.review_status !== 'open' ? 0.6 : 1 }}
                      >
                        Hide post
                      </button>
                      <button
                        onClick={() => void submitModerationSignalAction('delete_post')}
                        disabled={isSubmittingModerationSignalAction || selectedModerationSignal.review_status !== 'open'}
                        style={{ padding: '8px 14px', borderRadius: tokens.radius.full, border: '1px solid #3a2a2a', backgroundColor: 'transparent', color: '#9a6a6a', cursor: 'pointer', opacity: isSubmittingModerationSignalAction || selectedModerationSignal.review_status !== 'open' ? 0.6 : 1 }}
                      >
                        Delete post
                      </button>
                    </>
                  )}
                  <button
                    onClick={() => void submitModerationSignalAction('freeze_user')}
                    disabled={isSubmittingModerationSignalAction || selectedModerationSignal.review_status !== 'open'}
                    style={{ padding: '8px 14px', borderRadius: tokens.radius.full, border: '1px solid #242424', backgroundColor: 'transparent', color: '#555', cursor: 'pointer', opacity: isSubmittingModerationSignalAction || selectedModerationSignal.review_status !== 'open' ? 0.6 : 1 }}
                  >
                    Freeze user
                  </button>
                  <button
                    onClick={() => void submitModerationSignalAction('suspend_user')}
                    disabled={isSubmittingModerationSignalAction || selectedModerationSignal.review_status !== 'open'}
                    style={{ padding: '8px 14px', borderRadius: tokens.radius.full, border: '1px solid #242424', backgroundColor: 'transparent', color: '#555', cursor: 'pointer', opacity: isSubmittingModerationSignalAction || selectedModerationSignal.review_status !== 'open' ? 0.6 : 1 }}
                  >
                    Suspend user
                  </button>
                  <button
                    onClick={() => void submitModerationSignalAction('ban_user')}
                    disabled={isSubmittingModerationSignalAction || selectedModerationSignal.review_status !== 'open'}
                    style={{ padding: '8px 14px', borderRadius: tokens.radius.full, border: '1px solid #3a2a2a', backgroundColor: 'transparent', color: '#9a6a6a', cursor: 'pointer', opacity: isSubmittingModerationSignalAction || selectedModerationSignal.review_status !== 'open' ? 0.6 : 1 }}
                  >
                    Ban user
                  </button>
                  <button
                    onClick={() => void submitModerationSignalAction('dismiss_signal')}
                    disabled={isSubmittingModerationSignalAction || selectedModerationSignal.review_status !== 'open'}
                    style={{ padding: '8px 14px', borderRadius: tokens.radius.full, border: '1px solid #242424', backgroundColor: 'transparent', color: '#555', cursor: 'pointer', opacity: isSubmittingModerationSignalAction || selectedModerationSignal.review_status !== 'open' ? 0.6 : 1 }}
                  >
                    Dismiss
                  </button>
                </div>

                <div style={{ display: 'grid', gap: '8px' }}>
                  <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>Audit history</span>
                  {selectedModerationSignal.audit_history.length > 0 ? (
                    selectedModerationSignal.audit_history.map((entry) => (
                      <div
                        key={`signal-history-${entry.id}`}
                        style={{
                          padding: '10px 12px',
                          borderRadius: tokens.radius.md,
                          backgroundColor: tokens.colors.bg,
                          border: `1px solid ${tokens.colors.border}`,
                          display: 'grid',
                          gap: '4px',
                        }}
                      >
                        <span style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.sm }}>{entry.action}</span>
                        <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.xs }}>
                          {formatDateTime(entry.created_at)} {entry.reason ? `· ${entry.reason}` : ''}
                        </span>
                      </div>
                    ))
                  ) : (
                    <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>No audit entries yet.</span>
                  )}
                </div>

                {moderationDashboard && moderationDashboard.newest_unresolved_items.length > 0 && (
                  <div style={{ display: 'grid', gap: '8px' }}>
                    <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>Newest unresolved</span>
                    {moderationDashboard.newest_unresolved_items.map((item) => (
                      <button
                        key={`unresolved-${item.id}`}
                        onClick={() => void openModerationSignalDetail(item.id)}
                        style={{
                          textAlign: 'left',
                          padding: '10px 12px',
                          borderRadius: tokens.radius.md,
                          border: `1px solid ${tokens.colors.border}`,
                          backgroundColor: tokens.colors.bg,
                          color: tokens.colors.textPrimary,
                          cursor: 'pointer',
                        }}
                      >
                        #{item.id} · @{item.actor_user?.username || 'unknown'} · {item.reason_summary}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <div style={{ padding: '20px', color: tokens.colors.textSecondary }}>
                Select a queue item to inspect flagged text, media, related content, and moderation actions.
              </div>
            )}
          </aside>
        </div>
      ) : activeTab === 'waitlist' ? (
        <WaitlistAdminPanel token={token ?? ''} canManage={Boolean(adminSession?.capabilities.can_manage_waitlist)} />
      ) : activeTab === 'audit' ? (
        <section
          style={{
            backgroundColor: tokens.colors.surface,
            borderRadius: tokens.radius.lg,
            border: '1px solid #242424',
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              padding: '20px',
              borderBottom: '1px solid #1c1c1c',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              gap: '12px',
              flexWrap: 'wrap',
            }}
          >
            <div>
              <h2
                style={{
                  fontSize: tokens.font.lg,
                  fontWeight: Number(tokens.font.weightSemibold),
                  color: tokens.colors.textPrimary,
                  marginBottom: '6px',
                }}
              >
                Audit Log
              </h2>
              <p style={{ margin: 0, color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                {auditLogsTotal} entries across all admin actions.
              </p>
            </div>
          </div>

          {isLoadingAuditLogs && auditLogs.length === 0 ? (
            <div style={{ padding: '32px 20px', color: tokens.colors.textSecondary }}>Loading audit logs…</div>
          ) : auditLogsError ? (
            <div style={{ padding: '32px 20px', color: tokens.colors.danger }}>{auditLogsError}</div>
          ) : auditLogs.length === 0 ? (
            <div style={{ padding: '32px 20px', color: tokens.colors.textSecondary }}>No audit log entries found.</div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ backgroundColor: 'transparent' }}>
                    {['Timestamp', 'Admin Role', 'Action', 'Target Type', 'Target ID', 'Reason', 'Success'].map((heading) => (
                      <th
                        key={heading}
                        style={{
                          padding: '12px 16px',
                          textAlign: 'left',
                          fontSize: '11px',
                          fontWeight: 400,
                          textTransform: 'uppercase' as const,
                          letterSpacing: '0.06em',
                          color: '#404040',
                          borderBottom: '1px solid #1c1c1c',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {heading}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {auditLogs.map((log) => (
                    <tr
                      key={log.id}
                      style={{
                        borderBottom: '1px solid #1c1c1c',
                      }}
                    >
                      <td style={{ padding: '16px', color: tokens.colors.textSecondary, fontSize: tokens.font.sm, whiteSpace: 'nowrap' }}>
                        {new Date(log.created_at).toLocaleString()}
                      </td>
                      <td style={{ padding: '16px', color: tokens.colors.textPrimary, fontSize: tokens.font.sm }}>
                        {log.actor_role || '-'}
                      </td>
                      <td style={{ padding: '16px', color: tokens.colors.textPrimary, fontSize: tokens.font.sm }}>
                        {log.action}
                      </td>
                      <td style={{ padding: '16px', color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                        {log.target_type}
                      </td>
                      <td style={{ padding: '16px', color: tokens.colors.textSecondary, fontSize: tokens.font.sm, fontFamily: 'monospace' }}>
                        {log.target_id}
                      </td>
                      <td style={{ padding: '16px', color: tokens.colors.textSecondary, fontSize: tokens.font.sm, maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {log.reason || '-'}
                      </td>
                      <td style={{ padding: '16px', fontSize: tokens.font.sm }}>
                        <span
                          style={{
                            padding: '4px 8px',
                            borderRadius: tokens.radius.full,
                            fontSize: tokens.font.xs,
                            backgroundColor: 'transparent',
                            border: `1px solid ${log.success ? '#2a3a2a' : '#3a2a2a'}`,
                            color: log.success ? '#6a9a6a' : '#9a6a6a',
                          }}
                        >
                          {log.success ? 'Yes' : 'No'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {auditLogs.length < auditLogsTotal && (
            <div
              style={{
                padding: '16px 20px',
                borderTop: '1px solid #1c1c1c',
                display: 'flex',
                justifyContent: 'center',
              }}
            >
              <button
                onClick={() => setAuditLogsPage((page) => page + 1)}
                disabled={isLoadingAuditLogs}
                style={{
                  padding: '8px 14px',
                  borderRadius: tokens.radius.full,
                  border: '1px solid #242424',
                  backgroundColor: 'transparent',
                  color: '#555',
                  opacity: isLoadingAuditLogs ? 0.5 : 1,
                  cursor: isLoadingAuditLogs ? 'default' : 'pointer',
                }}
              >
                {isLoadingAuditLogs ? 'Loading...' : 'Load more'}
              </button>
            </div>
          )}
        </section>
      ) : (
        <StaffManagementPanel />
      )}

      {selectedPostId && (
        <div
          onClick={closePostDetail}
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.72)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '24px',
            zIndex: 44,
          }}
        >
          <div
            onClick={(event) => event.stopPropagation()}
            style={{
              width: 'min(760px, 100%)',
              maxHeight: 'min(88vh, 980px)',
              overflowY: 'auto',
              backgroundColor: tokens.colors.surface,
              borderRadius: tokens.radius.lg,
              border: `1px solid ${tokens.colors.border}`,
              boxShadow: '0 24px 80px rgba(0, 0, 0, 0.45)',
            }}
          >
            <div
              style={{
                padding: '20px',
                borderBottom: `1px solid ${tokens.colors.border}`,
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                gap: '12px',
                position: 'sticky',
                top: 0,
                backgroundColor: tokens.colors.surface,
              }}
            >
              <div>
                <h2 style={{ fontSize: tokens.font.lg, fontWeight: Number(tokens.font.weightSemibold), color: tokens.colors.textPrimary, marginBottom: '6px' }}>
                  Post Moderation
                </h2>
                <p style={{ margin: 0, color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                  Post #{selectedPostId}
                </p>
              </div>
              <button
                onClick={closePostDetail}
                style={{ background: 'none', border: 'none', color: tokens.colors.textSecondary, cursor: 'pointer', fontSize: tokens.font.sm }}
              >
                Close
              </button>
            </div>

            {isLoadingPostDetail ? (
              <div style={{ padding: '20px', color: tokens.colors.textSecondary }}>Loading post detail...</div>
            ) : postDetailError ? (
              <div style={{ padding: '20px', color: tokens.colors.danger }}>{postDetailError}</div>
            ) : selectedPost ? (
              <div style={{ padding: '20px', display: 'grid', gap: '16px' }}>
                {renderAdminPostSummary(selectedPost.post)}

                  <div style={{ display: 'grid', gap: '6px' }}>
                    <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>Moderation reason</span>
                    <textarea
                      value={postModerationReason}
                    onChange={(event) => setPostModerationReason(event.target.value)}
                    placeholder="Reason required for hide/delete actions"
                    maxLength={500}
                    style={{
                      minHeight: '88px',
                      padding: '10px 12px',
                      border: `1px solid ${tokens.colors.border}`,
                      borderRadius: tokens.radius.md,
                      backgroundColor: tokens.colors.bg,
                      color: tokens.colors.textPrimary,
                      fontSize: tokens.font.sm,
                      resize: 'vertical',
                    }}
                  />
                  <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                    {selectedPost.post.moderation_status === 'hidden' ? (
                      <button
                        onClick={() => void submitPostModeration('unhide')}
                        disabled={isSubmittingPostAction}
                        style={{
                          padding: '8px 14px',
                          borderRadius: tokens.radius.full,
                          border: `1px solid ${tokens.colors.border}`,
                          backgroundColor: tokens.colors.surfaceElevated,
                          color: tokens.colors.textPrimary,
                          cursor: isSubmittingPostAction ? 'default' : 'pointer',
                          opacity: isSubmittingPostAction ? 0.6 : 1,
                        }}
                      >
                        Unhide post
                      </button>
                    ) : (
                      <button
                        onClick={() => void submitPostModeration('hide')}
                        disabled={isSubmittingPostAction || selectedPost.post.moderation_status === 'deleted'}
                        style={{
                          padding: '8px 14px',
                          borderRadius: tokens.radius.full,
                          border: `1px solid ${tokens.colors.border}`,
                          backgroundColor: tokens.colors.surfaceElevated,
                          color: tokens.colors.textPrimary,
                          cursor: isSubmittingPostAction ? 'default' : 'pointer',
                          opacity: isSubmittingPostAction || selectedPost.post.moderation_status === 'deleted' ? 0.6 : 1,
                        }}
                      >
                        Hide post
                      </button>
                    )}
                    <button
                      onClick={() => void submitPostModeration('delete')}
                      disabled={isSubmittingPostAction || selectedPost.post.moderation_status === 'deleted'}
                      style={{
                        padding: '8px 14px',
                        borderRadius: tokens.radius.full,
                        border: '1px solid #3a2a2a',
                        backgroundColor: 'transparent',
                        color: '#9a6a6a',
                        cursor: isSubmittingPostAction ? 'default' : 'pointer',
                        opacity: isSubmittingPostAction || selectedPost.post.moderation_status === 'deleted' ? 0.6 : 1,
                      }}
                    >
                      {selectedPost.post.moderation_status === 'deleted' ? 'Deleted' : 'Delete post tree'}
                    </button>
                  </div>
                </div>

                {selectedPost.parent_post && renderAdminPostSummary(selectedPost.parent_post, 'Parent')}
                {selectedPost.original_post && renderAdminPostSummary(selectedPost.original_post, 'Original post')}

                <div style={{ display: 'grid', gap: '8px' }}>
                  <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>Recent replies</span>
                  {selectedPost.recent_replies.length > 0 ? (
                    selectedPost.recent_replies.map((post) => renderAdminPostSummary(post))
                  ) : (
                    <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>No replies.</span>
                  )}
                </div>

                <div style={{ display: 'grid', gap: '8px' }}>
                  <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>Recent reposts</span>
                  {selectedPost.recent_reposts.length > 0 ? (
                    selectedPost.recent_reposts.map((post) => renderAdminPostSummary(post))
                  ) : (
                    <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>No reposts.</span>
                  )}
                </div>

                <div style={{ display: 'grid', gap: '8px' }}>
                  <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>Audit history</span>
                  {selectedPost.moderation_history.length > 0 ? (
                    selectedPost.moderation_history.map((entry) => (
                      <div
                        key={`post-history-${entry.id}`}
                        style={{
                          padding: '10px 12px',
                          borderRadius: tokens.radius.md,
                          backgroundColor: tokens.colors.bg,
                          border: `1px solid ${tokens.colors.border}`,
                          display: 'grid',
                          gap: '4px',
                        }}
                      >
                        <span style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.sm }}>{entry.action}</span>
                        <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.xs }}>
                          {formatDateTime(entry.created_at)} {entry.reason ? `· ${entry.reason}` : ''}
                        </span>
                      </div>
                    ))
                  ) : (
                    <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>No post audit entries yet.</span>
                  )}
                </div>
              </div>
            ) : (
              <div style={{ padding: '20px', color: tokens.colors.textSecondary }}>Select a post to moderate.</div>
            )}
          </div>
        </div>
      )}

      {selectedInviteId && (
        <div
          onClick={closeInviteDetail}
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.72)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '24px',
            zIndex: 45,
          }}
        >
          <div
            onClick={(event) => event.stopPropagation()}
            style={{
              width: 'min(560px, 100%)',
              maxHeight: 'min(85vh, 920px)',
              overflowY: 'auto',
              backgroundColor: tokens.colors.surface,
              borderRadius: tokens.radius.lg,
              border: `1px solid ${tokens.colors.border}`,
              boxShadow: '0 24px 80px rgba(0, 0, 0, 0.45)',
            }}
          >
            <div
              style={{
                padding: '20px',
                borderBottom: `1px solid ${tokens.colors.border}`,
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                gap: '12px',
                position: 'sticky',
                top: 0,
                backgroundColor: tokens.colors.surface,
              }}
            >
              <div>
                <h2
                  style={{
                    fontSize: tokens.font.lg,
                    fontWeight: Number(tokens.font.weightSemibold),
                    color: tokens.colors.textPrimary,
                    marginBottom: '6px',
                  }}
                >
                  Invite Detail
                </h2>
                <p style={{ margin: 0, color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                  {revealedInviteCode || (selectedInviteSummary?.code ? maskInviteCode(selectedInviteSummary.code) : 'Selected invite')}
                </p>
              </div>

              <button
                onClick={closeInviteDetail}
                style={{
                  background: 'none',
                  border: 'none',
                  color: tokens.colors.textSecondary,
                  cursor: 'pointer',
                  fontSize: tokens.font.sm,
                }}
              >
                Close
              </button>
            </div>

            {isLoadingInviteDetail ? (
              <div style={{ padding: '20px', color: tokens.colors.textSecondary }}>
                Loading invite detail...
              </div>
            ) : inviteDetailError ? (
              <div style={{ padding: '20px', color: tokens.colors.danger }}>{inviteDetailError}</div>
            ) : selectedInvite ? (
              <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '18px' }}>
                <div
                  style={{
                    padding: '14px',
                    borderRadius: tokens.radius.md,
                    border: `1px solid ${tokens.colors.border}`,
                    backgroundColor: tokens.colors.bg,
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
                    <div style={{ display: 'grid', gap: '4px' }}>
                      <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>Invite code</span>
                      <code style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.md }}>
                        {revealedInviteCode || maskInviteCode(selectedInvite.code)}
                      </code>
                      {inviteCopyFeedback ? (
                        <span style={{ color: tokens.colors.success, fontSize: tokens.font.sm }}>{inviteCopyFeedback}</span>
                      ) : null}
                    </div>
                    <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
                      {selectedInvite.can_reveal_code && !revealedInviteCode && (
                        <button
                          onClick={() => void revealSelectedInviteCode()}
                          disabled={isRevealingInviteCode}
                          style={{
                            padding: '8px 14px',
                            borderRadius: tokens.radius.full,
                            border: `1px solid ${tokens.colors.border}`,
                            backgroundColor: tokens.colors.surfaceElevated,
                            color: tokens.colors.textPrimary,
                            cursor: isRevealingInviteCode ? 'default' : 'pointer',
                            opacity: isRevealingInviteCode ? 0.7 : 1,
                          }}
                        >
                          {isRevealingInviteCode ? 'Revealing...' : 'Reveal code'}
                        </button>
                      )}
                      {revealedInviteCode ? (
                        <button
                          onClick={() => void copyRevealedInviteCode()}
                          style={{
                            padding: '8px 14px',
                            borderRadius: tokens.radius.full,
                            border: `1px solid ${tokens.colors.border}`,
                            backgroundColor: tokens.colors.surfaceElevated,
                            color: tokens.colors.textPrimary,
                            cursor: 'pointer',
                          }}
                        >
                          Copy
                        </button>
                      ) : null}
                    </div>
                  </div>
                  {!revealedInviteCode && selectedInvite.can_reveal_code && (
                    <p style={{ margin: '10px 0 0 0', color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                      Full code reveal is audited and rate limited.
                    </p>
                  )}
                </div>

                <div style={{ display: 'grid', gap: '12px' }}>
                  {[
                    ['Internal label', selectedInvite.internal_note || '-'],
                    ['Created by', selectedInvite.created_by_username || '-'],
                    ['Assigned to', selectedInvite.assigned_to_username || '-'],
                    ['Created', formatDateTime(selectedInvite.created_at)],
                    ['Expiration', formatDateTime(selectedInvite.expires_at)],
                    ['Status', getInviteStatus(selectedInvite).label],
                    ['Used', selectedInvite.used ? 'Yes' : 'No'],
                    ['Used by user', selectedInvite.used_by_username || '-'],
                    ['Used at', formatDateTime(selectedInvite.used_at)],
                  ].map(([label, value]) => (
                    <div key={label} style={{ display: 'grid', gap: '4px' }}>
                      <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>{label}</span>
                      <span
                        style={{
                          color:
                            label === 'Status'
                              ? getInviteStatus(selectedInvite).color
                              : tokens.colors.textPrimary,
                          fontSize: tokens.font.sm,
                          textTransform: label === 'Status' ? 'capitalize' : 'none',
                        }}
                      >
                        {value}
                      </span>
                    </div>
                  ))}
                </div>

                <div
                  style={{
                    borderTop: `1px solid ${tokens.colors.border}`,
                    paddingTop: '18px',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', marginBottom: '12px' }}>
                    <h3
                      style={{
                        margin: 0,
                        color: tokens.colors.textPrimary,
                        fontSize: tokens.font.md,
                        fontWeight: Number(tokens.font.weightSemibold),
                      }}
                    >
                      Registered Users
                    </h3>
                    <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                      {selectedInvite.registered_users.length} shown
                    </span>
                  </div>

                  {selectedInvite.registered_users.length === 0 ? (
                    <p style={{ margin: 0, color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                      No users have registered with this invite yet.
                    </p>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                      {selectedInvite.registered_users.map((user) => (
                        <div
                          key={user.id}
                          style={{
                            padding: '12px',
                            borderRadius: tokens.radius.md,
                            backgroundColor: tokens.colors.bg,
                            border: `1px solid ${tokens.colors.border}`,
                          }}
                        >
                          <div
                            style={{
                              display: 'flex',
                              justifyContent: 'space-between',
                              gap: '12px',
                              marginBottom: '6px',
                              flexWrap: 'wrap',
                            }}
                          >
                            <button
                              onClick={() => void openUserFromInviteDetail(user.id)}
                              style={{
                                background: 'none',
                                border: 'none',
                                color: tokens.colors.textPrimary,
                                cursor: 'pointer',
                                padding: 0,
                                fontSize: tokens.font.sm,
                              }}
                            >
                              {user.username}
                            </button>
                            <span
                              style={{
                                color: getUserStatusBadge(user.status).color,
                                fontSize: tokens.font.sm,
                                textTransform: 'capitalize',
                              }}
                            >
                              {user.status}
                            </span>
                          </div>
                          <p style={{ margin: '0 0 4px 0', color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                            {user.display_name || 'No display name'}
                          </p>
                          <p style={{ margin: '0 0 4px 0', color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                            {user.email || 'No email'}
                          </p>
                          <p style={{ margin: 0, color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                            Registered {formatDate(user.created_at)}
                          </p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <div style={{ padding: '20px', color: tokens.colors.textSecondary }}>
                Select an invite to inspect usage and traceability.
              </div>
            )}
          </div>
        </div>
      )}

      {confirmState && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.7)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '16px',
            zIndex: 50,
          }}
        >
          <div
            style={{
              width: '100%',
              maxWidth: '460px',
              backgroundColor: tokens.colors.surface,
              border: `1px solid ${tokens.colors.border}`,
              borderRadius: tokens.radius.lg,
              padding: '20px',
            }}
          >
            <h2
              style={{
                marginTop: 0,
                marginBottom: '8px',
                color: tokens.colors.textPrimary,
                fontSize: tokens.font.lg,
                fontWeight: Number(tokens.font.weightSemibold),
              }}
            >
              {getActionConfig(confirmState.action).title}
            </h2>
            <p style={{ marginTop: 0, marginBottom: '16px', color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
              {getActionConfig(confirmState.action).message} User: {confirmState.user.username}
            </p>

            {getActionConfig(confirmState.action).requiresReason && (
              <div style={{ marginBottom: '16px' }}>
                <label
                  htmlFor="actionReason"
                  style={{
                    display: 'block',
                    marginBottom: '8px',
                    color: tokens.colors.textPrimary,
                    fontSize: tokens.font.sm,
                  }}
                >
                  Moderation reason
                </label>
                <textarea
                  id="actionReason"
                  value={actionReason}
                  onChange={(event) => setActionReason(event.target.value)}
                  rows={4}
                  placeholder="Required"
                  style={{
                    width: '100%',
                    padding: '12px',
                    boxSizing: 'border-box',
                    borderRadius: tokens.radius.md,
                    border: `1px solid ${tokens.colors.border}`,
                    backgroundColor: tokens.colors.bg,
                    color: tokens.colors.textPrimary,
                    fontSize: tokens.font.sm,
                    resize: 'vertical',
                  }}
                />
              </div>
            )}

            {actionError && (
              <div
                style={{
                  marginBottom: '16px',
                  padding: '10px 12px',
                  backgroundColor: 'rgba(244, 33, 46, 0.1)',
                  border: `1px solid ${tokens.colors.danger}`,
                  borderRadius: tokens.radius.md,
                  color: tokens.colors.danger,
                  fontSize: tokens.font.sm,
                }}
              >
                {actionError}
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
              <button
                onClick={closeConfirmModal}
                disabled={isSubmittingAction}
                style={{
                  padding: '10px 14px',
                  borderRadius: tokens.radius.full,
                  border: `1px solid ${tokens.colors.border}`,
                  backgroundColor: 'transparent',
                  color: tokens.colors.textPrimary,
                  cursor: isSubmittingAction ? 'default' : 'pointer',
                  opacity: isSubmittingAction ? 0.5 : 1,
                }}
              >
                Cancel
              </button>
              <button
                onClick={() => void submitModerationAction()}
                disabled={isSubmittingAction}
                style={{
                  padding: '10px 14px',
                  borderRadius: tokens.radius.full,
                  border: confirmState.action === 'ban' || confirmState.action === 'revokeSessions' ? '1px solid #3a2a2a' : '1px solid #242424',
                  backgroundColor: 'transparent',
                  color: confirmState.action === 'ban' || confirmState.action === 'revokeSessions' ? '#9a6a6a' : '#888',
                  cursor: isSubmittingAction ? 'default' : 'pointer',
                  opacity: isSubmittingAction ? 0.7 : 1,
                }}
              >
                {isSubmittingAction ? 'Saving...' : getActionConfig(confirmState.action).buttonLabel}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
    </div>
  )

  if (isPageLoading) {
    return (
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          height: '100vh',
          backgroundColor: tokens.colors.bg,
          color: tokens.colors.textSecondary,
        }}
      >
        Loading admin panel...
      </div>
    )
  }

  if (!isAuthorized) {
    return (
      <Layout>
        <div
          style={{
            minHeight: '60vh',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '24px',
          }}
        >
          <div
            style={{
              maxWidth: '520px',
              width: '100%',
              padding: '20px',
              borderRadius: tokens.radius.lg,
              backgroundColor: tokens.colors.surface,
              border: '1px solid #242424',
              color: tokens.colors.textPrimary,
              display: 'grid',
              gap: '8px',
            }}
          >
            <div style={{ fontSize: tokens.font.lg, fontWeight: Number(tokens.font.weightSemibold) }}>Admin access unavailable</div>
            <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
              {adminSessionError || 'This account does not currently have an active admin session.'}
            </div>
          </div>
        </div>
      </Layout>
    )
  }

  return <Layout>{pageContent}</Layout>
}
