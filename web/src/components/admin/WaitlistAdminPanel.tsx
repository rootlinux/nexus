'use client'

import { useCallback, useEffect, useState } from 'react'
import { LoaderCircle } from 'lucide-react'

import {
  type WaitlistApplicationResponse,
  type WaitlistInviteResponse,
  listWaitlistApplications,
  updateWaitlistApplication,
  createWaitlistInvite,
  getWaitlistInvite,
} from '../../lib/api'
import { tokens } from '../../styles/tokens'

type WaitlistStatus = 'new' | 'reviewed' | 'approved' | 'rejected'

interface WaitlistApplicationDetail extends WaitlistApplicationResponse {
  invite?: WaitlistInviteResponse | null
}

interface WaitlistAdminPanelProps {
  token: string
  canManage: boolean
}

const statusColors: Record<WaitlistStatus, { bg: string; text: string; border: string }> = {
  new: { bg: 'rgba(201, 169, 110, 0.15)', text: '#c9a96e', border: 'rgba(201, 169, 110, 0.3)' },
  reviewed: { bg: 'rgba(100, 100, 255, 0.15)', text: '#8888ff', border: 'rgba(100, 100, 255, 0.3)' },
  approved: { bg: 'rgba(0, 186, 124, 0.15)', text: '#00ba7c', border: 'rgba(0, 186, 124, 0.3)' },
  rejected: { bg: 'rgba(244, 33, 46, 0.15)', text: '#f4212e', border: 'rgba(244, 33, 46, 0.3)' },
}

const getInputStyle = (): React.CSSProperties => ({
  width: '100%',
  padding: '8px 12px',
  borderRadius: '6px',
  border: `1px solid ${tokens.colors.border}`,
  backgroundColor: tokens.colors.bg,
  color: tokens.colors.textPrimary,
  fontSize: '13px',
  outline: 'none',
  boxSizing: 'border-box',
})

