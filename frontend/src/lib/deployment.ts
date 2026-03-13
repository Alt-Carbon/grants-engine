/**
 * Deployment mode configuration.
 *
 * "hybrid" — Notion-primary: grants live in Notion, web app = Mission Control + Drafter + ops
 * "full"   — legacy mode (pipeline pages removed — always hybrid now)
 */

export const DEPLOYMENT_MODE =
  (process.env.NEXT_PUBLIC_DEPLOYMENT_MODE as "full" | "hybrid") || "hybrid";

export const isHybridMode = true; // Always hybrid — Notion is the UI for grants

export const LANDING_ROUTE = "/monitoring";

export const NOTION_WORKSPACE_URL =
  process.env.NEXT_PUBLIC_NOTION_WORKSPACE_URL ||
  "https://www.notion.so/altcarbon/8e9cd5d90239407282336006aa184e48?v=32150d0ec20e810b8108000ccd4064f9";

/** Routes hidden from sidebar in hybrid mode. */
export const HYBRID_HIDDEN_ROUTES = new Set([
  "/dashboard",
  "/pipeline",
  "/triage",
  "/toolkit",
  "/audit",
  "/config",
]);
