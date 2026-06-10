'use client'

import { useEffect, useState, useCallback, useRef } from 'react'

// Typed interface for the non-standard BeforeInstallPromptEvent
interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

let viewportFrameId: number | null = null
let lastAppHeight = ''
let lastDisplayMode = ''

function applyViewportState() {
  const root = document.documentElement
  const nextAppHeight = `${window.innerHeight * 0.01}px`

  const standalone =
    window.matchMedia('(display-mode: standalone)').matches ||
    (typeof navigator !== 'undefined' &&
      'standalone' in navigator &&
      Boolean((navigator as Navigator & { standalone?: boolean }).standalone))

  const nextDisplayMode = standalone ? 'standalone' : 'browser'

  if (nextAppHeight !== lastAppHeight) {
    root.style.setProperty('--app-height', nextAppHeight)
    lastAppHeight = nextAppHeight
  }

  if (nextDisplayMode !== lastDisplayMode) {
    root.dataset.displayMode = nextDisplayMode
    lastDisplayMode = nextDisplayMode
  }
}

function scheduleViewportState() {
  if (viewportFrameId !== null) {
    return
  }

  viewportFrameId = window.requestAnimationFrame(() => {
    viewportFrameId = null
    applyViewportState()
  })
}

function isIos() {
  return /iphone|ipad|ipod/i.test(navigator.userAgent)
}

function isStandalone() {
  return (
    window.matchMedia('(display-mode: standalone)').matches ||
    ('standalone' in navigator &&
      Boolean((navigator as Navigator & { standalone?: boolean }).standalone))
  )
}

function scheduleDeferredTask(task: () => void, delayMs = 15_000) {
  const win = window as Window & {
    requestIdleCallback?: (callback: IdleRequestCallback, options?: IdleRequestOptions) => number
    cancelIdleCallback?: (handle: number) => void
  }

  if (typeof win.requestIdleCallback === 'function' && typeof win.cancelIdleCallback === 'function') {
    const idleId = win.requestIdleCallback(() => task(), { timeout: delayMs })
    return () => win.cancelIdleCallback?.(idleId)
  }

  const timeoutId = window.setTimeout(task, delayMs)
  return () => window.clearTimeout(timeoutId)
}

