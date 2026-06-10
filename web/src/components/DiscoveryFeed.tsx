'use client'

import Link from 'next/link'
import { Bookmark, Heart, Image as ImageIcon, MessageCircle, Repeat2, Sparkles, TrendingUp } from 'lucide-react'

import { MemberTrustLine, formatRelativeTime, getDisplayPost, PostActionRow, PostAvatar, PostContextLine, PostHeader, PostMediaBlock, PostPreviewLink, getMemberTrustFacts, getPostContext } from './PostSurface'
import { QuotedPostEmbed } from './QuotedPostEmbed'
import { ReplyContext } from './ReplyContext'
import { getPostHref } from '../lib/routes'
import { tokens } from '../styles/tokens'
import type { DiscoveryPostEntry } from '../types'

interface DiscoveryFeedProps {
  items: DiscoveryPostEntry[]
  variant?: 'full' | 'compact'
  mode?: 'for_you' | 'trending'
}

function getDiscoveryModeLabel(mode: 'for_you' | 'trending') {
  return mode === 'trending' ? 'Trending' : 'For you'
}

function normalizeDiscoveryReason(reason: string | null | undefined) {
  if (!reason) {
    return null
  }

  const normalized = reason.replace(/\s+/g, ' ').trim()
  if (!normalized) {
    return null
  }

  const lowered = normalized.toLowerCase()

  if (lowered.includes('people you follow')) {
    return 'From people you follow'
  }

  if (
    lowered.includes('beyond your network') ||
    lowered.includes('outside your network') ||
    lowered.includes('beyond your circle')
  ) {
    return 'Trending beyond your circle'
  }

  if (/(score|scoring|rank|ranking|candidate|engagement|velocity|debug|model|algorithm)/.test(lowered)) {
    return null
  }

  return normalized
}

function EngagementRow({ item }: { item: DiscoveryPostEntry }) {
  const parts = [
    { icon: Heart, value: item.engagement.likes, label: 'likes' },
    { icon: Repeat2, value: item.engagement.reposts, label: 'reposts' },
    { icon: MessageCircle, value: item.engagement.replies, label: 'replies' },
  ]

  return (
    <div style={{ display: 'flex', gap: '14px', flexWrap: 'wrap', color: tokens.colors.textSecondary, fontSize: tokens.font.xs }}>
      {parts.map(({ icon: Icon, value, label }) => (
        <span key={label} style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
          <Icon size={14} strokeWidth={2} />
          <span>{value} {label}</span>
        </span>
      ))}
    </div>
  )
}

