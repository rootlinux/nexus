'use client'

import { useEffect, useState } from 'react'

import { getTrendingPosts } from '../../lib/api'
import { tokens } from '../../styles/tokens'
import type { DiscoveryFeedResponse } from '../../types'
import { DiscoveryFeed } from '../DiscoveryFeed'

const RAIL_CACHE_TTL_MS = 60_000

let trendingCache: { feed: DiscoveryFeedResponse | null; expiresAt: number } | null = null

export function TrendingSection() {
  const [feed, setFeed] = useState<DiscoveryFeedResponse | null>(() =>
    trendingCache && trendingCache.expiresAt > Date.now() ? trendingCache.feed : null
  )
  const [loading, setLoading] = useState(() => !(trendingCache && trendingCache.expiresAt > Date.now()))

  useEffect(() => {
    if (trendingCache && trendingCache.expiresAt > Date.now()) {
      return
    }

    let cancelled = false

    const loadTrending = async () => {
      try {
        const data = await getTrendingPosts(5)
        if (!cancelled) {
          trendingCache = {
            feed: data,
            expiresAt: Date.now() + RAIL_CACHE_TTL_MS,
          }
          setFeed(data)
        }
      } catch {
        if (!cancelled) {
          setFeed((previousFeed) => previousFeed ?? { mode: 'trending', window_hours: 48, items: [] })
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    void loadTrending()

    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {loading ? (
        <p style={{ margin: 0, color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>Reading the latest signal...</p>
      ) : !feed || !feed.items?.length ? (
        <p style={{ margin: 0, color: tokens.colors.textSecondary, fontSize: tokens.font.sm, lineHeight: 1.5 }}>
          Nothing is moving with enough weight yet. The rail will stay quiet until something earns it.
        </p>
      ) : (
        <DiscoveryFeed items={feed.items} variant="compact" />
      )}
    </div>
  )
}
