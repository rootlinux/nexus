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
