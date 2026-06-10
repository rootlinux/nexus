'use client'

import Link from 'next/link'

import { tokens } from '../../styles/tokens'
import type { LayoutNavItem } from './types'

interface SidebarNavItemProps {
  item: LayoutNavItem
  isActive: boolean
}

export function SidebarNavItem({ item, isActive }: SidebarNavItemProps) {
  const Icon = item.icon

  return (
    <Link
      href={item.href}
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '12px',
        padding: '9px 12px 9px 14px',
        fontSize: tokens.font.sm,
        borderRadius: tokens.radius.md,
        color: isActive ? tokens.colors.textPrimary : tokens.colors.textSecondary,
        fontWeight: isActive ? Number(tokens.font.weightMedium) : Number(tokens.font.weightNormal),
        transition: tokens.transition.fast,
        textDecoration: 'none',
        backgroundColor: isActive ? tokens.colors.surface : 'transparent',
        borderLeft: isActive ? `2px solid ${tokens.colors.accent}` : '2px solid transparent',
      }}
      onMouseEnter={(event) => {
        if (!isActive) {
          event.currentTarget.style.backgroundColor = tokens.colors.surface
          event.currentTarget.style.color = tokens.colors.textPrimary
        }
      }}
      onMouseLeave={(event) => {
        if (!isActive) {
          event.currentTarget.style.backgroundColor = 'transparent'
          event.currentTarget.style.color = tokens.colors.textSecondary
        }
      }}
    >
      <span style={{ display: 'flex', alignItems: 'center', gap: '13px', minWidth: 0 }}>
        <Icon
          size={17}
          strokeWidth={isActive ? 2.25 : 1.75}
          style={{ color: isActive ? tokens.colors.accent : 'inherit', flexShrink: 0 }}
        />
        <span>{item.label}</span>
      </span>
      {item.badge ? (
        <span
          style={{
            padding: '2px 7px',
            borderRadius: tokens.radius.full,
            backgroundColor: tokens.colors.accentMuted,
            color: tokens.colors.accent,
            fontSize: '10px',
            fontWeight: Number(tokens.font.weightMedium),
            letterSpacing: '0.04em',
            whiteSpace: 'nowrap',
          }}
        >
          {item.badge}
        </span>
      ) : null}
    </Link>
  )
}
