'use client'

import Link from 'next/link'

import { getPostHref, getProfileHref } from '../lib/routes'
import { tokens } from '../styles/tokens'
import type { Post } from '../types'
import { formatRelativeTime, PostAvatar, PostHeader, PostMediaBlock, UnavailablePostBlock } from './PostSurface'

export function QuotedPostEmbed({
  post,
  unavailable = false,
  placeholder,
}: {
  post?: Post | null
  unavailable?: boolean
  placeholder?: string | null
}) {
  if (unavailable || !post) {
    return <UnavailablePostBlock message={placeholder || 'This quoted post is currently unavailable.'} />
  }

  return (
    <div
      style={{
        display: 'block',
        marginTop: '12px',
        border: `1px solid ${tokens.colors.border}`,
        borderRadius: '16px',
        padding: '14px',
        backgroundColor: tokens.colors.surface,
        color: 'inherit',
      }}
    >
      <div style={{ display: 'flex', gap: '10px' }}>
        <Link href={getProfileHref(post.author.username)} style={{ textDecoration: 'none' }}>
          <PostAvatar user={post.author} size={28} />
        </Link>

        <div style={{ minWidth: 0, flex: 1 }}>
          <PostHeader author={post.author} timestamp={formatRelativeTime(post.created_at)} timestampHref={getPostHref(post.id)} />

          <Link href={getPostHref(post.id)} style={{ display: 'block', textDecoration: 'none', color: 'inherit' }}>
            {post.content ? (
              <div style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.sm, lineHeight: 1.45, marginTop: '6px', whiteSpace: 'pre-wrap' }}>
                {post.content}
              </div>
            ) : null}
          </Link>
          <PostMediaBlock postId={post.id} mediaUrl={post.media_url} maxHeight={280} />
        </div>
      </div>
    </div>
  )
}
