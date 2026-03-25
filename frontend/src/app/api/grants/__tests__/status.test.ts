import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock mongodb module before importing the route
vi.mock("@/lib/mongodb", () => ({
  getDb: vi.fn(),
}));

// Mock the mongodb ObjectId
vi.mock("mongodb", () => ({
  ObjectId: class MockObjectId {
    id: string;
    constructor(id: string) {
      // Mimic ObjectId validation — only accept 24-char hex strings
      if (!/^[a-f0-9]{24}$/i.test(id)) {
        throw new Error("Invalid ObjectId");
      }
      this.id = id;
    }
  },
}));

import { POST } from "@/app/api/grants/status/route";
import { getDb } from "@/lib/mongodb";

const mockGetDb = getDb as ReturnType<typeof vi.fn>;

function makeRequest(body: unknown): Request {
  return new Request("http://localhost:3000/api/grants/status", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("POST /api/grants/status", () => {
  const mockUpdateOne = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockGetDb.mockResolvedValue({
      collection: () => ({
        updateOne: mockUpdateOne,
      }),
    });
  });

  it("returns 200 on a valid status update", async () => {
    mockUpdateOne.mockResolvedValue({ matchedCount: 1, modifiedCount: 1 });

    const req = makeRequest({
      grant_id: "507f1f77bcf86cd799439011",
      status: "pursue",
    });

    const res = await POST(req);
    const json = await res.json();

    expect(res.status).toBe(200);
    expect(json.ok).toBe(true);
    expect(json.status).toBe("pursue");
  });

  it("returns 400 when grant_id is missing", async () => {
    const req = makeRequest({ status: "pursue" });

    const res = await POST(req);
    const json = await res.json();

    expect(res.status).toBe(400);
    expect(json.error).toContain("grant_id and status are required");
  });

  it("returns 400 when status is missing", async () => {
    const req = makeRequest({ grant_id: "507f1f77bcf86cd799439011" });

    const res = await POST(req);
    const json = await res.json();

    expect(res.status).toBe(400);
    expect(json.error).toContain("grant_id and status are required");
  });

  it("returns 400 for an invalid status string", async () => {
    const req = makeRequest({
      grant_id: "507f1f77bcf86cd799439011",
      status: "invalid_status",
    });

    const res = await POST(req);
    const json = await res.json();

    expect(res.status).toBe(400);
    expect(json.error).toContain("Invalid status");
  });

  it("returns 404 when grant is not found", async () => {
    mockUpdateOne.mockResolvedValue({ matchedCount: 0, modifiedCount: 0 });

    const req = makeRequest({
      grant_id: "507f1f77bcf86cd799439011",
      status: "pursue",
    });

    const res = await POST(req);
    const json = await res.json();

    expect(res.status).toBe(404);
    expect(json.error).toBe("Grant not found");
  });

  it("accepts all valid statuses", async () => {
    mockUpdateOne.mockResolvedValue({ matchedCount: 1, modifiedCount: 1 });

    const validStatuses = [
      "triage",
      "pursue",
      "pursuing",
      "drafting",
      "draft_complete",
      "submitted",
      "won",
      "passed",
      "auto_pass",
      "human_passed",
      "reported",
    ];

    for (const status of validStatuses) {
      const req = makeRequest({
        grant_id: "507f1f77bcf86cd799439011",
        status,
      });
      const res = await POST(req);
      expect(res.status).toBe(200);
    }
  });

  it("sets human_override fields for human_passed status", async () => {
    mockUpdateOne.mockResolvedValue({ matchedCount: 1, modifiedCount: 1 });

    const req = makeRequest({
      grant_id: "507f1f77bcf86cd799439011",
      status: "human_passed",
    });

    await POST(req);

    // Verify updateOne was called with human_override fields
    const updateCall = mockUpdateOne.mock.calls[0];
    const setFields = updateCall[1].$set;
    expect(setFields.status).toBe("human_passed");
    expect(setFields.human_override).toBe(true);
    expect(setFields.override_at).toBeDefined();
  });

  it("handles non-ObjectId grant_id strings gracefully", async () => {
    mockUpdateOne.mockResolvedValue({ matchedCount: 1, modifiedCount: 1 });

    const req = makeRequest({
      grant_id: "some-string-id",
      status: "pursue",
    });

    const res = await POST(req);
    const json = await res.json();

    expect(res.status).toBe(200);
    expect(json.ok).toBe(true);
  });
});
