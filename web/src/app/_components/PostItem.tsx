'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { MessageCircle, Repeat2, Heart, FileText, Bookmark, Share } from 'lucide-react'
import { tokens } from '../../styles/tokens'
import { Avatar } from './Avatar'
import { ReplyBox } from './ReplyBox'
import { RepliesList } from './RepliesList'
import {
  getDisplayPost,
  formatRelativeTime,
  PostActionRow,
  PostBody,
  PostHeader,
  PostMediaBlock,
  PostOwnerMenu,
  PostPreviewLink,
  getPostContext,
  PostContextLine,
  MemberTrustLine,
} from '../../components/PostSurface'
import { QuotedPostEmbed } from '../../components/QuotedPostEmbed'
import { ReplyContext } from '../../components/ReplyContext'
import { getPostHref, getProfileHref } from '../../lib/routes'
import type { Post } from '../../types'
import { useAuth } from '../../contexts/AuthContext'
import { AdminPostMenu } from '../../components/post/AdminPostMenu'
import { ReportPostMenu } from '../../components/post/ReportPostMenu'

interface PostItemProps {
  post: Post
  user: { id: number; username: string } | null
  replyContent: Record<number, string>
  replyingTo: number | null
  submittingReply: number | null
  showReplies: Record<number, boolean>
  replies: Record<number, Post[]>
  loadingReplies: Record<number, boolean>
  onToggleReplyBox: (postId: number) => void
  onReplyContentChange: (postId: number, content: string) => void
  onSubmitReply: (postId: number) => void
  onToggleReplies: (postId: number) => void
  onDeletePost: (postId: number) => Promise<boolean>
  onDeleteAsAdmin?: (postId: number) => Promise<boolean>
  onLike: (postId: number) => void
  onBookmark: (postId: number) => void
  onRepost: (postId: number) => void
  onShare: (postId: number, content: string) => void
  onCancelReply: (postId: number) => void
}

