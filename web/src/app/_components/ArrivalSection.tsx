'use client'

import { X, ShieldCheck } from 'lucide-react'
import { tokens } from '../../styles/tokens'
import type { AuthArrivalState } from '../../lib/arrival'

interface ArrivalSectionProps {
  activeArrival: AuthArrivalState
  feedIntroCopy: string
  onDismiss: () => void
}

export function ArrivalSection({ activeArrival, feedIntroCopy, onDismiss }: ArrivalSectionProps) {
  const getEyebrow = () => activeArrival.kind === 'signup' ? 'Access confirmed' : 'Welcome back'
  
  const getTitle = () => {
    const name = activeArrival.displayName || activeArrival.username
    return activeArrival.kind === 'signup'
      ? `${name}, you're in.`
      : `${name}, your access is active.`
  }
  
  const getBody = () => {
    if (activeArrival.kind === 'signup') {
      return 'Your first session opens into the live network, not a tutorial. Take a moment, read the room, then add something when it feels worth saying.'
    }
    return "You're back in. The feed below picks up where the conversation is already moving."
  }
  
  const getMeta = () => {
    if (activeArrival.inviter?.username) {
      return `You joined through @${activeArrival.inviter.username}.`
    }
    return activeArrival.kind === 'signup'
      ? 'Your private access is live.'
      : 'Your session is ready.'
  }

  return (
    <section style={{
      padding: '20px 16px',
      borderBottom: `1px solid ${tokens.colors.border}`,
      backgroundColor: tokens.colors.bg,
    }}>
      <div style={{
        border: `1px solid ${tokens.colors.border}`,
        borderRadius: tokens.radius.lg,
        padding: '18px',
        backgroundColor: tokens.colors.surface,
        boxShadow: '0 18px 40px rgba(0,0,0,0.22)',
      }}>
        <div style={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: '16px',
        }}>
          <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
            <div style={{
              width: '40px',
              height: '40px',
              borderRadius: '999px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              backgroundColor: `${tokens.colors.accent}20`,
              color: tokens.colors.accent,
              flexShrink: 0,
            }}>
              <ShieldCheck size={18} strokeWidth={2} />
            </div>
            <div>
              <div style={{
                color: tokens.colors.textSecondary,
                fontSize: tokens.font.xs,
                fontWeight: Number(tokens.font.weightSemibold),
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
                marginBottom: '8px',
              }}>
                {getEyebrow()}
              </div>
              <h2 style={{
                margin: 0,
                color: tokens.colors.textPrimary,
                fontSize: tokens.font.xl,
                fontWeight: Number(tokens.font.weightBold),
                letterSpacing: '-0.02em',
              }}>
                {getTitle()}
              </h2>
              <p style={{
                margin: '10px 0 0',
                color: tokens.colors.textSecondary,
                fontSize: tokens.font.sm,
                lineHeight: 1.6,
                maxWidth: '560px',
              }}>
                {getBody()}
              </p>
            </div>
          </div>

          <button
            type="button"
            className="btn-ghost"
            onClick={onDismiss}
            aria-label="Dismiss welcome"
            style={{
              color: tokens.colors.textSecondary,
              width: '32px',
              height: '32px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
          >
            <X size={16} />
          </button>
        </div>

        <div style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: '10px',
          marginTop: '16px',
        }}>
          <div style={{
            padding: '8px 12px',
            borderRadius: tokens.radius.full,
            border: `1px solid ${tokens.colors.border}`,
            color: tokens.colors.textPrimary,
            fontSize: tokens.font.sm,
            backgroundColor: tokens.colors.surfaceElevated,
          }}>
            {getMeta()}
          </div>
          <div style={{
            padding: '8px 12px',
            borderRadius: tokens.radius.full,
            border: `1px solid ${tokens.colors.border}`,
            color: tokens.colors.textSecondary,
            fontSize: tokens.font.sm,
            backgroundColor: tokens.colors.surfaceElevated,
          }}>
            {feedIntroCopy}
          </div>
        </div>
      </div>
    </section>
  )
}
