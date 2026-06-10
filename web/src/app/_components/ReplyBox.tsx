'use client'

import { tokens } from '../../styles/tokens'

interface ReplyBoxProps {
  postId: number
  value: string
  submitting: boolean
  onChange: (value: string) => void
  onCancel: () => void
  onSubmit: () => void
}

export function ReplyBox({ postId, value, submitting, onChange, onCancel, onSubmit }: ReplyBoxProps) {
  return (
    <div style={{
      marginTop: '12px',
      padding: '12px',
      backgroundColor: tokens.colors.surfaceElevated,
      borderRadius: tokens.radius.md,
      border: `1px solid ${tokens.colors.border}`,
    }}>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Write your reply"
        style={{
          width: '100%',
          minHeight: '60px',
          resize: 'none',
          border: 'none',
          background: 'transparent',
          color: tokens.colors.textPrimary,
          fontSize: tokens.font.base,
          fontFamily: 'inherit',
          outline: 'none',
          lineHeight: 1.4,
        }}
        maxLength={280}
        autoFocus
      />
      <div style={{
        display: 'flex',
        justifyContent: 'flex-end',
        marginTop: '8px',
        gap: '8px',
      }}>
        <button
          type="button"
          className="btn-ghost"
          onClick={onCancel}
          style={{
            color: tokens.colors.textSecondary,
            padding: '6px 12px',
            fontSize: tokens.font.sm,
          }}
        >
          Cancel
        </button>
        <button
          type="button"
          className="btn-ghost"
          onClick={onSubmit}
          disabled={submitting || !value?.trim()}
          style={{
            color: value?.trim() ? tokens.colors.textPrimary : tokens.colors.textMuted,
            borderRadius: tokens.radius.md,
            padding: '6px 16px',
            fontSize: tokens.font.sm,
            fontWeight: Number(tokens.font.weightMedium),
          }}
        >
          {submitting ? 'Posting…' : 'Reply'}
        </button>
      </div>
    </div>
  )
}
