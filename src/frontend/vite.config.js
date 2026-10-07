// Nexo evaluation client — Vite config.
// The dev/preview server proxies /api/* to the backend (127.0.0.1:8000) and attaches the Bearer token of the selected
// SYNTHETIC demo customer SERVER-SIDE. The browser and the JS bundle never see a token: the page only names a demo
// session (X-Demo-Session: A | B). Tokens come from the environment (AUTH_TOKEN_CUSTOMER_A/B), else from the repo's
// git-ignored .env. Without them the proxy answers 503 instead of guessing.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const BACKEND = process.env.NEXO_BACKEND_URL || "http://127.0.0.1:8000";
const SESSIONS = { A: "AUTH_TOKEN_CUSTOMER_A", B: "AUTH_TOKEN_CUSTOMER_B" };

function demoTokens() {
  const fromFile = {};
  try {
    for (const line of readFileSync(resolve(import.meta.dirname, "../../.env"), "utf8").split(/\r?\n/)) {
      const i = line.indexOf("=");
      if (i > 0) fromFile[line.slice(0, i).trim()] = line.slice(i + 1).trim();
    }
  } catch {
    /* no .env: environment only */
  }
  const out = {};
  for (const [session, name] of Object.entries(SESSIONS)) {
    const value = process.env[name] || fromFile[name];
    if (value) out[session] = value;
  }
  return out;
}

/** Adds the server-side Authorization header; rejects unknown sessions and any browser-supplied Authorization. */
export function demoAuth(tokens) {
  return (proxyReq, req, res) => {
    proxyReq.removeHeader("authorization");
    proxyReq.removeHeader("cookie");
    const session = String(req.headers["x-demo-session"] || "");
    proxyReq.removeHeader("x-demo-session");
    const token = tokens[session];
    if (!token) {
      res.writeHead(503, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ code: "demo_session_unavailable", detail: "Demo credentials are not configured." }));
      proxyReq.destroy();
      return;
    }
    proxyReq.setHeader("authorization", `Bearer ${token}`);
  };
}

const proxy = () => {
  const tokens = demoTokens();
  return {
    "/api": {
      target: BACKEND,
      changeOrigin: true,
      rewrite: (path) => path.replace(/^\/api/, ""),
      configure: (p) => p.on("proxyReq", demoAuth(tokens)),
    },
  };
};

export default defineConfig({
  plugins: [react()],
  server: { host: "127.0.0.1", port: 5173, strictPort: true, proxy: proxy() },
  preview: { host: "127.0.0.1", port: 4173, strictPort: true, proxy: proxy() },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/test/setup.ts"] },
});
