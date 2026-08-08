'use client'

import { type FormEvent, useState } from 'react'
import Link from 'next/link'
import { startRegistration } from '@simplewebauthn/browser'
import type { RegistrationResponseJSON } from '@simplewebauthn/browser'

import {
  adminEnrollmentRegisterBegin,
  adminEnrollmentRegisterComplete,
  requestAdminEnrollmentToken,
} from '../../../lib/api'
import { BrandLogo } from '../../../components/BrandLogo'
import { tokens } from '../../../styles/tokens'

const UNAVAILABLE =
  'First-passkey enrolment is not enabled on this backend. It is off by default and is ' +
  'refused outright in production — see the README for the local setup steps.'

function describeFailure(error: unknown): string {
  if (error instanceof Error && error.name === 'NotAllowedError') {
    return 'Your browser cancelled the passkey prompt. Nothing was saved — try again.'
  }

  const status = (error as { response?: { status?: number } })?.response?.status
  if (status === 404) {
    return UNAVAILABLE
  }

  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof detail === 'string') {
    return detail
  }
  if (error instanceof Error && error.message) {
    return error.message
  }
  return 'Enrolment failed. Check the backend logs for the audited reason.'
}

const cardStyle = {
  width: '100%',
  maxWidth: '520px',
  borderRadius: '14px',
  border: `1px solid ${tokens.colors.border}`,
  backgroundColor: tokens.colors.surface,
  padding: '28px',
  display: 'grid',
  gap: '16px',
} as const

const inputStyle = {
  width: '100%',
  padding: '10px 14px',
  borderRadius: '8px',
  border: `1px solid ${tokens.colors.border}`,
  backgroundColor: tokens.colors.bg,
  color: tokens.colors.textPrimary,
  outline: 'none',
  fontSize: '14px',
  boxSizing: 'border-box',
} as const

const labelStyle = {
  display: 'grid',
  gap: '6px',
  color: tokens.colors.textPrimary,
  fontSize: '13px',
} as const

