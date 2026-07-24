export interface Tool {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
  handler: (args: Record<string, unknown>) => Promise<unknown>;
}

const DEFAULT_REQUEST_TIMEOUT_MS = 10_000;

interface NexusClientConfig {
  baseUrl: string;
  serviceToken: string;
  requestTimeoutMs?: number;
}

interface ApiError {
  detail?: string;
  message?: string;
  status_code?: number;
}

export class NexusClient {
  private baseUrl: string;
  private serviceToken: string;
  private requestTimeoutMs: number;

  constructor(config: NexusClientConfig) {
    this.baseUrl = config.baseUrl;
    this.serviceToken = config.serviceToken;
    this.requestTimeoutMs = config.requestTimeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS;
  }

  private async request<T>(
    method: "GET" | "POST" | "DELETE",
    path: string,
    body?: Record<string, unknown>
  ): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const headers: Record<string, string> = {
      "X-Service-Token": this.serviceToken,
      "Content-Type": "application/json",
    };

    const options: RequestInit = {
      method,
      headers,
      signal: AbortSignal.timeout(this.requestTimeoutMs),
    };

    if (body && method !== "GET") {
      options.body = JSON.stringify(body);
    }

    let response: Response;
    try {
      response = await fetch(url, options);
    } catch (error) {
      if (error instanceof Error && (error.name === "TimeoutError" || error.name === "AbortError")) {
        throw new Error(`Request to ${path} timed out after ${this.requestTimeoutMs}ms`);
      }
      throw error;
    }

    if (!response.ok) {
      let errorMessage = `HTTP ${response.status}`;
      try {
        const errorData: ApiError = await response.json();
        errorMessage = errorData.detail || errorData.message || errorMessage;
      } catch {
        errorMessage = response.statusText || errorMessage;
      }
      throw new Error(`API Error (${response.status}): ${errorMessage}`);
    }

    if (response.status === 204) {
      return {} as T;
    }

    return response.json();
  }

  async listUsers(params: { limit?: number; offset?: number }): Promise<unknown> {
    const query = new URLSearchParams({
      limit: String(params.limit ?? 20),
      offset: String(params.offset ?? 0),
    });
    return this.request<unknown>("GET", `/admin/service/users?${query}`);
  }

  async getUser(params: { userId: string }): Promise<unknown> {
    return this.request<unknown>("GET", `/admin/service/users/${params.userId}`);
  }

  async listPosts(params: {
    limit?: number;
    offset?: number;
    userId?: string;
  }): Promise<unknown> {
    const query = new URLSearchParams({
      limit: String(params.limit ?? 20),
      offset: String(params.offset ?? 0),
    });
    if (params.userId) {
      query.set("user_id", params.userId);
    }
    return this.request<unknown>("GET", `/admin/service/posts?${query}`);
  }

  async getStats(): Promise<unknown> {
    return this.request<unknown>("GET", `/admin/service/stats`);
  }
}