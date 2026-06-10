'use client'

import { FormEvent, Suspense, useState } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'

import { completePasswordReset } from '../../../lib/api'
import { BrandLogo } from '../../../components/BrandLogo'
import { useCapturedToken } from '../useCapturedToken'
import { tokens } from '../../../styles/tokens'

function normalizeError(error: unknown): string {
  if (typeof error === 'string') {
    return error
  }
  if (error instanceof Error) {
    return error.message
  }
  if (error && typeof error === 'object') {
    const err = error as { detail?: unknown; message?: unknown }
    if (typeof err.detail === 'string') {
      return err.detail
    }
    if (typeof err.message === 'string') {
      return err.message
    }
  }
  return 'This reset link could not be completed.'
}

function ResetPasswordPageContent() {
  const searchParams = useSearchParams()
  const token = useCapturedToken(searchParams)
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    if (!token) {
      setError('This reset link is incomplete.')
      return
    }

    setIsSubmitting(true)
    setError('')
    setSuccess('')

    if (password !== confirmPassword) {
      setError('Your password confirmation must match.')
      setIsSubmitting(false)
      return
    }

    try {
      await completePasswordReset(token, password)
      setSuccess('Password updated. You can sign in with the new password now.')
      setPassword('')
      setConfirmPassword('')
    } catch (submitError) {
      setError(normalizeError((submitError as { response?: { data?: unknown } })?.response?.data || submitError))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <main style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', backgroundColor: tokens.colors.bg, padding: '24px' }}>
      <section style={{ width: '100%', maxWidth: '480px', borderRadius: '14px', border: `1px solid ${tokens.colors.border}`, backgroundColor: tokens.colors.surface, padding: '28px', display: 'grid', gap: '16px' }}>
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
          <BrandLogo variant="mark" width={22} />
          <span style={{ color: tokens.colors.textPrimary, fontSize: '15px', fontWeight: 500 }}>Nexus</span>
        </div>
        <div style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.1em', color: tokens.colors.textSecondary }}>
          Password reset
        </div>
        <h1 style={{ margin: 0, color: tokens.colors.textPrimary, fontSize: '28px', lineHeight: 1.15 }}>
          Choose a new password
        </h1>
        <p style={{ margin: 0, color: tokens.colors.textSecondary, fontSize: '14px', lineHeight: 1.6 }}>
          This link is short-lived and single use. Once the reset is complete, your other active sessions are signed out.
        </p>
        {error ? (
          <div style={{ padding: '12px 14px', borderRadius: '8px', border: `1px solid ${tokens.colors.danger}`, color: tokens.colors.danger, backgroundColor: 'rgba(244, 33, 46, 0.08)', fontSize: '13px' }}>
            {error}
          </div>
        ) : null}
        {success ? (
          <div style={{ padding: '12px 14px', borderRadius: '8px', border: `1px solid ${tokens.colors.success}`, color: tokens.colors.success, backgroundColor: 'rgba(0, 186, 124, 0.08)', fontSize: '13px' }}>
            {success}
          </div>
        ) : null}
        <form
          onSubmit={handleSubmit}
          autoComplete="on"
          method="post"
          name="password-reset-complete"
          style={{ display: 'grid', gap: '12px' }}
        >
          <label htmlFor="resetNewPassword" style={{ display: 'grid', gap: '6px', color: tokens.colors.textPrimary, fontSize: '13px' }}>
            New password
            <input
              id="resetNewPassword"
              type="password"
              name="new-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="new-password"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              enterKeyHint="next"
              required
              style={{ width: '100%', padding: '10px 14px', borderRadius: '8px', border: `1px solid ${tokens.colors.border}`, backgroundColor: tokens.colors.bg, color: tokens.colors.textPrimary, outline: 'none', fontSize: '14px', boxSizing: 'border-box' }}
            />
          </label>
          <label htmlFor="resetConfirmPassword" style={{ display: 'grid', gap: '6px', color: tokens.colors.textPrimary, fontSize: '13px' }}>
            Confirm new password
            <input
              id="resetConfirmPassword"
              type="password"
              name="confirm-password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              autoComplete="new-password"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              enterKeyHint="done"
              required
              style={{ width: '100%', padding: '10px 14px', borderRadius: '8px', border: `1px solid ${tokens.colors.border}`, backgroundColor: tokens.colors.bg, color: tokens.colors.textPrimary, outline: 'none', fontSize: '14px', boxSizing: 'border-box' }}
            />
          </label>
          <button
            type="submit"
            disabled={isSubmitting || !token}
            style={{ border: 'none', borderRadius: '8px', padding: '12px 16px', backgroundColor: isSubmitting ? tokens.colors.surfaceElevated : tokens.colors.accent, color: tokens.colors.bg, cursor: isSubmitting ? 'not-allowed' : 'pointer', fontWeight: 500, fontSize: '14px' }}
          >
            {isSubmitting ? 'Resetting password…' : 'Reset password'}
          </button>
        </form>
        <Link href="/auth" style={{ color: tokens.colors.textSecondary, fontSize: '13px', textDecoration: 'none' }}>
          Back to sign in
        </Link>
      </section>
    </main>
  )
}


export default function ResetPasswordPage() {
  return (
    <Suspense fallback={null}>
      <ResetPasswordPageContent />
    </Suspense>
  )
}
