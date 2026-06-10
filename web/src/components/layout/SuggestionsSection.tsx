'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'

import { getSuggestions, toggleFollow } from '../../lib/api'
import { resolveMediaUrl } from '../../lib/media'
import { getProfileHref } from '../../lib/routes'
import { getAvatarColor, tokens } from '../../styles/tokens'
import type { SuggestedUser } from '../../types'
import { getMemberTrustFacts } from '../PostSurface'

const RAIL_CACHE_TTL_MS = 60_000

let suggestionsCache: { items: SuggestedUser[]; expiresAt: number } | null = null

interface SuggestionsSectionProps {
  activationActive: boolean
}

function getErrorMessage(error: unknown) {
  if (
    typeof error === 'object' &&
    error !== null &&
    'response' in error &&
    typeof (error as { response?: unknown }).response === 'object' &&
    (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail &&
    typeof (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail === 'string'
  ) {
    return (error as { response?: { data?: { detail?: string } } }).response?.data?.detail || 'Could not update follow status.'
  }

  if (error instanceof Error && error.message) {
    return error.message
  }

  return 'Could not update follow status.'
}

export function SuggestionsSection({ activationActive }: SuggestionsSectionProps) {
  const [items, setItems] = useState<SuggestedUser[]>(() =>
    suggestionsCache && suggestionsCache.expiresAt > Date.now() ? suggestionsCache.items : []
  )
  const [loading, setLoading] = useState(() => !(suggestionsCache && suggestionsCache.expiresAt > Date.now()))
  const [pendingUsername, setPendingUsername] = useState<string | null>(null)
  const [followErrorByUsername, setFollowErrorByUsername] = useState<Record<string, string>>({})
  const isMountedRef = useRef(true)

  useEffect(() => {
    return () => {
      isMountedRef.current = false
    }
  }, [])

  useEffect(() => {
    if (suggestionsCache && suggestionsCache.expiresAt > Date.now()) {
      return
    }

    let cancelled = false

    const loadSuggestions = async () => {
      try {
        const data = await getSuggestions(5)
        const nextItems = Array.isArray(data?.users) ? data.users : []
        suggestionsCache = {
          items: nextItems,
          expiresAt: Date.now() + RAIL_CACHE_TTL_MS,
        }
        if (!cancelled) {
          setItems(nextItems)
        }
      } catch {
        if (!cancelled) {
          setItems((previousItems) => previousItems)
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    void loadSuggestions()

    return () => {
      cancelled = true
    }
  }, [])

  const handleFollow = async (username: string) => {
    try {
      setFollowErrorByUsername((previous) => ({ ...previous, [username]: '' }))
      setPendingUsername(username)
      const data = await toggleFollow(username)
      if (!isMountedRef.current) {
        return
      }
      setItems((previousItems) => {
        const nextItems = previousItems.map((user) =>
          user.username === username
            ? {
                ...user,
                is_following: data.following,
                followers_count: data.followers_count,
                following_count: data.following_count,
              }
            : user
        )
        suggestionsCache = {
          items: nextItems,
          expiresAt: Date.now() + RAIL_CACHE_TTL_MS,
        }
        return nextItems
      })
    } catch (error: unknown) {
      if (isMountedRef.current) {
        setFollowErrorByUsername((previous) => ({ ...previous, [username]: getErrorMessage(error) }))
      }
    } finally {
      if (isMountedRef.current) {
        setPendingUsername(null)
      }
    }
  }

  if (loading) {
    return <p style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm, margin: 0, lineHeight: 1.5 }}>Finding people worth keeping close...</p>
  }

  if (items.length === 0) {
    return (
      <p style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm, lineHeight: 1.4, margin: 0 }}>
        {activationActive
          ? 'Start with a few considered follows. The feed sharpens quickly once your circle has real shape.'
          : 'Introductions will settle here once your circle starts to take shape.'}
      </p>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
      {items.map((user) => {
        const membershipFacts = getMemberTrustFacts(user, { introducerLabel: 'Introduced by' })

        return (
          <div key={user.id} style={{ display: 'flex', gap: '10px', alignItems: 'flex-start' }}>
            <Link href={getProfileHref(user.username)} style={{ textDecoration: 'none' }}>
              <div
                style={{
                  width: '36px',
                  height: '36px',
                  borderRadius: '50%',
                  overflow: 'hidden',
                  backgroundColor: getAvatarColor(user.username),
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: tokens.colors.textPrimary,
                  fontWeight: Number(tokens.font.weightBold),
                  fontSize: tokens.font.sm,
                  flexShrink: 0,
                }}
              >
                {user.avatar_url ? (
                  <img src={resolveMediaUrl(user.avatar_url) || undefined} alt={user.username} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                ) : (
                  user.username.charAt(0).toUpperCase()
                )}
              </div>
            </Link>
            <div style={{ flex: 1, minWidth: 0 }}>
              <Link href={getProfileHref(user.username)} style={{ textDecoration: 'none' }}>
                <div style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.sm, fontWeight: Number(tokens.font.weightMedium) }}>
                  {user.display_name || user.username}
                </div>
                <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.xs }}>
                  @{user.username}
                </div>
              </Link>
              {membershipFacts.length ? (
                <div style={{ color: tokens.colors.textSecondary, fontSize: '11px', marginTop: '4px', lineHeight: 1.45 }}>
                  {membershipFacts.join(' · ')}
                </div>
              ) : null}
              <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.xs, marginTop: '4px', lineHeight: 1.4 }}>
                {user.reason}
              </div>
              {followErrorByUsername[user.username] ? (
                <div style={{ color: tokens.colors.danger, fontSize: tokens.font.xs, marginTop: '6px', lineHeight: 1.4 }}>
                  {followErrorByUsername[user.username]}
                </div>
              ) : null}
            </div>
            <button
              type="button"
              className="btn-ghost"
              onClick={() => void handleFollow(user.username)}
              disabled={pendingUsername === user.username}
              style={{
                borderRadius: tokens.radius.full,
                backgroundColor: 'transparent',
                color: tokens.colors.textPrimary,
                padding: '6px 12px',
                fontSize: tokens.font.xs,
                fontWeight: Number(tokens.font.weightMedium),
                flexShrink: 0,
              }}
            >
              {pendingUsername === user.username ? '...' : user.is_following ? 'Following' : 'Follow'}
            </button>
          </div>
        )
      })}
      {activationActive ? (
        <p style={{ margin: 0, color: tokens.colors.textSecondary, fontSize: tokens.font.xs, lineHeight: 1.5 }}>
          A few good follows are usually enough to make the next session feel more alive.
        </p>
      ) : null}
    </div>
  )
}
