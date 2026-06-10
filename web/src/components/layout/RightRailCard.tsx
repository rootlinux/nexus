'use client'

import type { ReactNode } from 'react'

import { tokens } from '../../styles/tokens'

interface RightRailCardProps {
  title: string
  eyebrow?: string
  children: ReactNode
  noBorder?: boolean
}

export function RightRailCard({ title, eyebrow, children, noBorder = false }: RightRailCardProps) {
  return (
    <div
      style={{
        backgroundColor: noBorder ? 'transparent' : tokens.colors.surface,
        border: noBorder ? 'none' : `1px solid ${tokens.colors.border}`,
        borderRadius: '10px',
        padding: '16px',
        marginBottom: '12px',
      }}
    >
      {eyebrow ? (
        <div
          style={{
            color: tokens.colors.textMuted,
            fontSize: '10px',
            textTransform: 'uppercase',
            letterSpacing: '0.08em',
            marginBottom: '6px',
          }}
        >
          {eyebrow}
        </div>
      ) : null}
      <h3
        style={{
          fontSize: tokens.font.sm,
          fontWeight: Number(tokens.font.weightSemibold),
          color: tokens.colors.textPrimary,
          marginBottom: '12px',
          letterSpacing: '-0.01em',
        }}
      >
        {title}
      </h3>
      {children}
    </div>
  )
}
