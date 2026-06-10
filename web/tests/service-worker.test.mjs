import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import vm from 'node:vm'
import { fileURLToPath } from 'node:url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

function loadServiceWorker(overrides = {}) {
  const listeners = new Map()
  const cacheStub = {
    addAll: async () => undefined,
    match: async () => undefined,
    put: async () => undefined,
  }

  const baseSelf = {
    location: { origin: 'https://app.example.test' },
    registration: {
      navigationPreload: { enable: async () => undefined },
      showNotification: async () => undefined,
    },
    clients: {
      matchAll: async () => [],
      openWindow: async () => undefined,
    },
    skipWaiting: () => undefined,
    addEventListener: (type, handler) => {
      listeners.set(type, handler)
    },
  }

  const context = {
    URL,
    Response,
    Promise,
    setTimeout,
    clearTimeout,
    caches: {
      open: async () => cacheStub,
      keys: async () => [],
      delete: async () => true,
      match: async () => undefined,
    },
    fetch: async () => new Response('ok'),
    ...overrides,
    self: { ...baseSelf, ...(overrides.self || {}) },
  }

  const source = fs.readFileSync(path.join(__dirname, '..', 'public', 'sw.js'), 'utf8')
  vm.runInNewContext(source, context, { filename: 'sw.js' })
  return { context, listeners }
}

test('push payload shows notification with route metadata', async () => {
  const notifications = []
  const { listeners, context } = loadServiceWorker({
    self: {
      registration: {
        showNotification: async (title, options) => {
          notifications.push({ title, options })
        },
      },
    },
  })

  const pushHandler = listeners.get('push')
  assert.ok(pushHandler)

  let waited = null
  await pushHandler({
    data: {
      json: () => ({
        title: 'New activity',
        body: 'alex followed you',
        url: '/notifications',
        tag: 'notification-1',
        notification_id: 1,
        notification_type: 'follow',
      }),
    },
    waitUntil(promise) {
      waited = promise
    },
  })
  await waited

  assert.equal(notifications.length, 1)
  assert.equal(notifications[0].title, 'New activity')
  assert.equal(notifications[0].options.body, 'alex followed you')
  assert.equal(notifications[0].options.tag, 'notification-1')
  assert.equal(notifications[0].options.data.url, '/notifications')
  assert.equal(notifications[0].options.data.notificationId, 1)
  assert.equal(notifications[0].options.data.notificationType, 'follow')
  assert.equal(context.self.location.origin, 'https://app.example.test')
})

test('notificationclick focuses an existing app client and navigates to the target url', async () => {
  const actions = []
  const client = {
    url: 'https://app.example.test/notifications',
    navigate: async (nextUrl) => {
      actions.push(['navigate', nextUrl])
    },
    focus: async () => {
      actions.push(['focus'])
    },
  }

  const { listeners } = loadServiceWorker({
    self: {
      clients: {
        matchAll: async () => [client],
        openWindow: async (nextUrl) => {
          actions.push(['openWindow', nextUrl])
        },
      },
    },
  })

  const clickHandler = listeners.get('notificationclick')
  assert.ok(clickHandler)

  let waited = null
  await clickHandler({
    notification: {
      data: { url: '/post/42?entry=notifications&focus=reply' },
      close() {
        actions.push(['close'])
      },
    },
    waitUntil(promise) {
      waited = promise
    },
  })
  await waited

  assert.deepEqual(actions, [
    ['close'],
    ['navigate', 'https://app.example.test/post/42?entry=notifications&focus=reply'],
    ['focus'],
  ])
})
