'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useParams, useRouter, useSearchParams } from 'next/navigation'
import { Bookmark, FileText, Heart, MessageCircle, Repeat2 } from 'lucide-react'

import { MemberTrustLine, PostBody, PostCard, formatRelativeTime, getDisplayPost, PostActionRow, PostAvatar, PostContextLine, PostHeader, PostMediaBlock, PostOwnerMenu, getPostContext } from '../../../components/PostSurface'
import { QuotedPostEmbed } from '../../../components/QuotedPostEmbed'
import { ReplyContext } from '../../../components/ReplyContext'
import Layout from '../../../components/Layout'
import { useAuth } from '../../../contexts/AuthContext'
import { createReply, deletePostById, getPost, getPostReplies, likePost, repostPost, toggleBookmarkPost } from '../../../lib/api'
import { buildConversationGuide } from '../../../lib/conversation'
import { getPostHref, getProfileHref } from '../../../lib/routes'
import type { ConversationEntryPoint } from '../../../lib/routes'
import { tokens } from '../../../styles/tokens'
import type { Post } from '../../../types'

function updateDisplayPost(post: Post, updater: (displayPost: Post) => Post) {
  if (post.original_post) {
    return { ...post, original_post: updater(post.original_post) }
  }
  return updater(post)
}

function getErrorMessage(error: unknown, fallback: string) {
  if (
    typeof error === 'object' &&
    error !== null &&
    'response' in error &&
    typeof (error as { response?: unknown }).response === 'object' &&
    (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail &&
    typeof (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail === 'string'
  ) {
    return (error as { response?: { data?: { detail?: string } } }).response?.data?.detail || fallback
  }

  if (error instanceof Error && error.message) {
    return error.message
  }

  return fallback
}

function isNotFoundError(error: unknown) {
  return (
    typeof error === 'object' &&
    error !== null &&
    'response' in error &&
    typeof (error as { response?: { status?: unknown } }).response?.status === 'number' &&
    (error as { response?: { status?: number } }).response?.status === 404
  )
}

export default function PostDetailPage() {
  const params = useParams()
  const router = useRouter()
  const searchParams = useSearchParams()
  const { completeActivationAction, isLoading: authLoading, saveRecentConversation, token, user } = useAuth()
  const id = Number(params.id)
  const [post, setPost] = useState<Post | null>(null)
  const [replies, setReplies] = useState<Post[]>([])
  const [repliesTotal, setRepliesTotal] = useState(0)
  const [repliesHasMore, setRepliesHasMore] = useState(false)
  const [loading, setLoading] = useState(true)
  const [repliesLoading, setRepliesLoading] = useState(true)
  const [loadingMoreReplies, setLoadingMoreReplies] = useState(false)
  const [replyContent, setReplyContent] = useState('')
  const [replying, setReplying] = useState(false)
  const [showReplies, setShowReplies] = useState(true)
  const [error, setError] = useState('')
  const [actionError, setActionError] = useState('')
  const [replyError, setReplyError] = useState('')
  const [isDeletingCurrentPost, setIsDeletingCurrentPost] = useState(false)
  const [deletingReplyId, setDeletingReplyId] = useState<number | null>(null)

  const loadReplies = async (page = 1, append = false) => {
    const data = await getPostReplies(id, page, 20, 'asc')
    const nextReplies = Array.isArray(data?.posts) ? data.posts : []

    setReplies((current) => (append ? [...current, ...nextReplies] : nextReplies))
    setRepliesTotal(typeof data?.total === 'number' ? data.total : nextReplies.length)
    setRepliesHasMore(Boolean(data?.has_more))
  }

  useEffect(() => {
    if (!id || Number.isNaN(id) || authLoading) return

    let cancelled = false
    const load = async () => {
      setLoading(true)
      setRepliesLoading(true)
      setError('')
      setActionError('')
      try {
        const postData = await getPost(id)
        if (!cancelled) {
          setPost(postData)
          completeActivationAction('opened_thread')
        }

        try {
          const repliesData = await getPostReplies(id, 1, 20, 'asc')
          if (!cancelled) {
            const nextReplies = Array.isArray(repliesData?.posts) ? repliesData.posts : []
            setReplies(nextReplies)
            setRepliesTotal(typeof repliesData?.total === 'number' ? repliesData.total : nextReplies.length)
            setRepliesHasMore(Boolean(repliesData?.has_more))
          }
        } catch (repliesError) {
          if (!cancelled) {
            setReplies([])
            setRepliesTotal(0)
            setRepliesHasMore(false)
            setActionError(getErrorMessage(repliesError, 'Could not load the rest of this conversation.'))
          }
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(isNotFoundError(loadError) ? 'This post could not be found.' : getErrorMessage(loadError, 'Could not load this conversation.'))
          setPost(null)
          setReplies([])
          setRepliesTotal(0)
          setRepliesHasMore(false)
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
          setRepliesLoading(false)
        }
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [authLoading, completeActivationAction, id, token])

  const displayPost = post ? getDisplayPost(post) : null
  const currentDisplayPostId = displayPost?.id ?? null
  const trimmedReplyContent = replyContent.trim()
  const whitespaceOnlyReply = replyContent.length > 0 && !trimmedReplyContent
  const entryPoint = searchParams.get('entry')
  const focus = searchParams.get('focus')
  const contextualEntry: ConversationEntryPoint | undefined =
    entryPoint === 'feed' ||
    entryPoint === 'profile' ||
    entryPoint === 'notifications' ||
    entryPoint === 'search' ||
    entryPoint === 'discovery' ||
    entryPoint === 'bookmarks' ||
    entryPoint === 'reply' ||
    entryPoint === 'quote'
      ? entryPoint
      : undefined

  useEffect(() => {
    if (!displayPost) {
      return
    }

    const recentConversationSource = focus === 'quote' || focus === 'reply'
      ? focus
      : contextualEntry || 'feed'

    saveRecentConversation({
      postId: displayPost.id,
      authorUsername: displayPost.author.username,
      authorDisplayName: displayPost.author.display_name,
      snippet: displayPost.content || 'Conversation without text',
      source: recentConversationSource,
    })
  }, [contextualEntry, displayPost, focus, saveRecentConversation])

  const conversationEntryCopy = useMemo(() => {
    switch (entryPoint) {
      case 'notifications':
        return {
          eyebrow: 'From notifications',
          text: 'You arrived from a fresh update. This view keeps the surrounding conversation close so you can pick it back up cleanly.',
        }
      case 'profile':
        return {
          eyebrow: 'From profile replies',
          text: 'You opened this from a profile. Stay here to read the surrounding exchange in order.',
        }
      case 'search':
        return {
          eyebrow: 'From search',
          text: 'You found this post mid-stream. This page gives you the nearby context so the conversation reads clearly.',
        }
      case 'discovery':
      case 'feed':
        return {
          eyebrow: 'From the feed',
          text: 'You stepped in from the feed. This is the cleaner place to read the full exchange and continue it.',
        }
      case 'bookmarks':
        return {
          eyebrow: 'From bookmarks',
          text: 'You saved this for later. The thread below keeps the conversation easy to re-enter.',
        }
      case 'reply':
        return {
          eyebrow: 'From a reply',
          text: 'This post sits inside a longer exchange. Step back one post if you want the line just before it.',
        }
      case 'quote':
        return {
          eyebrow: 'From a quote',
          text: 'This post carries both a reply and a quoted reference. The conversation stays grounded here without feeling busy.',
        }
      default:
        return null
    }
  }, [entryPoint])
  const conversationHeading = displayPost?.parent_post
    ? 'Conversation'
    : displayPost?.replies_count
      ? 'Discussion'
      : 'Post'
  const conversationGuide = useMemo(() => buildConversationGuide(replies), [replies])
  const highlightedReply = conversationGuide.highlightedReplyId
    ? replies.find((reply) => reply.id === conversationGuide.highlightedReplyId) || null
    : null
  const hasContinuationGuide = conversationGuide.continuingReplyCount > 0

  const refreshReplies = async () => {
    await loadReplies(1, false)
  }

  const handleLike = async () => {
    if (!post || !displayPost) return
    setActionError('')
    try {
      const data = await likePost(displayPost.id)
      setPost((current) =>
        current
          ? updateDisplayPost(current, (currentDisplayPost) => ({
              ...currentDisplayPost,
              likes_count: data.likes_count,
              is_liked_by_me: data.liked,
            }))
          : current
      )
    } catch (actionError) {
      setActionError(getErrorMessage(actionError, 'Failed to update like.'))
    }
  }

  const handleRepost = async () => {
    if (!post || !displayPost) return
    setActionError('')
    try {
      const data = await repostPost(displayPost.id)
      setPost((current) =>
        current
          ? updateDisplayPost(current, (currentDisplayPost) => ({
              ...currentDisplayPost,
              reposts_count: data.reposts_count,
              has_reposted: data.reposted,
            }))
          : current
      )
    } catch (actionError) {
      setActionError(getErrorMessage(actionError, 'Failed to update repost.'))
    }
  }

  const handleBookmark = async () => {
    if (!post || !displayPost) return
    setActionError('')
    const optimisticState = !displayPost.is_bookmarked
    setPost((current) =>
      current
        ? updateDisplayPost(current, (currentDisplayPost) => ({
            ...currentDisplayPost,
            is_bookmarked: optimisticState,
            is_bookmarked_by_me: optimisticState,
          }))
        : current
    )

    try {
      const data = await toggleBookmarkPost(displayPost.id)
      setPost((current) =>
        current
          ? updateDisplayPost(current, (currentDisplayPost) => ({
              ...currentDisplayPost,
              is_bookmarked: data.is_bookmarked,
              is_bookmarked_by_me: data.is_bookmarked,
            }))
          : current
      )
    } catch (bookmarkError) {
      setPost((current) =>
        current
          ? updateDisplayPost(current, (currentDisplayPost) => ({
              ...currentDisplayPost,
              is_bookmarked: !optimisticState,
              is_bookmarked_by_me: !optimisticState,
            }))
          : current
      )
      setActionError(getErrorMessage(bookmarkError, 'Failed to update bookmark.'))
    }
  }

  const handleReply = async () => {
    const content = trimmedReplyContent
    if (!post || !displayPost) return
    if (!content) {
      setReplyError('Reply cannot be empty.')
      return
    }

    setReplying(true)
    setActionError('')
    setReplyError('')
    try {
      const data = await createReply(displayPost.id, content)
      setReplyContent('')
      setShowReplies(true)
      setReplies((current) => [...current, data.reply])
      setRepliesTotal((current) => Math.max(current + 1, data.replies_count))
      setPost((current) =>
        current
          ? updateDisplayPost(current, (currentDisplayPost) => ({
              ...currentDisplayPost,
              replies_count: data.replies_count,
            }))
          : current
      )
      await refreshReplies()
    } catch (actionError) {
      setActionError(getErrorMessage(actionError, 'Failed to reply to post.'))
    } finally {
      setReplying(false)
    }
  }

  const handleLoadMoreReplies = async () => {
    if (!repliesHasMore || loadingMoreReplies) return

    setLoadingMoreReplies(true)
    setActionError('')
    try {
      const nextPage = Math.floor(replies.length / 20) + 1
      await loadReplies(nextPage, true)
    } catch (loadError) {
      setActionError(getErrorMessage(loadError, 'Failed to load more replies.'))
    } finally {
      setLoadingMoreReplies(false)
    }
  }

  const handleDeleteCurrentPost = async () => {
    if (!post || isDeletingCurrentPost) {
      return false
    }

    setIsDeletingCurrentPost(true)
    setActionError('')

    try {
      await deletePostById(post.id)
      router.replace(user?.username ? getProfileHref(user.username) : '/')
      return true
    } catch (deleteError) {
      setActionError(getErrorMessage(deleteError, 'Could not delete this post right now.'))
      return false
    } finally {
      setIsDeletingCurrentPost(false)
    }
  }

  const handleDeleteReply = async (replyId: number) => {
    if (deletingReplyId === replyId) {
      return false
    }

    setDeletingReplyId(replyId)
    setActionError('')

    try {
      await deletePostById(replyId)
      setReplies((current) => current.filter((reply) => reply.id !== replyId))
      setRepliesTotal((current) => Math.max(current - 1, 0))
      return true
    } catch (deleteError) {
      setActionError(getErrorMessage(deleteError, 'Could not delete this post right now.'))
      return false
    } finally {
      setDeletingReplyId(null)
    }
  }

  return (
    <Layout>
      <header
        className="app-sticky-header post-detail-header"
        style={{
          position: 'sticky',
          top: 0,
          zIndex: 10,
          backgroundColor: 'rgba(0,0,0,0.84)',
          backdropFilter: 'blur(12px)',
          borderBottom: `1px solid ${tokens.colors.borderSubtle}`,
          padding: '16px 24px',
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
        }}
      >
        <button
          onClick={() => router.back()}
          style={{ background: 'none', border: 'none', color: tokens.colors.textPrimary, cursor: 'pointer' }}
        >
          ←
        </button>
        <div style={{ color: tokens.colors.textPrimary, fontSize: '18px', fontWeight: 500 }}>Post</div>
      </header>

      {loading ? (
        <div className="post-detail-feedback" style={{ padding: '40px 16px', color: tokens.colors.textSecondary }}>Opening the conversation...</div>
      ) : !displayPost ? (
        <div className="post-detail-feedback" style={{ padding: '40px 16px', color: tokens.colors.danger }}>{error}</div>
      ) : (
        <>
          {conversationEntryCopy ? (
            <section
              className="post-detail-context"
              style={{
                padding: '16px 24px',
                borderBottom: `1px solid ${tokens.colors.borderSubtle}`,
                backgroundColor: tokens.colors.surface,
                display: 'grid',
                gap: '6px',
              }}
            >
              <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.xs, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
                {conversationEntryCopy.eyebrow}
              </div>
              <div style={{ color: tokens.colors.textPrimary, fontWeight: Number(tokens.font.weightSemibold) }}>
                {focus === 'reply' ? 'Reply context is in view' : focus === 'quote' ? 'Quote context is in view' : 'Conversation context is ready'}
              </div>
              <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm, lineHeight: 1.5 }}>
                {conversationEntryCopy.text}
              </div>
            </section>
          ) : null}

          <PostCard>
            {post ? (() => {
              const context = getPostContext(post)
              return context ? <PostContextLine icon={context.icon} text={context.text} /> : null
            })() : null}
            <div style={{ display: 'flex', gap: '12px' }}>
              <Link href={getProfileHref(displayPost.author.username)} style={{ textDecoration: 'none' }}>
                <PostAvatar user={displayPost.author} size={44} />
              </Link>
              <div style={{ flex: 1, minWidth: 0 }}>
                {displayPost.parent_post ? (
                  <div
                    style={{
                      marginBottom: '14px',
                      padding: '12px 14px',
                      borderRadius: '16px',
                      border: `1px solid ${tokens.colors.border}`,
                      backgroundColor: tokens.colors.surface,
                    }}
                  >
                    <div style={{ color: tokens.colors.textPrimary, fontWeight: Number(tokens.font.weightMedium), marginBottom: '8px' }}>
                      Earlier in the conversation
                    </div>
                    <ReplyContext post={displayPost} compact={false} entry={contextualEntry} />
                  </div>
                ) : null}
                <div style={{ display: 'grid', gap: '10px' }}>
                  <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm, letterSpacing: '0.04em', textTransform: 'uppercase' }}>
                    {conversationHeading}
                  </div>
                  <PostHeader
                    author={displayPost.author}
                    timestamp={formatRelativeTime(displayPost.created_at)}
                    detailLine={<MemberTrustLine user={displayPost.author} introducerLabel="Introduced by" />}
                    rightSlot={
                      user?.id === post?.author.id ? (
                        <PostOwnerMenu onDelete={handleDeleteCurrentPost} isDeleting={isDeletingCurrentPost} />
                      ) : null
                    }
                  />
                </div>
                {displayPost.content ? (
                  <PostBody style={{ marginTop: '12px', marginBottom: 0, color: '#e0e0e0', fontSize: '16px' }}>
                    {displayPost.content}
                  </PostBody>
                ) : null}
                <PostMediaBlock postId={displayPost.id} mediaUrl={displayPost.media_url} maxHeight={460} />
                {displayPost.quoted_post || displayPost.quoted_post_unavailable ? (
                  <QuotedPostEmbed
                    post={displayPost.quoted_post}
                    unavailable={displayPost.quoted_post_unavailable}
                    placeholder={displayPost.quoted_post_placeholder}
                  />
                ) : null}
                <div style={{ marginTop: '12px', color: '#404040', fontSize: '13px' }}>
                  {formatRelativeTime(displayPost.created_at)}
                </div>
                <div style={{ color: '#555', fontSize: '14px', borderTop: '1px solid #1c1c1c', borderBottom: '1px solid #1c1c1c', padding: '12px 0', marginTop: '12px' }}>
                  {displayPost.likes_count} likes · {displayPost.reposts_count} reposts
                </div>

                <PostActionRow
                  items={[
                    { icon: MessageCircle, label: 'Reply', count: displayPost.replies_count, alwaysShowLabel: showReplies, onClick: () => setShowReplies((current) => !current) },
                    { icon: Repeat2, label: 'Repost', count: displayPost.reposts_count, active: Boolean(displayPost.has_reposted), onClick: handleRepost },
                    { icon: FileText, label: 'Quote', alwaysShowLabel: true, onClick: () => router.push(`/compose/quote/${displayPost.id}`) },
                    { icon: Heart, label: 'Like', count: displayPost.likes_count, active: displayPost.is_liked_by_me, onClick: handleLike },
                    { icon: Bookmark, label: 'Bookmark', active: displayPost.is_bookmarked, alwaysShowLabel: true, onClick: handleBookmark },
                  ]}
                />
              </div>
            </div>
          </PostCard>

          <section className="post-detail-reply" style={{ padding: '20px 24px', borderBottom: `1px solid ${tokens.colors.borderSubtle}`, backgroundColor: tokens.colors.surface, display: 'grid', gap: '12px' }}>
            <div style={{ color: tokens.colors.textPrimary, fontWeight: Number(tokens.font.weightBold) }}>
              {entryPoint === 'notifications' || entryPoint === 'reply' || entryPoint === 'quote' ? 'Pick the conversation back up' : 'Continue the conversation'}
            </div>
            <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm, lineHeight: 1.5 }}>
              {entryPoint === 'notifications' || entryPoint === 'reply' || entryPoint === 'quote'
                ? 'Keep it close to the existing thread so the next person can step back in without extra work.'
                : 'Keep it close to the thread so the next person can follow it without extra work.'}
            </div>
            <textarea
              value={replyContent}
              onChange={(event) => {
                setReplyContent(event.target.value)
                if (replyError && event.target.value.trim()) {
                  setReplyError('')
                }
              }}
              placeholder="Post your reply..."
              style={{
                minHeight: '96px',
                resize: 'vertical',
                backgroundColor: tokens.colors.bg,
                border: `1px solid ${tokens.colors.border}`,
                borderRadius: tokens.radius.md,
                padding: '12px 14px',
                color: tokens.colors.textPrimary,
                fontSize: tokens.font.base,
                lineHeight: 1.6,
                outline: 'none',
              }}
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px' }}>
              <div style={{ color: replyError || actionError ? tokens.colors.danger : tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                {replyError || actionError || (whitespaceOnlyReply
                  ? 'Reply cannot be empty.'
                  : trimmedReplyContent
                    ? `${280 - trimmedReplyContent.length} characters left`
                    : 'Replies stay attached to this conversation for everyone who can view it.')}
              </div>
              <button
                type="button"
                className="btn-ghost"
                onClick={() => void handleReply()}
                disabled={replying || !replyContent.trim()}
                style={{
                  borderRadius: tokens.radius.full,
                  color: trimmedReplyContent ? tokens.colors.textPrimary : tokens.colors.textMuted,
                  padding: '10px 16px',
                  fontWeight: Number(tokens.font.weightSemibold),
                }}
              >
                {replying ? 'Posting...' : 'Reply'}
              </button>
            </div>
          </section>

          {showReplies ? (
            <section>
              {repliesLoading ? (
                <div style={{ padding: '20px 24px', color: tokens.colors.textSecondary }}>Loading the rest of the conversation...</div>
              ) : replies.length === 0 ? (
                <div style={{ padding: '24px', color: '#404040', backgroundColor: tokens.colors.surface, textAlign: 'center' }}>
                  No replies yet.
                </div>
              ) : (
                <>
                  <div style={{ padding: '12px 24px', color: tokens.colors.textMuted, fontSize: '11px', letterSpacing: '0.08em', textTransform: 'uppercase', borderBottom: `1px solid ${tokens.colors.borderSubtle}`, backgroundColor: tokens.colors.surface }}>
                    Replies
                  </div>
                  <div style={{ padding: '14px 24px', color: tokens.colors.textSecondary, fontSize: tokens.font.sm, borderBottom: `1px solid ${tokens.colors.borderSubtle}`, backgroundColor: tokens.colors.surface, display: 'grid', gap: '4px' }}>
                    <div style={{ color: tokens.colors.textPrimary, fontWeight: Number(tokens.font.weightSemibold) }}>Conversation flow</div>
                    <div>
                      Showing {replies.length} of {repliesTotal} {repliesTotal === 1 ? 'reply' : 'replies'} in posting order
                      {hasContinuationGuide ? ', with ongoing paths lightly marked.' : '.'}
                    </div>
                  </div>
                  {hasContinuationGuide ? (
                    <section
                      style={{
                        margin: '16px 24px',
                        padding: '14px 16px',
                        borderRadius: '18px',
                        border: `1px solid ${tokens.colors.border}`,
                        backgroundColor: tokens.colors.surface,
                        display: 'grid',
                        gap: '8px',
                      }}
                    >
                      <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.xs, letterSpacing: '0.05em', textTransform: 'uppercase' }}>
                        Conversation guide
                      </div>
                      {highlightedReply ? (
                        <>
                          <div style={{ color: tokens.colors.textPrimary, fontWeight: Number(tokens.font.weightSemibold) }}>
                            @{highlightedReply.author.username}&rsquo;s reply has the clearest continuation so far.
                          </div>
                          <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm, lineHeight: 1.5 }}>
                            {highlightedReply.replies_count} more {highlightedReply.replies_count === 1 ? 'reply continues' : 'replies continue'} from there. The full thread stays in order below.
                          </div>
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '14px', fontSize: tokens.font.sm }}>
                            <Link
                              href={getPostHref(highlightedReply.id, { entry: 'reply', focus: highlightedReply.is_quote ? 'quote' : 'reply' })}
                              style={{
                                color: tokens.colors.accent,
                                textDecoration: 'none',
                                fontWeight: Number(tokens.font.weightSemibold),
                              }}
                            >
                              Continue there
                            </Link>
                            <div style={{ color: tokens.colors.textSecondary }}>
                              {conversationGuide.continuingReplyCount === 1
                                ? 'One reply branch is still unfolding.'
                                : `${conversationGuide.continuingReplyCount} reply branches are still unfolding.`}
                            </div>
                          </div>
                        </>
                      ) : (
                        <>
                          <div style={{ color: tokens.colors.textPrimary, fontWeight: Number(tokens.font.weightSemibold) }}>
                            A few replies are still carrying this conversation forward.
                          </div>
                          <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm, lineHeight: 1.5 }}>
                            Look for the lightly marked replies below when you want the paths that are still being answered.
                          </div>
                        </>
                      )}
                    </section>
                  ) : null}
                  {replies.map((reply) => (
                    <PostCard key={reply.id} style={{ display: 'flex', gap: '12px' }}>
                      <Link href={getProfileHref(reply.author.username)} style={{ textDecoration: 'none' }}>
                        <PostAvatar user={reply.author} size={36} />
                      </Link>
                      <div style={{ minWidth: 0, flex: 1 }}>
                        <PostHeader
                          author={reply.author}
                          timestamp={formatRelativeTime(reply.created_at)}
                          detailLine={<MemberTrustLine user={reply.author} introducerLabel="Introduced by" memberSinceLabel="Since" />}
                          timestampHref={getPostHref(reply.id, { entry: 'reply', focus: reply.is_quote ? 'quote' : 'reply' })}
                          rightSlot={
                            user?.id === reply.author.id ? (
                              <PostOwnerMenu onDelete={() => handleDeleteReply(reply.id)} isDeleting={deletingReplyId === reply.id} />
                            ) : null
                          }
                        />
                        <ReplyContext post={reply} entry="reply" />
                        {conversationGuide.highlightedReplyIds.has(reply.id) || conversationGuide.continuingReplyIds.has(reply.id) || reply.author.id === displayPost.author.id ? (
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '8px' }}>
                            {conversationGuide.highlightedReplyIds.has(reply.id) ? (
                              <span
                                style={{
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  padding: '4px 10px',
                                  borderRadius: tokens.radius.full,
                                  backgroundColor: 'rgba(201, 169, 110, 0.14)',
                                  border: `1px solid rgba(201, 169, 110, 0.28)`,
                                  color: tokens.colors.accent,
                                  fontSize: tokens.font.xs,
                                  fontWeight: Number(tokens.font.weightSemibold),
                                }}
                              >
                                Worth following
                              </span>
                            ) : null}
                            {!conversationGuide.highlightedReplyIds.has(reply.id) && conversationGuide.continuingReplyIds.has(reply.id) ? (
                              <span
                                style={{
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  padding: '4px 10px',
                                  borderRadius: tokens.radius.full,
                                  backgroundColor: tokens.colors.surfaceElevated,
                                  border: `1px solid ${tokens.colors.border}`,
                                  color: tokens.colors.textSecondary,
                                  fontSize: tokens.font.xs,
                                  fontWeight: Number(tokens.font.weightSemibold),
                                }}
                              >
                                Still unfolding
                              </span>
                            ) : null}
                            {reply.author.id === displayPost.author.id ? (
                              <span
                                style={{
                                  display: 'inline-flex',
                                  alignItems: 'center',
                                  padding: '4px 10px',
                                  borderRadius: tokens.radius.full,
                                  backgroundColor: 'rgba(0, 186, 124, 0.12)',
                                  border: `1px solid rgba(0, 186, 124, 0.24)`,
                                  color: tokens.colors.success,
                                  fontSize: tokens.font.xs,
                                  fontWeight: Number(tokens.font.weightSemibold),
                                }}
                              >
                                From the conversation starter
                              </span>
                            ) : null}
                          </div>
                        ) : null}
                        {reply.content ? <PostBody style={{ marginTop: '8px', marginBottom: 0 }}>{reply.content}</PostBody> : null}
                        {reply.replies_count > 0 ? (
                          <div style={{ marginTop: '10px', color: tokens.colors.textSecondary, fontSize: tokens.font.sm, lineHeight: 1.5 }}>
                            {reply.replies_count} more {reply.replies_count === 1 ? 'reply continues' : 'replies continue'} from here.
                          </div>
                        ) : null}
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '14px', marginTop: '10px', fontSize: tokens.font.sm }}>
                          <Link
                            href={getPostHref(reply.id, { entry: 'reply', focus: reply.is_quote ? 'quote' : 'reply' })}
                            style={{ color: tokens.colors.accent, textDecoration: 'none', fontWeight: Number(tokens.font.weightSemibold) }}
                          >
                            {reply.replies_count > 0 ? 'Follow this path' : 'Open this reply'}
                          </Link>
                          {reply.parent_post && reply.parent_post.id !== currentDisplayPostId ? (
                            <Link
                              href={getPostHref(reply.parent_post.id, { entry: 'reply' })}
                              style={{ color: tokens.colors.textSecondary, textDecoration: 'none', fontWeight: Number(tokens.font.weightSemibold) }}
                            >
                              Step back earlier
                            </Link>
                          ) : null}
                        </div>
                      </div>
                    </PostCard>
                  ))}
                  {repliesHasMore ? (
                    <div style={{ padding: '16px 24px', backgroundColor: tokens.colors.surface }}>
                      <button
                        onClick={() => void handleLoadMoreReplies()}
                        disabled={loadingMoreReplies}
                        style={{
                          border: `1px solid ${tokens.colors.border}`,
                          backgroundColor: tokens.colors.surface,
                          color: tokens.colors.textPrimary,
                          borderRadius: tokens.radius.full,
                          padding: '10px 16px',
                          cursor: loadingMoreReplies ? 'default' : 'pointer',
                          fontWeight: Number(tokens.font.weightSemibold),
                        }}
                      >
                        {loadingMoreReplies ? 'Loading more...' : `Show ${Math.max(repliesTotal - replies.length, 0)} more replies`}
                      </button>
                    </div>
                  ) : null}
                </>
              )}
            </section>
          ) : null}
        </>
      )}
    </Layout>
  )
}
