'use client'

import { useCallback, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Check, Copy, MoreHorizontal, RefreshCw, Sparkles, Ticket } from 'lucide-react'

import Layout from '../../components/Layout'
import { useAuth } from '../../contexts/AuthContext'
import {
  generateCampaignInvite,
  getInviteCampaigns,
  getMyInvites,
  type InviteCampaign,
  type MyInvite,
} from '../../lib/api'
import { tokens } from '../../styles/tokens'

function formatDate(value?: string | null) {
  if (!value) {
    return 'No expiry'
  }

  return new Date(value).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

function getStatusLabel(status: string) {
  const normalized = status.toLowerCase()

  if (normalized === 'active') {
    return 'Available'
  }
  if (normalized === 'used') {
    return 'Redeemed'
  }
  if (normalized === 'expired') {
    return 'Expired'
  }

  return status.charAt(0).toUpperCase() + status.slice(1)
}

function LoadingCard() {
  return (
    <div
      style={{
        borderRadius: '10px',
        border: `1px solid ${tokens.colors.border}`,
        backgroundColor: tokens.colors.surface,
        padding: '16px 20px',
      }}
    >
      <div style={{ width: '72px', height: '10px', borderRadius: '4px', backgroundColor: tokens.colors.border, marginBottom: '14px' }} />
      <div style={{ width: '48%', height: '18px', borderRadius: '4px', backgroundColor: tokens.colors.surfaceElevated, marginBottom: '14px' }} />
      <div style={{ display: 'grid', gap: '8px' }}>
        <div style={{ width: '100%', height: '8px', borderRadius: '4px', backgroundColor: tokens.colors.border }} />
        <div style={{ width: '60%', height: '8px', borderRadius: '4px', backgroundColor: tokens.colors.border }} />
      </div>
    </div>
  )
}

export default function InvitesPage() {
  const router = useRouter()
  const { token, isLoading: isAuthLoading } = useAuth()
  const [invites, setInvites] = useState<MyInvite[]>([])
  const [campaigns, setCampaigns] = useState<InviteCampaign[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [copiedCode, setCopiedCode] = useState('')
  const [copyFeedback, setCopyFeedback] = useState('')
  const [openMenuCode, setOpenMenuCode] = useState('')
  const [submittingCampaignId, setSubmittingCampaignId] = useState<number | null>(null)

  const loadInvites = useCallback(async () => {
    setIsLoading(true)
    setError('')

    try {
      const [inviteData, campaignData] = await Promise.all([getMyInvites(), getInviteCampaigns()])
      setInvites(Array.isArray(inviteData?.invites) ? inviteData.invites : [])
      setCampaigns(Array.isArray(campaignData?.items) ? campaignData.items : [])
    } catch (inviteError) {
      setError(inviteError instanceof Error ? inviteError.message : 'Could not load your invites right now.')
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    if (isAuthLoading) {
      return
    }

    if (!token) {
      router.push('/auth')
      return
    }

    void loadInvites()
  }, [isAuthLoading, loadInvites, router, token])

  const handleCopy = async (code: string) => {
    try {
      await navigator.clipboard.writeText(code)
      setCopiedCode(code)
      setCopyFeedback(`Invite code ${code} copied.`)
      setOpenMenuCode('')
      window.setTimeout(() => {
        setCopiedCode((current) => (current === code ? '' : current))
      }, 1800)
      window.setTimeout(() => {
        setCopyFeedback((current) => (current === `Invite code ${code} copied.` ? '' : current))
      }, 2200)
    } catch {
      setCopyFeedback('')
      setError('Could not copy the invite code. Please try again.')
    }
  }

  const handleGenerate = async (campaignId: number) => {
    setSubmittingCampaignId(campaignId)
    setError('')

    try {
      const response = await generateCampaignInvite(campaignId)
      await handleCopy(response.code)
      await loadInvites()
    } catch (campaignError) {
      setError(campaignError instanceof Error ? campaignError.message : 'Could not generate an invite right now.')
    } finally {
      setSubmittingCampaignId(null)
    }
  }

  const availableInvites = invites.filter((invite) => invite.status.toLowerCase() === 'active').length
  const usedInvites = invites.filter((invite) => invite.status.toLowerCase() === 'used').length

  return (
    <Layout>
      <section className="invites-page" style={{ minHeight: '100vh', backgroundColor: tokens.colors.bg }}>
        <div
          className="invites-header"
          style={{
            padding: '16px 24px',
            borderBottom: `1px solid ${tokens.colors.borderSubtle}`,
          }}
        >
          <div style={{ color: tokens.colors.textPrimary, fontSize: '18px', fontWeight: 500 }}>Invites</div>
          <div style={{ color: tokens.colors.textSecondary, fontSize: '13px', marginTop: '2px' }}>
            Private access you can extend, all in one place.
          </div>
        </div>

        {/* Stats row */}
        {!isLoading && !error && (
          <div
            className="invite-stats-grid"
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(4, 1fr)',
              gap: '10px',
              padding: '16px 24px',
              borderBottom: `1px solid ${tokens.colors.borderSubtle}`,
            }}
          >
            {[
              { value: invites.length, label: 'Total' },
              { value: availableInvites, label: 'Available' },
              { value: usedInvites, label: 'Used' },
              { value: campaigns.filter((campaign) => campaign.is_active).length, label: 'Live campaigns' },
            ].map((stat) => (
              <div
                key={stat.label}
                style={{
                  backgroundColor: tokens.colors.surface,
                  border: `1px solid ${tokens.colors.border}`,
                  borderRadius: '10px',
                  padding: '16px 20px',
                }}
              >
                <div style={{ color: tokens.colors.textPrimary, fontSize: '24px', fontWeight: 500, lineHeight: 1 }}>
                  {stat.value}
                </div>
                <div style={{ color: tokens.colors.textSecondary, fontSize: '12px', marginTop: '4px' }}>
                  {stat.label}
                </div>
              </div>
            ))}
          </div>
        )}

        {copyFeedback && (
          <div
            className="invites-feedback"
            style={{
              margin: '0 24px 0',
              padding: '10px 14px',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '8px',
              border: `1px solid ${tokens.colors.border}`,
              borderRadius: '8px',
              backgroundColor: tokens.colors.surface,
              color: tokens.colors.textPrimary,
              fontSize: '13px',
            }}
          >
            <Check size={14} />
            {copyFeedback}
          </div>
        )}

        {!isLoading && campaigns.length > 0 ? (
          <div
            className="invite-campaigns"
            style={{
              padding: '16px 24px 0',
              display: 'grid',
              gap: '10px',
            }}
          >
            {campaigns.map((campaign) => {
              const disabled = !campaign.is_active || (campaign.user_remaining_allowance ?? 0) <= 0 || submittingCampaignId === campaign.id

              return (
                <article
                  key={campaign.id}
                  style={{
                    borderRadius: '10px',
                    border: `1px solid ${tokens.colors.border}`,
                    backgroundColor: tokens.colors.surface,
                    padding: '16px 20px',
                    display: 'grid',
                    gap: '10px',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'flex-start' }}>
                    <div>
                      <div style={{ color: tokens.colors.textPrimary, fontSize: '14px', fontWeight: 500 }}>
                        {campaign.public_label || campaign.name}
                      </div>
                      <div style={{ color: tokens.colors.textSecondary, fontSize: '13px', marginTop: '4px', lineHeight: 1.5 }}>
                        {campaign.description || 'Campaign invites follow the availability and timing rules set for this release.'}
                      </div>
                    </div>
                    <span
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '6px',
                        padding: '4px 10px',
                        borderRadius: '999px',
                        border: `1px solid ${tokens.colors.border}`,
                        color: campaign.is_active ? tokens.colors.textPrimary : tokens.colors.textMuted,
                        fontSize: '11px',
                        textTransform: 'uppercase',
                        letterSpacing: '0.06em',
                      }}
                    >
                      <Sparkles size={12} />
                      {campaign.is_active ? 'Live' : 'Locked'}
                    </span>
                  </div>

                  <div style={{ display: 'flex', gap: '18px', flexWrap: 'wrap' }}>
                    <div>
                      <div style={{ color: tokens.colors.textMuted, fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Your allowance</div>
                      <div style={{ color: tokens.colors.textPrimary, fontSize: '13px', marginTop: '2px' }}>
                        {campaign.user_generated_count ?? 0}/{campaign.per_user_invite_allowance}
                      </div>
                    </div>
                    <div>
                      <div style={{ color: tokens.colors.textMuted, fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Remaining</div>
                      <div style={{ color: tokens.colors.textPrimary, fontSize: '13px', marginTop: '2px' }}>
                        {campaign.user_remaining_allowance ?? 0}
                      </div>
                    </div>
                    <div>
                      <div style={{ color: tokens.colors.textMuted, fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Window</div>
                      <div style={{ color: tokens.colors.textPrimary, fontSize: '13px', marginTop: '2px' }}>
                        {campaign.expires_at ? `Until ${formatDate(campaign.expires_at)}` : 'No end date'}
                      </div>
                    </div>
                  </div>

                  <div>
                    <button
                      type="button"
                      className="btn-ghost"
                      disabled={disabled}
                      onClick={() => void handleGenerate(campaign.id)}
                      style={{
                        borderRadius: '20px',
                        padding: '8px 14px',
                        border: `1px solid ${tokens.colors.border}`,
                        color: disabled ? tokens.colors.textMuted : tokens.colors.textPrimary,
                        backgroundColor: 'transparent',
                        fontSize: '13px',
                      }}
                    >
                      {submittingCampaignId === campaign.id ? 'Creating…' : 'Create invite'}
                    </button>
                  </div>
                </article>
              )
            })}
          </div>
        ) : null}

        <div className="invites-list" style={{ padding: '16px 24px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {isLoading ? (
            <>
              <LoadingCard />
              <LoadingCard />
              <LoadingCard />
            </>
          ) : error ? (
            <div
              style={{
                borderRadius: '10px',
                border: `1px solid ${tokens.colors.border}`,
                backgroundColor: tokens.colors.surface,
                padding: '20px',
              }}
            >
              <div style={{ color: tokens.colors.textPrimary, fontSize: '14px', fontWeight: 500, marginBottom: '6px' }}>
                Invites are unavailable right now
              </div>
              <div style={{ color: tokens.colors.textSecondary, fontSize: '13px', lineHeight: 1.6, marginBottom: '14px' }}>{error}</div>
              <button
                type="button"
                className="btn-ghost"
                onClick={() => void loadInvites()}
                style={{
                  borderRadius: '20px',
                  padding: '8px 14px',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                  fontSize: '13px',
                }}
              >
                <RefreshCw size={14} />
                Try again
              </button>
            </div>
          ) : invites.length === 0 ? (
            <div
              style={{
                borderRadius: '10px',
                border: `1px solid ${tokens.colors.border}`,
                backgroundColor: tokens.colors.surface,
                padding: '24px 20px',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'flex-start',
                gap: '8px',
              }}
            >
              <Ticket size={18} color={tokens.colors.textMuted} />
              <div style={{ color: tokens.colors.textPrimary, fontSize: '14px', fontWeight: 500 }}>
                No invites yet
              </div>
              <div style={{ color: tokens.colors.textSecondary, fontSize: '13px', lineHeight: 1.6 }}>
                Invites are released selectively. When new access is assigned to your account, it will appear here automatically.
              </div>
            </div>
          ) : (
            invites.map((invite) => {
              const isCopied = copiedCode === invite.code
              const isMenuOpen = openMenuCode === invite.code

              return (
                <article
                  key={invite.code}
                  style={{
                    border: `1px solid ${tokens.colors.border}`,
                    borderRadius: '10px',
                    padding: '16px 20px',
                    backgroundColor: tokens.colors.surface,
                    position: 'relative',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px' }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      {/* Status badge */}
                      <div style={{ marginBottom: '10px' }}>
                        <span
                          style={{
                            display: 'inline-block',
                            padding: '3px 10px',
                            borderRadius: '20px',
                            border: `1px solid ${tokens.colors.border}`,
                            backgroundColor: 'transparent',
                            color: tokens.colors.textSecondary,
                            fontSize: '11px',
                            textTransform: 'uppercase' as const,
                            letterSpacing: '0.06em',
                          }}
                        >
                          {getStatusLabel(invite.status)}
                        </span>
                      </div>

                      {/* Code */}
                      <code
                        style={{
                          display: 'block',
                          color: tokens.colors.textPrimary,
                          fontSize: '14px',
                          fontFamily: 'monospace',
                          letterSpacing: '0.04em',
                          wordBreak: 'break-all',
                          marginBottom: '12px',
                        }}
                      >
                        {invite.code}
                      </code>

                      {invite.campaign_name ? (
                        <div style={{ color: tokens.colors.textSecondary, fontSize: '12px', marginBottom: '12px' }}>
                          Release: {invite.campaign_name}
                        </div>
                      ) : null}

                      {/* Meta */}
                      <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
                        {[
                          { label: 'Created', value: formatDate(invite.created_at) },
                          { label: 'Expires', value: formatDate(invite.expires_at) },
                          { label: 'Uses left', value: String(invite.remaining_uses) },
                        ].map((item) => (
                          <div key={`${invite.code}-${item.label}`}>
                            <div style={{ color: tokens.colors.textMuted, fontSize: '11px', textTransform: 'uppercase' as const, letterSpacing: '0.06em' }}>
                              {item.label}
                            </div>
                            <div style={{ color: tokens.colors.textPrimary, fontSize: '13px', marginTop: '2px' }}>{item.value}</div>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Three-dot menu */}
                    <div style={{ position: 'relative' }}>
                      <button
                        type="button"
                        className="btn-ghost"
                        onClick={() => setOpenMenuCode(isMenuOpen ? '' : invite.code)}
                        style={{
                          color: tokens.colors.textSecondary,
                          padding: '4px',
                          display: 'flex',
                          alignItems: 'center',
                        }}
                      >
                        <MoreHorizontal size={16} />
                      </button>

                      {isMenuOpen ? (
                        <div
                          style={{
                            position: 'absolute',
                            right: 0,
                            top: '28px',
                            backgroundColor: tokens.colors.surface,
                            border: `1px solid ${tokens.colors.border}`,
                            borderRadius: '8px',
                            overflow: 'hidden',
                            zIndex: 10,
                            minWidth: '140px',
                          }}
                        >
                          <button
                            type="button"
                            className="btn-ghost"
                            onClick={() => void handleCopy(invite.code)}
                            style={{
                              width: '100%',
                              padding: '10px 14px',
                              borderRadius: 0,
                              color: isCopied ? tokens.colors.textPrimary : tokens.colors.textSecondary,
                              fontSize: '13px',
                              display: 'flex',
                              alignItems: 'center',
                              gap: '8px',
                              textAlign: 'left',
                            }}
                          >
                            {isCopied ? <Check size={14} /> : <Copy size={14} />}
                            {isCopied ? 'Copied' : 'Copy code'}
                          </button>
                        </div>
                      ) : null}
                    </div>
                  </div>
                </article>
              )
            })
          )}
        </div>
      </section>
    </Layout>
  )
}
