export interface NexusMcpConfig {
  baseUrl: string;
  serviceToken: string;
}

const ALLOWED_PROTOCOLS = new Set(["http:", "https:"]);
const LOOPBACK_HOSTNAMES = new Set(["localhost", "127.0.0.1", "::1", "[::1]"]);

function parseHttpAllowedHosts(raw: string | undefined): Set<string> {
  return new Set(
    (raw || "")
      .split(",")
      .map((host) => host.trim().toLowerCase())
      .filter((host) => host.length > 0)
  );
}

export function validateBaseUrl(rawUrl: string, extraHttpAllowedHosts: Set<string> = new Set()): string {
  let parsed: URL;
  try {
    parsed = new URL(rawUrl);
  } catch {
    throw new Error(`NEXUS_API_BASE_URL is not a valid URL: "${rawUrl}"`);
  }

  if (!ALLOWED_PROTOCOLS.has(parsed.protocol)) {
    throw new Error(`NEXUS_API_BASE_URL must use http or https (got "${parsed.protocol}")`);
  }

  if (parsed.username || parsed.password) {
    throw new Error("NEXUS_API_BASE_URL must not embed a username or password");
  }

  if (parsed.protocol === "http:") {
    const hostname = parsed.hostname.toLowerCase();
    if (!LOOPBACK_HOSTNAMES.has(hostname) && !extraHttpAllowedHosts.has(hostname)) {
      throw new Error(
        `NEXUS_API_BASE_URL uses http:// with non-loopback host "${parsed.hostname}". ` +
          "Use https:// for remote hosts, or add the host to NEXUS_MCP_ALLOWED_HTTP_HOSTS " +
          "if it's a trusted Docker-internal hostname."
      );
    }
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

  const extraHttpAllowedHosts = parseHttpAllowedHosts(env.NEXUS_MCP_ALLOWED_HTTP_HOSTS);

  return {
    baseUrl: validateBaseUrl(rawBaseUrl, extraHttpAllowedHosts),
    serviceToken,
  };
}
