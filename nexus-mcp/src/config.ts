export interface NexusMcpConfig {
  baseUrl: string;
  serviceToken: string;
}

const ALLOWED_PROTOCOLS = new Set(["http:", "https:"]);

export function validateBaseUrl(rawUrl: string): string {
  let parsed: URL;
  try {
    parsed = new URL(rawUrl);
  } catch {
    throw new Error(`NEXUS_API_BASE_URL is not a valid URL: "${rawUrl}"`);
  }

  if (!ALLOWED_PROTOCOLS.has(parsed.protocol)) {
    throw new Error(`NEXUS_API_BASE_URL must use http or https (got "${parsed.protocol}")`);
  }

  return rawUrl.replace(/\/+$/, "");
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): NexusMcpConfig {
  const rawBaseUrl = env.NEXUS_API_BASE_URL || "";
  const serviceToken = env.NEXUS_SERVICE_TOKEN || "";

  if (!rawBaseUrl) {
    throw new Error(
      "NEXUS_API_BASE_URL environment variable is required (no default — refuses to guess an endpoint)"
    );
  }

  if (!serviceToken) {
    throw new Error("NEXUS_SERVICE_TOKEN environment variable is required");
  }

  return {
    baseUrl: validateBaseUrl(rawBaseUrl),
    serviceToken,
  };
}
