'use client'

import { FormEvent, useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'

import Layout from '../../components/Layout'
import { WebAuthnSetup } from '../../components/auth/WebAuthnSetup'
import { ReportProblemModal } from '../../components/feedback/ReportProblemModal'
import { useAuth } from '../../contexts/AuthContext'
import { listSessions, requestEmailChange, revokeOtherSessions, revokeSession } from '../../lib/api'
import { tokens } from '../../styles/tokens'
import type { SessionRead } from '../../types'

function getErrorMessage(error: unknown, fallback: string) {
  if (
    typeof error === 'object' &&
    error !== null &&
    'response' in error &&
    typeof (error as { response?: unknown }).response === 'object'
  ) {
    const response = (error as { response?: { data?: { detail?: unknown } } }).response
    if (typeof response?.data?.detail === 'string') {
      return response.data.detail
    }
  }
  if (error instanceof Error && error.message) {
    return error.message
  }
  return fallback
}

function formatDateTime(value?: string | null) {
  if (!value) {
    return 'Unavailable'
  }
  return new Date(value).toLocaleString()
}

export default function SecurityPage() {
  const router = useRouter()
  const { user, isLoading: isAuthLoading } = useAuth()
  const [sessions, setSessions] = useState<SessionRead[]>([])
  const [isLoadingSessions, setIsLoadingSessions] = useState(true)
  const [pendingSessionId, setPendingSessionId] = useState<number | null>(null)
  const [revokeOthersPassword, setRevokeOthersPassword] = useState('')
  const [emailChangeForm, setEmailChangeForm] = useState({ newEmail: '', currentPassword: '' })
  const [isSubmittingOthers, setIsSubmittingOthers] = useState(false)
  const [isSubmittingEmailChange, setIsSubmittingEmailChange] = useState(false)
  const [isReportProblemOpen, setIsReportProblemOpen] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const loadSessions = async () => {
    setIsLoadingSessions(true)
    try {
      const response = await listSessions()
      setSessions(response.sessions)
    } catch (loadError) {
      setError(getErrorMessage(loadError, 'Could not load your active sessions.'))
    } finally {
      setIsLoadingSessions(false)
    }
  }

  useEffect(() => {
    if (!isAuthLoading && !user) {
      router.push('/auth')
      return
    }
    if (user) {
      void loadSessions()
    }
  }, [isAuthLoading, router, user])

  const handleRevokeSession = async (sessionId: number) => {
    setPendingSessionId(sessionId)
    setError('')
    setSuccess('')
    try {
      await revokeSession(sessionId)
      setSuccess('Session revoked.')
      await loadSessions()
    } catch (revokeError) {
      setError(getErrorMessage(revokeError, 'Could not revoke this session.'))
    } finally {
      setPendingSessionId(null)
    }
  }

  const handleRevokeOthers = async (event: FormEvent) => {
    event.preventDefault()
    setIsSubmittingOthers(true)
    setError('')
    setSuccess('')
    try {
      const response = await revokeOtherSessions(revokeOthersPassword)
      setSuccess(`Revoked ${response.revoked_session_count} other session${response.revoked_session_count === 1 ? '' : 's'}.`)
      setRevokeOthersPassword('')
      await loadSessions()
    } catch (submitError) {
      setError(getErrorMessage(submitError, 'Could not revoke your other sessions.'))
    } finally {
      setIsSubmittingOthers(false)
    }
  }

  const handleEmailChange = async (event: FormEvent) => {
    event.preventDefault()
    setIsSubmittingEmailChange(true)
    setError('')
    setSuccess('')
    try {
      const response = await requestEmailChange(emailChangeForm.newEmail, emailChangeForm.currentPassword)
      setSuccess(response.message)
      setEmailChangeForm({ newEmail: '', currentPassword: '' })
    } catch (submitError) {
      setError(getErrorMessage(submitError, 'Could not start this email change.'))
    } finally {
      setIsSubmittingEmailChange(false)
    }
  }

  return (
    <Layout>
      <main style={{ maxWidth: '720px', margin: '0 auto', padding: '24px 16px 64px', display: 'grid', gap: '18px' }}>
        <section style={{ display: 'grid', gap: '8px' }}>
          <div style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.1em', color: tokens.colors.textSecondary }}>
            Account security
          </div>
          <h1 style={{ margin: 0, color: tokens.colors.textPrimary, fontSize: '30px', lineHeight: 1.1 }}>
            Sessions, keys, and email
          </h1>
          <p style={{ margin: 0, color: tokens.colors.textSecondary, fontSize: '14px', lineHeight: 1.6 }}>
            Review your active sessions, manage security keys, and confirm an email change from one place.
          </p>
        </section>

        {error ? (
          <div style={{ padding: '12px 14px', borderRadius: '10px', border: `1px solid ${tokens.colors.danger}`, color: tokens.colors.danger, backgroundColor: 'rgba(244, 33, 46, 0.08)', fontSize: '13px' }}>
            {error}
          </div>
        ) : null}
        {success ? (
          <div style={{ padding: '12px 14px', borderRadius: '10px', border: `1px solid ${tokens.colors.success}`, color: tokens.colors.success, backgroundColor: 'rgba(0, 186, 124, 0.08)', fontSize: '13px' }}>
            {success}
          </div>
        ) : null}

        <section style={{ borderRadius: '14px', border: `1px solid ${tokens.colors.border}`, backgroundColor: tokens.colors.surface, padding: '18px', display: 'grid', gap: '14px' }}>
          <div>
            <h2 style={{ margin: 0, color: tokens.colors.textPrimary, fontSize: '18px' }}>Active sessions</h2>
            <p style={{ margin: '6px 0 0', color: tokens.colors.textSecondary, fontSize: '13px', lineHeight: 1.5 }}>
              Your current session cannot be revoked here. Use sign out if you want to close the session you&apos;re using now.
            </p>
          </div>
          {isLoadingSessions ? (
            <div style={{ color: tokens.colors.textSecondary, fontSize: '14px' }}>Loading sessions…</div>
          ) : sessions.length === 0 ? (
            <div style={{ color: tokens.colors.textSecondary, fontSize: '14px' }}>No active sessions are available.</div>
          ) : (
            <div style={{ display: 'grid', gap: '12px' }}>
              {sessions.map((session) => (
                <article key={session.id} style={{ borderRadius: '12px', border: `1px solid ${tokens.colors.border}`, backgroundColor: tokens.colors.bg, padding: '14px', display: 'grid', gap: '10px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'flex-start' }}>
                    <div style={{ display: 'grid', gap: '4px' }}>
                      <div style={{ color: tokens.colors.textPrimary, fontSize: '14px', fontWeight: 600 }}>
                        {session.device_label || 'Unnamed browser session'}
                      </div>
                      <div style={{ color: tokens.colors.textSecondary, fontSize: '12px' }}>
                        Opened {formatDateTime(session.created_at)}
                      </div>
                    </div>
                    {session.is_current ? (
                      <span style={{ padding: '4px 8px', borderRadius: tokens.radius.full, backgroundColor: 'rgba(0, 186, 124, 0.12)', color: tokens.colors.success, fontSize: '11px', fontWeight: 600 }}>
                        Current
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => void handleRevokeSession(session.id)}
                        disabled={pendingSessionId === session.id}
                        style={{ border: `1px solid ${tokens.colors.border}`, borderRadius: '8px', padding: '8px 12px', backgroundColor: tokens.colors.surface, color: tokens.colors.textPrimary, cursor: pendingSessionId === session.id ? 'not-allowed' : 'pointer', fontSize: '12px' }}
                      >
                        {pendingSessionId === session.id ? 'Revoking…' : 'Revoke'}
                      </button>
                    )}
                  </div>
                  <div style={{ display: 'grid', gap: '4px', color: tokens.colors.textSecondary, fontSize: '12px' }}>
                    <div>Last used: {formatDateTime(session.last_used_at)}</div>
                    <div>Expires: {formatDateTime(session.expires_at)}</div>
                  </div>
                </article>
              ))}
            </div>
          )}
          <form onSubmit={handleRevokeOthers} autoComplete="on" method="post" name="revoke-other-sessions" style={{ display: 'grid', gap: '10px' }}>
            {user ? <input type="text" name="username" autoComplete="username" value={user.username} readOnly hidden /> : null}
            <label htmlFor="revokeOthersPassword" style={{ display: 'grid', gap: '6px', color: tokens.colors.textPrimary, fontSize: '13px' }}>
              Current password
              <input
                id="revokeOthersPassword"
                type="password"
                name="current-password"
                value={revokeOthersPassword}
                onChange={(event) => setRevokeOthersPassword(event.target.value)}
                autoComplete="current-password"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
                enterKeyHint="go"
                required
                style={{ width: '100%', padding: '10px 14px', borderRadius: '8px', border: `1px solid ${tokens.colors.border}`, backgroundColor: tokens.colors.bg, color: tokens.colors.textPrimary, outline: 'none', fontSize: '14px', boxSizing: 'border-box' }}
              />
            </label>
            <button
              type="submit"
              disabled={isSubmittingOthers}
              style={{ width: 'fit-content', border: 'none', borderRadius: '8px', padding: '11px 16px', backgroundColor: isSubmittingOthers ? tokens.colors.surfaceElevated : tokens.colors.accent, color: tokens.colors.bg, cursor: isSubmittingOthers ? 'not-allowed' : 'pointer', fontWeight: 600, fontSize: '13px' }}
            >
              {isSubmittingOthers ? 'Revoking…' : 'Revoke other sessions'}
            </button>
          </form>
        </section>

        <section style={{ borderRadius: '14px', border: `1px solid ${tokens.colors.border}`, backgroundColor: tokens.colors.surface, padding: '18px', display: 'grid', gap: '14px' }}>
          <div>
            <h2 style={{ margin: 0, color: tokens.colors.textPrimary, fontSize: '18px' }}>Security keys</h2>
            <p style={{ margin: '6px 0 0', color: tokens.colors.textSecondary, fontSize: '13px', lineHeight: 1.5 }}>
              Add a passkey or hardware security key to strengthen your admin account. Once registered, you'll be prompted for it after entering your password.
            </p>
          </div>
          <WebAuthnSetup />
        </section>

        <section style={{ borderRadius: '14px', border: `1px solid ${tokens.colors.border}`, backgroundColor: tokens.colors.surface, padding: '18px', display: 'grid', gap: '14px' }}>
          <div>
            <h2 style={{ margin: 0, color: tokens.colors.textPrimary, fontSize: '18px' }}>Change email</h2>
            <p style={{ margin: '6px 0 0', color: tokens.colors.textSecondary, fontSize: '13px', lineHeight: 1.5 }}>
              Your email changes only after the new inbox confirms it. For safety, completing the change signs your active sessions out again.
            </p>
          </div>
          <form onSubmit={handleEmailChange} autoComplete="on" method="post" name="change-email" style={{ display: 'grid', gap: '10px' }}>
            {user ? <input type="text" name="username" autoComplete="username" value={user.username} readOnly hidden /> : null}
            <label htmlFor="securityNewEmail" style={{ display: 'grid', gap: '6px', color: tokens.colors.textPrimary, fontSize: '13px' }}>
              New email
              <input
                id="securityNewEmail"
                type="email"
                name="email"
                value={emailChangeForm.newEmail}
                onChange={(event) => setEmailChangeForm((current) => ({ ...current, newEmail: event.target.value }))}
                autoComplete="email"
                inputMode="email"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
                enterKeyHint="next"
                required
                style={{ width: '100%', padding: '10px 14px', borderRadius: '8px', border: `1px solid ${tokens.colors.border}`, backgroundColor: tokens.colors.bg, color: tokens.colors.textPrimary, outline: 'none', fontSize: '14px', boxSizing: 'border-box' }}
              />
            </label>
            <label htmlFor="securityCurrentPassword" style={{ display: 'grid', gap: '6px', color: tokens.colors.textPrimary, fontSize: '13px' }}>
              Current password
              <input
                id="securityCurrentPassword"
                type="password"
                name="current-password"
                value={emailChangeForm.currentPassword}
                onChange={(event) => setEmailChangeForm((current) => ({ ...current, currentPassword: event.target.value }))}
                autoComplete="current-password"
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
                enterKeyHint="go"
                required
                style={{ width: '100%', padding: '10px 14px', borderRadius: '8px', border: `1px solid ${tokens.colors.border}`, backgroundColor: tokens.colors.bg, color: tokens.colors.textPrimary, outline: 'none', fontSize: '14px', boxSizing: 'border-box' }}
              />
            </label>
            <button
              type="submit"
              disabled={isSubmittingEmailChange}
              style={{ width: 'fit-content', border: 'none', borderRadius: '8px', padding: '11px 16px', backgroundColor: isSubmittingEmailChange ? tokens.colors.surfaceElevated : tokens.colors.accent, color: tokens.colors.bg, cursor: isSubmittingEmailChange ? 'not-allowed' : 'pointer', fontWeight: 600, fontSize: '13px' }}
            >
              {isSubmittingEmailChange ? 'Sending…' : 'Send confirmation email'}
            </button>
          </form>
          <div style={{ color: tokens.colors.textSecondary, fontSize: '12px', lineHeight: 1.6 }}>
            Password changes are still handled from your <Link href={user ? `/${user.username}` : '/'} style={{ color: tokens.colors.textPrimary }}>profile page</Link>.
          </div>
        </section>

        <section style={{ borderRadius: '14px', border: `1px solid ${tokens.colors.border}`, backgroundColor: tokens.colors.surface, padding: '18px', display: 'grid', gap: '14px' }}>
          <div style={{ display: 'grid', gap: '6px' }}>
            <h2 style={{ margin: 0, color: tokens.colors.textPrimary, fontSize: '18px' }}>Report a problem</h2>
            <p style={{ margin: 0, color: tokens.colors.textSecondary, fontSize: '13px', lineHeight: 1.6 }}>
              Found something off? Send the details.
            </p>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'center', flexWrap: 'wrap' }}>
            <div style={{ color: tokens.colors.textSecondary, fontSize: '12px', lineHeight: 1.6, maxWidth: '440px' }}>
              Share what happened from inside the app, with your current page and device details already filled in.
            </div>
            <button
              type="button"
              onClick={() => setIsReportProblemOpen(true)}
              style={{ border: 'none', borderRadius: '999px', padding: '11px 16px', backgroundColor: tokens.colors.accent, color: tokens.colors.bg, cursor: 'pointer', fontWeight: 600, fontSize: '13px' }}
            >
              Report a problem
            </button>
          </div>
        </section>
      </main>
      <ReportProblemModal isOpen={isReportProblemOpen} onClose={() => setIsReportProblemOpen(false)} user={user} />
    </Layout>
  )
}
