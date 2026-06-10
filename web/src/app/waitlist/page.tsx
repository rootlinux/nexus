'use client'

import { type CSSProperties, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { CheckCircle2, LoaderCircle } from 'lucide-react'

import { BrandLogo } from '../../components/BrandLogo'
import { tokens } from '../../styles/tokens'
import { submitWaitlistApplication, type WaitlistApplicationPayload } from '../../lib/api'

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

export default function WaitlistPage() {
  const router = useRouter()
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const [fullName, setFullName] = useState('')
  const [contact, setContact] = useState('')
  const [preferredUsername, setPreferredUsername] = useState('')
  const [reason, setReason] = useState('')
  const [referralSource, setReferralSource] = useState('')
  const [socialUrl, setSocialUrl] = useState('')

  const [fieldErrors, setFieldErrors] = useState<{
    full_name?: string
    contact?: string
    preferred_username?: string
    reason?: string
  }>({})

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

  const validateForm = (): boolean => {
    const errors: typeof fieldErrors = {}

    if (!fullName.trim()) {
      errors.full_name = 'Full name is required.'
    } else if (fullName.trim().length > 255) {
      errors.full_name = 'Full name must be 255 characters or less.'
    }

    if (!contact.trim()) {
      errors.contact = 'Contact (email or phone) is required.'
    } else if (contact.trim().length > 255) {
      errors.contact = 'Contact must be 255 characters or less.'
    }

    if (preferredUsername && preferredUsername.trim().length > 50) {
      errors.preferred_username = 'Preferred username must be 50 characters or less.'
    }

    if (!reason.trim()) {
      errors.reason = 'Please tell us why you want to join.'
    } else if (reason.trim().length > 5000) {
      errors.reason = 'Reason must be 5000 characters or less.'
    }

    setFieldErrors(errors)
    return Object.keys(errors).length === 0
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setSuccess('')

    if (!validateForm()) {
      return
    }

    setIsLoading(true)

    try {
      const payload: WaitlistApplicationPayload = {
        full_name: fullName.trim(),
        contact: contact.trim(),
        reason: reason.trim(),
      }

      if (preferredUsername.trim()) {
        payload.preferred_username = preferredUsername.trim()
      }
      if (referralSource.trim()) {
        payload.referral_source = referralSource.trim()
      }
      if (socialUrl.trim()) {
        payload.social_url = socialUrl.trim()
      }

      await submitWaitlistApplication(payload)
      setSuccess('Your application has been received. We review each one personally.')
      setFullName('')
      setContact('')
      setPreferredUsername('')
      setReason('')
      setReferralSource('')
      setSocialUrl('')
    } catch (err) {
      const errorData = (err as { response?: { data?: { detail?: string } } })?.response?.data
      if (errorData?.detail?.includes('already exists')) {
        setError('An application with this contact already exists.')
      } else {
        setError(normalizeError(err))
      }
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        minHeight: '100vh',
        padding: '48px 24px',
      }}
    >
      <Link
        href="/"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '8px',
          backgroundColor: tokens.colors.surface,
          border: `1px solid ${tokens.colors.border}`,
          borderRadius: '10px',
          padding: '10px 14px',
          textDecoration: 'none',
          marginBottom: '32px',
        }}
      >
        <BrandLogo variant="mark" width={22} />
        <span style={{ color: tokens.colors.textPrimary, fontSize: '14px', fontWeight: 500 }}>Nexus</span>
      </Link>

      <div style={{ width: '100%', maxWidth: '520px' }}>
        {success ? (
          <div
            style={{
              display: 'grid',
              gap: '16px',
              padding: '32px',
              borderRadius: '12px',
              backgroundColor: tokens.colors.surfaceElevated,
              border: `1px solid ${tokens.colors.border}`,
              textAlign: 'center',
            }}
          >
            <CheckCircle2 size={48} color={tokens.colors.success} style={{ margin: '0 auto' }} />
            <h2
              style={{
                margin: 0,
                fontSize: '20px',
                fontWeight: 500,
                color: tokens.colors.textPrimary,
              }}
            >
              Application received
            </h2>
            <p
              style={{
                margin: 0,
                fontSize: '14px',
                color: tokens.colors.textSecondary,
                lineHeight: 1.6,
              }}
            >
              {success}
            </p>
            <Link
              href="/auth"
              style={{
                marginTop: '8px',
                display: 'inline-block',
                padding: '10px 20px',
                borderRadius: '8px',
                backgroundColor: tokens.colors.accent,
                color: '#0a0a0a',
                fontSize: '14px',
                fontWeight: 500,
                textDecoration: 'none',
              }}
            >
              Sign in to your account
            </Link>
          </div>
        ) : (
          <>
            <div style={{ textAlign: 'center', marginBottom: '32px' }}>
              <p
                style={{
                  color: tokens.colors.textMuted,
                  fontSize: '11px',
                  textTransform: 'uppercase',
                  letterSpacing: '0.12em',
                  margin: '0 0 12px',
                }}
              >
                INVITE-ONLY · NEXUS BETA
              </p>
              <h1
                style={{
                  margin: '0 0 12px',
                  fontSize: '40px',
                  fontWeight: 400,
                  color: tokens.colors.textPrimary,
                  lineHeight: 1.15,
                }}
              >
                Apply to join.
              </h1>
              <p
                style={{
                  margin: 0,
                  fontSize: '16px',
                  color: tokens.colors.textSecondary,
                  lineHeight: 1.6,
                  fontStyle: 'italic',
                }}
              >
                Every application is read by a person.
              </p>
            </div>

            <form onSubmit={handleSubmit} style={{ display: 'grid', gap: '16px' }}>
              <div>
                <label style={{ display: 'block', color: tokens.colors.textPrimary, fontSize: '13px', marginBottom: '6px' }}>
                  Full name <span style={{ color: tokens.colors.danger }}>*</span>
                </label>
                <input
                  type="text"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  placeholder="Your full name"
                  maxLength={255}
                  style={getInputStyle(!!fieldErrors.full_name)}
                />
                {fieldErrors.full_name && (
                  <p style={{ margin: '4px 0 0', color: tokens.colors.danger, fontSize: '12px' }}>
                    {fieldErrors.full_name}
                  </p>
                )}
              </div>

              <div>
                <label style={{ display: 'block', color: tokens.colors.textPrimary, fontSize: '13px', marginBottom: '6px' }}>
                  Contact (email or phone) <span style={{ color: tokens.colors.danger }}>*</span>
                </label>
                <input
                  type="text"
                  value={contact}
                  onChange={(e) => setContact(e.target.value)}
                  placeholder="you@example.com or +1 555 123 4567"
                  maxLength={255}
                  style={getInputStyle(!!fieldErrors.contact)}
                />
                {fieldErrors.contact && (
                  <p style={{ margin: '4px 0 0', color: tokens.colors.danger, fontSize: '12px' }}>
                    {fieldErrors.contact}
                  </p>
                )}
              </div>

              <div>
                <label style={{ display: 'block', color: tokens.colors.textPrimary, fontSize: '13px', marginBottom: '6px' }}>
                  Preferred username
                </label>
                <input
                  type="text"
                  value={preferredUsername}
                  onChange={(e) => setPreferredUsername(e.target.value)}
                  placeholder="Desired username (optional)"
                  maxLength={50}
                  style={getInputStyle(!!fieldErrors.preferred_username)}
                />
                {fieldErrors.preferred_username && (
                  <p style={{ margin: '4px 0 0', color: tokens.colors.danger, fontSize: '12px' }}>
                    {fieldErrors.preferred_username}
                  </p>
                )}
              </div>

              <div>
                <label style={{ display: 'block', color: tokens.colors.textPrimary, fontSize: '13px', marginBottom: '6px' }}>
                  Why do you want to join? <span style={{ color: tokens.colors.danger }}>*</span>
                </label>
                <textarea
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="Tell us what draws you to Nexus..."
                  maxLength={5000}
                  rows={4}
                  style={{
                    ...getInputStyle(!!fieldErrors.reason),
                    resize: 'vertical',
                    minHeight: '88px',
                  }}
                />
                {fieldErrors.reason && (
                  <p style={{ margin: '4px 0 0', color: tokens.colors.danger, fontSize: '12px' }}>
                    {fieldErrors.reason}
                  </p>
                )}
              </div>

              <div>
                <label style={{ display: 'block', color: tokens.colors.textPrimary, fontSize: '13px', marginBottom: '6px' }}>
                  How did you hear about Nexus?
                </label>
                <input
                  type="text"
                  value={referralSource}
                  onChange={(e) => setReferralSource(e.target.value)}
                  placeholder="Friend, search, social media..."
                  maxLength={255}
                  style={getInputStyle()}
                />
              </div>

              <div>
                <label style={{ display: 'block', color: tokens.colors.textPrimary, fontSize: '13px', marginBottom: '6px' }}>
                  Social profile / website
                </label>
                <input
                  type="text"
                  value={socialUrl}
                  onChange={(e) => setSocialUrl(e.target.value)}
                  placeholder="https://..."
                  maxLength={500}
                  style={getInputStyle()}
                />
              </div>

              {error && (
                <div
                  style={{
                    padding: '12px 14px',
                    borderRadius: '8px',
                    backgroundColor: 'rgba(244, 33, 46, 0.12)',
                    border: `1px solid rgba(244, 33, 46, 0.4)`,
                    color: tokens.colors.danger,
                    fontSize: '14px',
                  }}
                >
                  {error}
                </div>
              )}

              <button
                type="submit"
                disabled={isLoading}
                style={{
                  marginTop: '8px',
                  width: '100%',
                  padding: '12px',
                  borderRadius: '8px',
                  backgroundColor: isLoading ? tokens.colors.surfaceElevated : tokens.colors.accent,
                  color: isLoading ? tokens.colors.textSecondary : '#0a0a0a',
                  border: 'none',
                  fontSize: '14px',
                  fontWeight: 500,
                  cursor: isLoading ? 'default' : 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '8px',
                }}
              >
                {isLoading && <LoaderCircle size={16} style={{ animation: 'spin 1s linear infinite' }} />}
                {isLoading ? 'Submitting...' : 'Apply for access'}
              </button>

              <p
                style={{
                  marginTop: '8px',
                  textAlign: 'center',
                  fontSize: '13px',
                  color: tokens.colors.textSecondary,
                }}
              >
                Already have an account?{' '}
                <Link href="/auth" style={{ color: tokens.colors.accent, textDecoration: 'none' }}>
                  Sign in
                </Link>
              </p>

              <p
                style={{
                  marginTop: '16px',
                  textAlign: 'center',
                  fontSize: '13px',
                  color: tokens.colors.textMuted,
                }}
              >
                Already introduced?{' '}
                <Link href="/auth" style={{ color: tokens.colors.accent, textDecoration: 'none' }}>
                  Use your invite →
                </Link>
              </p>
            </form>
          </>
        )}
      </div>

      <style jsx global>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  )
}
