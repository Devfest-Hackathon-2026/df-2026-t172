import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";
import { AUTH_REQUIRED_EVENT, MODE_EVENT, ApiError, getHealth, getPatients, request } from "../js/api.js";
import { clearPasscode, getPasscode, setPasscode } from "../js/auth.js";

const originalFetch = globalThis.fetch;
const testPasscode = "test-only-passcode";
let stored;

beforeEach(() => {
  stored = new Map();
  globalThis.window = Object.assign(new EventTarget(), {
    location: { origin: "http://localhost:8765" },
    sessionStorage: {
      getItem: (key) => stored.get(key) ?? null,
      setItem: (key, value) => stored.set(key, value),
      removeItem: (key) => stored.delete(key),
    },
  });
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  delete globalThis.window;
});

test("health does not transmit the stored passcode", async () => {
  setPasscode(testPasscode);
  globalThis.fetch = async (url, options) => {
    assert.equal(url.pathname, "/api/health");
    assert.equal(options.headers.has("X-Passcode"), false);
    return Response.json({ mode: "mock", status: "ok" });
  };
  assert.equal((await getHealth()).mode, "mock");
  assert.equal(getPasscode(), testPasscode);
});

test("protected reads send X-Passcode; candidate validation does not save it", async () => {
  globalThis.fetch = async (_, options) => {
    assert.equal(options.headers.get("X-Passcode"), testPasscode);
    return Response.json({ mode: "mock", patients: [] });
  };
  await getPatients({ passcode: testPasscode });
  assert.equal(getPasscode(), null);
});

test("JSON writes preserve the body, omit cookies and disallow redirects", async () => {
  setPasscode(testPasscode);
  const body = { confirm_id: "test_confirm", patient_id: "test_patient" };
  globalThis.fetch = async (url, options) => {
    assert.equal(url.origin, window.location.origin);
    assert.equal(options.method, "POST");
    assert.equal(options.headers.get("X-Passcode"), testPasscode);
    assert.equal(options.headers.get("Content-Type"), "application/json");
    assert.deepEqual(JSON.parse(options.body), body);
    assert.equal(options.credentials, "omit");
    assert.equal(options.redirect, "error");
    return Response.json({ mode: "mock", record_id: "test_record" });
  };
  await request("/api/records", { method: "POST", body });
});

test("multipart leaves Content-Type and boundary to the browser", async () => {
  setPasscode(testPasscode);
  const form = new FormData();
  form.set("patient_id", "test_patient");
  form.set("audio", new Blob(["test audio"]), "test.webm");
  globalThis.fetch = async (_, options) => {
    assert.equal(options.body, form);
    assert.equal(options.headers.has("Content-Type"), false);
    assert.equal(options.headers.get("X-Passcode"), testPasscode);
    return Response.json({ mode: "mock" });
  };
  await request("/api/drafts", { method: "POST", body: form });
});

test("missing authentication does not send a protected request", async () => {
  let calls = 0;
  let prompts = 0;
  globalThis.fetch = async () => { calls += 1; };
  window.addEventListener(AUTH_REQUIRED_EVENT, () => { prompts += 1; });
  await assert.rejects(getPatients(), { status: 401, code: "bad_passcode" });
  assert.equal(calls, 0);
  assert.equal(prompts, 1);
});

test("401 clears only the passcode and requests the authentication screen", async () => {
  setPasscode(testPasscode);
  window.sessionStorage.setItem("unrelated", "keep");
  let message;
  window.addEventListener(AUTH_REQUIRED_EVENT, (event) => { message = event.detail.message; });
  globalThis.fetch = async () => Response.json({
    mode: "mock", error: { code: "bad_passcode", message: "合言葉が違います" },
  }, { status: 401 });
  await assert.rejects(getPatients(), { status: 401, code: "bad_passcode" });
  assert.equal(getPasscode(), null);
  assert.equal(stored.get("unrelated"), "keep");
  assert.equal(message, "合言葉が違います");
});