export default function AdminEnrollmentPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [keyName, setKeyName] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [isEnrolled, setIsEnrolled] = useState(false)

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setError('')
    setIsSubmitting(true)

    try {
      // The password check and every eligibility rule live server-side; this page only
      // sequences the three calls and drives the browser's WebAuthn prompt in between.
      const { recovery_token: enrolmentToken } = await requestAdminEnrollmentToken(username, password)
      const options = await adminEnrollmentRegisterBegin(enrolmentToken)
      const credential: RegistrationResponseJSON = await startRegistration({ optionsJSON: options })
      await adminEnrollmentRegisterComplete(enrolmentToken, credential, keyName.trim())
      setPassword('')
      setIsEnrolled(true)
    } catch (submitError) {
      setError(describeFailure(submitError))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <main
      style={{
        minHeight: '100vh',
        display: 'grid',
        placeItems: 'center',
        backgroundColor: tokens.colors.bg,
        padding: '24px',
      }}
    >
      <section style={cardStyle}>
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
          <BrandLogo variant="mark" width={22} />
          <span style={{ color: tokens.colors.textPrimary, fontSize: '15px', fontWeight: 500 }}>Nexus</span>
        </div>
        <div
          style={{
            fontSize: '11px',
            textTransform: 'uppercase',
            letterSpacing: '0.1em',
            color: tokens.colors.textSecondary,
          }}
        >
          First administrator enrolment
        </div>

        {isEnrolled ? (
          <>
            <h1 style={{ margin: 0, color: tokens.colors.textPrimary, fontSize: '28px', lineHeight: 1.15 }}>
              Passkey registered
            </h1>
            <p style={{ margin: 0, color: tokens.colors.textSecondary, fontSize: '14px', lineHeight: 1.6 }}>
              Sign in normally now: password first, then this passkey. This enrolment page no
              longer works for the account — it only ever accepts a privileged account that
              owns no passkey. Set <code>ENABLE_ADMIN_WEBAUTHN_RECOVERY</code> and{' '}
              <code>ENABLE_BOOTSTRAP_ADMIN</code> back to <code>false</code> and restart.
            </p>
            <Link
              href="/login"
              style={{
                justifySelf: 'start',
                padding: '10px 16px',
                borderRadius: '8px',
                border: `1px solid ${tokens.colors.border}`,
                color: tokens.colors.textPrimary,
                fontSize: '14px',
                textDecoration: 'none',
              }}
            >
              Go to sign in
            </Link>
          </>
        ) : (
          <>
            <h1 style={{ margin: 0, color: tokens.colors.textPrimary, fontSize: '28px', lineHeight: 1.15 }}>
              Register the first passkey
            </h1>
            <p style={{ margin: 0, color: tokens.colors.textSecondary, fontSize: '14px', lineHeight: 1.6 }}>
              Privileged accounts cannot sign in with a password alone, and ordinary passkey
              registration needs a session you do not have yet. This one-time path closes
              itself the moment the account owns a passkey, and the backend refuses it
              entirely in production.
            </p>

            {error ? (
              <div
                role="alert"
                style={{
                  padding: '12px 14px',
                  borderRadius: '8px',
                  border: `1px solid ${tokens.colors.danger}`,
                  color: tokens.colors.danger,
                  backgroundColor: 'rgba(244, 33, 46, 0.08)',
                  fontSize: '13px',
                }}
              >
                {error}
              </div>
            ) : null}

            <form
              onSubmit={handleSubmit}
              autoComplete="on"
              method="post"
              name="admin-passkey-enrollment"
              style={{ display: 'grid', gap: '12px' }}
            >
              <label htmlFor="adminEnrollmentUsername" style={labelStyle}>
                Administrator username
                <input
                  id="adminEnrollmentUsername"
                  type="text"
                  name="username"
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  autoComplete="username"
                  autoCapitalize="none"
                  autoCorrect="off"
                  spellCheck={false}
                  enterKeyHint="next"
                  required
                  style={inputStyle}
                />
              </label>
              <label htmlFor="adminEnrollmentPassword" style={labelStyle}>
                Password
                <input
                  id="adminEnrollmentPassword"
                  type="password"
                  name="current-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete="current-password"
                  autoCapitalize="none"
                  autoCorrect="off"
                  spellCheck={false}
                  enterKeyHint="next"
                  required
                  style={inputStyle}
                />
              </label>
              <label htmlFor="adminEnrollmentKeyName" style={labelStyle}>
                Name this passkey
                <input
                  id="adminEnrollmentKeyName"
                  type="text"
                  name="security-key-name"
                  placeholder="For example: YubiKey 5 or Touch ID"
                  value={keyName}
                  onChange={(event) => setKeyName(event.target.value)}
                  maxLength={100}
                  enterKeyHint="done"
                  required
                  style={inputStyle}
                />
              </label>
              <button
                type="submit"
                disabled={isSubmitting || !username || !password || !keyName.trim()}
                style={{
                  padding: '11px 16px',
                  borderRadius: '8px',
                  border: 'none',
                  backgroundColor: tokens.colors.accent,
                  color: '#fff',
                  fontSize: '14px',
                  fontWeight: 500,
                  cursor: isSubmitting ? 'not-allowed' : 'pointer',
                  opacity: isSubmitting || !username || !password || !keyName.trim() ? 0.5 : 1,
                }}
              >
                {isSubmitting ? 'Registering…' : 'Register passkey'}
              </button>
            </form>

            <p style={{ margin: 0, color: tokens.colors.textSecondary, fontSize: '12px', lineHeight: 1.6 }}>
              Already have a passkey?{' '}
              <Link href="/login" style={{ color: tokens.colors.accent }}>
                Sign in
              </Link>
              .
            </p>
          </>
        )}
      </section>
    </main>
  )
}
