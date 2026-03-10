/**
 * Generate a comprehensive Grant Intelligence Brief as Markdown,
 * then download as .md or .pdf (via browser print).
 */

/* eslint-disable @typescript-eslint/no-explicit-any */

// ── Markdown builder ─────────────────────────────────────────────────────────

function buildMarkdown(data: any, grantTitle?: string): string {
  const ov = data.overview || {};
  const elig = data.eligibility || {};
  const scoring = data.scoring || {};
  const kd = data.key_dates || {};
  const reqs = data.requirements || {};
  const ft = data.funding_terms || {};
  const strat = data.strategy || {};
  const pw = data.past_winners || {};
  const contact = data.contact || {};
  const resources = data.resources || {};

  const lines: string[] = [];
  const hr = () => lines.push("", "---", "");
  const h1 = (t: string) => lines.push(`# ${t}`, "");
  const h2 = (t: string) => lines.push(`## ${t}`, "");
  const h3 = (t: string) => lines.push(`### ${t}`, "");
  const p = (t: string) => { if (t) lines.push(t, ""); };
  const kv = (k: string, v: string) => lines.push(`**${k}:** ${v}  `);
  const bull = (t: string) => lines.push(`- ${t}`);

  // ── Title ──
  h1("GRANT INTELLIGENCE BRIEF");
  lines.push(`**${ov.grant_name || grantTitle || "Unknown Grant"}**  `);
  lines.push(`Funder: ${ov.funder || "Unknown"}  `);
  lines.push(`*Generated ${new Date().toLocaleDateString()} by AltCarbon Grants Engine*`, "");
  hr();

  // ── 1. Overview ──
  h2("1. Grant Overview");
  if (ov.grant_type) kv("Type", ov.grant_type);
  if (ov.amount) kv("Funding", ov.amount);
  if (ov.max_funding_usd) kv("Max (USD)", `$${Number(ov.max_funding_usd).toLocaleString()}`);
  if (ov.deadline) kv("Deadline", ov.deadline);
  if (ov.days_to_deadline != null) {
    const urgent = ov.deadline_urgent ? " **(URGENT)**" : "";
    kv("Days remaining", `${ov.days_to_deadline}${urgent}`);
  }
  if (ov.geography) kv("Geography", ov.geography);
  if (ov.url) kv("Grant URL", ov.url);
  if (ov.application_url) kv("Apply URL", ov.application_url);
  if ((ov.themes_detected || []).length > 0) kv("Themes", ov.themes_detected.join(", "));
  lines.push("");
  if (ov.about_opportunity) {
    h3("About the opportunity");
    p(ov.about_opportunity);
  }

  // ── 2. Eligibility ──
  hr();
  h2("2. Eligibility");
  if (elig.summary) p(elig.summary);
  if (elig.details) {
    h3("Detailed requirements");
    p(elig.details);
  }
  if ((elig.checklist || []).length > 0) {
    h3("AltCarbon eligibility checklist");
    const icon: Record<string, string> = { met: "✅", likely_met: "🟡", verify: "🔍", not_met: "❌" };
    for (const item of elig.checklist) {
      const s = item.altcarbon_status || "verify";
      const note = item.note ? ` — ${item.note}` : "";
      bull(`${icon[s] || s} **${item.criterion || ""}**${note}`);
    }
    lines.push("");
  }

  // ── 3. AI Scoring ──
  hr();
  h2("3. AI Scoring & Analysis");
  if (scoring.weighted_total != null) kv("Overall score", `${scoring.weighted_total.toFixed(1)} / 10`);
  if (scoring.recommended_action) kv("Recommendation", `**${scoring.recommended_action.toUpperCase()}**`);
  lines.push("");

  const scores = scoring.scores || {};
  if (Object.keys(scores).length > 0) {
    h3("Score breakdown");
    lines.push("| Dimension | Score |");
    lines.push("|-----------|-------|");
    for (const [k, v] of Object.entries(scores)) {
      const name = k.replace(/_/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase());
      lines.push(`| ${name} | ${v} / 10 |`);
    }
    lines.push("");
  }

  if (scoring.rationale) { h3("Rationale"); p(scoring.rationale); }
  if (scoring.reasoning) { h3("Strategic reasoning"); p(scoring.reasoning); }
  if ((scoring.evidence_found || []).length > 0) {
    h3("Evidence found (AltCarbon fit)");
    for (const e of scoring.evidence_found) bull(e);
    lines.push("");
  }
  if ((scoring.evidence_gaps || []).length > 0) {
    h3("Evidence gaps");
    for (const e of scoring.evidence_gaps) bull(e);
    lines.push("");
  }
  if ((scoring.red_flags || []).length > 0) {
    h3("Red flags");
    for (const r of scoring.red_flags) bull(`⚠️ ${r}`);
    lines.push("");
  }

  // ── 4. Key Dates ──
  if (Object.values(kd).some(Boolean)) {
    hr();
    h2("4. Key Dates & Timelines");
    for (const [k, v] of Object.entries(kd)) {
      if (v) kv(k.replace(/_/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase()), String(v));
    }
    lines.push("");
  }

  // ── 5. Application Requirements ──
  hr();
  h2("5. Application Requirements");
  if ((reqs.documents_needed || []).length > 0) {
    h3("Documents needed");
    for (const d of reqs.documents_needed) bull(d);
    lines.push("");
  }
  if ((reqs.attachments || []).length > 0) {
    h3("Attachments");
    for (const a of reqs.attachments) bull(a);
    lines.push("");
  }
  if (reqs.submission_format) kv("Submission format", reqs.submission_format);
  if (reqs.submission_portal) kv("Submission portal", reqs.submission_portal);
  if (reqs.word_page_limits) kv("Word/page limits", reqs.word_page_limits);
  if (reqs.language) kv("Language", reqs.language);
  if (reqs.co_funding_required) kv("Co-funding required", reqs.co_funding_required);
  lines.push("");
  if (data.application_process) { h3("Application process"); p(data.application_process); }

  // ── 6. Evaluation Criteria ──
  if ((data.evaluation_criteria || []).length > 0) {
    hr();
    h2("6. Evaluation Criteria");
    for (const ec of data.evaluation_criteria) {
      const w = ec.weight ? ` (${ec.weight})` : "";
      const desc = ec.what_they_look_for ? `: ${ec.what_they_look_for}` : "";
      bull(`**${ec.criterion || ""}${w}**${desc}`);
    }
    lines.push("");
  }

  // ── 7. Application Sections ──
  if ((data.application_sections || []).length > 0) {
    hr();
    h2("7. Expected Application Structure");
    for (const sec of data.application_sections) {
      const lim = sec.limit ? ` [${sec.limit}]` : "";
      const desc = sec.what_to_cover ? `: ${sec.what_to_cover}` : "";
      bull(`**${sec.section || ""}${lim}**${desc}`);
    }
    lines.push("");
  }

  // ── 8. Funding Terms ──
  if (Object.values(ft).some((v: any) => (Array.isArray(v) ? v.length > 0 : !!v))) {
    hr();
    h2("8. Funding Terms");
    if (ft.disbursement_schedule) kv("Disbursement", ft.disbursement_schedule);
    if (ft.reporting_requirements) kv("Reporting", ft.reporting_requirements);
    if (ft.ip_ownership) kv("IP ownership", ft.ip_ownership);
    if (ft.audit_requirement) kv("Audit", ft.audit_requirement);
    lines.push("");
    if ((ft.permitted_costs || []).length > 0) {
      h3("Permitted costs");
      for (const c of ft.permitted_costs) bull(`✅ ${c}`);
      lines.push("");
    }
    if ((ft.excluded_costs || []).length > 0) {
      h3("Excluded costs");
      for (const c of ft.excluded_costs) bull(`❌ ${c}`);
      lines.push("");
    }
  }

  // ── 9. Strategy ──
  hr();
  h2("9. Strategic Analysis");
  if (strat.strategic_angle) { h3("Recommended angle for AltCarbon"); p(strat.strategic_angle); }
  if (strat.altcarbon_fit_verdict) kv("AltCarbon fit verdict", `**${strat.altcarbon_fit_verdict.toUpperCase()}**`);
  if (strat.strategic_note) { h3("Strategic note"); p(strat.strategic_note); }
  if (strat.funder_context) { h3("Funder background"); p(strat.funder_context); }
  if (strat.funder_pattern) { h3("Funder pattern (who gets funded)"); p(strat.funder_pattern); }
  if ((strat.application_tips || []).length > 0) {
    h3("Application tips");
    for (const tip of strat.application_tips) bull(`💡 ${tip}`);
    lines.push("");
  }

  // ── 10. Past Winners ──
  if ((pw.winners || []).length > 0) {
    hr();
    h2("10. Past Winners Analysis");
    if (pw.total_winners_found) kv("Total winners found", String(pw.total_winners_found));
    if (pw.altcarbon_comparable_count) kv("AltCarbon-comparable", String(pw.altcarbon_comparable_count));
    lines.push("");
    h3("Winners");
    for (const w of pw.winners) {
      const yr = w.year ? ` (${w.year})` : "";
      const country = w.country ? ` — ${w.country}` : "";
      const sim = w.altcarbon_similarity ? ` [${w.altcarbon_similarity} similarity]` : "";
      const brief = w.project_brief ? `: ${w.project_brief}` : "";
      bull(`**${w.name || "?"}${yr}${country}${sim}**${brief}`);
    }
    lines.push("");
  }

  // ── 11. Contact ──
  if (Object.values(contact).some((v: any) => (Array.isArray(v) ? v.length > 0 : !!v))) {
    hr();
    h2("11. Contact Information");
    if (contact.name) kv("Name", contact.name);
    if (contact.email) kv("Email", contact.email);
    for (const em of contact.emails_all || []) {
      if (em !== contact.email) kv("Also", em);
    }
    if (contact.phone) kv("Phone", contact.phone);
    if (contact.office) kv("Office", contact.office);
    lines.push("");
  }

  // ── 12. Resources ──
  if (Object.values(resources).some((v: any) => (Array.isArray(v) ? v.length > 0 : !!v))) {
    hr();
    h2("12. Resources & Links");
    for (const url of resources.brochure_urls || []) bull(`Brochure/guideline: ${url}`);
    for (const url of resources.info_session_urls || []) bull(`Info session: ${url}`);
    for (const url of resources.template_urls || []) bull(`Template: ${url}`);
    if (resources.faq_url) kv("FAQ", resources.faq_url);
    if (resources.guidelines_url) kv("Guidelines", resources.guidelines_url);
    lines.push("");
  }

  // ── Similar grants ──
  if ((data.similar_grants || []).length > 0) {
    h3("Similar grants / previous rounds");
    for (const sg of data.similar_grants) bull(sg);
    lines.push("");
  }

  return lines.join("\n");
}

