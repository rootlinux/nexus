'use client'

import { type CSSProperties, useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { CheckCircle2, KeyRound, LoaderCircle, Lock, ShieldCheck } from 'lucide-react'

import { register as registerAccount, requestEmailVerification, type InviteValidateResponse } from '../../../lib/api'
import { BrandLogo } from '../../../components/BrandLogo'
import { useAuth } from '../../../contexts/AuthContext'
import { useSignupGuard } from '../../../hooks/useSignupGuard'
import { tokens } from '../../../styles/tokens'

// =============================================================================
// SECURITY CONSTANTS
// =============================================================================

/**
 * Maximum field lengths enforced client-side.
 * Server enforces these too; client limits are UX-only.
 */
const MAX_USERNAME_LENGTH = 40
const MAX_EMAIL_LENGTH = 254
const MAX_PASSWORD_LENGTH = 128
const MAX_DISPLAYNAME_LENGTH = 80

// =============================================================================
// SAFE ERROR NORMALIZATION
// =============================================================================

/**
 * Normalize error responses to safe, human-readable strings.
 * This function is defensive: it never renders user-controlled content
 * directly and only extracts known-safe string fields from error objects.
 */
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

/**
 * Get a safe, human-readable invite error message.
 * Malicious strings in the backend message are handled defensively.
 */
function getInviteErrorMessage(backendMessage: string): string {
  if (typeof backendMessage !== 'string') {
    return 'This invite code is invalid or unavailable.'
  }

  const normalized = backendMessage.toLowerCase()

  if (normalized.includes('expired')) {
    return 'This invite code has expired.'
  }
  if (normalized.includes('already been used')) {
    return 'This invite code has already been used.'
  }
  if (normalized.includes('required')) {
    return 'Enter an invite code to continue.'
  }
  if (normalized.includes('invalid or unavailable')) {
    return 'This invite code is invalid or unavailable.'
  }

  return 'This invite code is invalid or unavailable.'
}

/**
 * Get a format validation message for invite codes.
 * Returns null if the code looks valid format-wise.
 * This is advisory UX-only; submit-time validation is authoritative.
 */
function getInviteFormatMessage(code: string): string | null {
  const trimmed = code.trim()

  if (!trimmed) {
    return null
  }

  if (/\s/.test(trimmed)) {
    return 'Enter the code exactly as shared, without spaces.'
  }

  if (trimmed.length < 8) {
    return 'Invite codes are usually at least 8 characters.'
  }

  return null
}

// =============================================================================
// UI TYPES
// =============================================================================

type InviteTone = 'neutral' | 'success' | 'danger'

interface FieldErrors {
  username?: string
  email?: string
  password?: string
  confirmPassword?: string
  inviteCode?: string
}

interface PendingVerificationState {
  email: string
  maskedEmail: string
  message: string
}

// =============================================================================
// TONE HELPERS
// =============================================================================

function getInviteTone(fieldError?: string, validation?: InviteValidateResponse | null): InviteTone {
  if (fieldError || validation?.valid === false) {
    return 'danger'
  }

  if (validation?.valid) {
    return 'success'
  }

  return 'neutral'
}

function getToneStyles(tone: InviteTone): CSSProperties {
  if (tone === 'success') {
    return {
      borderColor: tokens.colors.success,
      backgroundColor: 'rgba(0, 186, 124, 0.08)',
      color: tokens.colors.success,
    }
  }

  if (tone === 'danger') {
    return {
      borderColor: tokens.colors.danger,
      backgroundColor: 'rgba(244, 33, 46, 0.08)',
      color: tokens.colors.danger,
    }
  }

  return {
    borderColor: tokens.colors.border,
    backgroundColor: tokens.colors.surface,
    color: tokens.colors.textSecondary,
  }
}

// =============================================================================
// MAIN SIGNUP PAGE COMPONENT
// =============================================================================

export default function SignupPage() {
  const router = useRouter()
  const { user, isLoading: isAuthLoading } = useAuth()
  const { submitButtonRef, guardedSubmit, resetAttempt } = useSignupGuard()

  // =============================================================================
  // FORM STATE
  // =============================================================================
  const [displayName, setDisplayName] = useState('')
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [inviteCode, setInviteCode] = useState('')

  // =============================================================================
  // UI STATE
  // =============================================================================
  const [isLoading, setIsLoading] = useState(false)
  const [isResendingVerification, setIsResendingVerification] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({})
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [pendingVerification, setPendingVerification] = useState<PendingVerificationState | null>(null)
  const [inviteValidation, setInviteValidation] = useState<InviteValidateResponse | null>(null)

  // =============================================================================
  // REDIRECT IF ALREADY AUTHENTICATED
  // =============================================================================
  useEffect(() => {
    if (!isAuthLoading && user) {
      router.push('/')
    }
  }, [isAuthLoading, router, user])

  useEffect(() => {
    if (!isLoading) {
      resetAttempt()
    }
  }, [email, isLoading, resetAttempt, username])

  // =============================================================================
  // RESET MESSAGES HELPER
  // =============================================================================
  const resetMessages = () => {
    setError('')
    setSuccess('')
  }

  // =============================================================================
  // AUTHORITATIVE SIGNUP SUBMIT HANDLER
  // =============================================================================
  // F7: This is the SINGLE authoritative path for signup submission.
  // No other code path can initiate signup registration.
  // Synchronous lock prevents ALL duplicate attempts immediately.
  const handleSignupSubmit = async (event: React.FormEvent) => {
    // Prevent native form submit
    event.preventDefault()

    await guardedSubmit(async (requestKey) => {
      resetMessages()
      setFieldErrors({})
      await performSignupRegistration(requestKey)
    })
  }

  // =============================================================================
  // ISOLATED SIGNUP REGISTRATION LOGIC
  // =============================================================================
  const performSignupRegistration = async (requestKey: string) => {
    setIsLoading(true)

    try {
      const trimmedInvite = inviteCode.trim()
      const trimmedUsername = username.trim()
      const trimmedEmail = email.trim()
      const trimmedDisplayName = displayName.trim()

      // =============================================================================
      // SUBMIT-TIME VALIDATION (AUTHORITATIVE)
      // =============================================================================
      // All validation happens HERE, not at blur-time.

      if (!trimmedInvite) {
        setFieldErrors({ inviteCode: 'Enter an invite code to continue.' })
        setError('A valid invite code is required to continue.')
        return
      }

      const formatMessage = getInviteFormatMessage(trimmedInvite)
      if (formatMessage) {
        setFieldErrors({ inviteCode: formatMessage })
        setError('Check the invite code and try again.')
        return
      }

      if (password !== confirmPassword) {
        setFieldErrors({ confirmPassword: 'Your password confirmation must match.' })
        setError('Check your password confirmation and try again.')
        return
      }

      // =============================================================================
      // API CALL - SINGLE REQUEST
      // =============================================================================
      const registerResponse = await registerAccount(
        trimmedUsername,
        trimmedEmail,
        password,
        trimmedInvite,
        trimmedDisplayName,
        requestKey
      )

      // Success - show verification prompt
      setPendingVerification({
        email: registerResponse.email,
        maskedEmail: registerResponse.masked_email,
        message: registerResponse.message,
      })
      setSuccess(registerResponse.message)
      resetAttempt()
    } catch (submitError: unknown) {
      // =============================================================================
      // SAFE ERROR HANDLING
      // =============================================================================
      // All error extraction is defensive and safe.
      // No user-controlled content is rendered unsafely.
      const errorData = (submitError as { response?: { data?: unknown } })?.response?.data || submitError

      if (errorData && typeof errorData === 'object') {
        const errorObject = errorData as Record<string, unknown>
        const detailObject =
          errorObject.detail && typeof errorObject.detail === 'object'
            ? (errorObject.detail as Record<string, unknown>)
            : null

        // Handle email verification required response
        if (detailObject?.code === 'EMAIL_VERIFICATION_REQUIRED') {
          setPendingVerification({
            email: username.includes('@') ? username.trim() : email.trim(),
            maskedEmail: String(detailObject.masked_email || ''),
            message: typeof detailObject.message === 'string' ? detailObject.message : 'Verify your email before signing in.',
          })
          setSuccess(typeof detailObject.message === 'string' ? detailObject.message : 'Verify your email before signing in.')
          setError('')
          return
        }

        // Handle field-level validation errors
        if (Array.isArray(errorObject.detail)) {
          const nextFieldErrors: FieldErrors = {}

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
            } else if (field === 'invite_code') {
              nextFieldErrors.inviteCode = getInviteErrorMessage(message)
            }
          }

          if (Object.keys(nextFieldErrors).length > 0) {
            setFieldErrors(nextFieldErrors)
            setError('Review the highlighted fields and try again.')
            return
          }
        }
      }

      // Handle invite-related errors
      const normalizedError = normalizeError(errorData)
      if (normalizedError.toLowerCase().includes('invite')) {
        const inviteMessage = getInviteErrorMessage(normalizedError)
        setFieldErrors((current) => ({ ...current, inviteCode: inviteMessage }))
        setInviteValidation({ valid: false, message: inviteMessage })
        setError(inviteMessage)
        return
      }

      setError(normalizedError || 'Could not complete access right now.')
    } finally {
      setIsLoading(false)
    }
  }

  // =============================================================================
  // RESEND VERIFICATION HANDLER
  // =============================================================================
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

  // =============================================================================
  // UI HELPERS
  // =============================================================================
  const inviteTone = getInviteTone(fieldErrors.inviteCode, inviteValidation)
  const inviteToneStyles = getToneStyles(inviteTone)
  const inviteDetail = fieldErrors.inviteCode || inviteValidation?.message

  // =============================================================================
  // STYLE CONSTANTS
  // =============================================================================
  const cardStyle: CSSProperties = {
    display: 'grid',
    gap: '14px',
    padding: '20px',
    borderRadius: '10px',
    backgroundColor: tokens.colors.surface,
    border: `1px solid ${tokens.colors.border}`,
  }

  const cardLabelStyle: CSSProperties = {
    color: tokens.colors.textMuted,
    fontSize: '11px',
    textTransform: 'uppercase',
    letterSpacing: '0.1em',
    marginBottom: '2px',
  }

  const cardTitleStyle: CSSProperties = {
    color: tokens.colors.textPrimary,
    fontSize: '14px',
    fontWeight: 500,
    marginBottom: '4px',
  }

  const formCardLabelStyle: CSSProperties = {
    display: 'block',
    color: tokens.colors.textPrimary,
    fontSize: '14px',
    fontWeight: 500,
    marginBottom: '2px',
  }

  const formCardSubLabelStyle: CSSProperties = {
    color: tokens.colors.textSecondary,
    fontSize: '13px',
    marginBottom: '14px',
  }

  const inputLabelStyle: CSSProperties = {
    display: 'block',
    color: tokens.colors.textPrimary,
    fontSize: '13px',
    marginBottom: '6px',
  }

  const getInputStyle = (hasError = false): CSSProperties => ({
    width: '100%',
    padding: '10px 14px',
    borderRadius: '8px',
    border: `1px solid ${hasError ? tokens.colors.danger : tokens.colors.border}`,
    backgroundColor: tokens.colors.bg,
    color: tokens.colors.textPrimary,
    outline: 'none',
    fontSize: '14px',
    boxSizing: 'border-box',
  })

  const supportCards = [
    {
      label: 'ACCESS',
      icon: KeyRound,
      title: 'Enter your invite',
      text: 'Use the code shared by an existing member, exactly as it was issued.',
    },
    {
      label: 'IDENTITY',
      icon: ShieldCheck,
      title: 'Set your identity',
      text: 'Choose a display name, secure the account, and arrive without extra ceremony.',
    },
    {
      label: 'CONTEXT',
      icon: CheckCircle2,
      title: 'Arrive with context',
      text: 'Invite lineage stays subtle and visible only where it supports trust inside the network.',
    },
  ]

  // =============================================================================
  // RENDER
  // =============================================================================
  return (
    <div
      style={{
        display: 'flex',
        minHeight: '100vh',
      }}
      className="signup-shell"
    >
      {/* Left Panel - Branding */}
      <div
        className="signup-branding"
        style={{
          width: '50%',
          backgroundColor: tokens.colors.bg,
          padding: '48px',
          display: 'flex',
          flexDirection: 'column',
          gap: '0',
        }}
      >
        {/* Logo */}
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '8px',
            backgroundColor: tokens.colors.surface,
            border: `1px solid ${tokens.colors.border}`,
            borderRadius: '10px',
            padding: '10px 14px',
            alignSelf: 'flex-start',
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

        {/* Invite-only pill */}
        <div
          style={{
            marginTop: '20px',
            display: 'inline-block',
            alignSelf: 'flex-start',
            border: `1px solid ${tokens.colors.border}`,
            color: tokens.colors.textSecondary,
            fontSize: '11px',
            textTransform: 'uppercase',
            letterSpacing: '0.1em',
            padding: '4px 10px',
            borderRadius: '8px',
          }}
        >
          Invite-only access
        </div>

        {/* Headline */}
        <h1
          style={{
            marginTop: '28px',
            marginBottom: 0,
            fontSize: '40px',
            fontWeight: 500,
            color: tokens.colors.textPrimary,
            lineHeight: 1.15,
            maxWidth: '480px',
          }}
        >
          Create your account.
        </h1>

        {/* Body */}
        <p
          style={{
            marginTop: '16px',
            marginBottom: 0,
            fontSize: '15px',
            color: tokens.colors.textSecondary,
            lineHeight: 1.6,
            maxWidth: '440px',
          }}
        >
          Join through a personal invite and become part of a quieter network where context and trust matter most.
        </p>

        {/* Feature cards */}
        <div
          style={{
            marginTop: 'auto',
            paddingTop: '48px',
            display: 'flex',
            flexDirection: 'column',
            gap: '10px',
          }}
        >
          {supportCards.map((item) => (
            <div key={item.title} style={cardStyle}>
              <div style={cardLabelStyle}>{item.label}</div>
              <div style={cardTitleStyle}>{item.title}</div>
              <div style={{ color: tokens.colors.textSecondary, fontSize: '13px', lineHeight: 1.5, margin: 0 }}>{item.text}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Right Panel - Form */}
      <div
        className="signup-panel"
        style={{
          width: '50%',
          backgroundColor: tokens.colors.bg,
          padding: '48px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <div className="signup-form-wrap" style={{ width: '100%', maxWidth: '420px' }}>
          {/* Eyebrow */}
          <div style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.1em', color: tokens.colors.textSecondary }}>
            INVITE ACCESS
          </div>
          <div style={{ fontSize: '14px', color: tokens.colors.textSecondary, marginTop: '4px' }}>Invite-only sign-up</div>

          {/* Title */}
          <h2
            style={{
              margin: '28px 0 0',
              fontSize: '28px',
              fontWeight: 500,
              color: tokens.colors.textPrimary,
              lineHeight: 1.15,
            }}
          >
            Create your account
          </h2>
          <p style={{ margin: '8px 0 0', fontSize: '14px', color: tokens.colors.textSecondary, lineHeight: 1.6 }}>
            Create your account with a valid invite. Access stays personal, measured, and intentionally limited.
          </p>

          {/* Error message */}
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

          {/* Success message */}
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

          {/* Pending Verification State */}
          {pendingVerification ? (
            <div style={{ display: 'grid', gap: '12px', marginTop: '24px' }}>
              <div style={cardStyle}>
                <div>
                  <span style={formCardLabelStyle}>Verify your email</span>
                  <span style={formCardSubLabelStyle}>
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
                    className="signup-input"
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
                <Link
                  href="/auth"
                  style={{
                    display: 'block',
                    textAlign: 'center',
                    border: `1px solid ${tokens.colors.border}`,
                    borderRadius: '8px',
                    padding: '12px',
                    backgroundColor: 'transparent',
                    color: tokens.colors.textSecondary,
                    textDecoration: 'none',
                    fontSize: '14px',
                  }}
                >
                  Back to sign in
                </Link>
              </div>
            </div>
          ) : (
            /* Signup Form */
            <form
              onSubmit={handleSignupSubmit}
              autoComplete="on"
              method="post"
              name="signup"
              style={{ display: 'grid', gap: '12px', marginTop: '24px' }}
            >
              {/* Identity Card */}
              <div style={cardStyle}>
                <div>
                  <span style={formCardLabelStyle}>Identity</span>
                  <span style={formCardSubLabelStyle}>Choose the name people will see once you&apos;re in.</span>
                </div>
                <div>
                  <label htmlFor="displayName" style={inputLabelStyle}>
                    Display name
                  </label>
                  <input
                    id="displayName"
                    name="displayName"
                    type="text"
                    value={displayName}
                    onChange={(event) => setDisplayName(event.target.value.slice(0, MAX_DISPLAYNAME_LENGTH))}
                    placeholder="Your display name"
                    required
                    autoComplete="name"
                    autoCapitalize="words"
                    autoCorrect="off"
                    enterKeyHint="next"
                    className="signup-input"
                    style={getInputStyle()}
                  />
                </div>
              </div>

              {/* Account Details Card */}
              <div style={cardStyle}>
                <div>
                  <span style={formCardLabelStyle}>Account details</span>
                  <span style={formCardSubLabelStyle}>Choose the credentials you&apos;ll use each time you sign in.</span>
                </div>

                <div>
                  <label htmlFor="username" style={inputLabelStyle}>
                    Username
                  </label>
                  <input
                    id="username"
                    type="text"
                    name="username"
                    value={username}
                    onChange={(event) => setUsername(event.target.value.slice(0, MAX_USERNAME_LENGTH))}
                    placeholder="Choose a username"
                    autoComplete="username"
                    required
                    autoCapitalize="none"
                    autoCorrect="off"
                    spellCheck={false}
                    enterKeyHint="next"
                    className="signup-input"
                    style={getInputStyle(Boolean(fieldErrors.username))}
                  />
                  {fieldErrors.username && (
                    <p style={{ margin: '6px 0 0', color: tokens.colors.danger, fontSize: '12px' }}>{fieldErrors.username}</p>
                  )}
                </div>

                <div>
                  <label htmlFor="email" style={inputLabelStyle}>
                    Email
                  </label>
                  <input
                    id="email"
                    type="email"
                    name="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value.slice(0, MAX_EMAIL_LENGTH))}
                    placeholder="you@example.com"
                    autoComplete="email"
                    required
                    inputMode="email"
                    autoCapitalize="none"
                    autoCorrect="off"
                    spellCheck={false}
                    enterKeyHint="next"
                    className="signup-input"
                    style={getInputStyle(Boolean(fieldErrors.email))}
                  />
                  {fieldErrors.email && (
                    <p style={{ margin: '6px 0 0', color: tokens.colors.danger, fontSize: '12px' }}>{fieldErrors.email}</p>
                  )}
                </div>

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
                      setPassword(event.target.value.slice(0, MAX_PASSWORD_LENGTH))
                      setFieldErrors((current) => ({ ...current, password: undefined, confirmPassword: undefined }))
                    }}
                    placeholder="••••••••"
                    autoComplete="new-password"
                    required
                    autoCapitalize="none"
                    autoCorrect="off"
                    spellCheck={false}
                    enterKeyHint="next"
                    className="signup-input"
                    style={getInputStyle(Boolean(fieldErrors.password))}
                  />
                  {fieldErrors.password && (
                    <p style={{ margin: '6px 0 0', color: tokens.colors.danger, fontSize: '12px' }}>{fieldErrors.password}</p>
                  )}
                </div>

                <div>
                  <label htmlFor="confirmPassword" style={inputLabelStyle}>
                    Confirm password
                  </label>
                  <input
                    id="confirmPassword"
                    type="password"
                    name="confirm-password"
                    value={confirmPassword}
                    onChange={(event) => {
                      setConfirmPassword(event.target.value.slice(0, MAX_PASSWORD_LENGTH))
                      setFieldErrors((current) => ({ ...current, confirmPassword: undefined }))
                    }}
                    placeholder="••••••••"
                    autoComplete="new-password"
                    required
                    autoCapitalize="none"
                    autoCorrect="off"
                    spellCheck={false}
                    enterKeyHint="done"
                    className="signup-input"
                    style={getInputStyle(Boolean(fieldErrors.confirmPassword))}
                  />
                  {fieldErrors.confirmPassword && (
                    <p style={{ margin: '6px 0 0', color: tokens.colors.danger, fontSize: '12px' }}>{fieldErrors.confirmPassword}</p>
                  )}
                </div>
              </div>

              {/* Invite Code Card */}
              <div
                style={{
                  display: 'grid',
                  gap: '14px',
                  padding: '20px',
                  borderRadius: '10px',
                  backgroundColor: tokens.colors.surface,
                  border: `1px solid ${inviteToneStyles.borderColor}`,
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px', flexWrap: 'wrap' }}>
                  <div>
                    <span style={formCardLabelStyle}>Redeem access</span>
                    <span style={formCardSubLabelStyle}>
                      Enter the code exactly as it was shared. Validation confirms only what can be checked at this step.
                    </span>
                  </div>
                  <div
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '5px',
                      padding: '4px 10px',
                      borderRadius: '99px',
                      border: `1px solid ${tokens.colors.border}`,
                      color: tokens.colors.textSecondary,
                      fontSize: '11px',
                      flexShrink: 0,
                      maxWidth: '100%',
                    }}
                  >
                    <Lock size={11} />
                    Invite required
                  </div>
                </div>

                <div>
                  <label htmlFor="inviteCode" style={inputLabelStyle}>
                    Invite code
                  </label>
                  <input
                    id="inviteCode"
                    type="text"
                    name="inviteCode"
                    value={inviteCode}
                    onChange={(event) => {
                      setInviteCode(event.target.value)
                      setFieldErrors((current) => ({ ...current, inviteCode: undefined }))
                      setInviteValidation(null)
                      if (error) {
                        setError('')
                      }
                    }}
                    placeholder="Invite code"
                    autoComplete="off"
                    required
                    autoCapitalize="none"
                    autoCorrect="off"
                    spellCheck={false}
                    enterKeyHint="done"
                    className="signup-input"
                    style={{
                      ...getInputStyle(inviteTone === 'danger'),
                      borderColor: inviteToneStyles.borderColor,
                      padding: '12px 14px',
                      fontSize: '15px',
                      letterSpacing: '0.06em',
                    }}
                  />
                </div>

                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    color: inviteTone === 'success'
                      ? tokens.colors.success
                      : inviteTone === 'danger'
                        ? tokens.colors.danger
                        : tokens.colors.textMuted,
                    fontSize: '12px',
                    lineHeight: 1.5,
                    minHeight: '20px',
                  }}
                >
                  {inviteTone === 'success' ? (
                    <>
                      <CheckCircle2 size={13} />
                      <span>
                        {inviteDetail || 'Invite code accepted.'}
                        {inviteValidation?.expires_at ? ` Expires ${new Date(inviteValidation.expires_at).toLocaleDateString()}.` : ''}
                      </span>
                    </>
                  ) : inviteDetail ? (
                    <span>{inviteDetail}</span>
                  ) : (
                    <span>Enter the code exactly as it was issued.</span>
                  )}
                </div>
              </div>

              {/* Submit Button */}
              <button
                ref={submitButtonRef}
                type="submit"
                disabled={isLoading}
                style={{
                  marginTop: '4px',
                  width: '100%',
                  border: 'none',
                  borderRadius: '8px',
                  padding: '12px',
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
                    Creating your account…
                  </>
                ) : (
                  'Continue'
                )}
              </button>
            </form>
          )}

          {/* Bottom switch */}
          <div
            style={{
              marginTop: '20px',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              paddingTop: '16px',
              borderTop: `1px solid ${tokens.colors.borderSubtle}`,
            }}
          >
            <span style={{ fontSize: '13px', color: tokens.colors.textSecondary }}>
              Already have an account?
            </span>
            <Link
              href="/auth"
              style={{
                border: 'none',
                background: 'transparent',
                color: tokens.colors.textSecondary,
                cursor: 'pointer',
                padding: 0,
                fontSize: '13px',
                textDecoration: 'none',
              }}
            >
              Back to sign in
            </Link>
          </div>
        </div>
      </div>

      <style jsx global>{`
        .spin {
          animation: signup-spin 0.9s linear infinite;
        }

        @keyframes signup-spin {
          from {
            transform: rotate(0deg);
          }
          to {
            transform: rotate(360deg);
          }
        }

        .signup-input:focus {
          border-color: ${tokens.colors.accent} !important;
        }

        .signup-input::placeholder {
          color: ${tokens.colors.textMuted};
        }

        @media (max-width: 980px) {
          .signup-shell {
            flex-direction: column !important;
          }

          .signup-shell > div {
            width: 100% !important;
          }

          .signup-branding {
            display: none !important;
          }
        }
      `}</style>
    </div>
  )
}
