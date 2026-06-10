'use client'

import type { Post } from '../../types'
import type { AuthArrivalState } from '../../lib/arrival'

// Helper to update a post in a collection (handles both direct posts and quoted/original posts)
export function updatePostCollection(collection: Post[], targetPostId: number, updater: (post: Post) => Post): Post[] {
  return collection.map((post) => {
    if (post.id === targetPostId) {
      return updater(post)
    }

    if (post.original_post?.id === targetPostId) {
      return {
        ...post,
        original_post: updater(post.original_post),
      }
    }

    return post
  })
}

// Parse error response into user-friendly message
export async function getResponseError(response: Response, fallback: string): Promise<string> {
  try {
    const errorData = await response.json().catch(() => null)
    if (typeof errorData?.detail === 'string') {
      return errorData.detail
    }
    if (typeof errorData?.message === 'string') {
      return errorData.message
    }
  } catch {
    // ignore json parse errors
  }
  return fallback
}

// Get composer placeholder text based on arrival/returning state
export function getComposerPlaceholder(
  activeArrival: AuthArrivalState | null,
  shouldShowReturningLayer: boolean
): string {
  if (activeArrival?.kind === 'signup') {
    return "Your access is live. Add something when you're ready."
  }

  if (shouldShowReturningLayer) {
    return 'Pick the thread back up when you have something to add.'
  }

  if (activeArrival?.kind === 'login') {
    return 'What feels worth sharing today?'
  }

  return 'Write something…'
}

// Get feed intro copy based on arrival/returning/activation state
export function getFeedIntroCopy(
  activeArrival: AuthArrivalState | null,
  shouldShowReturningLayer: boolean,
  activationActive: boolean,
  activationStage: string | null
): string {
  if (activeArrival?.kind === 'signup') {
    return 'A private feed shaped by the people already inside.'
  }

  if (shouldShowReturningLayer) {
    return 'A calmer way back to the people, replies, and threads already close to you.'
  }

  if (activationActive && activationStage === 'second_session') {
    return 'Back on the thread. The next few reads and follows should feel more intentional now.'
  }

  if (activeArrival?.kind === 'login') {
    return 'Ready for you the moment you returned.'
  }

  return ''
}

// Get header title based on state
export function getHeaderTitle(
  activeArrival: AuthArrivalState | null,
  shouldShowReturningLayer: boolean
): string {
  return activeArrival?.kind === 'signup' 
    ? 'Your opening view' 
    : shouldShowReturningLayer 
      ? 'Your return view' 
      : 'Feed'
}
