'use client'

import Link from 'next/link'
import { tokens } from '../../styles/tokens'

interface ActivationRouteCardProps {
  href: string
  title: string
  body: string
  visited?: boolean
}

export function ActivationRouteCard({ href, title, body, visited }: ActivationRouteCardProps) {
  return (
    <Link
      href={href}
      style={{
        textDecoration: 'none',
        border: `1px solid ${tokens.colors.border}`,
        borderRadius: '16px',
        padding: '16px',
        backgroundColor: tokens.colors.surface,
        display: 'block',
      }}
    >
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '10px',
        marginBottom: '8px',
      }}>
        <div style={{
          color: tokens.colors.textPrimary,
          fontSize: tokens.font.base,
          fontWeight: Number(tokens.font.weightSemibold),
        }}>
          {title}
        </div>
        {visited ? (
          <span style={{
            color: tokens.colors.textSecondary,
            fontSize: tokens.font.xs,
            textTransform: 'uppercase',
            letterSpacing: '0.08em',
          }}>
            Seen
          </span>
        ) : null}
      </div>
      <div style={{
        color: tokens.colors.textSecondary,
        fontSize: tokens.font.sm,
        lineHeight: 1.55,
      }}>
        {body}
      </div>
    </Link>
  )
}
