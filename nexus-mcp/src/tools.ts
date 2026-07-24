import type { NexusClient, Tool } from "./client.js";

export function createTools(client: NexusClient): Tool[] {
  return [
    {
      name: "list_users",
      description: "List all users with pagination support",
      inputSchema: {
        type: "object",
        properties: {
          limit: { type: "number", description: "Maximum number of users to return", default: 20 },
          offset: { type: "number", description: "Number of users to skip", default: 0 },
        },
      },
      handler: async (args: Record<string, unknown>) => {
        const limit = (args.limit as number) ?? 20;
        const offset = (args.offset as number) ?? 0;
        return await client.listUsers({ limit, offset });
      },
    },
    {
      name: "get_user",
      description: "Get detailed information about a specific user by ID",
      inputSchema: {
        type: "object",
        properties: {
          user_id: { type: "string", description: "The user ID to retrieve" },
        },
        required: ["user_id"],
      },
      handler: async (args: Record<string, unknown>) => {
        return await client.getUser({ userId: args.user_id as string });
      },
    },
    {
      name: "list_posts",
      description: "List posts with optional user_id filter",
      inputSchema: {
        type: "object",
        properties: {
          limit: { type: "number", description: "Maximum number of posts to return", default: 20 },
          offset: { type: "number", description: "Number of posts to skip", default: 0 },
          user_id: { type: "string", description: "Filter posts by author user ID" },
        },
      },
      handler: async (args: Record<string, unknown>) => {
        return await client.listPosts({
          limit: (args.limit as number) ?? 20,
          offset: (args.offset as number) ?? 0,
          userId: args.user_id as string | undefined,
        });
      },
    },
    {
      name: "get_stats",
      description: "Get platform statistics including total users and posts",
      inputSchema: { type: "object", properties: {} },
      handler: async () => {
        return await client.getStats();
      },
    },
  ];
}
