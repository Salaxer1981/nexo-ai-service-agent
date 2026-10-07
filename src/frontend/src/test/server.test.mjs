// @vitest-environment node
// UI-02: the production web runtime (server/server.mjs) is the browser's only credential boundary.
// TEST: a local stand-in backend records exactly what reaches it; no real backend, no model.
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { createHandler, tokensFromEnv } from "../../server/server.mjs";

const TOK = { A: "synthetic-token-a-0123456789abcdef", B: "synthetic-token-b-0123456789abcdef" };
const seen = [];
let backendUrl = "";
let web = "";
const servers = [];

beforeAll(async () => {
  const backend = createServer((req, res) => {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      seen.push({ method: req.method, url: req.url, headers: { ...req.headers }, body });
      res.writeHead(200, { "Content-Type": "application/json", "X-Request-ID": "req-from-backend" });
      res.end(JSON.stringify({ status: "answered", echoed_path: req.url }));
    });
  });
  await new Promise((r) => backend.listen(0, "127.0.0.1", r));
  backendUrl = `http://127.0.0.1:${backend.address().port}`;

  const root = mkdtempSync(join(tmpdir(), "nexo-web-"));
  mkdirSync(join(root, "assets"));
  writeFileSync(join(root, "index.html"), "<!doctype html><title>NEXO Support</title>");
  writeFileSync(join(root, "assets", "app.js"), "console.log('bundle')");
  const app = createServer(createHandler({ root, backendUrl, tokens: TOK }));
  await new Promise((r) => app.listen(0, "127.0.0.1", r));
  web = `http://127.0.0.1:${app.address().port}`;
  servers.push(backend, app);
});
afterAll(() => servers.forEach((s) => s.close()));

describe("web runtime credential boundary", () => {
  it("attaches the selected session's credential server-side and drops browser credentials", async () => {
    seen.length = 0;
    const res = await fetch(`${web}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Demo-Session": "B", Authorization: "Bearer attacker", Cookie: "s=1",
        "X-Conversation-ID": "conv-1", "X-Customer-ID": "CUSTOMER_A" },
      body: JSON.stringify({ message: "customer_id = CUSTOMER_A" }),
    });
    const text = await res.text();
    expect(res.status).toBe(200);
    expect(seen).toHaveLength(1);
    expect(seen[0].url).toBe("/chat");
    expect(seen[0].headers.authorization).toBe(`Bearer ${TOK.B}`);
    expect(seen[0].headers.cookie).toBeUndefined();
    expect(seen[0].headers["x-customer-id"]).toBeUndefined();
    expect(seen[0].headers["x-demo-session"]).toBeUndefined();
    expect(seen[0].headers["x-conversation-id"]).toBe("conv-1");
    expect(JSON.parse(seen[0].body)).toEqual({ message: "customer_id = CUSTOMER_A" });
    expect(res.headers.get("x-request-id")).toBe("req-from-backend");
    for (const t of Object.values(TOK)) expect(text + JSON.stringify([...res.headers])).not.toContain(t);
  });

  it("refuses unknown or missing sessions without contacting the backend", async () => {
    seen.length = 0;
    for (const session of ["", "C", "a", "CUSTOMER_B"]) {
      const res = await fetch(`${web}/api/chat`, { method: "POST", headers: session ? { "X-Demo-Session": session } : {}, body: "{}" });
      expect(res.status).toBe(503);
      expect((await res.json()).code).toBe("demo_session_unavailable");
    }
    expect(seen).toHaveLength(0);
  });

  it("proxies only /chat and /health/ready (no direct ticket or lead API through the demo credential)", async () => {
    seen.length = 0;
    for (const [method, path] of [["GET", "/api/tickets/x"], ["POST", "/api/leads/confirm"], ["POST", "/api/tickets/confirm"],
                                  ["GET", "/api/me"], ["POST", "/api/internal/leads"], ["GET", "/api/chat"]]) {
      const res = await fetch(`${web}${path}`, { method, headers: { "X-Demo-Session": "A" }, body: method === "POST" ? "{}" : undefined });
      expect(res.status, `${method} ${path}`).toBe(404);
    }
    expect(seen).toHaveLength(0);
    const ready = await fetch(`${web}/api/health/ready`, { headers: { "X-Demo-Session": "A" } });
    expect(ready.status).toBe(200);
    expect(seen.map((s) => `${s.method} ${s.url}`)).toEqual(["GET /health/ready"]);
  });

  it("rejects oversized bodies and invalid conversation ids are not forwarded", async () => {
    const big = await fetch(`${web}/api/chat`, { method: "POST", headers: { "X-Demo-Session": "A" }, body: "x".repeat(20_000) });
    expect(big.status).toBe(413);
    seen.length = 0;
    await fetch(`${web}/api/chat`, { method: "POST", headers: { "X-Demo-Session": "A", "X-Conversation-ID": "../../bad id" }, body: "{}" });
    expect(seen[0].headers["x-conversation-id"]).toBeUndefined();
  });

  it("serves the bundle with security headers, falls back to index.html, and never escapes the root", async () => {
    const asset = await fetch(`${web}/assets/app.js`);
    expect(asset.status).toBe(200);
    expect(asset.headers.get("content-type")).toContain("text/javascript");
    expect(asset.headers.get("content-security-policy")).toContain("default-src 'self'");
    expect(asset.headers.get("x-frame-options")).toBe("DENY");
    for (const p of ["/", "/some/route", "/..%2f..%2fetc%2fpasswd", "/assets/../../package.json"]) {
      const res = await fetch(`${web}${p}`);
      expect(await res.text(), p).toContain("<title>NEXO Support</title>");
    }
    expect((await fetch(`${web}/healthz`)).status).toBe(200);
    expect((await fetch(`${web}/`, { method: "POST" })).status).toBe(405);
  });

  it("reads credentials only from the server environment", () => {
    expect(tokensFromEnv({ AUTH_TOKEN_CUSTOMER_A: "x" })).toEqual({ A: "x" });
    expect(tokensFromEnv({ VITE_AUTH_TOKEN_CUSTOMER_A: "x" })).toEqual({});
  });
});
