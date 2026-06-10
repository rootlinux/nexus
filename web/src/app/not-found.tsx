'use client'

import Link from 'next/link'
import { tokens } from '../styles/tokens'
import { Home } from 'lucide-react'

export default function NotFound() {
  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: tokens.colors.bg,
      color: tokens.colors.textPrimary,
      padding: '20px',
    }}>
      <h1 style={{
        fontSize: '72px',
        fontWeight: Number(tokens.font.weightBold),
        marginBottom: '8px',
        color: tokens.colors.textPrimary,
      }}>
        404
      </h1>
      <h2 style={{
        fontSize: tokens.font.xl,
        fontWeight: Number(tokens.font.weightSemibold),
        marginBottom: '16px',
        color: tokens.colors.textPrimary,
      }}>
        Page not found
      </h2>
      <p style={{
        fontSize: tokens.font.base,
        color: tokens.colors.textSecondary,
        marginBottom: '24px',
        textAlign: 'center',
      }}>
        The page you&apos;re looking for doesn&apos;t exist or has been moved.
      </p>
      <Link
        href="/"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          padding: '12px 24px',
          backgroundColor: tokens.colors.accent,
          color: tokens.colors.bg,
          borderRadius: tokens.radius.full,
          textDecoration: 'none',
          fontWeight: Number(tokens.font.weightSemibold),
          transition: tokens.transition.fast,
        }}
      >
        <Home size={18} strokeWidth={2} />
        Back to home
      </Link>
    </div>
  )
}
