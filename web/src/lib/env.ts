const DEFAULT_LOCAL_API_BASE = 'http://localhost:8000'

function normalizeApiBaseUrl(value: string) {
  return value.trim().replace(/\/$/, '')
}

export function getApiBaseUrl() {
  const configured = process.env.NEXT_PUBLIC_API_BASE_URL

  if (configured && configured.trim()) {
    return normalizeApiBaseUrl(configured)
  }

  if (process.env.NODE_ENV === 'production') {
    throw new Error('NEXT_PUBLIC_API_BASE_URL must be set for production builds and runtime')
  }

  return DEFAULT_LOCAL_API_BASE
}
