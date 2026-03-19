import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  formatCurrency,
  formatRelativeTime,
  formatDateShort,
  formatChars,
  getPriority,
  getThemeLabel,
  THEME_CONFIG,
} from "@/lib/utils";

// ── formatCurrency ──────────────────────────────────────────────────────────

describe("formatCurrency", () => {
  it("returns null for null/undefined", () => {
    expect(formatCurrency(null)).toBeNull();
    expect(formatCurrency(undefined)).toBeNull();
  });

  it("returns null for 0", () => {
    // 0 is falsy, so the function returns null
    expect(formatCurrency(0)).toBeNull();
  });

  it("formats small amounts below 1K", () => {
    expect(formatCurrency(500)).toBe("$500");
  });

  it("formats 1000 as $1K", () => {
    expect(formatCurrency(1000)).toBe("$1K");
  });

  it("formats 50000 as $50K", () => {
    expect(formatCurrency(50000)).toBe("$50K");
  });

  it("formats 1000000 as $1.0M", () => {
    expect(formatCurrency(1_000_000)).toBe("$1.0M");
  });

  it("formats 1500000 as $1.5M", () => {
    expect(formatCurrency(1_500_000)).toBe("$1.5M");
  });
});

// ── formatRelativeTime ──────────────────────────────────────────────────────

describe("formatRelativeTime", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-03-19T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns empty string for null", () => {
    expect(formatRelativeTime(null)).toBe("");
  });

  it("returns empty string for undefined", () => {
    expect(formatRelativeTime(undefined)).toBe("");
  });

  it("returns empty string for empty string", () => {
    expect(formatRelativeTime("")).toBe("");
  });

  it('returns "just now" for a time less than 1 minute ago', () => {
    const thirtySecsAgo = new Date("2026-03-19T11:59:45Z").toISOString();
    expect(formatRelativeTime(thirtySecsAgo)).toBe("just now");
  });

  it("returns minutes ago for times within the hour", () => {
    const fiveMinsAgo = new Date("2026-03-19T11:55:00Z").toISOString();
    expect(formatRelativeTime(fiveMinsAgo)).toBe("5m ago");
  });

  it("returns hours ago for times within the day", () => {
    const threeHoursAgo = new Date("2026-03-19T09:00:00Z").toISOString();
    expect(formatRelativeTime(threeHoursAgo)).toBe("3h ago");
  });

  it("returns days ago for times beyond 24 hours", () => {
    const twoDaysAgo = new Date("2026-03-17T12:00:00Z").toISOString();
    expect(formatRelativeTime(twoDaysAgo)).toBe("2d ago");
  });
});

// ── formatDateShort ─────────────────────────────────────────────────────────

describe("formatDateShort", () => {
  it('returns "--" for null', () => {
    expect(formatDateShort(null)).toBe("--");
  });

  it('returns "--" for undefined', () => {
    expect(formatDateShort(undefined)).toBe("--");
  });

  it('returns "--" for empty string', () => {
    expect(formatDateShort("")).toBe("--");
  });

  it("formats a valid ISO date as short date", () => {
    const result = formatDateShort("2026-03-19T12:00:00Z");
    // The exact format depends on locale, but should contain "Mar" and "19"
    expect(result).toContain("Mar");
    expect(result).toContain("19");
  });
});

// ── formatChars ─────────────────────────────────────────────────────────────

describe("formatChars", () => {
  it("returns string of number for values under 1000", () => {
    expect(formatChars(0)).toBe("0");
    expect(formatChars(500)).toBe("500");
    expect(formatChars(999)).toBe("999");
  });

  it("formats 1000 as 1.0k", () => {
    expect(formatChars(1000)).toBe("1.0k");
  });

  it("formats 5000 as 5.0k", () => {
    expect(formatChars(5000)).toBe("5.0k");
  });
});

// ── getPriority ─────────────────────────────────────────────────────────────

describe("getPriority", () => {
  it('returns Low for score below 5.0', () => {
    const result = getPriority(3.0);
    expect(result.label).toBe("Low");
    expect(result.className).toContain("red");
  });

  it('returns Medium for score exactly 5.0', () => {
    const result = getPriority(5.0);
    expect(result.label).toBe("Medium");
    expect(result.className).toContain("amber");
  });

  it('returns Medium for score between 5.0 and 6.5', () => {
    const result = getPriority(6.0);
    expect(result.label).toBe("Medium");
    expect(result.className).toContain("amber");
  });

  it('returns High for score exactly 6.5', () => {
    const result = getPriority(6.5);
    expect(result.label).toBe("High");
    expect(result.className).toContain("green");
  });

  it('returns High for score above 6.5', () => {
    const result = getPriority(9.0);
    expect(result.label).toBe("High");
    expect(result.className).toContain("green");
  });
});

// ── getThemeLabel ───────────────────────────────────────────────────────────

describe("getThemeLabel", () => {
  it("returns the correct config for a known theme key", () => {
    const result = getThemeLabel("climatetech");
    expect(result.label).toBe("Climate Tech");
    expect(result.bg).toBe("#ccfbf1");
    expect(result.color).toBe("#115e59");
  });

  it("returns all known themes correctly", () => {
    for (const [key, expected] of Object.entries(THEME_CONFIG)) {
      const result = getThemeLabel(key);
      expect(result).toEqual(expected);
    }
  });

  it("returns fallback with the key as label for unknown theme", () => {
    const result = getThemeLabel("unknown_theme");
    expect(result.label).toBe("unknown_theme");
    expect(result.bg).toBe("#f3f4f6");
    expect(result.color).toBe("#4b5563");
  });
});
