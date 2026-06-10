'use client'

import { tokens } from '../../styles/tokens'
import { resolveMediaUrl } from '../../lib/media'

interface AvatarProps {
  username: string
  avatarUrl?: string | null
  size?: number
}

export function Avatar({ username, avatarUrl, size = 40 }: AvatarProps) {
  const initial = username?.charAt(0)?.toUpperCase() || '?'
  return (
    <div style={{
      width: `${size}px`,
      height: `${size}px`,
      borderRadius: '50%',
      backgroundColor: tokens.colors.surfaceElevated,
      border: `1px solid ${tokens.colors.border}`,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      color: tokens.colors.textPrimary,
      fontWeight: Number(tokens.font.weightMedium),
      fontSize: Math.round(size * 0.4),
      flexShrink: 0,
      overflow: 'hidden',
    }}>
      {avatarUrl ? (
        <img src={resolveMediaUrl(avatarUrl) || undefined} alt={username} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
      ) : (
        initial
      )}
    </div>
  )
}
