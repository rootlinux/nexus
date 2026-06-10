'use client'

import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { Bell, Bookmark, Compass, House, MessageCircle, Search, Shield, User } from 'lucide-react'
import { usePathname } from 'next/navigation'

import { useAuth } from '../contexts/AuthContext'
import { getActivationStage, isMemberActivationActive } from '../lib/activation'
import { resolveMediaUrl, subscribeToCurrentUserProfileUpdate } from '../lib/media'
import { getRecentConversation, isReturningSessionEligible } from '../lib/reentry'
import { getProfileHref } from '../lib/routes'
import { tokens } from '../styles/tokens'
import { MobileNav } from './layout/MobileNav'
import { RightRail } from './layout/RightRail'
import { Sidebar } from './layout/Sidebar'
import type { LayoutNavItem } from './layout/types'

interface LayoutProps {
  children: ReactNode
}

export default function Layout({ children }: LayoutProps) {
  const pathname = usePathname()
  const { user, isLoading: isAuthLoading, memberActivationState, returningSessionState, markActivationSurface } = useAuth()
  const [profileOverrides, setProfileOverrides] = useState<{
    username: string
    displayName?: string | null
    avatarUrl?: string | null
  } | null>(null)
  const [isMobile, setIsMobile] = useState(false)

  const isLoggedIn = Boolean(user)
  const isAdmin = Boolean(user?.is_admin)
  const currentUsername = user?.username || ''
  const activeProfileOverrides = profileOverrides?.username === currentUsername ? profileOverrides : null
  const currentDisplayName = activeProfileOverrides?.displayName ?? user?.display_name ?? ''
  const currentAvatarUrl = activeProfileOverrides?.avatarUrl ?? resolveMediaUrl(user?.avatar_url)

  useEffect(() => {
    return subscribeToCurrentUserProfileUpdate((detail) => {
      setProfileOverrides((current) => ({
        username: currentUsername,
        displayName:
          typeof detail.display_name !== 'undefined'
            ? detail.display_name || ''
            : current?.username === currentUsername
              ? current.displayName
              : undefined,
        avatarUrl:
          typeof detail.avatar_url !== 'undefined'
            ? resolveMediaUrl(detail.avatar_url)
            : current?.username === currentUsername
              ? current.avatarUrl
              : undefined,
      }))
    })
  }, [currentUsername])

  useEffect(() => {
    const mediaQuery = window.matchMedia('(max-width: 639px)')
    const syncMobile = (event?: MediaQueryList | MediaQueryListEvent) => {
      const matches = 'matches' in (event || mediaQuery) ? (event || mediaQuery).matches : mediaQuery.matches
      setIsMobile((current) => (current === matches ? current : matches))
    }

    syncMobile(mediaQuery)

    if (typeof mediaQuery.addEventListener === 'function') {
      mediaQuery.addEventListener('change', syncMobile)
      return () => mediaQuery.removeEventListener('change', syncMobile)
    }

    mediaQuery.addListener(syncMobile)
    return () => mediaQuery.removeListener(syncMobile)
  }, [])

  const matchesRoute = useCallback(
    (href: string) => {
      if (href === '/') {
        return pathname === '/'
      }

      return pathname === href || pathname.startsWith(`${href}/`)
    },
    [pathname]
  )

  useEffect(() => {
    if (!isLoggedIn || !memberActivationState || !isMemberActivationActive(memberActivationState)) {
      return
    }

    if (matchesRoute('/')) {
      markActivationSurface('home')
      return
    }

    if (matchesRoute('/explore')) {
      markActivationSurface('explore')
      return
    }

    if (matchesRoute('/search')) {
      markActivationSurface('search')
      return
    }

    if (currentUsername && matchesRoute(getProfileHref(currentUsername))) {
      markActivationSurface('profile')
    }
  }, [currentUsername, isLoggedIn, markActivationSurface, matchesRoute, memberActivationState])

  if (isAuthLoading) {
    return null
  }

  if (!isLoggedIn) {
    return <>{children}</>
  }

  const activationActive = isMemberActivationActive(memberActivationState)
  const activationStage = getActivationStage(memberActivationState)
  const visitedSurfaces = new Set(memberActivationState?.visitedSurfaces || [])
  const completedActions = new Set(memberActivationState?.completedActions || [])
  const isMessagesPage = matchesRoute('/messages')
  const returningEligible = isReturningSessionEligible(returningSessionState)
  const recentConversation = getRecentConversation(returningSessionState)

  const navItems: LayoutNavItem[] = [
    { id: 'home', href: '/', label: 'Feed', icon: House },
    {
      id: 'explore',
      href: '/explore',
      label: 'Explore',
      icon: Search,
      badge: activationActive && !visitedSurfaces.has('explore') ? 'Start here' : undefined,
    },
    { id: 'discover', href: '/discover', label: 'Discover', icon: Compass },
    { id: 'bookmarks', href: '/bookmarks', label: 'Saved', icon: Bookmark },
    { id: 'notifications', href: '/notifications', label: 'Activity', icon: Bell },
    { id: 'messages', href: '/messages', label: 'Messages', icon: MessageCircle },
    { id: 'security', href: '/security', label: 'Security', icon: Shield },
    ...(isAdmin ? [{ id: 'admin', href: '/admin', label: 'Admin', icon: Shield }] : []),
    ...(currentUsername
      ? [
          {
            id: 'profile',
            href: getProfileHref(currentUsername),
            label: 'Profile',
            icon: User,
            badge: activationActive && !visitedSurfaces.has('profile') ? 'Shape it' : undefined,
          },
        ]
      : []),
  ]

  return (
    <div className="app-shell" style={{ display: 'flex', minHeight: '100vh', backgroundColor: tokens.colors.bg }}>
      {!isMobile && currentUsername ? (
        <Sidebar
          navItems={navItems}
          isActive={matchesRoute}
          profile={{
            username: currentUsername,
            displayName: currentDisplayName,
            avatarUrl: currentAvatarUrl,
          }}
        />
      ) : null}

      <main
        className="app-main"
        style={{
          flex: 1,
          minWidth: 0,
          maxWidth: isMobile ? '100%' : isMessagesPage ? '1120px' : '600px',
          minHeight: '100vh',
          backgroundColor: tokens.colors.bg,
          paddingBottom: isMobile ? 'calc(76px + var(--safe-area-bottom))' : 0,
        }}
      >
        {children}
      </main>

      {!isMobile && !isMessagesPage ? (
        <RightRail
          activationActive={activationActive}
          activationStage={activationStage}
          completedActions={completedActions}
          currentUsername={currentUsername}
          returningEligible={returningEligible}
          recentConversation={recentConversation}
        />
      ) : null}

      {isMobile ? <MobileNav navItems={navItems} isAdmin={isAdmin} isActive={matchesRoute} /> : null}
    </div>
  )
}
