import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { NexusClient } from "./client.js";
import type { Tool } from "./client.js";

const NEXUS_API_BASE_URL = process.env.NEXUS_API_BASE_URL || "https://api.example.com/api";
const NEXUS_SERVICE_TOKEN = process.env.NEXUS_SERVICE_TOKEN || "";

if (!NEXUS_SERVICE_TOKEN) {
  console.error("NEXUS_SERVICE_TOKEN environment variable is required");
  process.exit(1);
}

const client = new NexusClient({
  baseUrl: NEXUS_API_BASE_URL,
  serviceToken: NEXUS_SERVICE_TOKEN,
});

function makeTool(toolDef: Tool) {
  return {
    name: toolDef.name,
    description: toolDef.description,
    inputSchema: toolDef.inputSchema,
  };
}

const tools: Tool[] = [
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
    name: "delete_user",
    description: "Permanently delete a user account",
    inputSchema: {
      type: "object",
      properties: {
        user_id: { type: "string", description: "The user ID to delete" },
      },
      required: ["user_id"],
    },
    handler: async (args: Record<string, unknown>) => {
      return await client.deleteUser({ userId: args.user_id as string });
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
        user_id: { type: "string", description: "Filter posts by author user ID", optional: true },
      },
    },
    handler: async (args: Record<string, unknown>) => {
      return await client.listPosts({ 
        limit: args.limit as number ?? 20, 
        offset: args.offset as number ?? 0, 
        userId: args.user_id as string | undefined 
      });
    },
  },
  {
    name: "delete_post",
    description: "Permanently delete a post",
    inputSchema: {
      type: "object",
      properties: {
        post_id: { type: "string", description: "The post ID to delete" },
      },
      required: ["post_id"],
    },
    handler: async (args: Record<string, unknown>) => {
      return await client.deletePost({ postId: args.post_id as string });
    },
  },
  {
    name: "send_push_notification",
    description: "Send a push notification to a user",
    inputSchema: {
      type: "object",
      properties: {
        user_id: { type: "string", description: "Target user ID" },
        title: { type: "string", description: "Notification title" },
        body: { type: "string", description: "Notification body text" },
      },
      required: ["user_id", "title", "body"],
    },
    handler: async (args: Record<string, unknown>) => {
      return await client.sendPushNotification({ 
        userId: args.user_id as string, 
        title: args.title as string, 
        body: args.body as string 
      });
    },
  },
  {
    name: "get_stats",
    description: "Get platform statistics including total users, posts, and active sessions",
    inputSchema: { type: "object", properties: {} },
    handler: async () => {
      return await client.getStats();
    },
  },
];

const server = new Server(
  {
    name: "nexus-admin",
    version: "1.0.0",
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

server.setRequestHandler(ListToolsRequestSchema, async () => {
  return { tools: tools.map(makeTool) };
});

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const toolName = request.params.name;
  const tool = tools.find((t) => t.name === toolName);

  if (!tool) {
    return {
      content: [{ type: "text", text: `Unknown tool: ${toolName}` }],
      isError: true,
    };
  }

  try {
    const result = await tool.handler(request.params.arguments ?? {});
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return {
      content: [{ type: "text", text: `Error: ${message}` }],
      isError: true,
    };
  }
});

const transport = new StdioServerTransport();
server.connect(transport).catch((err) => {
  console.error("Failed to connect transport:", err);
  process.exit(1);
});