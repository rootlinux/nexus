'use client'

import Link from 'next/link'
import { LogOut, PenLine } from 'lucide-react'

import { useAuth } from '../../contexts/AuthContext'
import { getProfileHref } from '../../lib/routes'
import { getAvatarColor, tokens } from '../../styles/tokens'
import { BrandLogo } from '../BrandLogo'
import { SidebarNavItem } from './SidebarNavItem'
import type { LayoutNavItem, LayoutProfileSummary } from './types'

interface SidebarProps {
  navItems: LayoutNavItem[]
  isActive: (href: string) => boolean
  profile: LayoutProfileSummary
}

export function Sidebar({ navItems, isActive, profile }: SidebarProps) {
  const { logout } = useAuth()

  return (
    <aside
      className="app-sidebar"
      style={{
        width: '240px',
        position: 'sticky',
        top: 0,
        height: '100vh',
        padding: '20px 12px 20px 16px',
        display: 'flex',
        flexDirection: 'column',
        gap: '8px',
        flexShrink: 0,
        borderRight: `1px solid ${tokens.colors.borderSubtle}`,
      }}
    >
      <div style={{ padding: '4px 2px 12px' }}>
        <BrandLogo variant="mark" width={28} />
      </div>

      <nav style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '1px' }}>
        {navItems.map((item) => (
          <SidebarNavItem key={`sidebar-${item.id}`} item={item} isActive={isActive(item.href)} />
        ))}
      </nav>

      <Link
        href="/compose"
        className="btn-write"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '8px',
          width: '100%',
          height: '42px',
          borderRadius: tokens.radius.md,
          textDecoration: 'none',
          marginTop: '4px',
        }}
      >
        <PenLine size={15} strokeWidth={2.25} />
        <span>Write</span>
      </Link>

      <div
        style={{
          backgroundColor: tokens.colors.surface,
          border: `1px solid ${tokens.colors.border}`,
          borderRadius: '10px',
          padding: '12px',
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          marginTop: '4px',
        }}
      >
        <Link
          href={getProfileHref(profile.username)}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            textDecoration: 'none',
            flex: 1,
            minWidth: 0,
          }}
        >
          <div
            style={{
              width: '32px',
              height: '32px',
              borderRadius: '50%',
              backgroundColor: getAvatarColor(profile.username || 'x'),
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: tokens.colors.textPrimary,
              fontWeight: Number(tokens.font.weightBold),
              fontSize: tokens.font.sm,
              overflow: 'hidden',
              flexShrink: 0,
            }}
          >
            {profile.avatarUrl ? (
              <img src={profile.avatarUrl} alt={profile.username} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
            ) : (
              profile.username.charAt(0).toUpperCase()
            )}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div
              style={{
                color: tokens.colors.textPrimary,
                fontSize: tokens.font.sm,
                fontWeight: Number(tokens.font.weightMedium),
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              {profile.displayName || profile.username}
            </div>
            <div
              style={{
                color: tokens.colors.textSecondary,
                fontSize: tokens.font.xs,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              @{profile.username}
            </div>
          </div>
        </Link>
        <button
          onClick={() => {
            void logout()
          }}
          style={{
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            color: tokens.colors.textMuted,
            padding: '6px',
            borderRadius: tokens.radius.sm,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            transition: tokens.transition.fast,
            flexShrink: 0,
          }}
          onMouseEnter={(event) => {
            event.currentTarget.style.color = tokens.colors.danger
          }}
          onMouseLeave={(event) => {
            event.currentTarget.style.color = tokens.colors.textMuted
          }}
          title="Log out"
        >
          <LogOut size={16} strokeWidth={1.75} />
        </button>
      </div>
    </aside>
  )
}
