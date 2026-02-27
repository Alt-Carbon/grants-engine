import { MongoClient, Db } from "mongodb";

const DB_NAME = "altcarbon_grants";

declare global {
  // Survive Next.js hot reloads in development
  // eslint-disable-next-line no-var
  var _mongoClient: MongoClient | undefined;
}

let client: MongoClient | null = null;

function getClient(): MongoClient {
  if (client) return client;

  const uri = process.env.MONGODB_URI;
  if (!uri) {
    throw new Error("MONGODB_URI environment variable is not set");
  }

  if (process.env.NODE_ENV === "development") {
    if (!global._mongoClient) {
      global._mongoClient = new MongoClient(uri.trim());
    }
    client = global._mongoClient;
  } else {
    client = new MongoClient(uri.trim());
  }

  return client;
}

export async function getDb(): Promise<Db> {
  const c = getClient();
  await c.connect();
  return c.db(DB_NAME);
}
