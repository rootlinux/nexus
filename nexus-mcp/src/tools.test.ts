import { test } from "node:test";
import assert from "node:assert/strict";
import { NexusClient } from "./client.js";
import { createTools } from "./tools.js";

test("MCP tool surface exposes only the read-only tools — no delete or push tools", () => {
  const client = new NexusClient({ baseUrl: "https://api.example.com", serviceToken: "token" });
  const tools = createTools(client);
  const names = tools.map((tool) => tool.name).sort();

  assert.deepEqual(names, ["get_stats", "get_user", "list_posts", "list_users"]);
});

test("list_posts input schema only marks user_id as optional via absence from required, not a custom keyword", () => {
  const client = new NexusClient({ baseUrl: "https://api.example.com", serviceToken: "token" });
  const tools = createTools(client);
  const listPosts = tools.find((tool) => tool.name === "list_posts");
  assert.ok(listPosts);

  const schema = listPosts.inputSchema as {
    properties: Record<string, Record<string, unknown>>;
    required?: string[];
  };

  assert.equal("optional" in schema.properties.user_id, false);
  assert.equal((schema.required ?? []).includes("user_id"), false);
});
