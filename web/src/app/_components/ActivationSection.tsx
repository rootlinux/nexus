'use client'

import { tokens } from '../../styles/tokens'
import { ActivationRouteCard } from './ActivationRouteCard'

interface ActivationSectionProps {
  activationStage: string | null
  completedActions: Set<string>
  user: { username: string } | null
}

export function ActivationSection({ activationStage, completedActions, user }: ActivationSectionProps) {
  const isFirstSession = activationStage === 'first_session'
  
  return (
    <section style={{
      padding: '18px 16px 20px',
      borderBottom: `1px solid ${tokens.colors.border}`,
      backgroundColor: tokens.colors.bg,
    }}>
      <div style={{ marginBottom: '14px' }}>
        <div style={{
          color: tokens.colors.textSecondary,
          fontSize: tokens.font.xs,
          fontWeight: Number(tokens.font.weightSemibold),
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
          marginBottom: '6px',
        }}>
          {isFirstSession ? 'A calm starting point' : 'A quiet continuation'}
        </div>
        <div style={{
          color: tokens.colors.textPrimary,
          fontSize: tokens.font.xl,
          fontWeight: Number(tokens.font.weightBold),
          letterSpacing: '-0.02em',
          marginBottom: '8px',
        }}>
          {isFirstSession ? 'A few good places to begin' : 'Pick up the parts that make Nexus feel personal'}
        </div>
        <div style={{
          color: tokens.colors.textSecondary,
          fontSize: tokens.font.sm,
          lineHeight: 1.6,
          maxWidth: '560px',
        }}>
          {isFirstSession
            ? 'The fastest way to settle in is simple: read what is surfacing, find a few people who feel right, then add your own line once you know where you are.'
            : 'Your first footing is already there. One more strong read and one more thoughtful follow usually makes the network feel like yours.'}
        </div>
      </div>

      <div style={{
        display: 'grid',
        gap: '12px',
        gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
      }}>
        <ActivationRouteCard
          href="/explore"
          title={completedActions.has('opened_thread') ? 'Thread opened' : 'Begin with discovery'}
          body="Open one worthwhile thread from discovery and this step will clear."
          visited={completedActions.has('opened_thread')}
        />
        <ActivationRouteCard
          href="/search"
          title={completedActions.has('ran_search') ? 'Search completed' : 'Search a name or phrase'}
          body="Run one real search so the path back into the network feels familiar."
          visited={completedActions.has('ran_search')}
        />
        {user ? (
          <ActivationRouteCard
            href={`/u/${user.username}`}
            title={completedActions.has('tuned_profile') ? 'Profile set' : 'Refine your profile'}
            body="A short bio or clear display name completes this step."
            visited={completedActions.has('tuned_profile')}
          />
        ) : null}
      </div>
    </section>
  )
}
