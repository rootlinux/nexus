'use client'

import { type CSSProperties, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { CheckCircle2, KeyRound, LoaderCircle, ShieldCheck } from 'lucide-react'

import { requestEmailVerification, requestPasswordReset } from '../../lib/api'
import { BrandLogo } from '../../components/BrandLogo'
import { WebAuthnPrompt } from '../../components/auth/WebAuthnPrompt'
import { useAuth } from '../../contexts/AuthContext'
import { tokens } from '../../styles/tokens'

type AuthMode = 'login' | 'create' | 'forgotPassword'
type InviteTone = 'neutral' | 'success' | 'danger'

interface PendingVerificationState {
  email: string
  maskedEmail: string
  message: string
}

function normalizeError(error: unknown): string {
  if (typeof error === 'string') {
    return error
  }

  if (error instanceof Error) {
    return error.message
  }

  if (error && typeof error === 'object') {
    const err = error as Record<string, unknown>

    if (Array.isArray(err.detail)) {
      const messages = err.detail.map((entry) => {
        if (typeof entry === 'string') {
          return entry
        }

        if (entry && typeof entry === 'object') {
          const objectEntry = entry as Record<string, unknown>
          if (typeof objectEntry.msg === 'string') {
            return objectEntry.msg
          }
          if (typeof objectEntry.message === 'string') {
            return objectEntry.message
          }
        }

        return 'Please review the information you entered.'
      })

      return messages.join(', ')
    }

    if (typeof err.detail !== 'undefined') {
      return normalizeError(err.detail)
    }

    if (typeof err.message !== 'undefined') {
      return normalizeError(err.message)
    }
  }

  return 'An unexpected error occurred. Please try again.'
}

export default function AuthPage() {
  const router = useRouter()
  const { user, isLoading: isAuthLoading, login, completeMfaLogin, cancelMfaLogin, pendingMfaToken } = useAuth()

  const submitLockedRef = useRef(false)

  const [mode, setMode] = useState<AuthMode>('login')
  const [isLoading, setIsLoading] = useState(false)
  const [isResendingVerification, setIsResendingVerification] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [pendingVerification, setPendingVerification] = useState<PendingVerificationState | null>(null)

  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  const [fieldErrors, setFieldErrors] = useState<{
    username?: string
    email?: string
    password?: string
  }>({})

  useEffect(() => {
    if (!isAuthLoading && user) {
      router.push('/')
    }
  }, [isAuthLoading, router, user])

  const resetMessages = () => {
    setError('')
    setSuccess('')
  }

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()

    if (submitLockedRef.current) {
      return
    }
    submitLockedRef.current = true

    resetMessages()
    setFieldErrors({})
    setIsLoading(true)

    try {
      if (mode === 'login') {
        await login(username.trim(), password)
        return
      }

      if (mode === 'forgotPassword') {
        const response = await requestPasswordReset(email.trim())
        setSuccess(response.message)
        return
      }
    } catch (submitError: unknown) {
      const errorData = (submitError as { response?: { data?: unknown } })?.response?.data || submitError

      if (errorData && typeof errorData === 'object') {
        const errorObject = errorData as Record<string, unknown>
        const detailObject =
          errorObject.detail && typeof errorObject.detail === 'object'
            ? (errorObject.detail as Record<string, unknown>)
            : null

        if (detailObject?.code === 'EMAIL_VERIFICATION_REQUIRED') {
          setPendingVerification({
            email: username.includes('@') ? username.trim() : email.trim(),
            maskedEmail: String(detailObject.masked_email || ''),
            message: typeof detailObject.message === 'string' ? detailObject.message : 'Verify your email before signing in.',
          })
          setMode('login')
          setSuccess(typeof detailObject.message === 'string' ? detailObject.message : 'Verify your email before signing in.')
          setError('')
          return
        }

        if (Array.isArray(errorObject.detail)) {
          const nextFieldErrors: typeof fieldErrors = {}

          for (const entry of errorObject.detail) {
            if (!entry || typeof entry !== 'object') {
              continue
            }

            const objectEntry = entry as Record<string, unknown>
            const fieldPath = objectEntry.loc as string[] | undefined
            const message = objectEntry.msg as string | undefined
            const field = fieldPath?.[fieldPath.length - 1]

            if (!field || !message) {
              continue
            }

            if (field === 'username') {
              nextFieldErrors.username = message
            } else if (field === 'email') {
              nextFieldErrors.email = message
            } else if (field === 'password') {
              nextFieldErrors.password = message
            }
          }

          if (Object.keys(nextFieldErrors).length > 0) {
            setFieldErrors(nextFieldErrors)
            setError('Review the highlighted fields and try again.')
            return
          }
        }
      }

      const normalizedError = normalizeError(errorData)
      setError(mode === 'login' ? normalizedError || 'Could not sign you in right now.' : normalizedError || 'Could not complete access right now.')
    } finally {
      setIsLoading(false)
      submitLockedRef.current = false
    }
  }

  const switchMode = (nextMode: AuthMode) => {
    if (nextMode === 'create') {
      void router.push('/auth/signup')
      return
    }
    setMode(nextMode)
    resetMessages()
    setPendingVerification(null)
    setFieldErrors({})
    setPassword('')
  }

  const handleResendVerification = async () => {
    if (!pendingVerification?.email) {
      setError('Enter the account email to resend verification.')
      return
    }

    setIsResendingVerification(true)
    resetMessages()
    try {
      const response = await requestEmailVerification(pendingVerification.email.trim())
      setSuccess(response.message)
    } catch (resendError) {
      setError(normalizeError((resendError as { response?: { data?: unknown } })?.response?.data || resendError))
    } finally {
      setIsResendingVerification(false)
    }
  }

  const modeTitle = mode === 'login' ? 'Welcome back.' : mode === 'create' ? 'Create your account.' : 'Reset your password.'
  const modeDescription =
    mode === 'login'
      ? 'Pick up where you left off. Sessions last 14 days on this device.'
      : mode === 'create'
      ? 'Your introduction to the network starts here.'
      : "Enter your account email and we'll send a reset link if the account is eligible."
  const modeEyebrow = mode === 'login' ? 'MEMBER ACCESS' : mode === 'create' ? 'NEW MEMBER' : 'PASSWORD RESET'

  const submitLabel = mode === 'login' ? 'Sign in' : mode === 'create' ? 'Create account' : 'Send reset link'

  const inputLabelStyle: CSSProperties = {
    display: 'block',
    color: tokens.colors.textPrimary,
    fontSize: '13px',
    marginBottom: '6px',
  }

  const getInputStyle = (danger = false): CSSProperties => ({
    width: '100%',
    padding: '10px 14px',
    borderRadius: '8px',
    border: `1px solid ${danger ? tokens.colors.danger : tokens.colors.border}`,
    backgroundColor: tokens.colors.bg,
    color: tokens.colors.textPrimary,
    outline: 'none',
    fontSize: '14px',
    boxSizing: 'border-box',
  })

  return (
    <div
      style={{
        display: 'flex',
        minHeight: '100vh',
      }}
      className="auth-shell"
    >
      {/* Left Panel */}
      <div
        className="auth-branding"
        style={{
          width: '45%',
          backgroundColor: tokens.colors.bg,
          padding: '48px',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
        }}
      >
        <div>
          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '8px',
              backgroundColor: tokens.colors.surface,
              border: `1px solid ${tokens.colors.border}`,
              borderRadius: '10px',
              padding: '10px 14px',
            }}
          >
            <BrandLogo variant="mark" width={22} />
            <span style={{ color: tokens.colors.textPrimary, fontSize: '14px', fontWeight: 500 }}>Nexus</span>
            <span
              style={{
                border: `1px solid ${tokens.colors.border}`,
                color: tokens.colors.textSecondary,
                fontSize: '10px',
                borderRadius: '99px',
                padding: '2px 6px',
              }}
            >
              BETA
            </span>
          </div>
        </div>

        <div>
          <div
            style={{
              color: tokens.colors.textMuted,
              fontSize: '11px',
              textTransform: 'uppercase',
              letterSpacing: '0.14em',
              marginBottom: '16px',
            }}
          >
            MEMBER · 0000 0142
          </div>
          <blockquote
            style={{
              margin: '0 0 16px',
              padding: 0,
              fontSize: '28px',
              fontWeight: 400,
              color: tokens.colors.textPrimary,
              lineHeight: 1.25,
              fontStyle: 'italic',
            }}
          >
            &ldquo;It&rsquo;s the first network in a decade where I actually read what people write.&rdquo;
          </blockquote>
          <div
            style={{
              color: tokens.colors.textSecondary,
              fontSize: '13px',
            }}
          >
            — Elif K., joined Mar 2026
          </div>
        </div>

        <div
          style={{
            color: tokens.colors.textMuted,
            fontSize: '11px',
            fontFamily: 'monospace',
            letterSpacing: '0.08em',
          }}
        >
          NEXUS / {modeEyebrow}
        </div>
      </div>

      {/* Right Panel */}
      <div
        className="auth-panel"
        style={{
          width: '55%',
          backgroundColor: tokens.colors.bg,
          padding: '48px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <div className="auth-form-wrap" style={{ width: '100%', maxWidth: '420px' }}>
          {/* 3-mode segmented switcher */}
          <div
            className="auth-mode-switcher"
            style={{
              display: 'flex',
              gap: '4px',
              padding: '3px',
              borderRadius: '8px',
              backgroundColor: tokens.colors.surface,
              border: `1px solid ${tokens.colors.border}`,
            }}
          >
            {[
              { id: 'login' as const, label: 'Sign in' },
              { id: 'create' as const, label: 'Create' },
              { id: 'forgotPassword' as const, label: 'Reset' },
            ].map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => switchMode(item.id)}
                style={{
                  flex: 1,
                  border: 'none',
                  borderRadius: '6px',
                  padding: '8px 12px',
                  cursor: 'pointer',
                  backgroundColor: mode === item.id ? tokens.colors.surfaceElevated : 'transparent',
                  color: mode === item.id ? tokens.colors.textPrimary : tokens.colors.textSecondary,
                  fontSize: '13px',
                  fontWeight: mode === item.id ? 500 : 400,
                  transition: 'all 0.15s',
                }}
              >
                {item.label}
              </button>
            ))}
          </div>

          {/* Title */}
          <h2
            style={{
              margin: '24px 0 0',
              fontSize: '28px',
              fontWeight: 400,
              color: tokens.colors.textPrimary,
              lineHeight: 1.15,
            }}
          >
            {modeTitle}
          </h2>
          <p style={{ margin: '8px 0 0', fontSize: '14px', color: tokens.colors.textSecondary, lineHeight: 1.6 }}>
            {modeDescription}
          </p>

          {error && (
            <div
              style={{
                marginTop: '18px',
                padding: '12px 14px',
                borderRadius: '8px',
                border: `1px solid ${tokens.colors.danger}`,
                backgroundColor: 'rgba(244, 33, 46, 0.08)',
                color: tokens.colors.danger,
                fontSize: '13px',
                lineHeight: 1.5,
              }}
            >
              {error}
            </div>
          )}

          {success && (
            <div
              style={{
                marginTop: '18px',
                padding: '12px 14px',
                borderRadius: '8px',
                border: `1px solid ${tokens.colors.success}`,
                backgroundColor: 'rgba(0, 186, 124, 0.08)',
                color: tokens.colors.success,
                fontSize: '13px',
                lineHeight: 1.5,
              }}
            >
              {success}
            </div>
          )}

          {pendingMfaToken ? (
            <div style={{ marginTop: '24px' }}>
              <WebAuthnPrompt
                mfaSessionToken={pendingMfaToken}
                onSuccess={completeMfaLogin}
                onCancel={() => {
                  cancelMfaLogin()
                  setError('Sign-in cancelled. Enter your credentials again to try once more.')
                }}
              />
            </div>
          ) : pendingVerification ? (
            <div style={{ display: 'grid', gap: '12px', marginTop: '24px' }}>
              <div
                style={{
                  padding: '16px',
                  borderRadius: '10px',
                  backgroundColor: tokens.colors.surface,
                  border: `1px solid ${tokens.colors.border}`,
                }}
              >
                <span style={{ color: tokens.colors.textPrimary, fontSize: '14px', fontWeight: 500, display: 'block', marginBottom: '4px' }}>
                  Verify your email
                </span>
                <span style={{ color: tokens.colors.textSecondary, fontSize: '13px' }}>
                  {pendingVerification.message} We sent the link to {pendingVerification.maskedEmail}.
                </span>
              </div>
              <div>
                <label htmlFor="verificationEmail" style={inputLabelStyle}>
                  Email
                </label>
                <input
                  id="verificationEmail"
                  type="email"
                  name="email"
                  value={pendingVerification.email}
                  onChange={(event) => setPendingVerification((current) => current ? { ...current, email: event.target.value } : current)}
                  placeholder="you@example.com"
                  autoComplete="email"
                  inputMode="email"
                  autoCapitalize="none"
                  autoCorrect="off"
                  spellCheck={false}
                  className="auth-input"
                  style={getInputStyle()}
                />
              </div>
              <button
                type="button"
                onClick={() => {
                  void handleResendVerification()
                }}
                disabled={isResendingVerification}
                style={{
                  width: '100%',
                  border: 'none',
                  borderRadius: '8px',
                  padding: '12px',
                  backgroundColor: isResendingVerification ? tokens.colors.surfaceElevated : tokens.colors.accent,
                  color: tokens.colors.bg,
                  cursor: isResendingVerification ? 'not-allowed' : 'pointer',
                  fontSize: '14px',
                  fontWeight: 500,
                }}
              >
                {isResendingVerification ? 'Sending verification email…' : 'Resend verification email'}
              </button>
              <button
                type="button"
                onClick={() => switchMode('login')}
                style={{
                  border: `1px solid ${tokens.colors.border}`,
                  borderRadius: '8px',
                  padding: '12px',
                  backgroundColor: 'transparent',
                  color: tokens.colors.textSecondary,
                  cursor: 'pointer',
                  fontSize: '14px',
                }}
              >
                Back to sign in
              </button>
            </div>
          ) : (
            <form
              key={mode}
              onSubmit={handleSubmit}
              autoComplete="on"
              method="post"
              name={mode === 'login' ? 'login' : mode === 'create' ? 'create' : 'password-reset-request'}
              style={{ display: 'grid', gap: '14px', marginTop: '24px' }}
            >
              {mode === 'login' && (
                <div>
                  <label htmlFor="username" style={inputLabelStyle}>
                    Username or email
                  </label>
                  <input
                    id="username"
                    type="text"
                    name="username"
                    value={username}
                    onChange={(event) => setUsername(event.target.value)}
                    placeholder="Username or email"
                    autoComplete="username webauthn"
                    required
                    autoCapitalize="none"
                    autoCorrect="off"
                    spellCheck={false}
                    enterKeyHint="next"
                    className="auth-input"
                    style={getInputStyle(Boolean(fieldErrors.username))}
                  />
                  {fieldErrors.username && (
                    <p style={{ margin: '6px 0 0', color: tokens.colors.danger, fontSize: '12px' }}>{fieldErrors.username}</p>
                  )}
                </div>
              )}

              {mode === 'create' && (
                <div>
                  <label htmlFor="email" style={inputLabelStyle}>
                    Email
                  </label>
                  <input
                    id="email"
                    type="email"
                    name="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    placeholder="you@example.com"
                    autoComplete="email"
                    required
                    inputMode="email"
                    autoCapitalize="none"
                    autoCorrect="off"
                    spellCheck={false}
                    enterKeyHint="next"
                    className="auth-input"
                    style={getInputStyle(Boolean(fieldErrors.email))}
                  />
                  {fieldErrors.email && (
                    <p style={{ margin: '6px 0 0', color: tokens.colors.danger, fontSize: '12px' }}>{fieldErrors.email}</p>
                  )}
                </div>
              )}

              {mode === 'forgotPassword' && (
                <div>
                  <label htmlFor="email" style={inputLabelStyle}>
                    Email
                  </label>
                  <input
                    id="email"
                    type="email"
                    name="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    placeholder="you@example.com"
                    autoComplete="email"
                    required
                    inputMode="email"
                    autoCapitalize="none"
                    autoCorrect="off"
                    spellCheck={false}
                    enterKeyHint="send"
                    className="auth-input"
                    style={getInputStyle(Boolean(fieldErrors.email))}
                  />
                  {fieldErrors.email && (
                    <p style={{ margin: '6px 0 0', color: tokens.colors.danger, fontSize: '12px' }}>{fieldErrors.email}</p>
                  )}
                </div>
              )}

              {mode === 'login' && (
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                    <label htmlFor="password" style={{ ...inputLabelStyle, marginBottom: 0 }}>
                      Password
                    </label>
                    <button
                      type="button"
                      onClick={() => switchMode('forgotPassword')}
                      style={{
                        border: 'none',
                        background: 'transparent',
                        color: tokens.colors.accent,
                        cursor: 'pointer',
                        padding: 0,
                        fontSize: '12px',
                      }}
                    >
                      Forgot?
                    </button>
                  </div>
                  <input
                    id="password"
                    type="password"
                    name="current-password"
                    value={password}
                    onChange={(event) => {
                      setPassword(event.target.value)
                      setFieldErrors((current) => ({ ...current, password: undefined }))
                    }}
                    placeholder="••••••••"
                    autoComplete="current-password"
                    required
                    autoCapitalize="none"
                    autoCorrect="off"
                    spellCheck={false}
                    enterKeyHint="go"
                    className="auth-input"
                    style={getInputStyle(Boolean(fieldErrors.password))}
                  />
                  {fieldErrors.password && (
                    <p style={{ margin: '6px 0 0', color: tokens.colors.danger, fontSize: '12px' }}>{fieldErrors.password}</p>
                  )}
                </div>
              )}

              {mode === 'create' && (
                <div>
                  <label htmlFor="password" style={inputLabelStyle}>
                    Password
                  </label>
                  <input
                    id="password"
                    type="password"
                    name="new-password"
                    value={password}
                    onChange={(event) => {
                      setPassword(event.target.value)
                      setFieldErrors((current) => ({ ...current, password: undefined }))
                    }}
                    placeholder="••••••••"
                    autoComplete="new-password"
                    required
                    autoCapitalize="none"
                    autoCorrect="off"
                    spellCheck={false}
                    enterKeyHint="go"
                    className="auth-input"
                    style={getInputStyle(Boolean(fieldErrors.password))}
                  />
                  {fieldErrors.password && (
                    <p style={{ margin: '6px 0 0', color: tokens.colors.danger, fontSize: '12px' }}>{fieldErrors.password}</p>
                  )}
                </div>
              )}

              <button
                type="submit"
                disabled={isLoading}
                style={{
                  marginTop: '4px',
                  width: '100%',
                  border: 'none',
                  borderRadius: '8px',
                  padding: '14px',
                  backgroundColor: isLoading ? tokens.colors.surfaceElevated : tokens.colors.accent,
                  color: tokens.colors.bg,
                  cursor: isLoading ? 'not-allowed' : 'pointer',
                  fontSize: '14px',
                  fontWeight: 500,
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '8px',
                }}
              >
                {isLoading ? (
                  <>
                    <LoaderCircle size={16} className="spin" />
                    {mode === 'login' ? 'Signing in…' : mode === 'create' ? 'Creating account…' : 'Sending reset email…'}
                  </>
                ) : (
                  submitLabel
                )}
              </button>

              {mode === 'login' && (
                <div
                  style={{
                    marginTop: '12px',
                    textAlign: 'center',
                    paddingTop: '12px',
                    borderTop: `1px solid ${tokens.colors.borderSubtle}`,
                  }}
                >
                  <span style={{ fontSize: '12px', color: tokens.colors.textMuted }}>
                    Interested in joining?{' '}
                    <Link
                      href="/waitlist"
                      style={{
                        color: tokens.colors.accent,
                        textDecoration: 'none',
                        fontSize: '12px',
                      }}
                    >
                      Request access
                    </Link>
                  </span>
                </div>
              )}
            </form>
          )}
        </div>
      </div>

      <style jsx global>{`
        .spin {
          animation: auth-spin 0.9s linear infinite;
        }

        @keyframes auth-spin {
          from {
            transform: rotate(0deg);
          }
          to {
            transform: rotate(360deg);
          }
        }

        .auth-input:focus {
          border-color: ${tokens.colors.accent} !important;
        }

        .auth-input::placeholder {
          color: ${tokens.colors.textMuted};
        }

        @media (max-width: 980px) {
          .auth-shell {
            flex-direction: column !important;
          }

          .auth-shell > div {
            width: 100% !important;
          }

          .auth-branding {
            display: none !important;
          }
        }
      `}</style>
    </div>
  )
}
