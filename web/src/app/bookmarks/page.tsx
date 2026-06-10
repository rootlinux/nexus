'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { Bookmark, FileText, Heart, MessageCircle, Repeat2 } from 'lucide-react'

import Layout from '../../components/Layout'
import { QuotedPostEmbed } from '../../components/QuotedPostEmbed'
import { ReplyContext } from '../../components/ReplyContext'
import { deletePostById, getBookmarks, likePost, repostPost, toggleBookmarkPost } from '../../lib/api'
import { useAuth } from '../../contexts/AuthContext'
import { getPostHref, getProfileHref } from '../../lib/routes'
import { tokens } from '../../styles/tokens'
import type { FeedResponse, Post } from '../../types'
import { PostOwnerMenu, formatRelativeTime, getDisplayPost, PostActionRow, PostAvatar, PostContextLine, PostHeader, PostMediaBlock, PostPreviewLink, getPostContext } from '../../components/PostSurface'

function updatePostCollection(collection: Post[], targetPostId: number, updater: (post: Post) => Post): Post[] {
  return collection.map((post) => {
    if (post.id === targetPostId) {
      return updater(post)
    }

    if (post.original_post?.id === targetPostId) {
      return {
        ...post,
        original_post: updater(post.original_post),
      }
    }

    return post
  })
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

export default function BookmarksPage() {
  const router = useRouter()
  const { token, isLoading: isAuthLoading, user } = useAuth()
  const [posts, setPosts] = useState<Post[]>([])
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState('')
  const [cursor, setCursor] = useState<number | null>(null)
  const [hasMore, setHasMore] = useState(false)

  const loadBookmarks = async (cursorId?: number | null) => {
    try {
      if (cursorId) {
        setLoadingMore(true)
      } else {
        setLoading(true)
      }
      setError('')
      const data: FeedResponse = await getBookmarks(cursorId ?? null, 20)
      setPosts((prev) => (cursorId ? [...prev, ...(data.posts || [])] : data.posts || []))
      setCursor(data.next_cursor)
      setHasMore(data.has_more)
    } catch (loadError) {
      setError(getErrorMessage(loadError, 'Failed to load bookmarks.'))
      if (!cursorId) {
        setPosts([])
      }
    } finally {
      setLoading(false)
      setLoadingMore(false)
    }
  }

  useEffect(() => {
    if (isAuthLoading) {
      return
    }

    if (!token) {
      router.push('/auth')
      return
    }

    void loadBookmarks()
  }, [isAuthLoading, router, token])

  const handleLike = async (postId: number) => {
    try {
      const data = await likePost(postId)
      setPosts((prev) =>
        updatePostCollection(prev, postId, (post) => ({
          ...post,
          likes_count: data.likes_count,
          is_liked_by_me: data.liked,
        }))
      )
    } catch (actionError) {
      setError(getErrorMessage(actionError, 'Failed to update like.'))
    }
  }

  const handleRepost = async (postId: number) => {
    try {
      const data = await repostPost(postId)
      setPosts((prev) =>
        updatePostCollection(prev, postId, (post) => ({
          ...post,
          reposts_count: data.reposts_count,
          has_reposted: data.reposted,
        }))
      )
    } catch (actionError) {
      setError(getErrorMessage(actionError, 'Failed to update repost.'))
    }
  }

  const handleBookmark = async (postId: number) => {
    const previousPosts = posts
    setPosts((prev) =>
      updatePostCollection(prev, postId, (post) => ({
        ...post,
        is_bookmarked: !post.is_bookmarked,
        is_bookmarked_by_me: !post.is_bookmarked,
      }))
    )

    try {
      const data = await toggleBookmarkPost(postId)
      if (!data.is_bookmarked) {
        setPosts((prev) => prev.filter((post) => post.id !== postId && post.original_post?.id !== postId))
      } else {
        setPosts((prev) =>
          updatePostCollection(prev, postId, (post) => ({
            ...post,
            is_bookmarked: data.is_bookmarked,
            is_bookmarked_by_me: data.is_bookmarked,
          }))
        )
      }
    } catch (actionError) {
      setPosts(previousPosts)
      setError(getErrorMessage(actionError, 'Failed to update bookmark.'))
    }
  }

  const handleDeletePost = async (postId: number) => {
    try {
      setError('')
      await deletePostById(postId)
      setPosts((prev) => prev.filter((post) => post.id !== postId && post.original_post?.id !== postId))
      return true
    } catch (deleteError) {
      setError(getErrorMessage(deleteError, 'Could not delete this post right now.'))
      return false
    }
  }

  return (
    <Layout>
      <header
        className="app-sticky-header bookmarks-header"
        style={{
          position: 'sticky',
          top: 0,
          zIndex: 10,
          backgroundColor: tokens.colors.bg,
          borderBottom: `1px solid ${tokens.colors.borderSubtle}`,
          padding: '16px 24px',
        }}
      >
        <div style={{ color: tokens.colors.textPrimary, fontWeight: 500, fontSize: '18px' }}>Saved</div>
        <div style={{ color: tokens.colors.textSecondary, fontSize: '13px', marginTop: '2px' }}>Saved posts, private to you.</div>
      </header>

      {loading ? (
        <div style={{ padding: '40px 16px', color: tokens.colors.textSecondary }}>Loading bookmarks...</div>
      ) : error && posts.length === 0 ? (
        <div style={{ padding: '40px 16px', color: tokens.colors.danger }}>{error}</div>
      ) : posts.length === 0 ? (
        <div
          className="bookmarks-empty"
          style={{
            padding: '64px 24px',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '12px',
            textAlign: 'center',
          }}
        >
          <div
            style={{
              width: '52px',
              height: '52px',
              borderRadius: tokens.radius.full,
              border: `1px solid ${tokens.colors.border}`,
              backgroundColor: tokens.colors.surface,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Bookmark size={24} color={tokens.colors.textMuted} strokeWidth={1.7} />
          </div>
          <div style={{ color: tokens.colors.textPrimary, fontSize: '16px', fontWeight: 500 }}>Nothing saved yet.</div>
          <div style={{ color: tokens.colors.textSecondary, fontSize: '14px' }}>Posts you bookmark will appear here.</div>
        </div>
      ) : (
        <>
          {error ? (
            <div style={{ padding: '12px 16px', color: tokens.colors.danger, borderBottom: `1px solid ${tokens.colors.border}` }}>
              {error}
            </div>
          ) : null}

          {posts.map((post) => {
            const displayPost = getDisplayPost(post)
            const context = getPostContext(post)

            return (
              <article key={post.id} style={{ padding: '16px', borderBottom: `1px solid ${tokens.colors.border}` }}>
                {context ? <PostContextLine icon={context.icon} text={context.text} /> : null}

                <div style={{ display: 'flex', gap: '12px' }}>
                  <Link href={getProfileHref(displayPost.author.username)} style={{ textDecoration: 'none' }}>
                    <PostAvatar user={displayPost.author} />
                  </Link>

                  <div style={{ flex: 1, minWidth: 0 }}>
                    <PostHeader
                      author={displayPost.author}
                      timestamp={formatRelativeTime(post.created_at)}
                      timestampHref={getPostHref(displayPost.id, {
                        entry: 'bookmarks',
                        focus: displayPost.parent_id ? 'reply' : displayPost.is_quote ? 'quote' : 'conversation',
                      })}
                      rightSlot={
                        user?.id === post.author.id ? (
                          <PostOwnerMenu onDelete={() => handleDeletePost(post.id)} />
                        ) : null
                      }
                    />

                    {displayPost.content ? (
                      <PostPreviewLink post={displayPost} entry="bookmarks" style={{ marginTop: '6px' }}>
                        <ReplyContext post={displayPost} entry="bookmarks" />
                        <div style={{ color: tokens.colors.textPrimary, whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>
                          {displayPost.content}
                        </div>
                      </PostPreviewLink>
                    ) : null}

                    <PostMediaBlock postId={displayPost.id} mediaUrl={displayPost.media_url} />

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
                          count: displayPost.replies_count,
                          onClick: () =>
                            router.push(
                              getPostHref(displayPost.id, {
                                entry: 'bookmarks',
                                focus: displayPost.parent_id ? 'reply' : displayPost.is_quote ? 'quote' : 'conversation',
                              })
                            ),
                        },
                        { icon: Repeat2, label: 'Repost', count: displayPost.reposts_count, active: Boolean(displayPost.has_reposted), activeColor: tokens.colors.success, onClick: () => void handleRepost(displayPost.id) },
                        { icon: FileText, label: 'Quote', alwaysShowLabel: true, onClick: () => router.push(`/compose/quote/${displayPost.id}`) },
                        { icon: Heart, label: 'Like', count: displayPost.likes_count, active: displayPost.is_liked_by_me, activeColor: tokens.colors.danger, onClick: () => void handleLike(displayPost.id) },
                        { icon: Bookmark, label: 'Bookmark', active: displayPost.is_bookmarked, activeColor: tokens.colors.accent, alwaysShowLabel: true, onClick: () => void handleBookmark(displayPost.id) },
                      ]}
                    />
                  </div>
                </div>
              </article>
            )
          })}

          {hasMore ? (
            <div style={{ padding: '20px 16px' }}>
              <button
                onClick={() => void loadBookmarks(cursor)}
                disabled={loadingMore}
                style={{
                  width: '100%',
                  borderRadius: tokens.radius.full,
                  padding: '12px 16px',
                  fontWeight: Number(tokens.font.weightSemibold),
                }}
                className="btn-ghost"
              >
                {loadingMore ? 'Loading...' : 'Load more'}
              </button>
            </div>
          ) : null}
        </>
      )}
    </Layout>
  )
}