export function PwaBoot() {
  const [showUpdate, setShowUpdate] = useState(false)
  const [showInstall, setShowInstall] = useState(false)
  const [showIosHint, setShowIosHint] = useState(false)

  const swRegRef = useRef<ServiceWorkerRegistration | null>(null)
  const installPromptRef = useRef<BeforeInstallPromptEvent | null>(null)
  const updateCheckIntervalRef = useRef<number | null>(null)
  const swCleanupRef = useRef<(() => void) | null>(null)
  const deferredUpdateCleanupRef = useRef<(() => void) | null>(null)

  // ── SW update: user taps "Refresh" ────────────────────────────────────────
  const handleSkipWaiting = useCallback(() => {
    const waiting = swRegRef.current?.waiting
    if (waiting) {
      waiting.postMessage({ type: 'SKIP_WAITING' })
    }
    setShowUpdate(false)
  }, [])

  // ── Install prompt: Android / Chrome desktop ──────────────────────────────
  const handleInstall = useCallback(async () => {
    const prompt = installPromptRef.current
    if (!prompt) return
    await prompt.prompt()
    const { outcome } = await prompt.userChoice
    if (outcome === 'accepted') {
      installPromptRef.current = null
      setShowInstall(false)
    }
  }, [])

  useEffect(() => {
    scheduleViewportState()
    window.addEventListener('resize', scheduleViewportState)
    window.addEventListener('orientationchange', scheduleViewportState)
    let onControllerChange: (() => void) | null = null

    // ── Install prompt capture ───────────────────────────────────────────
    const onBeforeInstallPrompt = (e: Event) => {
      e.preventDefault()
      installPromptRef.current = e as BeforeInstallPromptEvent
      // Delay so it's not intrusive on first load
      window.setTimeout(() => {
        if (!isStandalone()) setShowInstall(true)
      }, 4000)
    }
    window.addEventListener('beforeinstallprompt', onBeforeInstallPrompt)

    // ── iOS "Add to Home Screen" hint ────────────────────────────────────
    // iOS Safari never fires beforeinstallprompt — show a manual nudge instead.
    if (isIos() && !isStandalone()) {
      const dismissed = sessionStorage.getItem('nexus-ios-hint-dismissed')
      if (!dismissed) {
        window.setTimeout(() => setShowIosHint(true), 5000)
      }
    }

    // ── Service Worker registration ──────────────────────────────────────
    if ('serviceWorker' in navigator) {
      // After SKIP_WAITING the new SW takes control → reload to pick it up.
      let reloading = false
      onControllerChange = () => {
        if (!reloading) {
          reloading = true
          window.location.reload()
        }
      }
      navigator.serviceWorker.addEventListener('controllerchange', onControllerChange)

      const register = async () => {
        try {
          const reg = await navigator.serviceWorker.register('/sw.js', { scope: '/' })
          swRegRef.current = reg

          const checkForUpdates = async () => {
            try {
              await reg.update()
            } catch {
              // Best-effort only; the current SW keeps working.
            }
          }

          // A SW installed before this page load is already waiting.
          if (reg.waiting && navigator.serviceWorker.controller) {
            setShowUpdate(true)
          }

          // A new SW found after page load installs then waits.
          reg.addEventListener('updatefound', () => {
            const next = reg.installing
            if (!next) return
            next.addEventListener('statechange', () => {
              if (next.state === 'installed' && navigator.serviceWorker.controller) {
                setShowUpdate(true)
              }
            })
          })

          deferredUpdateCleanupRef.current = scheduleDeferredTask(() => {
            void checkForUpdates()
          })

          const onVisibilityChange = () => {
            if (document.visibilityState === 'visible') {
              void checkForUpdates()
            }
          }

          const onOnline = () => {
            void checkForUpdates()
          }

          document.addEventListener('visibilitychange', onVisibilityChange)
          window.addEventListener('online', onOnline)
          updateCheckIntervalRef.current = window.setInterval(() => {
            void checkForUpdates()
          }, 15 * 60 * 1000)

          return () => {
            document.removeEventListener('visibilitychange', onVisibilityChange)
            window.removeEventListener('online', onOnline)
            if (updateCheckIntervalRef.current !== null) {
              window.clearInterval(updateCheckIntervalRef.current)
              updateCheckIntervalRef.current = null
            }
            deferredUpdateCleanupRef.current?.()
            deferredUpdateCleanupRef.current = null
          }
        } catch {
          // SW registration failure is non-fatal — app still works.
        }

        return undefined
      }

      if (document.readyState === 'complete') {
        void register().then((cleanup) => {
          if (cleanup) {
            swCleanupRef.current = cleanup
          }
        })
      } else {
        window.addEventListener(
          'load',
          () =>
            void register().then((cleanup) => {
              if (cleanup) {
                swCleanupRef.current = cleanup
              }
            }),
          { once: true }
        )
      }
    }

    return () => {
      window.removeEventListener('resize', scheduleViewportState)
      window.removeEventListener('orientationchange', scheduleViewportState)
      window.removeEventListener('beforeinstallprompt', onBeforeInstallPrompt)
      if (onControllerChange) {
        navigator.serviceWorker?.removeEventListener?.('controllerchange', onControllerChange)
      }
      if (viewportFrameId !== null) {
        window.cancelAnimationFrame(viewportFrameId)
        viewportFrameId = null
      }
      deferredUpdateCleanupRef.current?.()
      deferredUpdateCleanupRef.current = null
      swCleanupRef.current?.()
      swCleanupRef.current = null
    }
  }, [])

  return (
    <>
      {/* ── Update banner (top, above safe area) ───────────────────────── */}
      {showUpdate && (
        <div
          role="status"
          aria-live="polite"
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            zIndex: 9999,
            paddingTop: 'max(12px, env(safe-area-inset-top))',
            paddingBottom: '12px',
            paddingLeft: '16px',
            paddingRight: '16px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '12px',
            backgroundColor: '#1c1c1c',
            borderBottom: '1px solid #242424',
          }}
        >
          <span style={{ color: '#f0f0f0', fontSize: '14px', flex: 1, textAlign: 'center' }}>
            A new version is ready
          </span>
          <button
            onClick={handleSkipWaiting}
            style={{
              backgroundColor: '#c9a96e',
              color: '#1a0f00',
              border: 'none',
              borderRadius: '6px',
              padding: '7px 16px',
              fontSize: '13px',
              fontWeight: 600,
              cursor: 'pointer',
              flexShrink: 0,
            }}
          >
            Update now
          </button>
          <button
            onClick={() => setShowUpdate(false)}
            aria-label="Dismiss"
            style={{
              background: 'none',
              border: 'none',
              color: '#666',
              cursor: 'pointer',
              padding: '4px',
              fontSize: '18px',
              lineHeight: 1,
              flexShrink: 0,
            }}
          >
            ✕
          </button>
        </div>
      )}

      {/* ── Android / Desktop install prompt (above mobile nav) ────────── */}
      {showInstall && !showIosHint && (
        <div
          style={{
            position: 'fixed',
            bottom: 'calc(76px + max(0px, env(safe-area-inset-bottom)))',
            left: '16px',
            right: '16px',
            zIndex: 200,
            backgroundColor: '#141414',
            border: '1px solid #242424',
            borderRadius: '12px',
            padding: '14px 16px',
            display: 'flex',
            alignItems: 'center',
            gap: '12px',
            boxShadow: '0 4px 24px rgba(0,0,0,0.5)',
          }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ color: '#f0f0f0', fontSize: '14px', fontWeight: 500 }}>
              Install Nexus
            </div>
            <div style={{ color: '#666', fontSize: '12px', marginTop: '2px' }}>
              Keep Nexus close with a faster launch
            </div>
          </div>
          <button
            onClick={() => void handleInstall()}
            style={{
              backgroundColor: '#c9a96e',
              color: '#1a0f00',
              border: 'none',
              borderRadius: '8px',
              padding: '8px 16px',
              fontSize: '13px',
              fontWeight: 600,
              cursor: 'pointer',
              flexShrink: 0,
            }}
          >
            Install
          </button>
          <button
            onClick={() => setShowInstall(false)}
            aria-label="Dismiss"
            style={{
              background: 'none',
              border: 'none',
              color: '#666',
              cursor: 'pointer',
              padding: '4px',
              fontSize: '18px',
              lineHeight: 1,
              flexShrink: 0,
            }}
          >
            ✕
          </button>
        </div>
      )}

      {/* ── iOS "Add to Home Screen" hint ───────────────────────────────── */}
      {showIosHint && (
        <div
          style={{
            position: 'fixed',
            bottom: 'calc(76px + max(0px, env(safe-area-inset-bottom)))',
            left: '16px',
            right: '16px',
            zIndex: 200,
            backgroundColor: '#141414',
            border: '1px solid #242424',
            borderRadius: '12px',
            padding: '14px 16px',
            boxShadow: '0 4px 24px rgba(0,0,0,0.5)',
          }}
        >
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: '8px',
            }}
          >
            <div style={{ color: '#f0f0f0', fontSize: '14px', fontWeight: 500 }}>
              Install on iPhone
            </div>
            <button
              onClick={() => {
                sessionStorage.setItem('nexus-ios-hint-dismissed', '1')
                setShowIosHint(false)
              }}
              aria-label="Dismiss"
              style={{
                background: 'none',
                border: 'none',
                color: '#666',
                cursor: 'pointer',
                padding: '4px 0 4px 12px',
                fontSize: '18px',
                lineHeight: 1,
              }}
            >
              ✕
            </button>
          </div>
          <div style={{ color: '#888', fontSize: '13px', lineHeight: 1.55 }}>
            Open{' '}
            <strong style={{ color: '#c9a96e' }}>Share</strong>
            {' '}then choose{' '}
            <strong style={{ color: '#c9a96e' }}>Add to Home Screen</strong>
            {' '}to keep Nexus on your home screen.
          </div>
        </div>
      )}
    </>
  )
}