export default function WaitlistAdminPanel({ token, canManage }: WaitlistAdminPanelProps) {
  const [applications, setApplications] = useState<WaitlistApplicationResponse[]>([])
  const [selectedApp, setSelectedApp] = useState<WaitlistApplicationDetail | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [isLoadingDetail, setIsLoadingDetail] = useState(false)
  const [error, setError] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [adminNotes, setAdminNotes] = useState('')
  const [newStatus, setNewStatus] = useState<WaitlistStatus | ''>('')
  const [isUpdating, setIsUpdating] = useState(false)
  const [isCreatingInvite, setIsCreatingInvite] = useState(false)
  const [inviteCreateError, setInviteCreateError] = useState('')
  const [successMessage, setSuccessMessage] = useState('')

  const limit = 20

  const loadApplications = useCallback(async () => {
    setIsLoading(true)
    setError('')
    try {
      const params: { status?: string; search?: string; page: number; limit: number } = {
        page,
        limit,
      }
      if (statusFilter) params.status = statusFilter
      if (search) params.search = search
      const data = await listWaitlistApplications(params)
      setApplications(data.applications)
      setTotal(data.total)
    } catch (err) {
      setError((err as Error).message || 'Failed to load applications')
    } finally {
      setIsLoading(false)
    }
  }, [statusFilter, search, page])

  useEffect(() => {
    void loadApplications()
  }, [loadApplications])

  const loadApplicationDetail = useCallback(async (appId: number) => {
    setIsLoadingDetail(true)
    try {
      const app = applications.find(a => a.id === appId)
      if (!app) return

      let invite: WaitlistInviteResponse | undefined
      if (app.invite_id) {
        try {
          invite = await getWaitlistInvite(appId)
        } catch {
          // Invite might not exist yet
        }
      }

      setSelectedApp({ ...app, invite })
      setAdminNotes(app.admin_notes || '')
      setNewStatus(app.status as WaitlistStatus)
      setInviteCreateError('')
      setSuccessMessage('')
    } catch (err) {
      setError((err as Error).message || 'Failed to load application details')
    } finally {
      setIsLoadingDetail(false)
    }
  }, [applications])

  const handleSelectApp = (appId: number) => {
    void loadApplicationDetail(appId)
  }

  const handleUpdateStatus = async () => {
    if (!selectedApp || !newStatus) return
    setIsUpdating(true)
    setError('')
    setSuccessMessage('')
    try {
      await updateWaitlistApplication(selectedApp.id, {
        status: newStatus,
        admin_notes: adminNotes,
      })
      setSuccessMessage('Application updated')
      await loadApplications()
      if (selectedApp) {
        loadApplicationDetail(selectedApp.id)
      }
    } catch (err) {
      setError((err as Error).message || 'Failed to update application')
    } finally {
      setIsUpdating(false)
    }
  }

  const handleCreateInvite = async () => {
    if (!selectedApp) return
    setIsCreatingInvite(true)
    setInviteCreateError('')
    setSuccessMessage('')
    try {
      const invite = await createWaitlistInvite(selectedApp.id)
      setSuccessMessage(`Invite created: ${invite.code}`)
      await loadApplications()
      if (selectedApp) {
        loadApplicationDetail(selectedApp.id)
      }
    } catch (err) {
      const errorMsg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      if (errorMsg?.includes('already exists')) {
        setInviteCreateError('An invite already exists for this application')
      } else {
        setInviteCreateError((err as Error).message || 'Failed to create invite')
      }
    } finally {
      setIsCreatingInvite(false)
    }
  }

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return '-'
    return new Date(dateStr).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  }

  return (
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
            gap: '12px',
            flexWrap: 'wrap',
            alignItems: 'center',
          }}
        >
          <h2 style={{ margin: 0, fontSize: tokens.font.lg, fontWeight: 500, color: tokens.colors.textPrimary }}>
            Waitlist Applications
          </h2>
          <span style={{ fontSize: tokens.font.sm, color: tokens.colors.textSecondary }}>
            {total} total
          </span>
        </div>

        <div
          style={{
            padding: '16px 20px',
            borderBottom: '1px solid #1c1c1c',
            display: 'flex',
            gap: '12px',
            flexWrap: 'wrap',
            alignItems: 'center',
          }}
        >
          <input
            type="text"
            placeholder="Search by name, contact, or username..."
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1) }}
            style={{ ...getInputStyle(), maxWidth: '300px' }}
          />
          <select
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); setPage(1) }}
            style={{ ...getInputStyle(), maxWidth: '150px' }}
          >
            <option value="">All statuses</option>
            <option value="new">New</option>
            <option value="reviewed">Reviewed</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
          </select>
        </div>

        {isLoading ? (
          <div style={{ padding: '40px', textAlign: 'center', color: tokens.colors.textSecondary }}>
            <LoaderCircle size={24} style={{ animation: 'spin 1s linear infinite' }} />
          </div>
        ) : error ? (
          <div style={{ padding: '20px', color: tokens.colors.danger }}>{error}</div>
        ) : applications.length === 0 ? (
          <div style={{ padding: '40px', textAlign: 'center', color: tokens.colors.textSecondary }}>
            No applications found
          </div>
        ) : (
          <div>
            {applications.map((app) => {
              const statusStyle = statusColors[app.status as WaitlistStatus] || statusColors.new
              return (
                <div
                  key={app.id}
                  onClick={() => handleSelectApp(app.id)}
                  style={{
                    padding: '14px 20px',
                    borderBottom: '1px solid #1c1c1c',
                    cursor: 'pointer',
                    backgroundColor: selectedApp?.id === app.id ? tokens.colors.surfaceElevated : 'transparent',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px' }}>
                    <div>
                      <p style={{ margin: 0, fontSize: '14px', fontWeight: 500, color: tokens.colors.textPrimary }}>
                        {app.full_name}
                      </p>
                      <p style={{ margin: '4px 0 0', fontSize: '13px', color: tokens.colors.textSecondary }}>
                        {app.contact}
                      </p>
                      {app.preferred_username && (
                        <p style={{ margin: '2px 0 0', fontSize: '12px', color: tokens.colors.textMuted }}>
                          @{app.preferred_username}
                        </p>
                      )}
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '6px' }}>
                      <span
                        style={{
                          padding: '3px 8px',
                          borderRadius: '99px',
                          fontSize: '11px',
                          fontWeight: 500,
                          backgroundColor: statusStyle.bg,
                          color: statusStyle.text,
                          border: `1px solid ${statusStyle.border}`,
                        }}
                      >
                        {app.status}
                      </span>
                      <span style={{ fontSize: '11px', color: tokens.colors.textMuted }}>
                        {formatDate(app.created_at)}
                      </span>
                    </div>
                  </div>
                </div>
              )
            })}
            {total > limit && (
              <div
                style={{
                  padding: '16px 20px',
                  display: 'flex',
                  justifyContent: 'center',
                  gap: '12px',
                  alignItems: 'center',
                }}
              >
                <button
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page === 1}
                  style={{
                    padding: '6px 12px',
                    borderRadius: '6px',
                    border: `1px solid ${tokens.colors.border}`,
                    backgroundColor: page === 1 ? 'transparent' : tokens.colors.surfaceElevated,
                    color: page === 1 ? tokens.colors.textMuted : tokens.colors.textPrimary,
                    cursor: page === 1 ? 'default' : 'pointer',
                    fontSize: '13px',
                  }}
                >
                  Previous
                </button>
                <span style={{ fontSize: '13px', color: tokens.colors.textSecondary }}>
                  Page {page} of {Math.ceil(total / limit)}
                </span>
                <button
                  onClick={() => setPage(p => p + 1)}
                  disabled={page * limit >= total}
                  style={{
                    padding: '6px 12px',
                    borderRadius: '6px',
                    border: `1px solid ${tokens.colors.border}`,
                    backgroundColor: page * limit >= total ? 'transparent' : tokens.colors.surfaceElevated,
                    color: page * limit >= total ? tokens.colors.textMuted : tokens.colors.textPrimary,
                    cursor: page * limit >= total ? 'default' : 'pointer',
                    fontSize: '13px',
                  }}
                >
                  Next
                </button>
              </div>
            )}
          </div>
        )}
      </section>

      <aside
        style={{
          flex: '1 1 360px',
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
          }}
        >
          <h3 style={{ margin: 0, fontSize: '15px', fontWeight: 500, color: tokens.colors.textPrimary }}>
            Application Details
          </h3>
        </div>

        {!selectedApp ? (
          <div style={{ padding: '40px 20px', textAlign: 'center', color: tokens.colors.textSecondary }}>
            Select an application to view details
          </div>
        ) : isLoadingDetail ? (
          <div style={{ padding: '40px 20px', textAlign: 'center', color: tokens.colors.textSecondary }}>
            <LoaderCircle size={24} style={{ animation: 'spin 1s linear infinite' }} />
          </div>
        ) : (
          <div style={{ padding: '20px', display: 'grid', gap: '16px' }}>
            <div>
              <span style={{ fontSize: '11px', color: tokens.colors.textMuted, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Full Name
              </span>
              <p style={{ margin: '4px 0 0', fontSize: '14px', color: tokens.colors.textPrimary }}>
                {selectedApp.full_name}
              </p>
            </div>

            <div>
              <span style={{ fontSize: '11px', color: tokens.colors.textMuted, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Contact
              </span>
              <p style={{ margin: '4px 0 0', fontSize: '14px', color: tokens.colors.textPrimary }}>
                {selectedApp.contact}
              </p>
            </div>

            {selectedApp.preferred_username && (
              <div>
                <span style={{ fontSize: '11px', color: tokens.colors.textMuted, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  Preferred Username
                </span>
                <p style={{ margin: '4px 0 0', fontSize: '14px', color: tokens.colors.textPrimary }}>
                  @{selectedApp.preferred_username}
                </p>
              </div>
            )}

            <div>
              <span style={{ fontSize: '11px', color: tokens.colors.textMuted, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Why they want to join
              </span>
              <p style={{ margin: '4px 0 0', fontSize: '13px', color: tokens.colors.textSecondary, lineHeight: 1.5 }}>
                {selectedApp.reason}
              </p>
            </div>

            {selectedApp.referral_source && (
              <div>
                <span style={{ fontSize: '11px', color: tokens.colors.textMuted, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  Referral Source
                </span>
                <p style={{ margin: '4px 0 0', fontSize: '13px', color: tokens.colors.textSecondary }}>
                  {selectedApp.referral_source}
                </p>
              </div>
            )}

            {selectedApp.social_url && (
              <div>
                <span style={{ fontSize: '11px', color: tokens.colors.textMuted, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  Social / Website
                </span>
                <p style={{ margin: '4px 0 0', fontSize: '13px', color: tokens.colors.accent, wordBreak: 'break-all' }}>
                  {selectedApp.social_url}
                </p>
              </div>
            )}

            <div>
              <span style={{ fontSize: '11px', color: tokens.colors.textMuted, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Status
              </span>
              <select
                value={newStatus}
                onChange={(e) => setNewStatus(e.target.value as WaitlistStatus)}
                disabled={!canManage}
                style={{ ...getInputStyle(), marginTop: '6px' }}
              >
                <option value="new">New</option>
                <option value="reviewed">Reviewed</option>
                <option value="approved">Approved</option>
                <option value="rejected">Rejected</option>
              </select>
            </div>

            <div>
              <span style={{ fontSize: '11px', color: tokens.colors.textMuted, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Admin Notes
              </span>
              <textarea
                value={adminNotes}
                onChange={(e) => setAdminNotes(e.target.value)}
                placeholder={canManage ? "Add notes about this application..." : "Notes (view only)"}
                disabled={!canManage}
                rows={3}
                style={{
                  ...getInputStyle(),
                  marginTop: '6px',
                  resize: 'vertical',
                  minHeight: '72px',
                }}
              />
            </div>

            {canManage && (newStatus !== selectedApp.status || adminNotes !== (selectedApp.admin_notes || '')) && (
              <button
                onClick={() => void handleUpdateStatus()}
                disabled={isUpdating}
                style={{
                  padding: '10px 16px',
                  borderRadius: '8px',
                  backgroundColor: isUpdating ? tokens.colors.surfaceElevated : tokens.colors.accent,
                  color: isUpdating ? tokens.colors.textMuted : '#0a0a0a',
                  border: 'none',
                  fontSize: '14px',
                  fontWeight: 500,
                  cursor: isUpdating ? 'default' : 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '8px',
                }}
              >
                {isUpdating && <LoaderCircle size={14} style={{ animation: 'spin 1s linear infinite' }} />}
                {isUpdating ? 'Updating...' : 'Update Application'}
              </button>
            )}

            <div style={{ borderTop: '1px solid #1c1c1c', paddingTop: '16px' }}>
              <span style={{ fontSize: '11px', color: tokens.colors.textMuted, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Invite
              </span>

              {selectedApp.invite ? (
                <div
                  style={{
                    marginTop: '8px',
                    padding: '12px',
                    borderRadius: '8px',
                    backgroundColor: 'rgba(0, 186, 124, 0.1)',
                    border: '1px solid rgba(0, 186, 124, 0.3)',
                  }}
                >
                  <p style={{ margin: 0, fontSize: '13px', color: tokens.colors.textPrimary }}>
                    Code: <strong style={{ fontFamily: 'monospace' }}>{selectedApp.invite.code}</strong>
                  </p>
                  <p style={{ margin: '4px 0 0', fontSize: '12px', color: tokens.colors.textSecondary }}>
                    Expires: {formatDate(selectedApp.invite.expires_at)}
                  </p>
                  <p style={{ margin: '4px 0 0', fontSize: '12px', color: tokens.colors.textSecondary }}>
                    Status: {selectedApp.invite.is_active ? 'Active' : 'Inactive'}
                  </p>
                </div>
              ) : canManage && selectedApp.status === 'approved' ? (
                <div style={{ marginTop: '8px' }}>
                  <p style={{ margin: '0 0 8px', fontSize: '12px', color: tokens.colors.textSecondary }}>
                    No invite created yet for this approved application.
                  </p>
                  <button
                    onClick={() => void handleCreateInvite()}
                    disabled={isCreatingInvite}
                    style={{
                      width: '100%',
                      padding: '10px 16px',
                      borderRadius: '8px',
                      backgroundColor: isCreatingInvite ? tokens.colors.surfaceElevated : tokens.colors.accent,
                      color: isCreatingInvite ? tokens.colors.textMuted : '#0a0a0a',
                      border: 'none',
                      fontSize: '14px',
                      fontWeight: 500,
                      cursor: isCreatingInvite ? 'default' : 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: '8px',
                    }}
                  >
                    {isCreatingInvite && <LoaderCircle size={14} style={{ animation: 'spin 1s linear infinite' }} />}
                    {isCreatingInvite ? 'Creating...' : 'Create Invite'}
                  </button>
                  {inviteCreateError && (
                    <p style={{ margin: '8px 0 0', fontSize: '12px', color: tokens.colors.danger }}>
                      {inviteCreateError}
                    </p>
                  )}
                </div>
              ) : (
                <p style={{ margin: '8px 0 0', fontSize: '12px', color: tokens.colors.textMuted }}>
                  Application must be approved before creating an invite.
                </p>
              )}
            </div>

            {successMessage && (
              <div
                style={{
                  padding: '10px 12px',
                  borderRadius: '8px',
                  backgroundColor: 'rgba(0, 186, 124, 0.1)',
                  border: '1px solid rgba(0, 186, 124, 0.3)',
                  color: tokens.colors.success,
                  fontSize: '13px',
                }}
              >
                {successMessage}
              </div>
            )}
          </div>
        )}
      </aside>

      <style jsx global>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  )
}