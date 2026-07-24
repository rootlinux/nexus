import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { NexusClient } from "./client.js";
import type { Tool } from "./client.js";
import { loadConfig } from "./config.js";
import { createTools } from "./tools.js";

function makeTool(toolDef: Tool) {
  return {
    name: toolDef.name,
    description: toolDef.description,
    inputSchema: toolDef.inputSchema,
  };
}

async function main() {
  const config = loadConfig();
  const client = new NexusClient(config);
  const tools = createTools(client);

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
  await server.connect(transport);
}

main().catch((err) => {
  console.error(err instanceof Error ? err.message : String(err));
  process.exit(1);
});
