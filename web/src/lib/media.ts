import { getApiBaseUrl } from './env'

const API_BASE = getApiBaseUrl()

export function resolveMediaUrl(mediaUrl: string | null | undefined) {
  if (!mediaUrl) {
    return null
  }

  const normalizedMediaUrl = mediaUrl.trim()
  if (!normalizedMediaUrl) {
    return null
  }

  let parsedUrl: URL
  try {
    parsedUrl = new URL(normalizedMediaUrl, API_BASE)
  } catch {
    return null
  }

  const isAbsoluteInput = /^[a-zA-Z][a-zA-Z\d+\-.]*:/.test(normalizedMediaUrl) || normalizedMediaUrl.startsWith('//')
  if (isAbsoluteInput) {
    const protocol = parsedUrl.protocol.toLowerCase()
    if (protocol !== 'http:' && protocol !== 'https:') {
      return null
    }
    return parsedUrl.toString()
  }

  const normalizedBase = API_BASE.replace(/\/$/, '')
  const normalizedPath = normalizedMediaUrl.startsWith('/') ? normalizedMediaUrl : `/${normalizedMediaUrl}`
  return `${normalizedBase}${normalizedPath}`
}

export interface CurrentUserProfileUpdateDetail {
  display_name?: string | null
  avatar_url?: string | null
}

const CURRENT_USER_PROFILE_UPDATED_EVENT = 'current-user-profile-updated'

export function emitCurrentUserProfileUpdate(detail: CurrentUserProfileUpdateDetail) {
  if (typeof window === 'undefined') {
    return
  }

  window.dispatchEvent(new CustomEvent<CurrentUserProfileUpdateDetail>(CURRENT_USER_PROFILE_UPDATED_EVENT, { detail }))
}

export function subscribeToCurrentUserProfileUpdate(
  callback: (detail: CurrentUserProfileUpdateDetail) => void
) {
  if (typeof window === 'undefined') {
    return () => undefined
  }

  const listener = (event: Event) => {
    const customEvent = event as CustomEvent<CurrentUserProfileUpdateDetail>
    callback(customEvent.detail || {})
  }

  window.addEventListener(CURRENT_USER_PROFILE_UPDATED_EVENT, listener)
  return () => window.removeEventListener(CURRENT_USER_PROFILE_UPDATED_EVENT, listener)
}