test("non-JSON 401 still clears the rejected passcode", async () => {
  setPasscode(testPasscode);
  globalThis.fetch = async () => new Response("Unauthorized", { status: 401 });
  await assert.rejects(getPatients(), { status: 401 });
  assert.equal(getPasscode(), null);
});

test("a delayed 401 does not invalidate a newer passcode", async () => {
  setPasscode(testPasscode);
  let prompts = 0;
  window.addEventListener(AUTH_REQUIRED_EVENT, () => { prompts += 1; });
  globalThis.fetch = async () => {
    setPasscode("new-test-only-passcode");
    return Response.json({ mode: "mock", error: { code: "bad_passcode" } }, { status: 401 });
  };
  await assert.rejects(getPatients(), { status: 401 });
  assert.equal(getPasscode(), "new-test-only-passcode");
  assert.equal(prompts, 0);
});

test("HTTP errors retain the backend message and mode without retries or logout", async () => {
  setPasscode(testPasscode);
  let calls = 0;
  const modes = [];
  window.addEventListener(MODE_EVENT, (event) => modes.push(event.detail.mode));
  for (const status of [409, 413, 422, 429, 502]) {
    globalThis.fetch = async () => {
      calls += 1;
      return Response.json({
        mode: "live", error: { code: "test_error", message: "確認が必要です" },
      }, { status });
    };
    await assert.rejects(request("/api/records", { method: "POST", body: {} }), {
      name: "ApiError", status, code: "test_error", message: "確認が必要です",
    });
  }
  assert.equal(calls, 5);
  assert.deepEqual(modes, ["live", "live", "live", "live", "live"]);
  assert.equal(getPasscode(), testPasscode);
});

test("network failures do not erase authentication or return fake data", async () => {
  setPasscode(testPasscode);
  globalThis.fetch = async () => { throw new TypeError("Failed to fetch"); };
  await assert.rejects(getPatients(), { name: "ApiError", code: "network_error" });
  assert.equal(getPasscode(), testPasscode);
});

test("unexpected successful responses cannot validate a passcode", async () => {
  for (const response of [
    new Response("<html>Not an API</html>"),
    Response.json({ mode: "invalid", patients: [] }),
    Response.json({ mode: "mock", patients: {} }),
  ]) {
    globalThis.fetch = async () => response;
    await assert.rejects(getPatients({ passcode: testPasscode }), {
      name: "ApiError", code: "invalid_response",
    });
  }
  assert.equal(getPasscode(), null);
});

test("timeouts and intentional aborts have distinct errors", async () => {
  setPasscode(testPasscode);
  globalThis.fetch = async (_, { signal }) => new Promise((resolve, reject) => {
    if (signal.aborted) reject(new DOMException("Aborted", "AbortError"));
    else signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
  });
  await assert.rejects(request("/api/tasks", { timeoutMs: 5 }), { code: "timeout" });
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(request("/api/tasks", { signal: controller.signal }), { code: "aborted" });
  assert.equal(getPasscode(), testPasscode);
});

test("external destinations and paths outside /api/ cannot receive credentials", async () => {
  setPasscode(testPasscode);
  globalThis.fetch = async () => { assert.fail("must not make a request"); };
  for (const path of ["https://example.com/api/patients", "//example.com/api/patients", "/api/../index.html"]) {
    await assert.rejects(request(path), { code: "invalid_endpoint" });
  }
});

test("storage errors are handled without falling back to localStorage", () => {
  window.sessionStorage = {
    getItem() { throw new Error("Blocked"); },
    setItem() { throw new Error("Blocked"); },
    removeItem() { throw new Error("Blocked"); },
  };
  assert.equal(getPasscode(), null);
  assert.throws(() => setPasscode(testPasscode), /合言葉を保持できません/);
  assert.doesNotThrow(clearPasscode);
});
