export function requestHoldReason(existingReason = ""): string | null {
  if (typeof window === "undefined") return existingReason || null;

  const reason = window.prompt(
    "Why is this grant on hold?",
    existingReason
  );

  if (reason === null) return null;

  const trimmed = reason.trim();
  return trimmed ? trimmed : null;
}
