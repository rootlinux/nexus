import { test } from "node:test";
import assert from "node:assert/strict";
import { NexusClient } from "./client.js";

test("request passes an AbortSignal derived from the configured timeout to fetch", async () => {
  const originalFetch = globalThis.fetch;
  let capturedSignal: AbortSignal | undefined;

  globalThis.fetch = (async (_url: string, options?: RequestInit) => {
    capturedSignal = options?.signal ?? undefined;
    return new Response(JSON.stringify({ total_users: 1, total_posts: 2 }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;

  try {
    const client = new NexusClient({
      baseUrl: "https://api.example.com",
      serviceToken: "token",
      requestTimeoutMs: 1_000,
    });
    await client.getStats();
    assert.ok(capturedSignal instanceof AbortSignal, "expected fetch to receive an AbortSignal");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("request wraps an aborted/timed-out fetch into a clear timeout error", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () => {
    throw new DOMException("The operation was aborted.", "TimeoutError");
  }) as typeof fetch;

  try {
    const client = new NexusClient({
      baseUrl: "https://api.example.com",
      serviceToken: "token",
      requestTimeoutMs: 50,
    });

    await assert.rejects(() => client.getStats(), /timed out after 50ms/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("request resolves normally when the server responds", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () =>
    new Response(JSON.stringify({ total_users: 1, total_posts: 2 }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })) as typeof fetch;

  try {
    const client = new NexusClient({
      baseUrl: "https://api.example.com",
      serviceToken: "token",
      requestTimeoutMs: 5_000,
    });

    const result = await client.getStats();
    assert.deepEqual(result, { total_users: 1, total_posts: 2 });
  } finally {
    globalThis.fetch = originalFetch;
  }
});