export function DiscoveryFeed({ items, variant = 'full', mode = 'trending' }: DiscoveryFeedProps) {
  if (variant === 'compact') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {items.map((item) => {
          const compactAuthor = getDisplayPost(item.post).author
          const compactTrustFacts = getMemberTrustFacts(compactAuthor, {
            introducerLabel: 'Introduced by',
            memberSinceLabel: 'Since',
          })

          return (
          <Link
            key={item.post_id}
            href={getPostHref(item.post_id, {
              entry: 'discovery',
              focus: item.post.parent_id ? 'reply' : item.post.is_quote ? 'quote' : 'conversation',
            })}
            style={{
              display: 'flex',
              gap: '12px',
              textDecoration: 'none',
              padding: '10px 0',
              borderTop: `1px solid ${tokens.colors.border}`,
            }}
          >
            <div style={{ minWidth: 0, flex: 1 }}>
              {compactTrustFacts.length ? (
                <div style={{ color: tokens.colors.textSecondary, fontSize: '11px', marginBottom: '4px', lineHeight: 1.45 }}>
                  {compactTrustFacts.join(' · ')}
                </div>
              ) : null}
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px', flexWrap: 'wrap' }}>
                <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.xs }}>
                  {getDiscoveryModeLabel(mode)}
                </span>
                {item.category_label ? (
                  <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.xs }}>
                    {item.category_label}
                  </span>
                ) : null}
                <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.xs }}>
                  @{item.author.username}
                </span>
              </div>
              <div style={{
                color: tokens.colors.textPrimary,
                fontSize: tokens.font.base,
                fontWeight: Number(tokens.font.weightMedium),
                lineHeight: 1.35,
                display: '-webkit-box',
                WebkitLineClamp: 2,
                WebkitBoxOrient: 'vertical',
                overflow: 'hidden',
              }}>
                {item.content_preview}
              </div>
              <div style={{ marginTop: '6px' }}>
                <EngagementRow item={item} />
              </div>
            </div>
          </Link>
        )})}
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      {items.map((item) => {
        const showTrendingChrome = mode === 'trending'
        const displayPost = getDisplayPost(item.post)
        const context = getPostContext(item.post)
        const discoveryReason = normalizeDiscoveryReason(item.discovery_reason)

        return (
          <article
            key={item.post_id}
            style={{
              borderBottom: `1px solid ${tokens.colors.border}`,
              padding: '18px 16px',
              transition: tokens.transition.fast,
            }}
          >
            <div style={{ display: 'flex', gap: '14px' }}>
              <PostAvatar user={displayPost.author} size={42} />

              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'flex-start', marginBottom: '10px' }}>
                  <div style={{ minWidth: 0 }}>
                    {context ? <PostContextLine icon={context.icon} text={context.text} style={{ marginBottom: '8px' }} /> : null}
                    <PostHeader
                      author={displayPost.author}
                      timestamp={formatRelativeTime(item.created_at)}
                      detailLine={<MemberTrustLine user={displayPost.author} introducerLabel="Introduced by" />}
                      timestampHref={getPostHref(displayPost.id, {
                        entry: 'discovery',
                        focus: displayPost.parent_id ? 'reply' : displayPost.is_quote ? 'quote' : 'conversation',
                      })}
                    />
                    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                      <span style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '6px',
                        padding: '4px 10px',
                        borderRadius: tokens.radius.full,
                        backgroundColor: `${tokens.colors.accent}16`,
                        color: tokens.colors.accent,
                        fontSize: tokens.font.xs,
                        fontWeight: Number(tokens.font.weightSemibold),
                      }}>
                        {showTrendingChrome ? <TrendingUp size={12} strokeWidth={2.2} /> : <Sparkles size={12} strokeWidth={2.2} />}
                        {getDiscoveryModeLabel(mode)}
                      </span>
                      {item.category_label ? (
                        <span style={{
                          padding: '4px 10px',
                          borderRadius: tokens.radius.full,
                          backgroundColor: tokens.colors.surface,
                          border: `1px solid ${tokens.colors.border}`,
                          color: tokens.colors.textSecondary,
                          fontSize: tokens.font.xs,
                        }}>
                          {item.category_label}
                        </span>
                      ) : null}
                    </div>
                  </div>
                </div>

                {discoveryReason ? (
                  <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm, marginBottom: '10px', lineHeight: 1.45 }}>
                    {discoveryReason}
                  </div>
                ) : null}

                {displayPost.content ? (
                  <PostPreviewLink post={displayPost} entry="discovery" style={{ marginBottom: '12px' }}>
                    <div style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.md, lineHeight: 1.45, whiteSpace: 'pre-wrap' }}>
                      <ReplyContext post={displayPost} entry="discovery" />
                      {displayPost.content}
                    </div>
                  </PostPreviewLink>
                ) : null}

                {displayPost.media_url || item.media_url ? (
                  <div style={{ marginBottom: '12px' }}>
                    <PostMediaBlock postId={displayPost.id} mediaUrl={displayPost.media_url || item.media_url} maxHeight={360} />
                  </div>
                ) : item.post.media_url || item.has_media ? (
                  <div style={{
                    marginBottom: '12px',
                    borderRadius: '18px',
                    border: `1px dashed ${tokens.colors.border}`,
                    color: tokens.colors.textSecondary,
                    padding: '18px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '10px',
                    fontSize: tokens.font.sm,
                  }}>
                    <ImageIcon size={16} strokeWidth={2} />
                    Media attached
                  </div>
                ) : null}

                {displayPost.quoted_post || displayPost.quoted_post_unavailable ? (
                  <QuotedPostEmbed
                    post={displayPost.quoted_post}
                    unavailable={displayPost.quoted_post_unavailable}
                    placeholder={displayPost.quoted_post_placeholder}
                  />
                ) : null}

                <PostActionRow
                  items={[
                    {
                      icon: MessageCircle,
                      label: 'Reply',
                      count: item.engagement.replies,
                      href: getPostHref(item.post_id, {
                        entry: 'discovery',
                        focus: displayPost.parent_id ? 'reply' : displayPost.is_quote ? 'quote' : 'conversation',
                      }),
                    },
                    { icon: Repeat2, label: 'Repost', count: item.engagement.reposts },
                    { icon: Heart, label: 'Like', count: item.engagement.likes },
                    {
                      icon: Bookmark,
                      label: 'Bookmark',
                      alwaysShowLabel: true,
                      href: getPostHref(item.post_id, {
                        entry: 'discovery',
                        focus: displayPost.parent_id ? 'reply' : displayPost.is_quote ? 'quote' : 'conversation',
                      }),
                    },
                  ]}
                />
              </div>
            </div>
          </article>
        )
      })}
    </div>
  )
}
