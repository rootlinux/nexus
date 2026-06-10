'use client'

import { FormEvent, useCallback, useEffect, useRef, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Search, UserPlus, Users } from 'lucide-react'

import Layout from '../../components/Layout'
import { DiscoveryFeed } from '../../components/DiscoveryFeed'
import { getAvatarColor, tokens } from '../../styles/tokens'
import { getSearchHref } from '../../lib/routes'
import { resolveMediaUrl } from '../../lib/media'
import { getDiscoverUsers, getDiscoverPosts, toggleFollow } from '../../lib/api'
import type { DiscoverUser, DiscoverUsersResponse } from '../../lib/api'
import type { DiscoveryFeedResponse } from '../../types'

// ---------------------------------------------------------------------------
// User card (inside horizontal scroll)
// ---------------------------------------------------------------------------

interface UserCardProps {
  user: DiscoverUser
}

function UserCard({ user }: UserCardProps) {
  const [following, setFollowing] = useState(false)
  const [loading, setLoading] = useState(false)

  const handleFollow = useCallback(async () => {
    if (loading) return
    // Optimistic update
    setFollowing((prev) => !prev)
    setLoading(true)
    try {
      await toggleFollow(user.username)
    } catch {
      // Revert on failure
      setFollowing((prev) => !prev)
    } finally {
      setLoading(false)
    }
  }, [loading, user.username])

  const avatarUrl = resolveMediaUrl(user.avatar_url)
  const displayName = user.display_name || user.username
  const initials = displayName.charAt(0).toUpperCase()

  return (
    <div
      style={{
        flexShrink: 0,
        width: '148px',
        padding: '16px 14px 14px',
        borderRadius: tokens.radius.lg,
        border: `1px solid ${tokens.colors.border}`,
        backgroundColor: tokens.colors.surface,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: '6px',
      }}
    >
      {/* Avatar */}
      <div style={{
        width: '52px',
        height: '52px',
        borderRadius: '50%',
        backgroundColor: getAvatarColor(user.username),
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: tokens.colors.textPrimary,
        fontWeight: Number(tokens.font.weightBold),
        fontSize: tokens.font.md,
        overflow: 'hidden',
        flexShrink: 0,
        marginBottom: '4px',
      }}>
        {avatarUrl ? (
          <img src={avatarUrl} alt={displayName} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
        ) : initials}
      </div>

      {/* Name */}
      <div style={{
        color: tokens.colors.textPrimary,
        fontSize: tokens.font.xs,
        fontWeight: Number(tokens.font.weightMedium),
        textAlign: 'center',
        lineHeight: 1.3,
        overflow: 'hidden',
        display: '-webkit-box',
        WebkitLineClamp: 2,
        WebkitBoxOrient: 'vertical',
        width: '100%',
      }}>
        {displayName}
      </div>

      {/* Username */}
      <div style={{
        color: tokens.colors.textSecondary,
        fontSize: '12px',
        textAlign: 'center',
        whiteSpace: 'nowrap',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        width: '100%',
      }}>
        @{user.username}
      </div>

      {/* Mutual count */}
      {user.mutual_count > 0 ? (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '4px',
          color: tokens.colors.textMuted,
          fontSize: '11px',
        }}>
          <Users size={11} strokeWidth={1.75} />
          <span>{user.mutual_count} ortak</span>
        </div>
      ) : null}

      {/* Follow button */}
      <button
        onClick={() => { void handleFollow() }}
        disabled={loading}
        style={{
          marginTop: '6px',
          width: '100%',
          padding: '7px 0',
          borderRadius: tokens.radius.full,
          border: following ? `1px solid ${tokens.colors.border}` : 'none',
          backgroundColor: following ? 'transparent' : tokens.colors.accent,
          color: following ? tokens.colors.textSecondary : tokens.colors.bg,
          fontSize: '13px',
          fontWeight: Number(tokens.font.weightMedium),
          cursor: loading ? 'wait' : 'pointer',
          transition: tokens.transition.fast,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '5px',
        }}
      >
        {!following ? <UserPlus size={13} strokeWidth={2} /> : null}
        {following ? 'Takip ediliyor' : 'Takip et'}
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Suggested users horizontal section
// ---------------------------------------------------------------------------

