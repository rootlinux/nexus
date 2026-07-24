export interface Tool {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
  handler: (args: Record<string, unknown>) => Promise<unknown>;
}

interface NexusClientConfig {
  baseUrl: string;
  serviceToken: string;
}

interface ApiError {
  detail?: string;
  message?: string;
  status_code?: number;
}

export class NexusClient {
  private baseUrl: string;
  private serviceToken: string;

  constructor(config: NexusClientConfig) {
    this.baseUrl = config.baseUrl;
    this.serviceToken = config.serviceToken;
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
    };

    if (body && method !== "GET") {
      options.body = JSON.stringify(body);
    }

    const response = await fetch(url, options);

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

  async deleteUser(params: { userId: string }): Promise<unknown> {
    return this.request<unknown>("DELETE", `/admin/service/users/${params.userId}`);
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

  async deletePost(params: { postId: string }): Promise<unknown> {
    return this.request<unknown>("DELETE", `/admin/service/posts/${params.postId}`);
  }

  async sendPushNotification(params: {
    userId: string;
    title: string;
    body: string;
  }): Promise<unknown> {
    return this.request<unknown>("POST", `/admin/service/notifications/push`, {
      user_id: params.userId,
      title: params.title,
      body: params.body,
    });
  }

  async getStats(): Promise<unknown> {
    return this.request<unknown>("GET", `/admin/service/stats`);
  }
}