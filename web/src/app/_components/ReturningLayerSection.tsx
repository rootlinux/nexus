'use client'

import Link from 'next/link'
import { Bell, ArrowUpRight, X } from 'lucide-react'
import { tokens } from '../../styles/tokens'
import type { Notification } from '../../types'
import {
  getNotificationReentryFocus,
  notificationPrimaryPost,
  type RecentConversationState,
} from '../../lib/reentry'
import { getPostHref, type ConversationEntryPoint } from '../../lib/routes'

interface ReturningLayerSectionProps {
  recentConversation: RecentConversationState | null
  featuredNotification: Notification | null
  unreadReentryCount: number
  hoursAway: number | null
  loadingReentrySignals: boolean
  onDismiss: () => void
}

export function ReturningLayerSection({
  recentConversation,
  featuredNotification,
  unreadReentryCount,
  hoursAway,
  loadingReentrySignals,
  onDismiss,
}: ReturningLayerSectionProps) {
  return (
    <section style={{
      padding: '18px 16px 20px',
      borderBottom: `1px solid ${tokens.colors.border}`,
      backgroundColor: tokens.colors.bg,
    }}>
      <div style={{
        border: `1px solid ${tokens.colors.border}`,
        borderRadius: '18px',
        padding: '18px',
        backgroundColor: tokens.colors.surface,
        boxShadow: '0 18px 40px rgba(0,0,0,0.18)',
        display: 'grid',
        gap: '16px',
      }}>
        <div style={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: '16px',
        }}>
          <div style={{ display: 'grid', gap: '8px', maxWidth: '560px' }}>
            <div style={{
              color: tokens.colors.textSecondary,
              fontSize: tokens.font.xs,
              fontWeight: Number(tokens.font.weightSemibold),
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
            }}>
              Pick back up
            </div>
            <h2 style={{
              margin: 0,
              color: tokens.colors.textPrimary,
              fontSize: tokens.font.xl,
              fontWeight: Number(tokens.font.weightBold),
              letterSpacing: '-0.02em',
            }}>
              {hoursAway && hoursAway >= 24
                ? 'Welcome back. A few quieter threads are still worth your time.'
                : 'Your circle is ready when you want to step back in.'}
            </h2>
            <p style={{
              margin: 0,
              color: tokens.colors.textSecondary,
              fontSize: tokens.font.sm,
              lineHeight: 1.65,
            }}>
              {featuredNotification
                ? `${unreadReentryCount > 0 ? `${unreadReentryCount} conversation update${unreadReentryCount === 1 ? '' : 's'} still matter${unreadReentryCount === 1 ? 's' : ''}` : 'A recent conversation is still open'}. Start with one strong thread instead of scanning everything again.`
                : recentConversation
                  ? 'You do not need to reorient from scratch. Your last worthwhile thread is still one clean step away.'
                  : 'The network stays selective, so your next move can stay simple: revisit one thread, glance at activity, then return to the feed if something deserves more attention.'}
            </p>
          </div>

          <button
            onClick={onDismiss}
            aria-label="Dismiss returning session guidance"
            style={{
              background: 'transparent',
              border: `1px solid ${tokens.colors.border}`,
              borderRadius: '999px',
              color: tokens.colors.textSecondary,
              width: '32px',
              height: '32px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer',
              flexShrink: 0,
            }}
          >
            <X size={16} />
          </button>
        </div>

        <div style={{
          display: 'grid',
          gap: '12px',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
        }}>
          {featuredNotification ? (
            <Link
              href={getPostHref(notificationPrimaryPost(featuredNotification)?.id || featuredNotification.id, {
                entry: 'notifications',
                focus: getNotificationReentryFocus(featuredNotification),
              })}
              style={{
                textDecoration: 'none',
                border: `1px solid ${tokens.colors.border}`,
                borderRadius: '16px',
                padding: '14px',
                backgroundColor: tokens.colors.surfaceElevated,
                display: 'grid',
                gap: '8px',
              }}
            >
              <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.xs, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                Reopen conversation
              </div>
              <div style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.base, fontWeight: Number(tokens.font.weightSemibold), lineHeight: 1.4 }}>
                {(featuredNotification.actor.display_name || featuredNotification.actor.username)} {featuredNotification.notification_type === 'mention' ? 'pulled you back into a thread' : 'moved the thread forward'}
              </div>
              <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm, lineHeight: 1.5 }}>
                {(notificationPrimaryPost(featuredNotification)?.content_snippet || 'Open the surrounding exchange and pick up from the latest turn.')}
              </div>
            </Link>
          ) : null}

          {recentConversation ? (
            <Link
              href={getPostHref(recentConversation.postId, {
                entry: recentConversation.source as 'reply' | 'quote',
                focus: recentConversation.source === 'reply' || recentConversation.source === 'quote' ? recentConversation.source as 'reply' | 'quote' : 'conversation',
              })}
              style={{
                textDecoration: 'none',
                border: `1px solid ${tokens.colors.border}`,
                borderRadius: '16px',
                padding: '14px',
                backgroundColor: tokens.colors.surfaceElevated,
                display: 'grid',
                gap: '8px',
              }}
            >
              <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.xs, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                Recent thread
              </div>
              <div style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.base, fontWeight: Number(tokens.font.weightSemibold), lineHeight: 1.4 }}>
                {(recentConversation.authorDisplayName || recentConversation.authorUsername)} is still a clean place to step back in
              </div>
              <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm, lineHeight: 1.5 }}>
                {recentConversation.snippet}
              </div>
            </Link>
          ) : null}
        </div>

        <div style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: '10px',
        }}>
          <Link
            href="/notifications"
            style={{
              textDecoration: 'none',
              padding: '10px 16px',
              borderRadius: tokens.radius.full,
              backgroundColor: tokens.colors.textPrimary,
              color: tokens.colors.bg,
              fontSize: tokens.font.sm,
              fontWeight: Number(tokens.font.weightSemibold),
              display: 'inline-flex',
              alignItems: 'center',
              gap: '8px',
            }}
          >
            <Bell size={14} />
            Review activity
          </Link>
          {recentConversation ? (
            <Link
              href={getPostHref(recentConversation.postId, {
                entry: recentConversation.source,
                focus: recentConversation.source === 'reply' || recentConversation.source === 'quote' ? recentConversation.source : 'conversation',
              })}
              style={{
                textDecoration: 'none',
                padding: '10px 16px',
                borderRadius: tokens.radius.full,
                border: `1px solid ${tokens.colors.border}`,
                color: tokens.colors.textPrimary,
                fontSize: tokens.font.sm,
                fontWeight: Number(tokens.font.weightSemibold),
                display: 'inline-flex',
                alignItems: 'center',
                gap: '8px',
              }}
            >
              Open recent thread
              <ArrowUpRight size={14} />
            </Link>
          ) : null}
          <div style={{
            padding: '10px 14px',
            borderRadius: tokens.radius.full,
            border: `1px solid ${tokens.colors.border}`,
            color: tokens.colors.textSecondary,
            fontSize: tokens.font.sm,
          }}>
            {loadingReentrySignals
              ? 'Refreshing your recent context…'
              : hoursAway
                ? `Last seen about ${hoursAway} hour${hoursAway === 1 ? '' : 's'} ago.`
                : 'A quieter route back in.'}
          </div>
        </div>
      </div>
    </section>
  )
}
