/**
 * Deployment mode configuration.
 *
 * "full"   — complete web dashboard (pipeline, dashboard, triage, etc.)
 * "hybrid" — Notion-primary: grants live in Notion, web app = Mission Control + Drafter + ops
 */

export const DEPLOYMENT_MODE =
  (process.env.NEXT_PUBLIC_DEPLOYMENT_MODE as "full" | "hybrid") || "full";

export const isHybridMode = DEPLOYMENT_MODE === "hybrid";

export const LANDING_ROUTE = isHybridMode ? "/monitoring" : "/dashboard";

export const NOTION_WORKSPACE_URL =
  process.env.NEXT_PUBLIC_NOTION_WORKSPACE_URL ||
  "https://www.notion.so/altcarbon/8e9cd5d90239407282336006aa184e48?v=32150d0ec20e810b8108000ccd4064f9";

/** Routes hidden from sidebar in hybrid mode. */
export const HYBRID_HIDDEN_ROUTES = new Set([
  "/dashboard",
  "/pipeline",
  "/triage",
]);
