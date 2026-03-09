const FASTAPI_URL = process.env.FASTAPI_URL!.replace(/\/+$/, "");
const INTERNAL_SECRET = process.env.INTERNAL_SECRET!;

export async function apiPost<T = unknown>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${FASTAPI_URL}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-internal-secret": INTERNAL_SECRET,
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
  const res = await fetch(`${FASTAPI_URL}${path}`, {
    headers: { "x-internal-secret": INTERNAL_SECRET },
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`FastAPI ${path} failed (${res.status}): ${text}`);
  }
  return res.json() as Promise<T>;
}
