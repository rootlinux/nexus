'use client'

import { Suspense, useEffect, useState } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'

import { completeEmailVerification } from '../../../lib/api'
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
  return 'This verification link could not be completed.'
}

function VerifyEmailPageContent() {
  const searchParams = useSearchParams()
  const token = useCapturedToken(searchParams)
  const [status, setStatus] = useState<'loading' | 'verified' | 'already_verified' | 'error'>('loading')
  const [message, setMessage] = useState('Verifying your email...')

  useEffect(() => {
    const run = async () => {
      if (!token) {
        setStatus('error')
        setMessage('This verification link is incomplete.')
        return
      }

      try {
        const response = await completeEmailVerification(token)
        setStatus(response.status)
        setMessage(response.message)
      } catch (error) {
        setStatus('error')
        setMessage(normalizeError((error as { response?: { data?: unknown } })?.response?.data || error))
      }
    }

    void run()
  }, [token])

  return (
    <main style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', backgroundColor: tokens.colors.bg, padding: '24px' }}>
      <section style={{ width: '100%', maxWidth: '480px', borderRadius: '14px', border: `1px solid ${tokens.colors.border}`, backgroundColor: tokens.colors.surface, padding: '28px', display: 'grid', gap: '16px' }}>
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
          <BrandLogo variant="mark" width={22} />
          <span style={{ color: tokens.colors.textPrimary, fontSize: '15px', fontWeight: 500 }}>Nexus</span>
        </div>
        <div style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.1em', color: tokens.colors.textSecondary }}>
          Email Verification
        </div>
        <h1 style={{ margin: 0, color: tokens.colors.textPrimary, fontSize: '28px', lineHeight: 1.15 }}>
          {status === 'loading' ? 'Checking your link' : status === 'verified' ? 'Email verified' : status === 'already_verified' ? 'Already verified' : 'Verification could not be completed'}
        </h1>
        <p style={{ margin: 0, color: tokens.colors.textSecondary, fontSize: '14px', lineHeight: 1.6 }}>
          {message}
        </p>
        <Link href="/auth" style={{ display: 'inline-flex', justifyContent: 'center', padding: '12px 16px', borderRadius: '8px', backgroundColor: tokens.colors.accent, color: tokens.colors.bg, textDecoration: 'none', fontWeight: 500, fontSize: '14px' }}>
          Back to sign in
        </Link>
      </section>
    </main>
  )
}


export default function VerifyEmailPage() {
  return (
    <Suspense fallback={null}>
      <VerifyEmailPageContent />
    </Suspense>
  )
}