export function PostItem({
  post,
  user,
  replyContent,
  replyingTo,
  submittingReply,
  showReplies,
  replies,
  loadingReplies,
  onToggleReplyBox,
  onReplyContentChange,
  onSubmitReply,
  onToggleReplies,
  onDeletePost,
  onDeleteAsAdmin,
  onLike,
  onBookmark,
  onRepost,
  onShare,
  onCancelReply,
}: PostItemProps) {
  const router = useRouter()
  const { user: authUser } = useAuth()
  const displayPost = getDisplayPost(post)
  const actorUsername = post.author?.username || 'unknown'
  const contentUsername = displayPost.author?.username || actorUsername
  const contentDisplayName = displayPost.author?.display_name || contentUsername

  return (
    <article
      style={{
        backgroundColor: tokens.colors.surface,
        borderBottom: `1px solid ${tokens.colors.borderSubtle}`,
        padding: '20px 24px',
        transition: tokens.transition.fast,
        cursor: 'pointer',
        position: 'relative',
      }}
      onMouseEnter={e => {
        e.currentTarget.style.backgroundColor = tokens.colors.surfaceElevated
      }}
      onMouseLeave={e => {
        e.currentTarget.style.backgroundColor = tokens.colors.surface
      }}
    >
      <div style={{ display: 'flex', gap: '12px', position: 'relative' }}>
        {/* Avatar */}
        <Link href={getProfileHref(contentUsername)} style={{ flexShrink: 0, textDecoration: 'none' }}>
          <Avatar username={contentUsername} avatarUrl={displayPost.author?.avatar_url} />
        </Link>

        {/* Content */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {post.feed_reason && (
            <div style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              marginBottom: '8px',
              padding: '4px 10px',
              borderRadius: tokens.radius.full,
              background: `${tokens.colors.surface}cc`,
              border: `1px solid ${tokens.colors.border}`,
              color: tokens.colors.textSecondary,
              fontSize: tokens.font.xs,
              fontWeight: Number(tokens.font.weightSemibold),
              letterSpacing: '0.02em',
            }}>
              <span style={{
                width: '6px',
                height: '6px',
                borderRadius: '999px',
                backgroundColor: tokens.colors.accent,
                opacity: 0.75,
              }} />
              {post.feed_reason}
            </div>
          )}
          {(() => {
            const context = getPostContext(post)
            return context ? <PostContextLine icon={context.icon} text={context.text} style={{ marginBottom: '6px' }} /> : null
          })()}
          
          <PostHeader
            author={{ username: contentUsername, display_name: contentDisplayName }}
            timestamp={formatRelativeTime(post.created_at)}
            detailLine={<MemberTrustLine user={displayPost.author} introducerLabel="Introduced by" />}
            timestampHref={getPostHref(displayPost.id, {
              entry: 'feed',
              focus: displayPost.parent_id ? 'reply' : displayPost.is_quote ? 'quote' : 'conversation',
            })}
            rightSlot={
              <>
                {user?.id === post.author?.id ? (
                  <PostOwnerMenu onDelete={() => onDeletePost(post.id)} />
                ) : authUser?.is_admin && onDeleteAsAdmin ? (
                  <AdminPostMenu postId={post.id} onDeleteAsAdmin={onDeleteAsAdmin} />
                ) : user ? (
                  <ReportPostMenu postId={post.id} />
                ) : null}
              </>
            }
          />

          <PostPreviewLink post={displayPost} entry="feed" style={{ marginTop: '2px' }}>
            <div style={{ fontSize: tokens.font.base }}>
              <PostBody style={{ marginTop: 0, marginBottom: 0 }}>
                <ReplyContext post={displayPost} entry="feed" />
                {displayPost.content}
              </PostBody>
            </div>
          </PostPreviewLink>

          <PostMediaBlock postId={displayPost.id} mediaUrl={displayPost.media_url} maxHeight={400} />

          {displayPost.quoted_post || displayPost.quoted_post_unavailable ? (
            <QuotedPostEmbed
              post={displayPost.quoted_post}
              unavailable={displayPost.quoted_post_unavailable}
              placeholder={displayPost.quoted_post_placeholder}
            />
          ) : null}

          <div style={{ marginTop: '12px', paddingTop: '12px', borderTop: `1px solid ${tokens.colors.borderSubtle}` }}>
            <PostActionRow
              items={[
                { icon: MessageCircle, label: 'Reply', count: displayPost.replies_count, onClick: (e) => { e.preventDefault(); e.stopPropagation(); onToggleReplyBox(displayPost.id) } },
                { icon: Repeat2, label: 'Repost', count: displayPost.reposts_count, active: Boolean(displayPost.has_reposted), activeColor: tokens.colors.success, onClick: (e) => { e.preventDefault(); e.stopPropagation(); onRepost(displayPost.id) } },
                { icon: FileText, label: 'Quote', alwaysShowLabel: true, onClick: (e) => { e.preventDefault(); e.stopPropagation(); router.push(`/compose/quote/${displayPost.id}`) } },
                { icon: Heart, label: 'Like', count: displayPost.likes_count, active: displayPost.is_liked_by_me, activeColor: tokens.colors.danger, onClick: (e) => { e.preventDefault(); e.stopPropagation(); onLike(displayPost.id) } },
                { icon: Bookmark, label: 'Bookmark', active: displayPost.is_bookmarked, activeColor: tokens.colors.accent, alwaysShowLabel: true, onClick: (e) => { e.preventDefault(); e.stopPropagation(); onBookmark(displayPost.id) } },
                { icon: Share, label: 'Share', alwaysShowLabel: true, onClick: (e) => { e.preventDefault(); e.stopPropagation(); onShare(displayPost.id, displayPost.content) } },
              ]}
            />
          </div>

          {/* Reply box */}
          {replyingTo === displayPost.id && (
            <ReplyBox
              postId={displayPost.id}
              value={replyContent[displayPost.id] || ''}
              submitting={submittingReply === displayPost.id}
              onChange={(value) => onReplyContentChange(displayPost.id, value)}
              onCancel={() => onCancelReply(displayPost.id)}
              onSubmit={() => onSubmitReply(displayPost.id)}
            />
          )}

          {/* Show replies toggle and replies list */}
          {displayPost.replies_count > 0 && (
            <RepliesList
              postId={displayPost.id}
              replies={replies[displayPost.id] || []}
              loading={loadingReplies[displayPost.id] || false}
              repliesCount={displayPost.replies_count}
              showReplies={showReplies[displayPost.id] || false}
              onToggle={() => onToggleReplies(displayPost.id)}
            />
          )}
        </div>
      </div>
    </article>
  )
}
