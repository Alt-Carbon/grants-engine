import { auth } from "@/lib/auth";

function getUrl() {
  return (process.env.FASTAPI_URL ?? "").replace(/\/+$/, "");
}
function getSecret() {
  return process.env.INTERNAL_SECRET ?? "";
}

/**
 * Get the current user's email from the NextAuth session.
 * Works in Server Components and API routes.
 */
async function getUserEmail(): Promise<string> {
  try {
    const session = await auth();
    return session?.user?.email || "";
  } catch {
    return "";
  }
}

/**
 * Build headers for backend requests — includes auth secret + user identity.
 */
async function getHeaders(contentType = false): Promise<Record<string, string>> {
  const headers: Record<string, string> = {
    "x-internal-secret": getSecret(),
    "x-user-email": await getUserEmail(),
  };
  if (contentType) {
    headers["Content-Type"] = "application/json";
  }
  return headers;
}

export async function apiPost<T = unknown>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${getUrl()}${path}`, {
    method: "POST",
    headers: await getHeaders(true),
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`FastAPI ${path} failed (${res.status}): ${text}`);
  }
  return res.json() as Promise<T>;
}

export async function apiGet<T = unknown>(path: string): Promise<T> {
  const res = await fetch(`${getUrl()}${path}`, {
    headers: await getHeaders(),
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`FastAPI ${path} failed (${res.status}): ${text}`);
  }
  return res.json() as Promise<T>;
}

/**
 * Helper for API proxy routes — extracts user email from the incoming request's
 * NextAuth session and returns headers to forward to the backend.
 */
export async function proxyHeaders(contentType = true): Promise<Record<string, string>> {
  return getHeaders(contentType);
}
