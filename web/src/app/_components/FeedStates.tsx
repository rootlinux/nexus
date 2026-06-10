'use client'

import { tokens } from '../../styles/tokens'
import type { LucideIcon } from 'lucide-react'
import { AlertCircle, FileText } from 'lucide-react'

interface PostSkeletonProps {
  // No props needed - self-contained
}

export function PostSkeleton() {
  return (
    <div style={{
      padding: '20px 24px',
      borderBottom: `1px solid ${tokens.colors.borderSubtle}`,
      backgroundColor: tokens.colors.surface,
      display: 'flex',
      gap: '12px',
    }}>
      <div style={{
        width: '40px',
        height: '40px',
        borderRadius: '50%',
        backgroundColor: tokens.colors.surface,
        animation: 'pulse 1.5s ease-in-out infinite',
      }} />
      <div style={{ flex: 1 }}>
        <div style={{
          height: '14px',
          width: '120px',
          backgroundColor: tokens.colors.surface,
          borderRadius: '4px',
          marginBottom: '8px',
          animation: 'pulse 1.5s ease-in-out infinite',
        }} />
        <div style={{
          height: '14px',
          width: '80%',
          backgroundColor: tokens.colors.surface,
          borderRadius: '4px',
          marginBottom: '12px',
          animation: 'pulse 1.5s ease-in-out infinite',
        }} />
        <div style={{
          height: '32px',
          backgroundColor: tokens.colors.surface,
          borderRadius: '4px',
          animation: 'pulse 1.5s ease-in-out infinite',
        }} />
      </div>
    </div>
  )
}

interface EmptyStateProps {
  title: string
  message: string
  icon: LucideIcon
}

export function EmptyState({ title, message, icon: Icon }: EmptyStateProps) {
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '60px 20px',
      textAlign: 'center',
    }}>
      <Icon size={48} strokeWidth={1.5} style={{ marginBottom: '16px', color: tokens.colors.textSecondary, opacity: 0.5 }} />
      <h3 style={{
        fontSize: tokens.font.xl,
        fontWeight: Number(tokens.font.weightSemibold),
        color: tokens.colors.textPrimary,
        marginBottom: '8px',
      }}>
        {title}
      </h3>
      <p style={{
        color: tokens.colors.textSecondary,
        fontSize: tokens.font.base,
        maxWidth: '280px',
      }}>
        {message}
      </p>
    </div>
  )
}

interface ErrorStateProps {
  message: string
  onRetry: () => void
}

export function ErrorState({ message, onRetry }: ErrorStateProps) {
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '60px 20px',
      textAlign: 'center',
    }}>
      <AlertCircle size={48} strokeWidth={1.5} style={{ marginBottom: '16px', color: tokens.colors.danger }} />
      <h3 style={{
        fontSize: tokens.font.lg,
        fontWeight: Number(tokens.font.weightSemibold),
        color: tokens.colors.danger,
        marginBottom: '8px',
      }}>
        Something went wrong
      </h3>
      <p style={{
        color: tokens.colors.textSecondary,
        fontSize: tokens.font.sm,
        marginBottom: '16px',
      }}>
        {message}
      </p>
      <button
        onClick={onRetry}
        style={{
          backgroundColor: tokens.colors.accent,
          color: tokens.colors.bg,
          border: 'none',
          borderRadius: tokens.radius.full,
          padding: '10px 20px',
          fontWeight: Number(tokens.font.weightMedium),
          cursor: 'pointer',
          transition: tokens.transition.fast,
        }}
      >
        Try again
      </button>
    </div>
  )
}
