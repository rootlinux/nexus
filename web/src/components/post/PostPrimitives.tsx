import type { CSSProperties, ReactNode } from 'react'
import Link from 'next/link'
import type { LucideIcon } from 'lucide-react'
import { ShieldCheck } from 'lucide-react'

import { resolveMediaUrl } from '../../lib/media'
import { getPostHref, getProfileHref, type ConversationEntryPoint } from '../../lib/routes'
import { tokens } from '../../styles/tokens'
import type { Post, User } from '../../types'
import { getMemberTrustFacts } from './postSurfaceHelpers'

export function PostCard({
  children,
  style,
}: {
  children: ReactNode
  style?: CSSProperties
}) {
  return (
    <div
      style={{
        backgroundColor: tokens.colors.surface,
        borderBottom: `1px solid ${tokens.colors.borderSubtle}`,
        padding: '20px 24px',
        ...style,
      }}
    >
      {children}
    </div>
  )
}

export function PostBody({
  children,
  style,
}: {
  children: ReactNode
  style?: CSSProperties
}) {
  return (
    <div
      style={{
        color: tokens.colors.textPrimary,
        fontSize: tokens.font.base,
        lineHeight: 1.6,
        margin: '10px 0 16px 0',
        wordBreak: 'break-word',
        ...style,
      }}
    >
      {children}
    </div>
  )
}

export function MemberTrustLine({
  user,
  introducerLabel,
  memberSinceLabel,
  style,
}: {
  user: Pick<User, 'created_at' | 'inviter'>
  introducerLabel?: string
  memberSinceLabel?: string
  style?: CSSProperties
}) {
  const facts = getMemberTrustFacts(user, { introducerLabel, memberSinceLabel })

  if (facts.length === 0) {
    return null
  }

  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '6px',
        color: tokens.colors.textMuted,
        fontSize: tokens.font.xs,
        lineHeight: 1.45,
        ...style,
      }}
    >
      <ShieldCheck size={12} strokeWidth={2} />
      <span>{facts.join(' · ')}</span>
    </div>
  )
}

export function PostAvatar({
  user,
  size = 40,
}: {
  user: Pick<User, 'username'> & { avatar_url?: string | null }
  size?: number
}) {
  return (
    <div
      style={{
        width: size,
        height: size,
        borderRadius: '50%',
        overflow: 'hidden',
        backgroundColor: tokens.colors.surfaceElevated,
        border: `1px solid ${tokens.colors.border}`,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: tokens.colors.textPrimary,
        fontWeight: Number(tokens.font.weightMedium),
        fontSize: Math.round(size * 0.4),
        flexShrink: 0,
      }}
    >
      {user.avatar_url ? (
        <img
          src={resolveMediaUrl(user.avatar_url) || undefined}
          alt={user.username}
          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
        />
      ) : (
        user.username.charAt(0).toUpperCase()
      )}
    </div>
  )
}

export function PostContextLine({
  icon: Icon,
  text,
  style,
}: {
  icon?: LucideIcon
  text: string
  style?: CSSProperties
}) {
  return (
    <div
      style={{
        color: tokens.colors.textMuted,
        fontSize: '12px',
        marginBottom: '8px',
        display: 'flex',
        alignItems: 'center',
        gap: '6px',
        ...style,
      }}
    >
      {Icon ? (
        <Icon size={13} strokeWidth={1.75} />
      ) : (
        <span style={{ width: '4px', height: '4px', borderRadius: '50%', backgroundColor: tokens.colors.textMuted, flexShrink: 0 }} />
      )}
      <span>{text}</span>
    </div>
  )
}

export function PostHeader({
  author,
  timestamp,
  timestampHref,
  rightSlot,
  detailLine,
}: {
  author: Pick<User, 'username' | 'display_name'>
  timestamp: string
  timestampHref?: string
  rightSlot?: ReactNode
  detailLine?: ReactNode
}) {
  const timestampNode = timestampHref ? (
    <Link
      href={timestampHref}
      style={{ color: tokens.colors.textMuted, fontSize: '13px', textDecoration: 'none' }}
    >
      {timestamp}
    </Link>
  ) : (
    <span style={{ color: tokens.colors.textMuted, fontSize: '13px' }}>{timestamp}</span>
  )

  return (
    <div style={{ display: 'grid', gap: detailLine ? '4px' : 0 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'flex-start' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap', minWidth: 0 }}>
          <Link
            href={getProfileHref(author.username)}
            style={{
              color: tokens.colors.textPrimary,
              fontWeight: Number(tokens.font.weightMedium),
              fontSize: tokens.font.base,
              textDecoration: 'none',
            }}
          >
            {author.display_name || author.username}
          </Link>
          <span style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>@{author.username}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
          {timestampNode}
          {rightSlot ? <div style={{ flexShrink: 0 }}>{rightSlot}</div> : null}
        </div>
      </div>
      {detailLine ? <div>{detailLine}</div> : null}
    </div>
  )
}

export function PostMediaBlock({
  postId,
  mediaUrl,
  maxHeight = 420,
}: {
  postId: number
  mediaUrl?: string | null
  maxHeight?: number
}) {
  const resolvedMediaUrl = resolveMediaUrl(mediaUrl)
  if (!resolvedMediaUrl) {
    return null
  }

  return (
    <Link
      href={getPostHref(postId)}
      style={{
        display: 'block',
        marginTop: '12px',
        borderRadius: '10px',
        overflow: 'hidden',
        border: `1px solid ${tokens.colors.border}`,
      }}
    >
      <img
        src={resolvedMediaUrl}
        alt="Post media"
        style={{ width: '100%', maxHeight: `${maxHeight}px`, objectFit: 'cover', display: 'block' }}
      />
    </Link>
  )
}

export function PostPreviewLink({
  post,
  entry,
  children,
  style,
}: {
  post: Pick<Post, 'id' | 'parent_id' | 'is_quote'>
  entry?: ConversationEntryPoint
  children: ReactNode
  style?: CSSProperties
}) {
  return (
    <Link
      href={getPostHref(post.id, {
        entry,
        focus: post.parent_id ? 'reply' : post.is_quote ? 'quote' : 'conversation',
      })}
      style={{
        display: 'block',
        color: 'inherit',
        textDecoration: 'none',
        ...style,
      }}
    >
      {children}
    </Link>
  )
}

export function UnavailablePostBlock({ message }: { message: string }) {
  return (
    <div
      style={{
        marginTop: '12px',
        border: `1px solid ${tokens.colors.border}`,
        borderRadius: '10px',
        padding: '14px',
        backgroundColor: tokens.colors.surfaceElevated,
        color: tokens.colors.textSecondary,
        fontSize: tokens.font.sm,
        lineHeight: 1.5,
      }}
    >
      {message}
    </div>
  )
}
