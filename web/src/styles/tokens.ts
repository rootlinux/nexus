export const tokens = {
  colors: {
    bg:              '#0a0a0a',
    surface:         '#141414',
    surfaceElevated: '#1c1c1c',
    border:          '#242424',
    borderSubtle:    '#1c1c1c',
    textPrimary:     '#f0f0f0',
    textSecondary:   '#666666',
    textMuted:       '#404040',
    accent:          '#c9a96e',
    accentHover:     '#d4b87e',
    accentMuted:     'rgba(201, 169, 110, 0.24)',
    danger:          '#f4212e',
    dangerMuted:     'rgba(244, 33, 46, 0.32)',
    dangerSurface:   'rgba(244, 33, 46, 0.12)',
    success:         '#00ba7c',
    successMuted:    'rgba(0, 186, 124, 0.24)',
  },
  font: {
    xs: '13px',
    sm: '14px',
    base: '15px',
    md: '16px',
    lg: '20px',
    xl: '24px',
    weightNormal: '400',
    weightMedium: '500',
    weightSemibold: '600',
    weightBold: '700',
  },
  radius: {
    sm: '4px',
    md: '8px',
    lg: '16px',
    full: '9999px',
  },
  transition: {
    fast: '150ms ease-out',
    normal: '300ms ease-out',
  }
}

export const avatarColors = ['#5a7795', '#7e9588', '#b18763', '#7d6f95', '#8d6872']

export function getAvatarColor(username: string): string {
  const firstChar = username.charAt(0).toLowerCase()
  const charCode = firstChar.charCodeAt(0) - 97
  return avatarColors[charCode % avatarColors.length]
}

function decodeBase64Url(value: string): string {
  const normalized = value.replace(/-/g, '+').replace(/_/g, '/')
  const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=')
  return atob(padded)
}

export function decodeJWT(token: string): { sub: string; username: string; is_admin: boolean } | null {
  try {
    const parts = token.split('.')
    if (parts.length !== 3) return null
    const payload = JSON.parse(decodeBase64Url(parts[1]))
    return {
      sub: payload.sub || '',
      username: payload.username || '',
      is_admin: payload.is_admin || false
    }
  } catch {
    return null
  }
}
