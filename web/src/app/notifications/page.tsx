'use client'

import { Suspense, useCallback, useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { AtSign, Heart, MessageCircle, Quote, Repeat2, Settings, UserPlus } from 'lucide-react'

import Layout from '../../components/Layout'
import {
  deletePushSubscription,
  getNotifications,
  getNotificationSettings,
  getPushSubscriptions,
  markAllNotificationsRead,
  markNotificationRead,
  testPushNotification,
  upsertPushSubscription,
  updateNotificationSettings,
} from '../../lib/api'
import { useAuth } from '../../contexts/AuthContext'
import { resolveMediaUrl } from '../../lib/media'
import {
  getNotificationReentryFocus,
  getNotificationReentrySource,
  getRecentConversation,
  isNotificationReentryCandidate,
  notificationPrimaryPost,
} from '../../lib/reentry'
import { getPostHref, getProfileHref } from '../../lib/routes'
import { tokens } from '../../styles/tokens'
import type { Notification, NotificationSettings, PushSubscriptionRecord, PushSubscriptionsResponse } from '../../types'

type NotificationTab = 'all' | 'mentions'
type BrowserNotificationState = NotificationPermission | 'unsupported'

const defaultSettings: NotificationSettings = {
  push_likes: true,
  push_replies: true,
  push_reposts: true,
  push_mentions: true,
  push_follows: true,
  email_likes: false,
  email_replies: false,
  email_reposts: false,
  email_mentions: false,
  email_follows: false,
}

function formatTime(dateStr: string) {
  return new Date(dateStr).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function notificationHref(notification: Notification) {
  const primaryPost = notificationPrimaryPost(notification)
  if (primaryPost?.id) {
    return getPostHref(primaryPost.id, {
      entry: 'notifications',
      focus: getNotificationReentryFocus(notification),
    })
  }
  return getProfileHref(notification.actor.username)
}

function getBrowserNotificationState(): BrowserNotificationState {
  if (!supportsPushApi()) {
    return 'unsupported'
  }

  return Notification.permission
}

function supportsPushApi() {
  if (typeof window === 'undefined') {
    return false
  }

  return (
    window.isSecureContext &&
    typeof Notification !== 'undefined' &&
    'serviceWorker' in navigator &&
    'PushManager' in window
  )
}

function urlBase64ToUint8Array(base64String: string) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const normalized = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const rawData = window.atob(normalized)
  const outputArray = new Uint8Array(rawData.length)

  for (let i = 0; i < rawData.length; i += 1) {
    outputArray[i] = rawData.charCodeAt(i)
  }

  return outputArray
}

async function ensurePushServiceWorker() {
  if (!('serviceWorker' in navigator)) {
    throw new Error('Service workers are not available in this browser.')
  }

  const registration = await navigator.serviceWorker.register('/sw.js', { scope: '/' })
  await navigator.serviceWorker.ready
  return registration
}

function notificationCopy(notification: Notification) {
  switch (notification.notification_type) {
    case 'like':
      return 'liked your post'
    case 'repost':
      return 'reposted your post'
    case 'quote':
      return 'quoted your post'
    case 'follow':
      return 'followed you'
    case 'reply':
      return 'replied to your post'
    case 'mention':
      return 'mentioned you'
  }
}

function notificationTone(notification: Notification) {
  const muted = tokens.colors.textMuted
  switch (notification.notification_type) {
    case 'like':
      return { icon: <Heart size={10} color={muted} />, label: 'Like' }
    case 'repost':
      return { icon: <Repeat2 size={10} color={muted} />, label: 'Repost' }
    case 'quote':
      return { icon: <Quote size={10} color={muted} />, label: 'Quote' }
    case 'follow':
      return { icon: <UserPlus size={10} color={muted} />, label: 'Follow' }
    case 'reply':
      return { icon: <MessageCircle size={10} color={muted} />, label: 'Reply' }
    case 'mention':
      return { icon: <AtSign size={10} color={muted} />, label: 'Mention' }
  }
}

function notificationCards(notification: Notification) {
  const cards: Array<{ key: string; label: string; context: NonNullable<Notification['post']> }> = []

  if (notification.notification_type === 'quote' && notification.source_post) {
    cards.push({ key: 'source', label: 'Quote', context: notification.source_post })
  }

  if (notification.notification_type === 'reply' && notification.source_post) {
    cards.push({ key: 'source', label: 'Reply', context: notification.source_post })
  }

  if (notification.notification_type === 'mention' && notification.source_post) {
    cards.push({ key: 'source', label: 'Mention', context: notification.source_post })
  }

  if (notification.post && notification.post.id !== notification.source_post?.id) {
    cards.push({
      key: 'target',
      label:
        notification.notification_type === 'like' || notification.notification_type === 'repost'
          ? 'Post'
          : 'Your post',
      context: notification.post,
    })
  } else if (!cards.length && notification.post) {
    cards.push({ key: 'target', label: 'Post', context: notification.post })
  }

  return cards
}

function ActorAvatar({
  username,
  avatarUrl,
}: {
  username: string
  avatarUrl?: string | null
}) {
  const resolvedAvatar = resolveMediaUrl(avatarUrl)
  const initial = username.charAt(0).toUpperCase()

  return (
    <div
      style={{
        width: '36px',
        height: '36px',
        borderRadius: '50%',
        overflow: 'hidden',
        backgroundColor: tokens.colors.surfaceElevated,
        border: `1px solid ${tokens.colors.border}`,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: tokens.colors.textPrimary,
        fontWeight: Number(tokens.font.weightMedium),
        fontSize: '14px',
        flexShrink: 0,
      }}
    >
      {resolvedAvatar ? (
        <img src={resolvedAvatar} alt={username} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
      ) : (
        initial
      )}
    </div>
  )
}

function NotificationsPageContent() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const tab = (searchParams.get('tab') as NotificationTab) || 'all'
  const { token, isLoading: isAuthLoading, returningSessionState, saveRecentConversation } = useAuth()

  const [items, setItems] = useState<Notification[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [settings, setSettings] = useState<NotificationSettings>(defaultSettings)
  const [savingField, setSavingField] = useState<string | null>(null)
  const [markingAllRead, setMarkingAllRead] = useState(false)
  const [browserNotificationState, setBrowserNotificationState] = useState<BrowserNotificationState>('unsupported')
  const [permissionRequesting, setPermissionRequesting] = useState(false)
  const [pushSubscriptions, setPushSubscriptions] = useState<PushSubscriptionRecord[]>([])
  const [pushConfigured, setPushConfigured] = useState(false)
  const [vapidPublicKey, setVapidPublicKey] = useState<string | null>(null)
  const [pushSyncing, setPushSyncing] = useState(false)
  const [pushSyncError, setPushSyncError] = useState('')
  const [currentDeviceEndpoint, setCurrentDeviceEndpoint] = useState<string | null>(null)
  const [testPushSending, setTestPushSending] = useState(false)
  const [testPushFeedback, setTestPushFeedback] = useState<{ kind: 'success' | 'error'; message: string } | null>(null)

  const groupedSettings = useMemo(
    () => [
      {
        title: 'Push Notifications',
        fields: [
          ['push_likes', 'Likes'],
          ['push_replies', 'Replies'],
          ['push_reposts', 'Reposts'],
          ['push_mentions', 'Mentions'],
          ['push_follows', 'New followers'],
        ] as Array<[keyof NotificationSettings, string]>,
      },
      {
        title: 'Email Notifications',
        fields: [
          ['email_likes', 'Likes'],
          ['email_replies', 'Replies'],
          ['email_reposts', 'Reposts'],
          ['email_mentions', 'Mentions'],
          ['email_follows', 'New followers'],
        ] as Array<[keyof NotificationSettings, string]>,
      },
    ],
    []
  )
  const actionableItems = useMemo(
    () => items.filter((notification) => isNotificationReentryCandidate(notification)),
    [items]
  )
  const featuredItem = actionableItems.find((notification) => notification.is_unread) || actionableItems[0] || null
  const unreadActionableCount = actionableItems.filter((notification) => notification.is_unread).length
  const recentConversation = getRecentConversation(returningSessionState)
  const browserNotificationsSupported = browserNotificationState !== 'unsupported'
  const browserNotificationsGranted = browserNotificationState === 'granted'
  const activePushSubscriptionCount = pushSubscriptions.filter((subscription) => subscription.is_active).length
  const currentDeviceSubscription =
    currentDeviceEndpoint == null
      ? null
      : pushSubscriptions.find(
          (subscription) => subscription.endpoint === currentDeviceEndpoint && subscription.is_active
        ) || null
  const currentDeviceSubscribed = Boolean(currentDeviceSubscription)

  const applyPushData = useCallback((pushData: PushSubscriptionsResponse) => {
    setPushSubscriptions(pushData.subscriptions || [])
    setPushConfigured(pushData.push_configured)
    setVapidPublicKey(pushData.vapid_public_key || null)
  }, [])

  const reloadPushData = useCallback(async () => {
    const pushData = await getPushSubscriptions()
    applyPushData(pushData)
    return pushData
  }, [applyPushData])

  const syncCurrentPushSubscription = useCallback(async (subscribeIfMissing: boolean) => {
    if (!supportsPushApi()) {
      setCurrentDeviceEndpoint(null)
      return
    }

    const registration = await ensurePushServiceWorker()
    let subscription = await registration.pushManager.getSubscription()
    if (!subscription && subscribeIfMissing) {
      if (!pushConfigured || !vapidPublicKey) {
        throw new Error('Push notifications are not configured for this environment.')
      }
      subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(vapidPublicKey),
      })
    }

    if (!subscription) {
      setCurrentDeviceEndpoint(null)
      return
    }

    const serialized = subscription.toJSON()
    const p256dh = serialized.keys?.p256dh
    const auth = serialized.keys?.auth

    if (!p256dh || !auth) {
      throw new Error('The browser did not return a complete push subscription.')
    }

    setCurrentDeviceEndpoint(subscription.endpoint)
    const serverSubscription = pushSubscriptions.find(
      (item) => item.endpoint === subscription.endpoint && item.is_active
    )
    if (!serverSubscription || serverSubscription.p256dh !== p256dh) {
      await upsertPushSubscription({
        endpoint: subscription.endpoint,
        keys: { p256dh, auth },
        user_agent: navigator.userAgent,
      })
      await reloadPushData()
    }
  }, [pushConfigured, pushSubscriptions, reloadPushData, vapidPublicKey])

  useEffect(() => {
    setBrowserNotificationState(getBrowserNotificationState())
  }, [])

  useEffect(() => {
    if (isAuthLoading) {
      return
    }

    if (!token) {
      router.push('/auth')
      return
    }

    let cancelled = false

    const load = async () => {
      setLoading(true)
      setError('')
      try {
        const [notificationData, settingsData, pushData] = await Promise.all([
          getNotifications(tab),
          getNotificationSettings(),
          getPushSubscriptions(),
        ])
        if (!cancelled) {
          setItems(notificationData.notifications || [])
          setSettings(settingsData || defaultSettings)
          applyPushData(pushData)
        }
      } catch {
        if (!cancelled) {
          setError('Could not load activity.')
          setItems([])
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [applyPushData, isAuthLoading, router, tab, token])

  useEffect(() => {
    if (!token || !browserNotificationsSupported || browserNotificationState !== 'granted') {
      return
    }

    let cancelled = false

    const sync = async () => {
      try {
        await syncCurrentPushSubscription(true)
        if (!cancelled) {
          setPushSyncError('')
        }
      } catch (error) {
        if (!cancelled) {
          setPushSyncError(error instanceof Error ? error.message : 'Could not activate push notifications on this browser.')
        }
      }
    }

    void sync()

    return () => {
      cancelled = true
    }
  }, [browserNotificationState, browserNotificationsSupported, pushConfigured, pushSubscriptions, syncCurrentPushSubscription, token, vapidPublicKey])

  const handleOpen = async (notification: Notification) => {
    const primaryPost = notificationPrimaryPost(notification)

    if (primaryPost?.id) {
      saveRecentConversation({
        postId: primaryPost.id,
        authorUsername: primaryPost.author_username || notification.actor.username,
        authorDisplayName: primaryPost.author_display_name || notification.actor.display_name,
        snippet: primaryPost.content_snippet || 'Conversation without text',
        source: getNotificationReentrySource(notification),
      })
    }

    if (notification.is_unread) {
      try {
        const updated = await markNotificationRead(notification.id)
        setItems((prev) =>
          prev.map((item) =>
            item.id === notification.id ? { ...item, is_unread: false, read_at: updated.read_at } : item
          )
        )
      } catch {
        // Route anyway.
      }
    }

    router.push(notificationHref(notification))
  }

  const handleToggleSetting = async (field: keyof NotificationSettings) => {
    const nextValue = !settings[field]
    setSavingField(field)
    try {
      const updated = await updateNotificationSettings({ [field]: nextValue })
      setSettings(updated)
    } finally {
      setSavingField(null)
    }
  }

  const handleMarkAllRead = async () => {
    setMarkingAllRead(true)
    try {
      const updated = await markAllNotificationsRead()
      setItems((prev) =>
        prev.map((item) => ({
          ...item,
          is_unread: false,
          read_at: item.read_at || updated.read_at,
        }))
      )
    } finally {
      setMarkingAllRead(false)
    }
  }

  const handleEnableBrowserNotifications = async () => {
    if (!browserNotificationsSupported || permissionRequesting) {
      return
    }

    setPermissionRequesting(true)
    setPushSyncError('')
    try {
      const permission = await Notification.requestPermission()
      setBrowserNotificationState(permission)
      if (permission === 'granted') {
        setPushSyncing(true)
        try {
          await syncCurrentPushSubscription(true)
          setPushSyncError('')
        } finally {
          setPushSyncing(false)
        }
      }
    } finally {
      setPermissionRequesting(false)
    }
  }

  const handleSubscribeCurrentBrowser = async () => {
    if (!browserNotificationsSupported || browserNotificationState !== 'granted' || pushSyncing) {
      return
    }

    setPushSyncing(true)
    setPushSyncError('')
    try {
      await syncCurrentPushSubscription(true)
    } catch (error) {
      setPushSyncError(error instanceof Error ? error.message : 'Could not activate push notifications on this browser.')
    } finally {
      setPushSyncing(false)
    }
  }

  const handleDisablePushNotifications = async () => {
    if (!supportsPushApi() || pushSyncing) {
      return
    }

    setPushSyncing(true)
    setPushSyncError('')
    try {
      const registration = await ensurePushServiceWorker()
      const subscription = await registration.pushManager.getSubscription()
      const endpoint = subscription?.endpoint || currentDeviceEndpoint
      if (subscription) {
        await subscription.unsubscribe()
      }
      if (endpoint) {
        await deletePushSubscription(endpoint)
      }
      setCurrentDeviceEndpoint(null)
      await reloadPushData()
    } catch (error) {
      setPushSyncError(error instanceof Error ? error.message : 'Could not remove the browser push subscription.')
    } finally {
      setPushSyncing(false)
    }
  }

  const handleSendTestNotification = async () => {
    if (!currentDeviceSubscribed || testPushSending) {
      return
    }

    setTestPushSending(true)
    setTestPushFeedback(null)
    try {
      const result = await testPushNotification({ title: 'Test push', body: 'Push delivery is working!', url: '/notifications' })
      if (result.failed_count > 0 && result.sent_count === 0) {
        setTestPushFeedback({ kind: 'error', message: `Test push failed. ${result.failed_count} subscription(s) could not be reached.` })
      } else {
        setTestPushFeedback({ kind: 'success', message: `Test sent to ${result.sent_count} of ${result.total_active} active subscription(s).` })
      }
    } catch (error) {
      setTestPushFeedback({ kind: 'error', message: error instanceof Error ? error.message : 'Failed to send test notification.' })
    } finally {
      setTestPushSending(false)
    }
  }

  const pageContent = (
    <>
      <header
        className="app-sticky-header notifications-header"
        style={{
          position: 'sticky',
          top: 0,
          zIndex: 30,
          backgroundColor: tokens.colors.bg,
          borderBottom: `1px solid ${tokens.colors.borderSubtle}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '16px 24px',
        }}
      >
        <div style={{ color: tokens.colors.textPrimary, fontWeight: 500, fontSize: '18px' }}>Activity</div>
        <button
          type="button"
          className="btn-ghost"
          onClick={() => setSettingsOpen((current) => !current)}
          style={{ color: tokens.colors.textSecondary }}
          aria-label="Notification settings"
        >
          <Settings size={20} />
        </button>
      </header>

      <div style={{ display: 'flex', borderBottom: `1px solid ${tokens.colors.border}` }}>
        {(['all', 'mentions'] as NotificationTab[]).map((candidate) => (
          <Link
            key={candidate}
            href={`/notifications?tab=${candidate}`}
            style={{
              flex: 1,
              textAlign: 'center',
              padding: '14px 8px',
              textDecoration: 'none',
              color: tab === candidate ? tokens.colors.textPrimary : tokens.colors.textSecondary,
              borderBottom: tab === candidate ? `2px solid ${tokens.colors.textPrimary}` : '2px solid transparent',
              fontWeight: tab === candidate ? Number(tokens.font.weightSemibold) : Number(tokens.font.weightMedium),
            }}
          >
            {candidate === 'all' ? 'All' : 'Mentions'}
          </Link>
        ))}
      </div>

      {(featuredItem || recentConversation) ? (
        <section
          style={{
            padding: '16px',
            borderBottom: `1px solid ${tokens.colors.border}`,
            backgroundColor: tokens.colors.surface,
            display: 'grid',
            gap: '12px',
          }}
        >
          <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.xs, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            Re-entry
          </div>
          <div style={{ color: tokens.colors.textPrimary, fontWeight: Number(tokens.font.weightBold), fontSize: tokens.font.lg }}>
            {featuredItem
              ? unreadActionableCount > 0
                ? `${unreadActionableCount} thread update${unreadActionableCount === 1 ? '' : 's'} worth reopening`
                : 'A clean place to reconnect'
              : 'Your last thread is still close'}
          </div>
          <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm, lineHeight: 1.55 }}>
            {featuredItem
              ? 'Start with the reply, quote, or mention that actually moved the conversation. You should not need to scan the whole list to find your way back in.'
              : 'Your recent conversation is still one step away if you want to resume where you left it.'}
          </div>
          <div style={{ display: 'grid', gap: '10px', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
            {featuredItem ? (
              <button
                onClick={() => void handleOpen(featuredItem)}
                style={{
                  textAlign: 'left',
                  border: `1px solid ${tokens.colors.border}`,
                  borderRadius: tokens.radius.lg,
                  backgroundColor: tokens.colors.surfaceElevated,
                  padding: '14px',
                  cursor: 'pointer',
                  display: 'grid',
                  gap: '8px',
                }}
              >
                <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.xs, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                  Worth reopening
                </div>
                <div style={{ color: tokens.colors.textPrimary, fontWeight: Number(tokens.font.weightSemibold), lineHeight: 1.4 }}>
                  {featuredItem.actor.display_name || featuredItem.actor.username} {notificationCopy(featuredItem)}
                </div>
                <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm, lineHeight: 1.5 }}>
                  {notificationPrimaryPost(featuredItem)?.content_snippet || 'Open the surrounding conversation.'}
                </div>
              </button>
            ) : null}

            {recentConversation ? (
              <Link
                href={getPostHref(recentConversation.postId, {
                  entry: recentConversation.source,
                  focus: recentConversation.source === 'reply' || recentConversation.source === 'quote' ? recentConversation.source : 'conversation',
                })}
                style={{
                  textDecoration: 'none',
                  border: `1px solid ${tokens.colors.border}`,
                  borderRadius: tokens.radius.lg,
                  backgroundColor: tokens.colors.surfaceElevated,
                  padding: '14px',
                  display: 'grid',
                  gap: '8px',
                }}
              >
                <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.xs, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                  Recent thread
                </div>
                <div style={{ color: tokens.colors.textPrimary, fontWeight: Number(tokens.font.weightSemibold), lineHeight: 1.4 }}>
                  {recentConversation.authorDisplayName || recentConversation.authorUsername}
                </div>
                <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm, lineHeight: 1.5 }}>
                  {recentConversation.snippet}
                </div>
              </Link>
            ) : null}
          </div>
        </section>
      ) : null}

      {settingsOpen && (
        <section
          style={{
            padding: '16px',
            borderBottom: `1px solid ${tokens.colors.border}`,
            backgroundColor: tokens.colors.surface,
            display: 'grid',
            gap: '18px',
          }}
        >
          {groupedSettings.map((group) => (
            <div key={group.title} style={{ display: 'grid', gap: '10px' }}>
              <div style={{ color: tokens.colors.textPrimary, fontWeight: Number(tokens.font.weightSemibold) }}>{group.title}</div>
              {group.title === 'Push Notifications' ? (
                <div
                  style={{
                    padding: '12px',
                    borderRadius: tokens.radius.md,
                    border: `1px solid ${tokens.colors.border}`,
                    backgroundColor: tokens.colors.surfaceElevated,
                    color: tokens.colors.textSecondary,
                    display: 'grid',
                    gap: '10px',
                    fontSize: tokens.font.sm,
                    lineHeight: 1.5,
                  }}
                >
                  <div>
                    {!browserNotificationsSupported
                      ? 'This browser cannot create Push API subscriptions for the web app. In-app notifications still work, and these settings continue to apply to any other active devices on your account.'
                      : !pushConfigured
                        ? 'Push notifications are not configured for this environment yet, so this browser cannot finish subscribing.'
                        : currentDeviceSubscribed
                          ? `This browser is subscribed for push. Your account currently has ${activePushSubscriptionCount} active subscription${activePushSubscriptionCount === 1 ? '' : 's'}.`
                          : browserNotificationsGranted
                            ? 'System notification permission is granted, but this browser is not subscribed yet. Finish subscribing this device to receive pushes here.'
                        : browserNotificationState === 'denied'
                          ? 'System notifications are blocked for this browser. Re-enable them in browser settings before this device can subscribe.'
                          : 'Enable browser notifications to let this browser register a real push subscription.'}
                  </div>
                  {pushSyncError ? (
                    <div style={{ color: tokens.colors.danger }}>{pushSyncError}</div>
                  ) : null}
                  <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                    {browserNotificationsSupported && !browserNotificationsGranted ? (
                      <button
                        type="button"
                        className="btn-ghost"
                        onClick={() => void handleEnableBrowserNotifications()}
                        disabled={permissionRequesting || browserNotificationState === 'denied' || !pushConfigured}
                        style={{
                          justifySelf: 'flex-start',
                          color:
                            permissionRequesting || browserNotificationState === 'denied' || !pushConfigured
                              ? tokens.colors.textMuted
                              : tokens.colors.textPrimary,
                        }}
                      >
                        {permissionRequesting
                          ? 'Enabling…'
                          : !pushConfigured
                            ? 'Push unavailable here'
                            : browserNotificationState === 'denied'
                              ? 'Blocked in browser'
                              : 'Enable notifications'}
                      </button>
                    ) : null}
                    {browserNotificationsGranted && !currentDeviceSubscribed && pushConfigured ? (
                      <button
                        type="button"
                        className="btn-ghost"
                        onClick={() => void handleSubscribeCurrentBrowser()}
                        disabled={pushSyncing}
                        style={{
                          justifySelf: 'flex-start',
                          color: pushSyncing ? tokens.colors.textMuted : tokens.colors.textPrimary,
                        }}
                      >
                        {pushSyncing ? 'Subscribing…' : 'Subscribe this browser'}
                      </button>
                    ) : null}
                    {browserNotificationsGranted && currentDeviceSubscribed ? (
                      <button
                        type="button"
                        className="btn-ghost"
                        onClick={() => void handleDisablePushNotifications()}
                        disabled={pushSyncing}
                        style={{
                          justifySelf: 'flex-start',
                          color: pushSyncing ? tokens.colors.textMuted : tokens.colors.textPrimary,
                        }}
                      >
                        {pushSyncing ? 'Removing…' : 'Remove this browser'}
                      </button>
                    ) : null}
                    {currentDeviceSubscribed ? (
                      <button
                        type="button"
                        className="btn-ghost"
                        onClick={() => void handleSendTestNotification()}
                        disabled={testPushSending}
                        style={{
                          justifySelf: 'flex-start',
                          color: testPushSending ? tokens.colors.textMuted : tokens.colors.textPrimary,
                        }}
                      >
                        {testPushSending ? 'Sending…' : 'Send test notification'}
                      </button>
                    ) : null}
                    {testPushFeedback ? (
                      <div
                        style={{
                          fontSize: tokens.font.sm,
                          color: testPushFeedback.kind === 'success' ? tokens.colors.textSecondary : tokens.colors.danger,
                          padding: '4px 0',
                        }}
                      >
                        {testPushFeedback.message}
                      </div>
                    ) : null}
                  </div>
                </div>
              ) : null}
              {group.fields.map(([field, label]) => (
                <button
                  key={field}
                  onClick={() => void handleToggleSetting(field)}
                  disabled={false}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '10px 0',
                    background: 'none',
                    border: 'none',
                    color: tokens.colors.textPrimary,
                    cursor: 'pointer',
                    borderBottom: `1px solid ${tokens.colors.border}`,
                    opacity: 1,
                  }}
                >
                  <span>{label}</span>
                  <span style={{ color: settings[field] ? tokens.colors.textPrimary : tokens.colors.textMuted }}>
                    {savingField === field ? 'Saving…' : settings[field] ? 'On' : 'Off'}
                  </span>
                </button>
              ))}
            </div>
          ))}
        </section>
      )}

      <div style={{ padding: '12px 16px', borderBottom: `1px solid ${tokens.colors.border}` }}>
        <button
          type="button"
          className="btn-ghost"
          onClick={() => void handleMarkAllRead()}
          disabled={markingAllRead}
          style={{
            color: markingAllRead ? tokens.colors.textMuted : tokens.colors.textSecondary,
            padding: 0,
            fontSize: tokens.font.sm,
          }}
        >
          {markingAllRead ? 'Marking…' : 'Mark all read'}
        </button>
      </div>

      {loading ? (
        <div style={{ padding: '32px 16px', color: tokens.colors.textSecondary }}>Loading recent activity…</div>
      ) : error ? (
        <div style={{ padding: '32px 16px', color: tokens.colors.danger }}>{error}</div>
      ) : items.length === 0 ? (
        <div style={{ padding: '40px 24px', color: tokens.colors.textMuted, fontSize: '14px', textAlign: 'center', lineHeight: 1.6 }}>
          Nothing new right now.
        </div>
      ) : (
        items.map((notification) => {
          const tone = notificationTone(notification)
          const cards = notificationCards(notification)
          const actorName = notification.actor.display_name || notification.actor.username

          return (
            <button
              key={notification.id}
              onClick={() => void handleOpen(notification)}
              style={{
                width: '100%',
                textAlign: 'left',
                border: 'none',
                borderBottom: `1px solid ${tokens.colors.borderSubtle}`,
                borderLeft: notification.is_unread ? `2px solid ${tokens.colors.textMuted}` : '2px solid transparent',
                backgroundColor: 'transparent',
                padding: '14px 24px',
                cursor: 'pointer',
                display: 'grid',
                gap: '10px',
              }}
            >
              <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
                <div style={{ position: 'relative', flexShrink: 0 }}>
                  <ActorAvatar username={notification.actor.username} avatarUrl={notification.actor.avatar_url} />
                  <div
                    style={{
                      position: 'absolute',
                      right: '-4px',
                      bottom: '-4px',
                      width: '18px',
                      height: '18px',
                      borderRadius: '50%',
                      border: `1px solid ${tokens.colors.border}`,
                      backgroundColor: tokens.colors.surfaceElevated,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}
                  >
                    {tone.icon}
                  </div>
                </div>
                <div style={{ flex: 1, minWidth: 0, display: 'grid', gap: '10px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
                    <div
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '5px',
                        color: tokens.colors.textMuted,
                        fontSize: tokens.font.xs,
                      }}
                    >
                      {tone.icon}
                      {tone.label}
                    </div>
                    <div style={{ color: tokens.colors.textMuted, fontSize: '11px' }}>
                      {formatTime(notification.created_at)}
                    </div>
                  </div>

                  <div style={{ lineHeight: 1.5, fontSize: '14px' }}>
                    <span style={{ color: tokens.colors.textPrimary, fontWeight: 500 }}>{actorName}</span>
                    <span style={{ color: tokens.colors.textSecondary }}> {notificationCopy(notification)}</span>
                  </div>

                  {cards.length > 0 ? (
                    <div style={{ display: 'grid', gap: '8px' }}>
                      {cards.map(({ key, label, context }) => (
                        <div
                          key={`${notification.id}-${key}`}
                          style={{
                            padding: '10px 12px',
                            borderRadius: '8px',
                            border: `1px solid ${tokens.colors.borderSubtle}`,
                            backgroundColor: tokens.colors.surfaceElevated,
                            display: 'grid',
                            gap: '4px',
                          }}
                        >
                          <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.xs, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                            {label}
                          </div>
                          {context.is_available ? (
                            <>
                              {context.author_username ? (
                                <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm }}>
                                  {context.author_display_name || context.author_username} @{context.author_username}
                                </div>
                              ) : null}
                              <div style={{ color: tokens.colors.textPrimary, whiteSpace: 'pre-wrap' }}>
                                {context.content_snippet || '[No text content]'}
                              </div>
                              {context.id ? (
                                <div style={{ color: tokens.colors.textMuted, fontSize: tokens.font.xs }}>
                                  Open conversation
                                </div>
                              ) : null}
                            </>
                          ) : (
                            <div style={{ color: tokens.colors.textSecondary }}>
                              {context.unavailable_reason || 'This post is no longer available.'}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
              </div>
            </button>
          )
        })
      )}
    </>
  )

  return <Layout>{pageContent}</Layout>
}

export default function NotificationsPage() {
  return (
    <Suspense fallback={<Layout><div style={{ padding: '32px 16px', color: tokens.colors.textSecondary }}>Gathering the latest conversation updates...</div></Layout>}>
      <NotificationsPageContent />
    </Suspense>
  )
}
