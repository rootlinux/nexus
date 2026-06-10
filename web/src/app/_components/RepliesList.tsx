'use client'

import { tokens } from '../../styles/tokens'
import { Avatar } from './Avatar'
import { PostHeader } from '../../components/PostSurface'
import { MemberTrustLine } from '../../components/PostSurface'
import { formatRelativeTime } from '../../components/PostSurface'

interface Reply {
  id: number
  author?: {
    username: string
    display_name?: string | null
    avatar_url?: string | null
  } | null
  content: string
  created_at: string
}

interface RepliesListProps {
  postId: number
  replies: Reply[]
  loading: boolean
  onToggle: () => void
  repliesCount: number
  showReplies: boolean
}

export function RepliesList({ replies, loading, repliesCount, showReplies, onToggle }: RepliesListProps) {
  return (
    <>
      {/* Show replies toggle */}
      {repliesCount > 0 && (
        <button
          type="button"
          onClick={(e) => {
            e.preventDefault()
            e.stopPropagation()
            onToggle()
          }}
          style={{
            background: 'none',
            border: 'none',
            color: tokens.colors.textSecondary,
            cursor: 'pointer',
            padding: '8px 0',
            fontSize: tokens.font.sm,
            marginTop: '4px',
          }}
        >
          {showReplies ? 'Hide replies' : `Show ${repliesCount} ${repliesCount === 1 ? 'reply' : 'replies'}`}
        </button>
      )}
      
      {/* Replies list */}
      {showReplies && replies && (
        <div style={{
          marginTop: '12px',
          borderLeft: `2px solid ${tokens.colors.border}`,
          paddingLeft: '16px',
        }}>
          {loading ? (
            <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
              Loading replies…
            </div>
          ) : (
            replies.map(reply => (
              <div key={reply.id} style={{
                padding: '8px 0',
                borderBottom: `1px solid ${tokens.colors.border}`,
              }}>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
                  <Avatar username={reply.author?.username || 'x'} size={28} />
                  <div style={{ flex: 1 }}>
                    <PostHeader
                      author={{ username: reply.author?.username || 'x', display_name: reply.author?.username || 'x' }}
                      timestamp={formatRelativeTime(reply.created_at)}
                    />
                    <div style={{
                      color: tokens.colors.textPrimary,
                      fontSize: tokens.font.sm,
                      marginTop: '2px',
                    }}>
                      {reply.content}
                    </div>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </>
  )
}
