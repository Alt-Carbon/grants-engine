import { MongoClient, Db } from "mongodb";

const uri = process.env.MONGODB_URI!;
const DB_NAME = "altcarbon_grants";

if (!uri) {
  throw new Error("MONGODB_URI environment variable is not set");
}

declare global {
  // Survive Next.js hot reloads in development
  // eslint-disable-next-line no-var
  var _mongoClient: MongoClient | undefined;
}

let client: MongoClient;

if (process.env.NODE_ENV === "development") {
  if (!global._mongoClient) {
    global._mongoClient = new MongoClient(uri);
  }
  client = global._mongoClient;
} else {
  client = new MongoClient(uri);
}

export async function getDb(): Promise<Db> {
  await client.connect();
  return client.db(DB_NAME);
}