// ── Markdown → styled HTML (for PDF) ─────────────────────────────────────────

function markdownToHtml(md: string): string {
  let html = md
    // Horizontal rules
    .replace(/^---$/gm, '<hr/>')
    // Tables
    .replace(/^\|(.+)\|$/gm, (match) => {
      const cells = match.split("|").filter(Boolean).map((c) => c.trim());
      if (cells.every((c) => /^[-:]+$/.test(c))) return "<!--sep-->";
      return `<tr>${cells.map((c) => `<td>${inlineFormat(c)}</td>`).join("")}</tr>`;
    })
    // Headers
    .replace(/^### (.+)$/gm, "<h3>$1</h3>")
    .replace(/^## (.+)$/gm, "<h2>$1</h2>")
    .replace(/^# (.+)$/gm, "<h1>$1</h1>")
    // Bullet items
    .replace(/^- (.+)$/gm, (_, t) => `<li>${inlineFormat(t)}</li>`)
    // Paragraphs (non-empty lines that aren't already tags)
    .replace(/^(?!<[a-z/!])(.+)$/gm, (_, t) => `<p>${inlineFormat(t)}</p>`);

  // Wrap consecutive <li> in <ul>
  html = html.replace(/(<li>[\s\S]*?<\/li>)(\s*(?:<li>))/g, "$1$2");
  html = html.replace(/((?:<li>[\s\S]*?<\/li>\s*)+)/g, "<ul>$1</ul>");

  // Wrap consecutive <tr> in <table>
  html = html.replace(/((?:<tr>[\s\S]*?<\/tr>\s*)+)/g, "<table>$1</table>");
  html = html.replace(/<!--sep-->\s*/g, "");

  return html;
}

function inlineFormat(text: string): string {
  return text
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/  $/, "<br/>");
}

// ── Download as .md ──────────────────────────────────────────────────────────

export async function generateIntelBriefMd(data: any, grantTitle?: string): Promise<void> {
  const md = buildMarkdown(data, grantTitle);
  const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
  const filename = `${(data.overview?.grant_name || grantTitle || "Grant").replace(/[^a-zA-Z0-9]+/g, "_")}_Intelligence_Brief.md`;

  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ── Download as .pdf (browser print) ─────────────────────────────────────────

export async function generateIntelBriefPdf(data: any, grantTitle?: string): Promise<void> {
  const md = buildMarkdown(data, grantTitle);
  const html = markdownToHtml(md);
  const title = data.overview?.grant_name || grantTitle || "Intelligence Brief";

  const styledHtml = `<!DOCTYPE html>
<html><head>
<meta charset="utf-8"/>
<title>${title} — Intelligence Brief</title>
<style>
  @page { margin: 1in 0.8in; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 11pt; color: #1a1a1a; line-height: 1.6; max-width: 100%; }
  h1 { font-size: 18pt; color: #5B21B6; border-bottom: 2px solid #5B21B6; padding-bottom: 6px; margin-top: 24px; }
  h2 { font-size: 14pt; color: #1e3a5f; margin-top: 20px; }
  h3 { font-size: 12pt; color: #374151; margin-top: 14px; }
  hr { border: none; border-top: 1px solid #d1d5db; margin: 16px 0; }
  p { margin: 4px 0; }
  ul { margin: 6px 0; padding-left: 20px; }
  li { margin: 3px 0; }
  table { width: 100%; border-collapse: collapse; margin: 8px 0; }
  td { border: 1px solid #d1d5db; padding: 6px 10px; font-size: 10pt; }
  tr:first-child td { background: #f3f4f6; font-weight: 600; }
  strong { font-weight: 600; }
  em { font-style: italic; color: #6b7280; }
</style>
</head><body>${html}</body></html>`;

  const printWindow = window.open("", "_blank");
  if (!printWindow) {
    // Fallback: download as HTML if popup blocked
    const blob = new Blob([styledHtml], { type: "text/html;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(title).replace(/[^a-zA-Z0-9]+/g, "_")}_Intelligence_Brief.html`;
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

// ── Build brief data from raw grant document (skip backend endpoint) ─────────

export function grantToBriefData(grant: any): any {
  const da = grant.deep_analysis || {};
  const contact = da.contact || {};
  const resources = da.resources || {};
  const ft = da.funding_terms || {};
  const kd = da.key_dates || {};
  const reqs = da.requirements || {};

  return {
    overview: {
      grant_name: grant.grant_name || grant.title || "",
      funder: grant.funder || "",
      grant_type: grant.grant_type || "",
      amount: grant.amount || "",
      max_funding_usd: grant.max_funding_usd,
      currency: grant.currency || "",
      deadline: String(grant.deadline || ""),
      days_to_deadline: grant.days_to_deadline,
      deadline_urgent: grant.deadline_urgent || false,
      geography: grant.geography || "",
      url: grant.url || "",
      application_url: grant.application_url || "",
      about_opportunity: grant.about_opportunity || da.opportunity_summary || "",
      themes_detected: grant.themes_detected || [],
    },
    eligibility: {
      summary: grant.eligibility || "",
      details: grant.eligibility_details || "",
      checklist: da.eligibility_checklist || [],
    },
    scoring: {
      weighted_total: grant.weighted_total,
      scores: grant.scores || {},
      recommended_action: grant.recommended_action || "",
      rationale: grant.rationale || "",
      reasoning: grant.reasoning || "",
      evidence_found: grant.evidence_found || [],
      evidence_gaps: grant.evidence_gaps || [],
      red_flags: [...(grant.red_flags || []), ...(da.red_flags || [])],
    },
    key_dates: kd,
    requirements: {
      documents_needed: reqs.documents_needed || [],
      attachments: reqs.attachments || [],
      submission_format: reqs.submission_format || "",
      submission_portal: reqs.submission_portal || "",
      word_page_limits: reqs.word_page_limits || "",
      language: reqs.language || "",
      co_funding_required: reqs.co_funding_required || "",
    },
    evaluation_criteria: da.evaluation_criteria || [],
    application_sections: da.application_sections || [],
    application_process: grant.application_process || da.application_process_detailed || "",
    funding_terms: {
      disbursement_schedule: ft.disbursement_schedule || "",
      reporting_requirements: ft.reporting_requirements || "",
      ip_ownership: ft.ip_ownership || "",
      permitted_costs: ft.permitted_costs || [],
      excluded_costs: ft.excluded_costs || [],
      audit_requirement: ft.audit_requirement || "",
    },
    strategy: {
      strategic_angle: da.strategic_angle || "",
      application_tips: da.application_tips || [],
      funder_context: grant.funder_context || "",
      funder_pattern: da.funder_pattern || "",
      altcarbon_fit_verdict: da.altcarbon_fit_verdict || "",
      strategic_note: da.strategic_note || "",
    },
    past_winners: {
      winners: da.winners || [],
      total_winners_found: da.total_winners_found || 0,
      altcarbon_comparable_count: da.altcarbon_comparable_count || 0,
    },
    contact: {
      name: contact.name || "",
      email: contact.email || "",
      emails_all: contact.emails_all || [],
      phone: contact.phone || "",
      office: contact.office || "",
    },
    resources: {
      brochure_urls: resources.brochure_urls || [],
      info_session_urls: resources.info_session_urls || [],
      template_urls: resources.template_urls || [],
      faq_url: resources.faq_url || "",
      guidelines_url: resources.guidelines_url || "",
    },
    similar_grants: da.similar_grants || [],
  };
}
