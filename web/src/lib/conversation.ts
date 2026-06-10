import type { Post } from '../types'

export type ConversationGuide = {
  highlightedReplyId: number | null
  highlightedReplyIds: Set<number>
  continuingReplyIds: Set<number>
  highlightedReason: 'ongoing' | null
  continuingReplyCount: number
}

function compareReplies(a: Post, b: Post) {
  if (b.replies_count !== a.replies_count) {
    return b.replies_count - a.replies_count
  }

  const timeDelta = new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
  if (timeDelta !== 0) {
    return timeDelta
  }

  return a.id - b.id
}

export function buildConversationGuide(replies: Post[]): ConversationGuide {
  const continuingReplies = replies
    .filter((reply) => reply.replies_count > 0)
    .sort(compareReplies)

  const continuingReplyIds = new Set(continuingReplies.map((reply) => reply.id))

  if (!continuingReplies.length) {
    return {
      highlightedReplyId: null,
      highlightedReplyIds: new Set<number>(),
      continuingReplyIds,
      highlightedReason: null,
      continuingReplyCount: 0,
    }
  }

  const [topReply, secondReply] = continuingReplies
  const hasClearLead =
    topReply.replies_count >= 2 &&
    (!secondReply || topReply.replies_count > secondReply.replies_count)

  return {
    highlightedReplyId: hasClearLead ? topReply.id : null,
    highlightedReplyIds: hasClearLead ? new Set<number>([topReply.id]) : new Set<number>(),
    continuingReplyIds,
    highlightedReason: hasClearLead ? 'ongoing' : null,
    continuingReplyCount: continuingReplies.length,
  }
}