interface SuggestedUsersSectionProps {
  users: DiscoverUser[]
}

function SuggestedUsersSection({ users }: SuggestedUsersSectionProps) {
  if (users.length === 0) {
    return (
      <div style={{ padding: '20px 16px' }}>
        <div style={{
          borderRadius: tokens.radius.lg,
          border: `1px solid ${tokens.colors.border}`,
          backgroundColor: tokens.colors.surface,
          padding: '24px',
          color: tokens.colors.textSecondary,
          fontSize: tokens.font.sm,
          textAlign: 'center',
        }}>
          Henüz öneri bulunmuyor. Birkaç kişiyi takip etmeye başla.
        </div>
      </div>
    )
  }

  return (
    <div style={{ padding: '20px 0 0' }}>
      <div style={{ padding: '0 16px', marginBottom: '12px' }}>
        <div style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.sm, fontWeight: Number(tokens.font.weightMedium) }}>
          Tanıyor Olabileceğin Kişiler
        </div>
      </div>
      <div
        style={{
          display: 'flex',
          gap: '10px',
          overflowX: 'auto',
          padding: '0 16px 4px',
          scrollbarWidth: 'none',
        }}
      >
        {users.map((user) => (
          <UserCard key={user.id} user={user} />
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Trending posts section
// ---------------------------------------------------------------------------

interface TrendingPostsSectionProps {
  feed: DiscoveryFeedResponse | null
  loading: boolean
  error: string
}

function TrendingPostsSection({ feed, loading, error }: TrendingPostsSectionProps) {
  return (
    <div style={{ marginTop: '24px' }}>
      <div style={{ padding: '0 16px', marginBottom: '12px' }}>
        <div style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.sm, fontWeight: Number(tokens.font.weightMedium) }}>
          Trend Postlar
        </div>
      </div>

      {loading ? (
        <div style={{ padding: '0 16px' }}>
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} style={{
              borderBottom: `1px solid ${tokens.colors.border}`,
              padding: '18px 0',
              display: 'flex',
              gap: '14px',
            }}>
              <div style={{ width: '42px', height: '42px', borderRadius: '50%', backgroundColor: tokens.colors.surface, flexShrink: 0 }} />
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <div style={{ width: '140px', height: '14px', borderRadius: tokens.radius.md, backgroundColor: tokens.colors.surface }} />
                <div style={{ width: '100%', height: '13px', borderRadius: tokens.radius.md, backgroundColor: tokens.colors.surface }} />
                <div style={{ width: '75%', height: '13px', borderRadius: tokens.radius.md, backgroundColor: tokens.colors.surface }} />
              </div>
            </div>
          ))}
        </div>
      ) : error ? (
        <div style={{ padding: '0 16px' }}>
          <div style={{
            borderRadius: tokens.radius.lg,
            border: `1px solid ${tokens.colors.border}`,
            backgroundColor: tokens.colors.surface,
            padding: '20px',
            color: tokens.colors.textSecondary,
            fontSize: tokens.font.sm,
          }}>
            {error}
          </div>
        </div>
      ) : feed && feed.items?.length > 0 ? (
        <DiscoveryFeed items={feed.items} mode={feed.mode} />
      ) : (
        <div style={{ padding: '0 16px' }}>
          <div style={{
            borderRadius: tokens.radius.lg,
            border: `1px solid ${tokens.colors.border}`,
            backgroundColor: tokens.colors.surface,
            padding: '24px',
          }}>
            <div style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.base, fontWeight: Number(tokens.font.weightMedium), marginBottom: '6px' }}>
              Henüz trend post yok
            </div>
            <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm, lineHeight: 1.5 }}>
              Ağ genişledikçe burada daha fazla içerik belirecek.
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function DiscoverPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const initialQuery = searchParams.get('q') ?? ''

  const [searchQuery, setSearchQuery] = useState(initialQuery)
  const [searchFocused, setSearchFocused] = useState(false)

  const [users, setUsers] = useState<DiscoverUser[]>([])
  const [usersLoading, setUsersLoading] = useState(true)

  const [feed, setFeed] = useState<DiscoveryFeedResponse | null>(null)
  const [feedLoading, setFeedLoading] = useState(true)
  const [feedError, setFeedError] = useState('')

  const blurTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    let cancelled = false

    const load = async () => {
      try {
        const data: DiscoverUsersResponse = await getDiscoverUsers(12)
        if (!cancelled) setUsers(data.users)
      } catch {
        // Silently ignore — empty state handles it
      } finally {
        if (!cancelled) setUsersLoading(false)
      }
    }

    void load()
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    let cancelled = false

    const load = async () => {
      try {
        setFeedLoading(true)
        setFeedError('')
        const data = await getDiscoverPosts(15)
        if (!cancelled) setFeed(data)
      } catch (err) {
        if (!cancelled) {
          setFeedError(err instanceof Error ? err.message : 'Trend postlar şu an yüklenemiyor.')
        }
      } finally {
        if (!cancelled) setFeedLoading(false)
      }
    }

    void load()
    return () => { cancelled = true }
  }, [])

  function handleSearchSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (blurTimerRef.current) clearTimeout(blurTimerRef.current)
    setSearchFocused(false)
    router.push(getSearchHref(searchQuery))
  }

  function handleSearchBlur() {
    blurTimerRef.current = setTimeout(() => setSearchFocused(false), 120)
  }

  return (
    <Layout>
      <div style={{ minHeight: '100vh', backgroundColor: tokens.colors.bg }}>
        {/* Sticky header with search */}
        <div
          className="app-sticky-header"
          style={{
            position: 'sticky',
            top: 0,
            zIndex: 10,
            backgroundColor: tokens.colors.bg,
            borderBottom: `1px solid ${tokens.colors.borderSubtle}`,
            padding: '16px 16px 14px',
          }}
        >
          <div style={{ color: tokens.colors.textPrimary, fontSize: '18px', fontWeight: 500, marginBottom: '2px' }}>
            Keşfet
          </div>
          <div style={{ color: tokens.colors.textSecondary, fontSize: '13px', marginBottom: '12px' }}>
            Yeni insanlar ve içerikler bul.
          </div>

          <form onSubmit={handleSearchSubmit} style={{ margin: 0 }}>
            <div style={{
              backgroundColor: tokens.colors.surface,
              border: `1px solid ${searchFocused ? tokens.colors.accent : tokens.colors.border}`,
              borderRadius: tokens.radius.md,
              padding: '10px 14px',
              display: 'flex',
              alignItems: 'center',
              gap: '10px',
              transition: `border-color ${tokens.transition.fast}`,
            }}>
              <Search size={16} strokeWidth={2} color={searchFocused ? tokens.colors.accent : tokens.colors.textSecondary} />
              <input
                value={searchQuery}
                onFocus={() => setSearchFocused(true)}
                onBlur={handleSearchBlur}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="Kişi veya post ara"
                style={{
                  width: '100%',
                  border: 'none',
                  outline: 'none',
                  background: 'transparent',
                  color: tokens.colors.textPrimary,
                  fontSize: '14px',
                }}
              />
            </div>
          </form>
        </div>

        {/* Suggested people */}
        {usersLoading ? (
          <div style={{ padding: '20px 0 0' }}>
            <div style={{ padding: '0 16px', marginBottom: '12px' }}>
              <div style={{ width: '200px', height: '16px', borderRadius: tokens.radius.md, backgroundColor: tokens.colors.surface }} />
            </div>
            <div style={{ display: 'flex', gap: '10px', padding: '0 16px', overflowX: 'hidden' }}>
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} style={{
                  flexShrink: 0,
                  width: '148px',
                  height: '178px',
                  borderRadius: tokens.radius.lg,
                  backgroundColor: tokens.colors.surface,
                  border: `1px solid ${tokens.colors.border}`,
                }} />
              ))}
            </div>
          </div>
        ) : (
          <SuggestedUsersSection users={users} />
        )}

        {/* Trending posts */}
        <TrendingPostsSection feed={feed} loading={feedLoading} error={feedError} />

        {/* Bottom padding for mobile nav */}
        <div style={{ height: '32px' }} />
      </div>
    </Layout>
  )
}
