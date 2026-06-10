'use client'

import Link from 'next/link'

import { getPostHref, getProfileHref } from '../lib/routes'
import type { ConversationEntryPoint } from '../lib/routes'
import { tokens } from '../styles/tokens'
import type { Post } from '../types'

function truncateSnippet(value: string, limit: number) {
  if (value.length <= limit) {
    return value
  }

  return `${value.slice(0, Math.max(limit - 1, 0)).trimEnd()}…`
}

export function ReplyContext({
  post,
  compact = true,
  entry,
}: {
  post: Pick<Post, 'id' | 'parent_id' | 'parent_post' | 'is_quote' | 'quoted_post_id'>
  compact?: boolean
  entry?: ConversationEntryPoint
}) {
  if (!post.parent_id || !post.parent_post?.author) {
    return null
  }

  const parent = post.parent_post
  const parentAuthor = parent.author
  const snippet = (parent.content || '').trim()
  const compactSnippet = snippet ? truncateSnippet(snippet.replace(/\s+/g, ' '), 84) : ''
  const conversationHref = getPostHref(post.id, {
    entry,
    focus: post.is_quote || post.quoted_post_id ? 'quote' : 'reply',
  })
  const parentHref = getPostHref(parent.id, { entry: 'reply' })

  if (compact) {
    return (
      <div
        style={{
          marginTop: '4px',
          marginBottom: '8px',
          color: tokens.colors.textSecondary,
          fontSize: tokens.font.sm,
          lineHeight: 1.5,
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          gap: '6px',
        }}
      >
        <span>Replying to</span>
        <Link
          href={getProfileHref(parentAuthor.username)}
          style={{
            color: tokens.colors.accent,
            textDecoration: 'none',
            fontWeight: Number(tokens.font.weightSemibold),
          }}
        >
          @{parentAuthor.username}
        </Link>
        {compactSnippet ? (
          <span style={{ color: tokens.colors.textSecondary }}>
            · “{compactSnippet}”
          </span>
        ) : (
          <span style={{ color: tokens.colors.textSecondary }}>· earlier in the conversation</span>
        )}
        <Link
          href={conversationHref}
          style={{
            color: tokens.colors.accent,
            textDecoration: 'none',
            fontWeight: Number(tokens.font.weightSemibold),
          }}
        >
          Follow this stretch
        </Link>
      </div>
    )
  }

  return (
    <div
      style={{
        marginTop: '0',
        marginBottom: '12px',
        color: tokens.colors.textSecondary,
        fontSize: tokens.font.base,
        lineHeight: 1.5,
      }}
    >
      <div style={{ fontSize: tokens.font.sm, marginBottom: '8px', letterSpacing: '0.01em' }}>
        Earlier in this conversation
      </div>
      <div style={{ marginBottom: '8px' }}>
        <span>Replying to </span>
        <Link
          href={getProfileHref(parentAuthor.username)}
          style={{
            color: tokens.colors.accent,
            textDecoration: 'none',
            fontWeight: Number(tokens.font.weightSemibold),
          }}
        >
          @{parentAuthor.username}
        </Link>
        {post.is_quote || post.quoted_post_id ? <span> while carrying a quote forward.</span> : null}
      </div>
      {snippet ? (
        <Link
          href={parentHref}
          style={{
            display: 'block',
            marginTop: '8px',
            padding: '12px 14px',
            borderRadius: '14px',
            border: `1px solid ${tokens.colors.border}`,
            backgroundColor: tokens.colors.surface,
            color: tokens.colors.textSecondary,
            textDecoration: 'none',
          }}
        >
          <div style={{ color: tokens.colors.textPrimary, fontWeight: Number(tokens.font.weightSemibold), marginBottom: '4px' }}>
            {parentAuthor.display_name || parentAuthor.username}
          </div>
          <div style={{ fontSize: tokens.font.sm, whiteSpace: 'pre-wrap' }}>{snippet}</div>
        </Link>
      ) : (
        <div
          style={{
            marginTop: '8px',
            padding: '12px 14px',
            borderRadius: '14px',
            border: `1px solid ${tokens.colors.border}`,
            backgroundColor: tokens.colors.surface,
            color: tokens.colors.textSecondary,
            fontSize: tokens.font.sm,
          }}
        >
          Earlier post in the conversation
        </div>
      )}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '14px', marginTop: '10px', fontSize: tokens.font.sm }}>
        <Link
          href={parentHref}
          style={{
            color: tokens.colors.accent,
            textDecoration: 'none',
            fontWeight: Number(tokens.font.weightSemibold),
          }}
        >
          Step back one post
        </Link>
        <Link
          href={conversationHref}
          style={{
            color: tokens.colors.textSecondary,
            textDecoration: 'none',
            fontWeight: Number(tokens.font.weightSemibold),
          }}
        >
          Follow this stretch
        </Link>
      </div>
    </div>
  )
}
