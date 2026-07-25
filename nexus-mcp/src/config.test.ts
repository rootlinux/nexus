import { test } from "node:test";
import assert from "node:assert/strict";
import { loadConfig, validateBaseUrl } from "./config.js";

test("validateBaseUrl accepts a well-formed https URL", () => {
  assert.equal(validateBaseUrl("https://api.example.com"), "https://api.example.com");
});

test("validateBaseUrl accepts a well-formed http URL", () => {
  assert.equal(validateBaseUrl("http://localhost:8000"), "http://localhost:8000");
});

test("validateBaseUrl strips trailing slashes", () => {
  assert.equal(validateBaseUrl("https://api.example.com/api/"), "https://api.example.com/api");
});

test("validateBaseUrl rejects a malformed URL", () => {
  assert.throws(() => validateBaseUrl("not a url"), /is not a valid URL/);
});

test("validateBaseUrl rejects a non-http(s) scheme", () => {
  assert.throws(() => validateBaseUrl("javascript:alert(1)"), /must use http or https/);
});

test("validateBaseUrl rejects an ftp URL", () => {
  assert.throws(() => validateBaseUrl("ftp://files.example.com"), /must use http or https/);
});

test("loadConfig throws when NEXUS_API_BASE_URL is missing", () => {
  assert.throws(
    () => loadConfig({ NEXUS_SERVICE_TOKEN: "token" } as NodeJS.ProcessEnv),
    /NEXUS_API_BASE_URL environment variable is required/
  );
});

test("loadConfig throws when NEXUS_SERVICE_TOKEN is missing", () => {
  assert.throws(
    () => loadConfig({ NEXUS_API_BASE_URL: "https://api.example.com" } as NodeJS.ProcessEnv),
    /NEXUS_SERVICE_TOKEN environment variable is required/
  );
});

test("loadConfig throws on an invalid NEXUS_API_BASE_URL scheme", () => {
  assert.throws(
    () =>
      loadConfig({
        NEXUS_API_BASE_URL: "javascript:alert(1)",
        NEXUS_SERVICE_TOKEN: "token",
      } as NodeJS.ProcessEnv),
    /must use http or https/
  );
});

test("loadConfig returns a normalized config when both variables are set", () => {
  const config = loadConfig({
    NEXUS_API_BASE_URL: "https://api.example.com/",
    NEXUS_SERVICE_TOKEN: "token",
  } as NodeJS.ProcessEnv);
  assert.deepEqual(config, { baseUrl: "https://api.example.com", serviceToken: "token" });
});

test("validateBaseUrl rejects http:// against a non-loopback host", () => {
  assert.throws(() => validateBaseUrl("http://api.example.com"), /non-loopback host/);
});

test("validateBaseUrl accepts http:// against 127.0.0.1 and ::1", () => {
  assert.equal(validateBaseUrl("http://127.0.0.1:8000"), "http://127.0.0.1:8000");
  assert.equal(validateBaseUrl("http://[::1]:8000"), "http://[::1]:8000");
});

test("validateBaseUrl accepts http:// against an explicitly allowlisted host", () => {
  const allowed = new Set(["backend"]);
  assert.equal(validateBaseUrl("http://backend:8000", allowed), "http://backend:8000");
});

test("validateBaseUrl still rejects an unlisted non-loopback host even with an allowlist set", () => {
  const allowed = new Set(["backend"]);
  assert.throws(() => validateBaseUrl("http://other-host:8000", allowed), /non-loopback host/);
});

test("validateBaseUrl rejects a URL with embedded userinfo", () => {
  assert.throws(
    () => validateBaseUrl("https://user:pass@api.example.com"),
    /must not embed a username or password/
  );
});

test("validateBaseUrl rejects embedded userinfo even on an otherwise-allowed loopback http URL", () => {
  assert.throws(
    () => validateBaseUrl("http://user:pass@localhost:8000"),
    /must not embed a username or password/
  );
});

test("loadConfig honors NEXUS_MCP_ALLOWED_HTTP_HOSTS for docker-internal hostnames", () => {
  const config = loadConfig({
    NEXUS_API_BASE_URL: "http://backend:8000",
    NEXUS_SERVICE_TOKEN: "token",
    NEXUS_MCP_ALLOWED_HTTP_HOSTS: "backend,other-host",
  } as NodeJS.ProcessEnv);
  assert.deepEqual(config, { baseUrl: "http://backend:8000", serviceToken: "token" });
});

test("loadConfig rejects a remote http host when NEXUS_MCP_ALLOWED_HTTP_HOSTS is unset", () => {
  assert.throws(
    () =>
      loadConfig({
        NEXUS_API_BASE_URL: "http://api.example.com",
        NEXUS_SERVICE_TOKEN: "token",
      } as NodeJS.ProcessEnv),
    /non-loopback host/
  );
});
