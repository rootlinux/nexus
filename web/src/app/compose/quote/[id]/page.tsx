'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'

import { QuotedPostEmbed } from '../../../../components/QuotedPostEmbed'
import Layout from '../../../../components/Layout'
import { createPost, getPost } from '../../../../lib/api'
import { getPostHref } from '../../../../lib/routes'
import { tokens } from '../../../../styles/tokens'
import type { Post } from '../../../../types'

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

export default function QuoteComposerPage() {
  const params = useParams()
  const router = useRouter()
  const postId = Number(params.id)

  const [targetPost, setTargetPost] = useState<Post | null>(null)
  const [content, setContent] = useState('')
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!postId) {
      setLoading(false)
      setError('Quoted post not found.')
      return
    }

    let cancelled = false

    const load = async () => {
      try {
        setLoading(true)
        setError('')
        const data = await getPost(postId)
        if (!cancelled) {
          setTargetPost(data)
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(getErrorMessage(loadError, 'Quoted post not found.'))
          setTargetPost(null)
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
  }, [postId])

  const handleSubmit = async () => {
    if (!targetPost || !content.trim()) {
      return
    }

    try {
      setSubmitting(true)
      setError('')
      const created = await createPost({
        content,
        quoted_post_id: targetPost.id,
      })
      router.push(getPostHref(created.id))
    } catch (submitError) {
      setError(getErrorMessage(submitError, 'Failed to publish quote.'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Layout>
      <header
        className="app-sticky-header"
        style={{
          position: 'sticky',
          top: 0,
          zIndex: 10,
          backgroundColor: 'rgba(10, 10, 10, 0.9)',
          backdropFilter: 'blur(12px)',
          borderBottom: `1px solid ${tokens.colors.borderSubtle}`,
          padding: '12px 16px',
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
        }}
      >
        <button
          type="button"
          onClick={() => router.back()}
          className="btn-ghost"
          style={{ padding: '8px 12px', color: tokens.colors.textPrimary }}
        >
          ←
        </button>
        <div style={{ color: tokens.colors.textPrimary, fontWeight: Number(tokens.font.weightBold) }}>Quote post</div>
      </header>

      {loading ? (
        <div style={{ padding: '32px 16px', color: tokens.colors.textSecondary }}>Loading quoted post...</div>
      ) : !targetPost ? (
        <div style={{ padding: '32px 16px', color: tokens.colors.danger }}>{error || 'Quoted post not found.'}</div>
      ) : (
        <section style={{ padding: '16px', display: 'grid', gap: '14px' }}>
          <div
            style={{
              border: `1px solid ${tokens.colors.border}`,
              borderRadius: '10px',
              backgroundColor: tokens.colors.surface,
              padding: '14px 16px',
              color: tokens.colors.textSecondary,
              fontSize: tokens.font.sm,
              lineHeight: 1.6,
            }}
          >
            Add your take while keeping the original post clearly separate.
          </div>

          <textarea
            value={content}
            onChange={(event) => setContent(event.target.value)}
            placeholder="Add your commentary"
            style={{
              minHeight: '140px',
              resize: 'vertical',
              backgroundColor: tokens.colors.surface,
              border: `1px solid ${tokens.colors.border}`,
              borderRadius: '16px',
              padding: '14px 16px',
              color: tokens.colors.textPrimary,
              fontSize: tokens.font.md,
              lineHeight: 1.5,
              outline: 'none',
            }}
            maxLength={280}
          />

          <div style={{ color: content.length > 260 ? tokens.colors.danger : tokens.colors.textSecondary, fontSize: tokens.font.sm, textAlign: 'right' }}>
            {content.length}/280
          </div>

          <QuotedPostEmbed post={targetPost} />

          {error ? <div style={{ color: tokens.colors.danger, fontSize: tokens.font.sm }}>{error}</div> : null}

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px' }}>
            <Link href={getPostHref(targetPost.id)} style={{ color: tokens.colors.textSecondary, fontSize: tokens.font.sm, textDecoration: 'none' }}>
              View original
            </Link>
            <button
              onClick={() => void handleSubmit()}
              disabled={submitting || !content.trim()}
              className="btn-ghost"
              style={{
                borderRadius: tokens.radius.full,
                backgroundColor: content.trim() ? tokens.colors.surfaceElevated : 'transparent',
                borderColor: content.trim() ? tokens.colors.accent : tokens.colors.border,
                color: content.trim() ? tokens.colors.textPrimary : tokens.colors.textMuted,
                padding: '10px 18px',
                fontWeight: Number(tokens.font.weightSemibold),
              }}
            >
              {submitting ? 'Posting...' : 'Post quote'}
            </button>
          </div>
        </section>
      )}
    </Layout>
  )
}
