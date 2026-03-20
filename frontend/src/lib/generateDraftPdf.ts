/**
 * Generate a polished PDF of a grant draft for upload to funder portals.
 * Uses the same browser-print approach as generateIntelBrief.ts.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */

// ── Types ───────────────────────────────────────────────────────────────────

interface DraftContent {
  grant_id: string;
  grant_title: string;
  funder: string;
  deadline: string;
  max_funding: string | number;
  version: number;
  sections: Record<
    string,
    {
      content: string;
      word_count: number;
      word_limit: number;
      within_limit: boolean;
    }
  >;
  evidence_gaps: string[];
  total_word_count: number;
  created_at: string;
}

// ── Markdown → HTML (minimal) ────────────────────────────────────────────────

function markdownToHtml(md: string): string {
  return md
    .replace(/^### (.+)$/gm, "<h3>$1</h3>")
    .replace(/^## (.+)$/gm, "<h2>$1</h2>")
    .replace(/^# (.+)$/gm, "<h1>$1</h1>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/^- (.+)$/gm, "<li>$1</li>")
    .replace(/(<li>.*<\/li>\n?)+/g, (m) => `<ul>${m}</ul>`)
    .replace(/^---$/gm, "<hr/>")
    .replace(/\n{2,}/g, "</p><p>")
    .replace(/\n/g, "<br/>")
    .replace(/^/, "<p>")
    .replace(/$/, "</p>");
}

// ── Build clean Markdown (submission-ready, no internal markers) ────────────

function buildSubmissionMarkdown(data: DraftContent): string {
  const lines: string[] = [];

  lines.push(`# ${data.grant_title}`);
  lines.push("");
  lines.push(`**Submitted to:** ${data.funder}`);
  if (data.deadline) lines.push(`  \n**Deadline:** ${data.deadline}`);
  if (data.max_funding) {
    const funding =
      typeof data.max_funding === "number"
        ? `$${data.max_funding.toLocaleString()}`
        : data.max_funding;
    lines.push(`  \n**Funding:** ${funding}`);
  }
  lines.push("");
  lines.push("---");
  lines.push("");

  // Sections in order
  for (const [name, sec] of Object.entries(data.sections)) {
    lines.push(`## ${name}`);
    lines.push("");
    // Clean content: strip [EVIDENCE NEEDED: ...] markers for submission PDF
    const cleaned = sec.content.replace(
      /\[EVIDENCE NEEDED:[^\]]*\]/gi,
      ""
    );
    lines.push(cleaned.trim());
    lines.push("");
    lines.push("---");
    lines.push("");
  }

  return lines.join("\n");
}

// ── Build internal review Markdown (with word counts, gaps) ─────────────────

function buildReviewMarkdown(data: DraftContent): string {
  const lines: string[] = [];

  lines.push(`# ${data.grant_title} — Draft Review Copy`);
  lines.push("");
  lines.push(`**Funder:** ${data.funder}`);
  if (data.deadline) lines.push(`  \n**Deadline:** ${data.deadline}`);
  lines.push(`  \n**Draft Version:** v${data.version}`);
  lines.push(
    `  \n**Generated:** ${new Date().toLocaleDateString()} by AltCarbon Grants Engine`
  );
  lines.push(`  \n**Total Word Count:** ${data.total_word_count}`);
  lines.push("");
  lines.push("---");
  lines.push("");

  for (const [name, sec] of Object.entries(data.sections)) {
    const status = sec.within_limit
      ? `${sec.word_count}/${sec.word_limit} words`
      : `${sec.word_count}/${sec.word_limit} words (OVER LIMIT)`;
    lines.push(`## ${name}`);
    lines.push(`*${status}*`);
    lines.push("");
    lines.push(sec.content);
    lines.push("");
    lines.push("---");
    lines.push("");
  }

  if (data.evidence_gaps.length > 0) {
    lines.push("## Evidence Gaps (Fill Before Submission)");
    lines.push("");
    for (const gap of data.evidence_gaps) {
      lines.push(`- ${gap}`);
    }
    lines.push("");
  }

  return lines.join("\n");
}

// ── Download as Markdown ────────────────────────────────────────────────────

export function downloadDraftMarkdown(
  data: DraftContent,
  mode: "submission" | "review" = "submission"
): void {
  const md =
    mode === "submission"
      ? buildSubmissionMarkdown(data)
      : buildReviewMarkdown(data);
  const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  const suffix = mode === "submission" ? "" : "_review";
  a.download = `${data.grant_title.replace(/[^a-zA-Z0-9]+/g, "_")}${suffix}_v${data.version}.md`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ── Download as PDF (browser print) ─────────────────────────────────────────

export async function generateDraftPdf(
  data: DraftContent,
  mode: "submission" | "review" = "submission"
): Promise<void> {
  const md =
    mode === "submission"
      ? buildSubmissionMarkdown(data)
      : buildReviewMarkdown(data);
  const html = markdownToHtml(md);
  const title = data.grant_title || "Grant Draft";

  const styledHtml = `<!DOCTYPE html>
<html><head>
<meta charset="utf-8"/>
<title>${title} — Grant Application</title>
<style>
  @page { margin: 1in 0.8in; }
  body {
    font-family: "Times New Roman", Georgia, serif;
    font-size: 11pt;
    color: #1a1a1a;
    line-height: 1.65;
    max-width: 100%;
  }
  h1 {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 18pt;
    color: #1e3a5f;
    border-bottom: 2px solid #1e3a5f;
    padding-bottom: 6px;
    margin-top: 24px;
  }
  h2 {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 13pt;
    color: #1e3a5f;
    margin-top: 22px;
    margin-bottom: 8px;
  }
  h3 {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 11pt;
    color: #374151;
    margin-top: 14px;
  }
  hr { border: none; border-top: 1px solid #d1d5db; margin: 16px 0; }
  p { margin: 6px 0; text-align: justify; }
  ul { margin: 6px 0; padding-left: 20px; }
  li { margin: 3px 0; }
  strong { font-weight: 700; }
  em { font-style: italic; color: #6b7280; font-size: 10pt; }
  @media print {
    body { font-size: 11pt; }
    h1 { page-break-before: auto; }
    h2 { page-break-after: avoid; }
  }
</style>
</head><body>${html}</body></html>`;

  const printWindow = window.open("", "_blank");
  if (!printWindow) {
    // Fallback: download as HTML if popup blocked
    const blob = new Blob([styledHtml], { type: "text/html;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${title.replace(/[^a-zA-Z0-9]+/g, "_")}_v${data.version}.html`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    return;
  }

  printWindow.document.write(styledHtml);
  printWindow.document.close();
  printWindow.onload = () => {
    printWindow.print();
  };
}

// ── Fetch draft content from API ────────────────────────────────────────────

export async function fetchDraftContent(
  grantId: string
): Promise<DraftContent | null> {
  try {
    const res = await fetch(`/api/draft/${grantId}/content`);
    if (!res.ok) return null;
    return (await res.json()) as DraftContent;
  } catch {
    return null;
  }
}
