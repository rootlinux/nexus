import { useCallback, useRef } from 'react'
import type { RefObject } from 'react'
import { v4 as uuidv4 } from 'uuid'

export interface SignupGuard {
  submitButtonRef: RefObject<HTMLButtonElement | null>
  guardedSubmit: (submitFn: (requestKey: string) => Promise<void>) => Promise<void>
  resetAttempt: () => void
}

export function useSignupGuard(): SignupGuard {
  const submitButtonRef = useRef<HTMLButtonElement | null>(null)
  const requestKeyRef = useRef<string | null>(null)
  const inFlightRef = useRef(false)

  const lock = useCallback(() => {
    inFlightRef.current = true
    const button = submitButtonRef.current
    if (!button) {
      return
    }

    button.disabled = true
    button.setAttribute('aria-busy', 'true')
  }, [])

  const unlock = useCallback(() => {
    inFlightRef.current = false
    const button = submitButtonRef.current
    if (!button) {
      return
    }

    button.disabled = false
    button.removeAttribute('disabled')
    button.removeAttribute('aria-busy')
  }, [])

  const guardedSubmit = useCallback(async (submitFn: (requestKey: string) => Promise<void>) => {
    if (inFlightRef.current) {
      return
    }

    if (requestKeyRef.current === null) {
      requestKeyRef.current = uuidv4()
    }
    const requestKey = requestKeyRef.current

    lock()
    try {
      await submitFn(requestKey)
    } finally {
      unlock()
    }
  }, [lock, unlock])

  const resetAttempt = useCallback(() => {
    requestKeyRef.current = null
    unlock()
  }, [unlock])

  return {
    submitButtonRef,
    guardedSubmit,
    resetAttempt,
  }
}
