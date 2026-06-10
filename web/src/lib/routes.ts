const RESERVED_PROFILE_SEGMENTS = new Set([
  'admin',
  'auth',
  'discover',
  'explore',
  'invites',
  'login',
  'messages',
  'post',
  'register',
  'search',
  'u',
])

export type SearchTab = 'top' | 'latest' | 'people'
export type ConversationEntryPoint =
  | 'feed'
  | 'profile'
  | 'notifications'
  | 'search'
  | 'discovery'
  | 'bookmarks'
  | 'reply'
  | 'quote'
export type ConversationFocus = 'conversation' | 'reply' | 'quote'

export function getProfileHref(username: string): string {
  const normalizedUsername = username.trim()
  const encodedUsername = encodeURIComponent(normalizedUsername)

  if (RESERVED_PROFILE_SEGMENTS.has(normalizedUsername.toLowerCase())) {
    return `/u/${encodedUsername}`
  }

  return `/${encodedUsername}`
}

export function getPostHref(
  postId: number,
  options?: {
    entry?: ConversationEntryPoint
    focus?: ConversationFocus
  }
): string {
  const params = new URLSearchParams()

  if (options?.entry) {
    params.set('entry', options.entry)
  }

  if (options?.focus && options.focus !== 'conversation') {
    params.set('focus', options.focus)
  }

  const queryString = params.toString()
  return queryString ? `/post/${postId}?${queryString}` : `/post/${postId}`
}

export function getSearchHref(query: string, type: SearchTab = 'top'): string {
  const params = new URLSearchParams()
  const normalizedQuery = query.trim()

  if (normalizedQuery) {
    params.set('q', normalizedQuery)
  }

  if (type !== 'top') {
    params.set('type', type)
  }

  const queryString = params.toString()
  return queryString ? `/search?${queryString}` : '/search'
}
