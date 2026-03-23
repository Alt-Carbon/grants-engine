import { MongoClient, Db } from "mongodb";

const DB_NAME = "altcarbon_grants";

declare global {
  // Survive Next.js hot reloads in development
  // eslint-disable-next-line no-var
  var _mongoClient: MongoClient | undefined;
}

let client: MongoClient | null = null;

const MONGO_OPTIONS = {
  maxPoolSize: 10,
  serverSelectionTimeoutMS: 10_000,
  socketTimeoutMS: 45_000,
};

function getClient(): MongoClient {
  const uri = process.env.MONGODB_URI;
  if (!uri) {
    throw new Error("MONGODB_URI environment variable is not set");
  }

  if (process.env.NODE_ENV === "development") {
    if (!global._mongoClient) {
      global._mongoClient = new MongoClient(uri.trim(), MONGO_OPTIONS);
    }
    client = global._mongoClient;
  } else {
    if (!client) {
      client = new MongoClient(uri.trim(), MONGO_OPTIONS);
    }
  }

  return client;
}

export async function getDb(): Promise<Db> {
  const c = getClient();
  try {
    await c.connect();
  } catch {
    // Stale connection — reset and retry once
    client = null;
    global._mongoClient = undefined;
    const fresh = getClient();
    await fresh.connect();
    return fresh.db(DB_NAME);
  }
  return c.db(DB_NAME);
}
