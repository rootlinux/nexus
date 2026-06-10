'use client'

import Link from 'next/link'
import { ArrowUpRight, Compass } from 'lucide-react'

import type { ActivationAction, ActivationStage } from '../../lib/activation'
import { getPostHref, getProfileHref } from '../../lib/routes'
import { tokens } from '../../styles/tokens'
import type { RecentConversationState } from '../../lib/reentry'
import { RightRailCard } from './RightRailCard'
import { SearchSection } from './SearchSection'
import { SuggestionsSection } from './SuggestionsSection'

interface RightRailProps {
  activationActive: boolean
  activationStage: ActivationStage
  completedActions: ReadonlySet<ActivationAction>
  currentUsername: string
  returningEligible: boolean
  recentConversation: RecentConversationState | null
}

function ActivationChecklistCard({
  activationStage,
  completedActions,
  currentUsername,
}: Pick<RightRailProps, 'activationStage' | 'completedActions' | 'currentUsername'>) {
  return (
    <RightRailCard
      eyebrow={activationStage === 'first_session' ? 'First Pass' : 'Next Session'}
      title={activationStage === 'first_session' ? 'A good way to begin' : 'Pick up where you left off'}
    >
      <div style={{ display: 'flex', gap: '10px', alignItems: 'flex-start', marginBottom: '14px' }}>
        <div
          style={{
            width: '32px',
            height: '32px',
            borderRadius: '999px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: `${tokens.colors.accent}18`,
            color: tokens.colors.accent,
            flexShrink: 0,
          }}
        >
          <Compass size={15} strokeWidth={2} />
        </div>
        <p style={{ margin: 0, color: tokens.colors.textSecondary, fontSize: tokens.font.sm, lineHeight: 1.55 }}>
          {activationStage === 'first_session'
            ? 'Start with discovery, open a few threads, and let the room introduce itself before you add your own line.'
            : 'Your first read is already underway. A few more people, one strong thread, and the network tends to feel much more personal.'}
        </p>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {[
          {
            href: '/explore',
            title: completedActions.has('opened_thread') ? 'Thread opened' : 'Read what is surfacing',
            body: 'Open one strong conversation to let discovery count as complete.',
          },
          {
            href: '/search',
            title: completedActions.has('ran_search') ? 'Search completed' : 'Find a person or phrase',
            body: 'Run one real search so the shortcut becomes part of your flow.',
          },
          ...(currentUsername
            ? [
                {
                  href: getProfileHref(currentUsername),
                  title: completedActions.has('tuned_profile') ? 'Profile tuned' : 'Set your profile tone',
                  body: 'A display name or short bio is enough to complete this pass.',
                },
              ]
            : []),
        ].map((item) => (
          <Link
            key={item.href}
            href={item.href}
            style={{
              display: 'block',
              textDecoration: 'none',
              border: `1px solid ${tokens.colors.border}`,
              borderRadius: tokens.radius.md,
              padding: '10px 12px',
              backgroundColor: tokens.colors.surfaceElevated,
            }}
          >
            <div style={{ color: tokens.colors.textPrimary, fontSize: tokens.font.sm, fontWeight: Number(tokens.font.weightMedium), marginBottom: '4px' }}>
              {item.title}
            </div>
            <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.xs, lineHeight: 1.5 }}>{item.body}</div>
          </Link>
        ))}
      </div>
    </RightRailCard>
  )
}

function RecentConversationCard({ recentConversation }: { recentConversation: RecentConversationState }) {
  return (
    <RightRailCard eyebrow="Re-entry" title="Recent thread">
      <div style={{ display: 'grid', gap: '10px' }}>
        <p style={{ margin: 0, color: tokens.colors.textSecondary, fontSize: tokens.font.sm, lineHeight: 1.55 }}>
          The last conversation you opened is still the cleanest place to step back in if the feed feels broad.
        </p>
        <Link
          href={getPostHref(recentConversation.postId, {
            entry: recentConversation.source,
            focus: recentConversation.source === 'reply' || recentConversation.source === 'quote' ? recentConversation.source : 'conversation',
          })}
          style={{
            display: 'block',
            textDecoration: 'none',
            border: `1px solid ${tokens.colors.border}`,
            borderRadius: tokens.radius.md,
            padding: '10px 12px',
            backgroundColor: tokens.colors.surfaceElevated,
          }}
        >
          <div
            style={{
              color: tokens.colors.textPrimary,
              fontSize: tokens.font.sm,
              fontWeight: Number(tokens.font.weightMedium),
              marginBottom: '4px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: '8px',
            }}
          >
            <span>{recentConversation.authorDisplayName || recentConversation.authorUsername}</span>
            <ArrowUpRight size={13} color={tokens.colors.textMuted} />
          </div>
          <div style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.xs, lineHeight: 1.5 }}>{recentConversation.snippet}</div>
        </Link>
      </div>
    </RightRailCard>
  )
}

export function RightRail({
  activationActive,
  activationStage,
  completedActions,
  currentUsername,
  returningEligible,
  recentConversation,
}: RightRailProps) {
  return (
    <aside
      className="app-rail"
      style={{
        width: '320px',
        position: 'sticky',
        top: 0,
        height: '100vh',
        padding: '20px 16px',
        overflowY: 'auto',
        flexShrink: 0,
      }}
    >
      <SearchSection />

      {activationActive ? (
        <ActivationChecklistCard
          activationStage={activationStage}
          completedActions={completedActions}
          currentUsername={currentUsername}
        />
      ) : null}

      {!activationActive && returningEligible && recentConversation ? (
        <RecentConversationCard recentConversation={recentConversation} />
      ) : null}

      <RightRailCard eyebrow="Members" title="Suggested people">
        <SuggestionsSection activationActive={activationActive} />
      </RightRailCard>
    </aside>
  )
}
