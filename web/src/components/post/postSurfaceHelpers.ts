import type { LucideIcon } from 'lucide-react'
import { FileText, Repeat2 } from 'lucide-react'

import type { Post, User } from '../../types'

export function formatRelativeTime(value: string) {
  const timestamp = new Date(value).getTime()
  const diffMs = Date.now() - timestamp
  const diffMinutes = Math.max(Math.floor(diffMs / 60000), 0)

  if (diffMinutes < 1) return 'now'
  if (diffMinutes < 60) return `${diffMinutes}m`

  const diffHours = Math.floor(diffMinutes / 60)
  if (diffHours < 24) return `${diffHours}h`

  const diffDays = Math.floor(diffHours / 24)
  if (diffDays < 7) return `${diffDays}d`

  return new Date(value).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function getDisplayPost(post: Post): Post {
  return post.original_post || post
}

export function formatMemberSince(value: string) {
  return new Date(value).toLocaleDateString(undefined, { month: 'short', year: 'numeric' })
}

export function getMemberTrustFacts(
  user: Pick<User, 'created_at' | 'inviter'>,
  {
    includeIntroducer = true,
    includeMemberSince = true,
    introducerLabel = 'Introduced by',
    memberSinceLabel = 'Here since',
  }: {
    includeIntroducer?: boolean
    includeMemberSince?: boolean
    introducerLabel?: string
    memberSinceLabel?: string
  } = {}
) {
  const facts: string[] = []

  if (includeIntroducer && user.inviter?.username) {
    facts.push(`${introducerLabel} @${user.inviter.username}`)
  }

  if (includeMemberSince && user.created_at) {
    facts.push(`${memberSinceLabel} ${formatMemberSince(user.created_at)}`)
  }

  return facts
}

export function getPostContext(post: Post): { icon?: LucideIcon; text: string } | null {
  if (post.is_repost) {
    return { icon: Repeat2, text: `@${post.author.username} reposted` }
  }

  if (post.is_quote) {
    return { icon: FileText, text: `@${post.author.username} added a quote` }
  }

  return null
}
