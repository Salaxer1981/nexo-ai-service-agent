// Nexo evaluation client — production runtime (UI-02). Zero dependencies (Node.js standard library only).
//
// Serves the built bundle (dist/) and proxies exactly two backend routes:
//   POST /api/chat          -> POST {BACKEND_URL}/chat
//   GET  /api/health/ready  -> GET  {BACKEND_URL}/health/ready
// The page names a demo session (X-Demo-Session: A | B). This server attaches that SYNTHETIC customer's Bearer token
// server-side (AUTH_TOKEN_CUSTOMER_A / _B from the container environment). The browser never receives a credential;
// any browser-supplied Authorization / Cookie is dropped. Identity is still decided only by the backend.
import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer, request as httpRequest } from "node:http";
import { extname, join, normalize, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".json": "application/json",
  ".woff2": "font/woff2",
};
const ROUTES = { "POST /api/chat": "/chat", "GET /api/health/ready": "/health/ready" };
const MAX_BODY = 16 * 1024; // /chat messages are <= 1000 chars
const SECURITY_HEADERS = {
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
  "X-Frame-Options": "DENY",
  "Content-Security-Policy":
    "default-src 'self'; style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; " +
    "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
};

function json(res, status, body) {
  res.writeHead(status, { ...SECURITY_HEADERS, "Content-Type": "application/json", "Cache-Control": "no-store" });
  res.end(JSON.stringify(body));
}

function serveStatic(res, root, urlPath) {
  const clean = normalize(decodeURIComponent(urlPath.split("?")[0])).replace(/^([/\\])+/, "");
  let file = resolve(root, clean);
  if (!file.startsWith(root + sep) || !existsSync(file) || !statSync(file).isFile()) file = join(root, "index.html"); // SPA
  const isIndex = file.endsWith("index.html");
  res.writeHead(200, {
    ...SECURITY_HEADERS,
    "Content-Type": MIME[extname(file)] || "application/octet-stream",
    "Cache-Control": isIndex ? "no-store" : "public, max-age=31536000, immutable",
  });
  createReadStream(file).pipe(res);
}

/** Builds the request handler. `tokens` = { A?: string, B?: string } (server-side only). */
export function createHandler({ root, backendUrl, tokens, timeoutMs = 120_000 }) {
  const backend = new URL(backendUrl);
  return (req, res) => {
    const path = (req.url || "/").split("?")[0];
    if (path === "/healthz") return json(res, 200, { status: "ok" });
    if (!path.startsWith("/api/")) {
      if (req.method !== "GET" && req.method !== "HEAD") return json(res, 405, { detail: "Method not allowed" });
      return serveStatic(res, root, path);
    }
    const target = ROUTES[`${req.method} ${path}`];
    if (!target) return json(res, 404, { detail: "Not found" });
    const token = tokens[String(req.headers["x-demo-session"] || "")];
    if (!token) return json(res, 503, { code: "demo_session_unavailable", detail: "Demo credentials are not configured." });

    const chunks = [];
    let size = 0;
    req.on("data", (c) => {
      size += c.length;
      if (size > MAX_BODY) {
        json(res, 413, { detail: "Request too large" });
        req.destroy();
      } else chunks.push(c);
    });
    req.on("end", () => {
      if (res.headersSent) return;
      const body = Buffer.concat(chunks);
      // Only these headers reach the backend; everything else from the browser (Authorization, Cookie, ...) is dropped.
      const headers = { authorization: `Bearer ${token}`, accept: "application/json" };
      if (req.method === "POST") {
        headers["content-type"] = "application/json";
        headers["content-length"] = String(body.length);
      }
      const conv = req.headers["x-conversation-id"];
      if (typeof conv === "string" && /^[A-Za-z0-9._-]{1,64}$/.test(conv)) headers["x-conversation-id"] = conv;
      const upstream = httpRequest(
        { protocol: backend.protocol, hostname: backend.hostname, port: backend.port, method: req.method, path: target, headers, timeout: timeoutMs },
        (up) => {
          const out = { ...SECURITY_HEADERS, "Content-Type": up.headers["content-type"] || "application/json", "Cache-Control": "no-store" };
          if (up.headers["x-request-id"]) out["X-Request-ID"] = up.headers["x-request-id"];
          res.writeHead(up.statusCode || 502, out);
          up.pipe(res);
        },
      );
      upstream.on("timeout", () => upstream.destroy(new Error("timeout")));
      upstream.on("error", () => {
        if (!res.headersSent) json(res, 502, { code: "backend_unreachable", detail: "The service is not reachable." });
        else res.end();
      });
      upstream.end(req.method === "POST" ? body : undefined);
    });
  };
}

export function tokensFromEnv(env = process.env) {
  const out = {};
  if (env.AUTH_TOKEN_CUSTOMER_A) out.A = env.AUTH_TOKEN_CUSTOMER_A;
  if (env.AUTH_TOKEN_CUSTOMER_B) out.B = env.AUTH_TOKEN_CUSTOMER_B;
  return out;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const root = resolve(process.env.WEB_ROOT || join(fileURLToPath(new URL(".", import.meta.url)), "..", "dist"));
  const port = Number(process.env.PORT || 8080);
  const host = process.env.HOST || "0.0.0.0";
  const backendUrl = process.env.BACKEND_URL || "http://127.0.0.1:8000";
  const tokens = tokensFromEnv();
  createServer(createHandler({ root, backendUrl, tokens })).listen(port, host, () => {
    // Session names only; never a credential value.
    process.stdout.write(`nexo-web listening on ${host}:${port}; backend ${backendUrl}; demo sessions: ${Object.keys(tokens).join(",") || "none"}\n`);
  });
}
