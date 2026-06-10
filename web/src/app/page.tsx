'use client'

import { useEffect, useState, type FormEvent, type KeyboardEvent } from 'react'
import { useRouter } from 'next/navigation'
import Layout from '../components/Layout'
import { API_BASE_URL, authFetch, createPost, deletePostById, adminDeletePost, getNotifications, uploadPostImage } from '../lib/api'
import { useAuth } from '../contexts/AuthContext'
import { isMemberActivationActive, getActivationStage } from '../lib/activation'
import type { AuthArrivalState } from '../lib/arrival'
import {
  isReturningSessionEligible,
  isReturningSessionDismissed,
  getRecentConversation,
  getReturningSessionHoursAway,
  isNotificationReentryCandidate,
} from '../lib/reentry'
import { tokens } from '../styles/tokens'
import type { FeedResponse, Notification, Post } from '../types'
import { FileText } from 'lucide-react'

// Components
import { Avatar } from './_components/Avatar'
import { PostSkeleton, EmptyState, ErrorState } from './_components/FeedStates'
import { ActivationRouteCard } from './_components/ActivationRouteCard'
import { ArrivalSection } from './_components/ArrivalSection'
import { ActivationSection } from './_components/ActivationSection'
import { ReturningLayerSection } from './_components/ReturningLayerSection'
import { Composer } from './_components/Composer'
import { PostItem } from './_components/PostItem'

// Hooks
import { updatePostCollection, getResponseError, getComposerPlaceholder, getFeedIntroCopy, getHeaderTitle } from './_hooks/usePageHelpers'

