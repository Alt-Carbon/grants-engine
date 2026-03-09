function getUrl() {
  return (process.env.FASTAPI_URL ?? "").replace(/\/+$/, "");
}
function getSecret() {
  return process.env.INTERNAL_SECRET ?? "";
}

export async function apiPost<T = unknown>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${getUrl()}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-internal-secret": getSecret(),
    },
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
    headers: { "x-internal-secret": getSecret() },
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`FastAPI ${path} failed (${res.status}): ${text}`);
  }
  return res.json() as Promise<T>;
}
