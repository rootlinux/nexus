'use client'

import Link from 'next/link'

import { tokens } from '../../styles/tokens'
import type { LayoutNavItem } from './types'

interface MobileNavProps {
  navItems: LayoutNavItem[]
  isAdmin: boolean
  isActive: (href: string) => boolean
}

export function MobileNav({ navItems, isAdmin, isActive }: MobileNavProps) {
  const mobileItemIds = isAdmin
    ? (['home', 'discover', 'notifications', 'messages', 'admin', 'profile'] as const)
    : (['home', 'discover', 'notifications', 'messages', 'profile'] as const)

  return (
    <nav
      className="app-mobile-nav"
      style={{
        position: 'fixed',
        bottom: 0,
        left: 0,
        right: 0,
        minHeight: '60px',
        backgroundColor: tokens.colors.surface,
        borderTop: `1px solid ${tokens.colors.border}`,
        display: 'flex',
        justifyContent: 'space-around',
        alignItems: 'center',
        zIndex: 100,
      }}
    >
      {mobileItemIds.map((id) => {
        const item = navItems.find((candidate) => candidate.id === id)
        if (!item) {
          return null
        }

        const Icon = item.icon

        return (
          <Link
            key={`mobile-${item.id}`}
            href={item.href}
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              flex: 1,
              minHeight: '44px',
              padding: '6px 4px',
              color: isActive(item.href) ? tokens.colors.accent : tokens.colors.textMuted,
              fontSize: '10px',
              textDecoration: 'none',
              gap: '2px',
            }}
          >
            <Icon size={22} strokeWidth={isActive(item.href) ? 2 : 1.75} />
            {item.label}
          </Link>
        )
      })}
    </nav>
  )
}