export default function Home() {
  const router = useRouter()
  const {
    token,
    user,
    isLoading: isAuthLoading,
    arrivalState,
    memberActivationState,
    returningSessionState,
    clearArrivalState,
    dismissReturningSessionCue,
  } = useAuth()

  // Feed state
  const [posts, setPosts] = useState<Post[]>([])
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState('')
  const [cursor, setCursor] = useState<number | null>(null)
  const [hasMore, setHasMore] = useState(true)
  const [currentUser, setCurrentUser] = useState<{ username: string } | null>(null)

  // Composer state
  const [newPost, setNewPost] = useState('')
  const [posting, setPosting] = useState(false)
  const [selectedImage, setSelectedImage] = useState<File | null>(null)
  const [imagePreview, setImagePreview] = useState<string | null>(null)
  const [uploadingImage, setUploadingImage] = useState(false)
  const [imageError, setImageError] = useState('')
  const [showEmojiPicker, setShowEmojiPicker] = useState(false)

  // Reply state
  const [replyContent, setReplyContent] = useState<Record<number, string>>({})
  const [replyingTo, setReplyingTo] = useState<number | null>(null)
  const [submittingReply, setSubmittingReply] = useState<number | null>(null)

  // Show replies state
  const [showReplies, setShowReplies] = useState<Record<number, boolean>>({})
  const [replies, setReplies] = useState<Record<number, Post[]>>({})
  const [loadingReplies, setLoadingReplies] = useState<Record<number, boolean>>({})

  // Reentry signals
  const [recentNotifications, setRecentNotifications] = useState<Notification[]>([])
  const [loadingReentrySignals, setLoadingReentrySignals] = useState(false)

  // Activation / arrival state
  const [activeArrival, setActiveArrival] = useState<AuthArrivalState | null>(null)
  const activationActive = isMemberActivationActive(memberActivationState)
  const activationStage = getActivationStage(memberActivationState)
  const completedActions = new Set(memberActivationState?.completedActions || [])

  // Returning session derived state
  const returningEligible = isReturningSessionEligible(returningSessionState)
  const returningDismissed = isReturningSessionDismissed(returningSessionState)
  const recentConversation = getRecentConversation(returningSessionState)
  const hoursAway = getReturningSessionHoursAway(returningSessionState)
  const actionableNotifications = recentNotifications.filter((notification) => isNotificationReentryCandidate(notification))
  const featuredNotification = actionableNotifications.find((notification) => notification.is_unread) || actionableNotifications[0] || null
  const unreadReentryCount = actionableNotifications.filter((notification) => notification.is_unread).length
  const shouldShowReturningLayer = Boolean(
    user &&
    !activationActive &&
    returningEligible &&
    !returningDismissed &&
    (recentConversation || featuredNotification)
  )

  // Toast state
  const [toast, setToast] = useState<{ message: string; visible: boolean }>({ message: '', visible: false })

  // Sync arrival state
  useEffect(() => {
    if (!arrivalState || activeArrival) return
    if (arrivalState.kind === 'signup' || activationActive) {
      setActiveArrival(arrivalState)
    }
    clearArrivalState()
  }, [activationActive, activeArrival, arrivalState, clearArrivalState])

  // Auth guard and initial feed load
  useEffect(() => {
    if (isAuthLoading) return
    if (!token) {
      router.push('/auth')
      return
    }
    setCurrentUser(user ? { username: user.username } : null)
    void fetchFeed()
  }, [isAuthLoading, router, token, user])

  // Load reentry signals
  useEffect(() => {
    if (!token || activationActive || !returningEligible) {
      setRecentNotifications([])
      return
    }

    let cancelled = false

    const loadReentrySignals = async () => {
      setLoadingReentrySignals(true)
      try {
        const data = await getNotifications('all', undefined, 6)
        if (!cancelled) {
          setRecentNotifications(Array.isArray(data?.notifications) ? data.notifications : [])
        }
      } catch {
        if (!cancelled) setRecentNotifications([])
      } finally {
        if (!cancelled) setLoadingReentrySignals(false)
      }
    }

    void loadReentrySignals()
    return () => { cancelled = true }
  }, [activationActive, returningEligible, token])

  // Feed fetching
  async function fetchFeed(cursorId?: number) {
    try {
      if (!cursorId) setLoading(true)
      else setLoadingMore(true)

      const url = cursorId
        ? `${API_BASE_URL}/posts/feed?cursor=${cursorId}&limit=20`
        : `${API_BASE_URL}/posts/feed?limit=20`

      const res = await authFetch(url)
      if (!res.ok) {
        const errText = await res.text()
        setError(`Could not load the feed: ${res.status} - ${errText}`)
        return
      }
      const data: FeedResponse = await res.json()

      if (cursorId) {
        setPosts(prev => [...prev, ...(data.posts || [])])
      } else {
        setPosts(data.posts || [])
      }
      setCursor(data.next_cursor)
      setHasMore(data.has_more)
    } catch (error: unknown) {
      setError(`Connection error: ${error instanceof Error ? error.message : 'Could not load the feed.'}`)
    } finally {
      setLoading(false)
      setLoadingMore(false)
    }
  }

  function loadMore() {
    if (!loadingMore && hasMore && cursor) {
      fetchFeed(cursor)
    }
  }

  // Image handling
  function handleImageSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return

    const allowedTypes = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
    if (file.type === 'image/svg+xml' || file.type === 'image/svg') {
      setImageError('SVG files are not allowed for security reasons.')
      return
    }
    if (!allowedTypes.includes(file.type)) {
      setImageError('Invalid file type. Only JPEG, PNG, GIF, and WebP are allowed.')
      return
    }
    if (file.size > 5 * 1024 * 1024) {
      setImageError('File too large. Maximum size is 5MB.')
      return
    }

    setImageError('')
    setSelectedImage(file)
    if (imagePreview) URL.revokeObjectURL(imagePreview)
    setImagePreview(URL.createObjectURL(file))
  }

  function removeImage() {
    if (imagePreview) URL.revokeObjectURL(imagePreview)
    setSelectedImage(null)
    setImagePreview(null)
    setImageError('')
  }

  async function uploadImage(file: File): Promise<string | null> {
    const data = await uploadPostImage(file)
    return typeof data?.url === 'string' && data.url.trim() ? data.url : null
  }

  // Post submission
  async function submitPost() {
    if (posting || uploadingImage) return
    if (!newPost.trim() && !selectedImage) return

    setPosting(true)
    setImageError('')

    try {
      let mediaUrl = null

      if (selectedImage) {
        setUploadingImage(true)
        try {
          mediaUrl = await uploadImage(selectedImage)
          if (!mediaUrl) throw new Error('Upload completed without a media URL.')
        } catch (uploadError: unknown) {
          setImageError(uploadError instanceof Error ? uploadError.message : 'Failed to upload image')
          setPosting(false)
          setUploadingImage(false)
          return
        }
        setUploadingImage(false)
      }

      await createPost({ content: newPost, media_url: mediaUrl })

      setNewPost('')
      removeImage()
      setShowEmojiPicker(false)
      await fetchFeed()
    } catch (error: unknown) {
      setError(error instanceof Error ? error.message : 'Failed to publish post.')
    } finally {
      setPosting(false)
      setUploadingImage(false)
    }
  }

  function handleComposerSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void submitPost()
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return
    event.preventDefault()
    if (posting || uploadingImage || (!newPost.trim() && !selectedImage)) return
    event.currentTarget.form?.requestSubmit()
  }

  function closeEmojiPicker() {
    setShowEmojiPicker(false)
  }

  function toggleEmojiPicker() {
    setShowEmojiPicker((current) => !current)
  }

  // Post actions
  async function likePost(postId: number) {
    try {
      const res = await authFetch(`${API_BASE_URL}/posts/${postId}/like`, { method: 'POST' })
      if (res.ok) {
        const data = await res.json()
        setPosts(prev => updatePostCollection(prev, postId, (post) => ({
          ...post,
          likes_count: data.likes_count,
          is_liked_by_me: data.liked,
        })))
      } else {
        setError(await getResponseError(res, 'Failed to update like.'))
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to update like.')
    }
  }

  async function bookmarkPost(postId: number) {
    const previousPosts = posts
    const targetPost = posts.find((item) => item.id === postId || item.original_post?.id === postId)
    const currentBookmarkState = targetPost
      ? (targetPost.id === postId ? targetPost.is_bookmarked : targetPost.original_post?.is_bookmarked) || false
      : false
    const optimisticState = !currentBookmarkState

    setPosts((prev) => updatePostCollection(prev, postId, (post) => ({
      ...post,
      is_bookmarked: optimisticState,
      is_bookmarked_by_me: optimisticState,
    })))

    try {
      const res = await authFetch(`${API_BASE_URL}/posts/${postId}/bookmark`, { method: 'POST' })
      if (res.ok) {
        const data = await res.json()
        setPosts((prev) => updatePostCollection(prev, postId, (post) => ({
          ...post,
          is_bookmarked: data.is_bookmarked,
          is_bookmarked_by_me: data.is_bookmarked,
        })))
      } else {
        setPosts(previousPosts)
        setError(await getResponseError(res, 'Failed to update bookmark.'))
      }
    } catch (e) {
      setPosts(previousPosts)
      setError(e instanceof Error ? e.message : 'Failed to update bookmark.')
    }
  }

  async function deletePost(postId: number) {
    try {
      setError('')
      await deletePostById(postId)
      setPosts((prev) => prev.filter((post) => post.id !== postId && post.original_post?.id !== postId))
      setReplies((prev) => {
        const next = { ...prev }
        delete next[postId]
        return next
      })
      setShowReplies((prev) => {
        const next = { ...prev }
        delete next[postId]
        return next
      })
      if (replyingTo === postId) setReplyingTo(null)
      return true
    } catch (error: unknown) {
      setError(error instanceof Error ? error.message : 'Could not delete this post right now.')
      return false
    }
  }

  async function deletePostAsAdmin(postId: number) {
    try {
      setError('')
      await adminDeletePost(postId)
      setPosts((prev) => prev.filter((post) => post.id !== postId && post.original_post?.id !== postId))
      setReplies((prev) => {
        const next = { ...prev }
        delete next[postId]
        return next
      })
      setShowReplies((prev) => {
        const next = { ...prev }
        delete next[postId]
        return next
      })
      if (replyingTo === postId) setReplyingTo(null)
      setToast({ message: 'Post removed.', visible: true })
      setTimeout(() => setToast((t) => ({ ...t, visible: false })), 3000)
      return true
    } catch (error: unknown) {
      setError(error instanceof Error ? error.message : 'Could not remove this post.')
      return false
    }
  }

  async function repostPost(postId: number) {
    try {
      const res = await authFetch(`${API_BASE_URL}/posts/${postId}/repost`, { method: 'POST' })
      if (res.ok) {
        const data = await res.json()
        setPosts(prev => updatePostCollection(prev, postId, (post) => ({
          ...post,
          reposts_count: data.reposts_count,
          has_reposted: data.reposted,
        })))
        await fetchFeed()
      } else {
        setError(await getResponseError(res, 'Failed to update repost.'))
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to update repost.')
    }
  }

  async function sharePost(postId: number, content: string) {
    const url = `${window.location.origin}/post/${postId}`
    const title = content.slice(0, 50) + (content.length > 50 ? '...' : '')

    if (navigator.share) {
      try {
        await navigator.share({ title, url })
      } catch {
        // User cancelled or error
      }
    } else {
      try {
        await navigator.clipboard.writeText(url)
        showToast('Link copied!')
      } catch (e) {
        console.error('Failed to copy:', e)
      }
    }
  }

  // Toast helper
  function showToast(message: string) {
    setToast({ message, visible: true })
    setTimeout(() => setToast({ message: '', visible: false }), 2000)
  }

  // Reply handling
  function toggleReplyBox(postId: number) {
    setReplyingTo(prev => prev === postId ? null : postId)
    if (!replyingTo) {
      setReplyContent(prev => ({ ...prev, [postId]: '' }))
    }
  }

  function handleReplyContentChange(postId: number, content: string) {
    setReplyContent(prev => ({ ...prev, [postId]: content }))
  }

  async function submitReply(postId: number) {
    const content = replyContent[postId]?.trim()
    if (!content) return

    setSubmittingReply(postId)
    try {
      const res = await authFetch(`${API_BASE_URL}/posts/${postId}/replies`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      })
      if (res.ok) {
        const data = await res.json()
        setPosts((prev) => updatePostCollection(prev, postId, (post) => ({
          ...post,
          replies_count: data.replies_count,
        })))
        setReplyContent(prev => ({ ...prev, [postId]: '' }))
        setReplyingTo(null)
        if (showReplies[postId]) loadReplies(postId)
      } else {
        setError(await getResponseError(res, 'Failed to reply to post.'))
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to reply to post.')
    } finally {
      setSubmittingReply(null)
    }
  }

  function cancelReply(postId: number) {
    setReplyingTo(null)
    setReplyContent(prev => ({ ...prev, [postId]: '' }))
  }

  async function toggleReplies(postId: number) {
    const currentlyShowing = showReplies[postId]
    setShowReplies(prev => ({ ...prev, [postId]: !currentlyShowing }))
    if (!currentlyShowing && !replies[postId]?.length) {
      await loadReplies(postId)
    }
  }

  async function loadReplies(postId: number) {
    setLoadingReplies(prev => ({ ...prev, [postId]: true }))
    try {
      const res = await authFetch(`${API_BASE_URL}/posts/${postId}/replies`)
      if (res.ok) {
        const data = await res.json()
        setReplies(prev => ({ ...prev, [postId]: data.posts || [] }))
      }
    } catch (e) {
      console.error('Load replies error:', e)
    } finally {
      setLoadingReplies(prev => ({ ...prev, [postId]: false }))
    }
  }

  function dismissArrival() {
    setActiveArrival(null)
  }

  // Derived values for rendering
  const headerTitle = getHeaderTitle(activeArrival, shouldShowReturningLayer)
  const feedIntroCopy = getFeedIntroCopy(activeArrival, shouldShowReturningLayer, activationActive, activationStage)
  const composerPlaceholder = getComposerPlaceholder(activeArrival, shouldShowReturningLayer)

  const pageContent = (
    <>
      {/* Sticky Header */}
      <header className="app-sticky-header" style={{
        position: 'sticky',
        top: 0,
        backgroundColor: tokens.colors.bg,
        borderBottom: `1px solid ${tokens.colors.borderSubtle}`,
        padding: '16px 24px',
        zIndex: 10,
      }}>
        <div style={{
          color: tokens.colors.textPrimary,
          fontSize: '18px',
          fontWeight: Number(tokens.font.weightMedium),
          letterSpacing: '-0.01em',
          marginBottom: '2px',
        }}>
          {headerTitle}
        </div>
        <div style={{
          color: tokens.colors.textSecondary,
          fontSize: '13px',
          lineHeight: 1.4,
        }}>
          {feedIntroCopy}
        </div>
      </header>

      {/* Arrival Section */}
      {activeArrival && (
        <ArrivalSection
          activeArrival={activeArrival}
          feedIntroCopy={feedIntroCopy}
          onDismiss={dismissArrival}
        />
      )}

      {/* Activation Section */}
      {activationActive ? (
        <ActivationSection
          activationStage={activationStage}
          completedActions={completedActions}
          user={user ? { username: user.username } : null}
        />
      ) : null}

      {/* Returning Layer Section */}
      {shouldShowReturningLayer ? (
        <ReturningLayerSection
          recentConversation={recentConversation}
          featuredNotification={featuredNotification}
          unreadReentryCount={unreadReentryCount}
          hoursAway={hoursAway}
          loadingReentrySignals={loadingReentrySignals}
          onDismiss={dismissReturningSessionCue}
        />
      ) : null}

      {/* Error Banner */}
      {error && (
        <div style={{
          backgroundColor: `${tokens.colors.danger}15`,
          borderBottom: `1px solid ${tokens.colors.danger}`,
          color: tokens.colors.danger,
          padding: '12px 16px',
          fontSize: tokens.font.sm,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}>
          <span>{error}</span>
          <button
            onClick={() => setError('')}
            style={{
              background: 'none',
              border: 'none',
              color: tokens.colors.danger,
              cursor: 'pointer',
              fontSize: '18px',
              padding: '4px',
            }}
          >
            ×
          </button>
        </div>
      )}

      {/* Composer */}
      <Composer
        username={currentUser?.username || 'x'}
        newPost={newPost}
        posting={posting}
        uploadingImage={uploadingImage}
        selectedImage={selectedImage}
        imagePreview={imagePreview}
        imageError={imageError}
        showEmojiPicker={showEmojiPicker}
        placeholder={composerPlaceholder}
        onPostChange={setNewPost}
        onSubmit={handleComposerSubmit}
        onKeyDown={handleComposerKeyDown}
        onImageSelect={handleImageSelect}
        onRemoveImage={removeImage}
        onCloseEmojiPicker={closeEmojiPicker}
        onToggleEmojiPicker={toggleEmojiPicker}
      />

      {/* Post List */}
      {loading ? (
        <div>
          <PostSkeleton />
          <PostSkeleton />
          <PostSkeleton />
        </div>
      ) : error && posts.length === 0 ? (
        <ErrorState message={error} onRetry={() => fetchFeed(1)} />
      ) : posts.length === 0 ? (
        activationActive ? (
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '56px 20px 64px',
            textAlign: 'center',
          }}>
            <FileText size={48} strokeWidth={1.5} style={{ marginBottom: '16px', color: tokens.colors.textSecondary, opacity: 0.5 }} />
            <h3 style={{
              fontSize: tokens.font.xl,
              fontWeight: Number(tokens.font.weightSemibold),
              color: tokens.colors.textPrimary,
              marginBottom: '10px',
            }}>
              The feed has not filled in yet
            </h3>
            <p style={{
              color: tokens.colors.textSecondary,
              fontSize: tokens.font.base,
              maxWidth: '420px',
              lineHeight: 1.65,
              margin: 0,
            }}>
              That can happen early in a selective network. The room is not empty, just easier to enter through discovery, a few strong follows, and the threads already moving elsewhere.
            </p>
          </div>
        ) : shouldShowReturningLayer ? (
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '56px 20px 64px',
            textAlign: 'center',
          }}>
            <FileText size={48} strokeWidth={1.5} style={{ marginBottom: '16px', color: tokens.colors.textSecondary, opacity: 0.5 }} />
            <h3 style={{
              fontSize: tokens.font.xl,
              fontWeight: Number(tokens.font.weightSemibold),
              color: tokens.colors.textPrimary,
              marginBottom: '10px',
            }}>
              The feed is quiet, but your next step does not have to be
            </h3>
            <p style={{
              color: tokens.colors.textSecondary,
              fontSize: tokens.font.base,
              maxWidth: '460px',
              lineHeight: 1.65,
              margin: 0,
            }}>
              Nothing broad is breaking through right now. Re-enter through one thread you already touched or the activity that moved since you were last here.
            </p>
          </div>
        ) : (
          <EmptyState
            title={activeArrival?.kind === 'signup' ? 'Your network is taking shape' : 'The feed is quiet for now'}
            message={activeArrival?.kind === 'signup'
              ? 'You made it in before the room filled up. The network is still selective, so this opening view can be quiet while new posts settle in.'
              : 'Nothing is breaking through right now. Check back shortly for the next considered posts from your network.'}
            icon={FileText}
          />
        )
      ) : (
        <>
          {posts.map(post => (
            <PostItem
              key={post.id}
              post={post}
              user={user}
              replyContent={replyContent}
              replyingTo={replyingTo}
              submittingReply={submittingReply}
              showReplies={showReplies}
              replies={replies}
              loadingReplies={loadingReplies}
              onToggleReplyBox={toggleReplyBox}
              onReplyContentChange={handleReplyContentChange}
              onSubmitReply={submitReply}
              onToggleReplies={toggleReplies}
              onDeletePost={deletePost}
              onDeleteAsAdmin={deletePostAsAdmin}
              onLike={likePost}
              onBookmark={bookmarkPost}
              onRepost={repostPost}
              onShare={sharePost}
              onCancelReply={cancelReply}
            />
          ))}

          {hasMore && (
            <button
              onClick={loadMore}
              disabled={loadingMore}
              style={{
                width: '100%',
                padding: '16px',
                background: 'transparent',
                border: 'none',
                borderTop: `1px solid ${tokens.colors.borderSubtle}`,
                color: tokens.colors.textSecondary,
                fontSize: tokens.font.sm,
                cursor: loadingMore ? 'default' : 'pointer',
                transition: tokens.transition.fast,
              }}
            >
              {loadingMore ? 'Loading…' : 'Load more'}
            </button>
          )}
        </>
      )}
    </>
  )

  return (
    <Layout>
      {pageContent}
    </Layout>
  )
}
