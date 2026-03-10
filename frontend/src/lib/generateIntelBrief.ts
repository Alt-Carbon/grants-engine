/**
 * Generate a comprehensive Grant Intelligence Brief as .docx
 *
 * Uses the `docx` library for client-side document generation.
 */
import {
  Document,
  Paragraph,
  TextRun,
  HeadingLevel,
  AlignmentType,
  BorderStyle,
  Table,
  TableRow,
  TableCell,
  WidthType,
  ShadingType,
  Packer,
  type ISectionOptions,
} from "docx";
import { saveAs } from "file-saver";

/* eslint-disable @typescript-eslint/no-explicit-any */

// ── Helpers ──────────────────────────────────────────────────────────────────

function heading(text: string, level: (typeof HeadingLevel)[keyof typeof HeadingLevel] = HeadingLevel.HEADING_1): Paragraph {
  return new Paragraph({ heading: level, spacing: { before: 300, after: 100 }, children: [new TextRun({ text, bold: true })] });
}

function subheading(text: string): Paragraph {
  return heading(text, HeadingLevel.HEADING_2);
}

function label(text: string): Paragraph {
  return new Paragraph({
    spacing: { before: 200, after: 40 },
    children: [new TextRun({ text, bold: true, size: 20, color: "444444" })],
  });
}

function body(text: string): Paragraph {
  if (!text) return new Paragraph({ children: [] });
  return new Paragraph({
    spacing: { after: 80 },
    children: [new TextRun({ text, size: 20 })],
  });
}

function bullet(text: string, color?: string): Paragraph {
  return new Paragraph({
    bullet: { level: 0 },
    spacing: { after: 40 },
    children: [new TextRun({ text, size: 20, color: color || "000000" })],
  });
}

function kvRow(key: string, value: string): Paragraph {
  return new Paragraph({
    spacing: { after: 40 },
    children: [
      new TextRun({ text: `${key}: `, bold: true, size: 20 }),
      new TextRun({ text: value, size: 20 }),
    ],
  });
}

function divider(): Paragraph {
  return new Paragraph({
    spacing: { before: 100, after: 100 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" } },
    children: [],
  });
}

function scoreCell(text: string, shade?: string): TableCell {
  return new TableCell({
    width: { size: 50, type: WidthType.PERCENTAGE },
    shading: shade ? { type: ShadingType.SOLID, color: shade } : undefined,
    children: [new Paragraph({ children: [new TextRun({ text, size: 18 })] })],
  });
}

// ── Main generator ──────────────────────────────────────────────────────────

export async function generateIntelBrief(data: any, grantTitle?: string): Promise<void> {
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

  const children: Paragraph[] = [];

  // ── Title page ──
  children.push(
    new Paragraph({ spacing: { before: 600 }, children: [] }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 100 },
      children: [new TextRun({ text: "GRANT INTELLIGENCE BRIEF", bold: true, size: 36, color: "5B21B6" })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 40 },
      children: [new TextRun({ text: ov.grant_name || grantTitle || "Unknown Grant", bold: true, size: 28 })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 200 },
      children: [new TextRun({ text: `Funder: ${ov.funder || "Unknown"}`, size: 22, color: "666666" })],
    }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { after: 40 },
      children: [new TextRun({ text: `Generated ${new Date().toLocaleDateString()} by AltCarbon Grants Engine`, size: 18, italics: true, color: "999999" })],
    }),
    divider()
  );

  // ── 1. Overview ──
  children.push(heading("1. Grant Overview"));
  if (ov.grant_type) children.push(kvRow("Type", ov.grant_type));
  if (ov.amount) children.push(kvRow("Funding", ov.amount));
  if (ov.max_funding_usd) children.push(kvRow("Max (USD)", `$${Number(ov.max_funding_usd).toLocaleString()}`));
  if (ov.deadline) children.push(kvRow("Deadline", ov.deadline));
  if (ov.days_to_deadline != null) {
    const urgent = ov.deadline_urgent ? " (URGENT)" : "";
    children.push(kvRow("Days remaining", `${ov.days_to_deadline}${urgent}`));
  }
  if (ov.geography) children.push(kvRow("Geography", ov.geography));
  if (ov.url) children.push(kvRow("Grant URL", ov.url));
  if (ov.application_url) children.push(kvRow("Apply URL", ov.application_url));
  if ((ov.themes_detected || []).length > 0) children.push(kvRow("Themes", ov.themes_detected.join(", ")));
  if (ov.about_opportunity) {
    children.push(label("About the opportunity"));
    children.push(body(ov.about_opportunity));
  }

  // ── 2. Eligibility ──
  children.push(divider(), heading("2. Eligibility"));
  if (elig.summary) children.push(body(elig.summary));
  if (elig.details) {
    children.push(label("Detailed requirements"));
    children.push(body(elig.details));
  }
  if ((elig.checklist || []).length > 0) {
    children.push(label("AltCarbon eligibility checklist"));
    const statusIcon: Record<string, string> = {
      met: "[MET]",
      likely_met: "[LIKELY]",
      verify: "[VERIFY]",
      not_met: "[NOT MET]",
    };
    const statusColor: Record<string, string> = {
      met: "16A34A",
      likely_met: "CA8A04",
      verify: "2563EB",
      not_met: "DC2626",
    };
    for (const item of elig.checklist) {
      const s = item.altcarbon_status || "verify";
      children.push(new Paragraph({
        bullet: { level: 0 },
        spacing: { after: 40 },
        children: [
          new TextRun({ text: `${statusIcon[s] || s} `, bold: true, size: 20, color: statusColor[s] || "000000" }),
          new TextRun({ text: `${item.criterion || ""}`, bold: true, size: 20 }),
          new TextRun({ text: item.note ? ` — ${item.note}` : "", size: 20, color: "666666" }),
        ],
      }));
    }
  }

  // ── 3. AI Scoring ──
  children.push(divider(), heading("3. AI Scoring & Analysis"));
  if (scoring.weighted_total != null) {
    children.push(kvRow("Overall score", `${scoring.weighted_total.toFixed(1)} / 10`));
  }
  if (scoring.recommended_action) children.push(kvRow("Recommendation", scoring.recommended_action.toUpperCase()));

  const scores = scoring.scores || {};
  if (Object.keys(scores).length > 0) {
    children.push(label("Score breakdown"));
    const rows = Object.entries(scores).map(([k, v]) =>
      new TableRow({
        children: [
          scoreCell(k.replace(/_/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase())),
          scoreCell(`${v} / 10`, Number(v) >= 7 ? "DCFCE7" : Number(v) >= 4 ? "FEF9C3" : "FEE2E2"),
        ],
      })
    );
    children.push(new Paragraph({ children: [] })); // spacer
    children.push(
      // @ts-expect-error — Table is valid in section children
      new Table({ rows, width: { size: 100, type: WidthType.PERCENTAGE } })
    );
  }

  if (scoring.rationale) {
    children.push(label("Rationale"));
    children.push(body(scoring.rationale));
  }
  if (scoring.reasoning) {
    children.push(label("Strategic reasoning"));
    children.push(body(scoring.reasoning));
  }
  if ((scoring.evidence_found || []).length > 0) {
    children.push(label("Evidence found (AltCarbon fit)"));
    for (const e of scoring.evidence_found) children.push(bullet(e, "16A34A"));
  }
  if ((scoring.evidence_gaps || []).length > 0) {
    children.push(label("Evidence gaps"));
    for (const e of scoring.evidence_gaps) children.push(bullet(e, "CA8A04"));
  }
  if ((scoring.red_flags || []).length > 0) {
    children.push(label("Red flags"));
    for (const r of scoring.red_flags) children.push(bullet(r, "DC2626"));
  }

  // ── 4. Key Dates ──
  if (Object.values(kd).some(Boolean)) {
    children.push(divider(), heading("4. Key Dates & Timelines"));
    for (const [k, v] of Object.entries(kd)) {
      if (v) children.push(kvRow(k.replace(/_/g, " ").replace(/\b\w/g, (c: string) => c.toUpperCase()), String(v)));
    }
  }

  // ── 5. Application Requirements ──
  children.push(divider(), heading("5. Application Requirements"));
  if ((reqs.documents_needed || []).length > 0) {
    children.push(label("Documents needed"));
    for (const d of reqs.documents_needed) children.push(bullet(d));
  }
  if ((reqs.attachments || []).length > 0) {
    children.push(label("Attachments"));
    for (const a of reqs.attachments) children.push(bullet(a));
  }
  if (reqs.submission_format) children.push(kvRow("Submission format", reqs.submission_format));
  if (reqs.submission_portal) children.push(kvRow("Submission portal", reqs.submission_portal));
  if (reqs.word_page_limits) children.push(kvRow("Word/page limits", reqs.word_page_limits));
  if (reqs.language) children.push(kvRow("Language", reqs.language));
  if (reqs.co_funding_required) children.push(kvRow("Co-funding required", reqs.co_funding_required));

  if (data.application_process) {
    children.push(label("Application process"));
    children.push(body(data.application_process));
  }

  // ── 6. Evaluation Criteria ──
  if ((data.evaluation_criteria || []).length > 0) {
    children.push(divider(), heading("6. Evaluation Criteria"));
    for (const ec of data.evaluation_criteria) {
      const w = ec.weight ? ` (${ec.weight})` : "";
      children.push(new Paragraph({
        bullet: { level: 0 },
        spacing: { after: 60 },
        children: [
          new TextRun({ text: `${ec.criterion || ""}${w}`, bold: true, size: 20 }),
          new TextRun({ text: ec.what_they_look_for ? `: ${ec.what_they_look_for}` : "", size: 20, color: "444444" }),
        ],
      }));
    }
  }

  // ── 7. Application Sections ──
  if ((data.application_sections || []).length > 0) {
    children.push(divider(), heading("7. Expected Application Structure"));
    for (const sec of data.application_sections) {
      const lim = sec.limit ? ` [${sec.limit}]` : "";
      children.push(new Paragraph({
        bullet: { level: 0 },
        spacing: { after: 60 },
        children: [
          new TextRun({ text: `${sec.section || ""}${lim}`, bold: true, size: 20 }),
          new TextRun({ text: sec.what_to_cover ? `: ${sec.what_to_cover}` : "", size: 20, color: "444444" }),
        ],
      }));
    }
  }

  // ── 8. Funding Terms ──
  if (Object.values(ft).some((v) => (Array.isArray(v) ? v.length > 0 : !!v))) {
    children.push(divider(), heading("8. Funding Terms"));
    if (ft.disbursement_schedule) children.push(kvRow("Disbursement", ft.disbursement_schedule));
    if (ft.reporting_requirements) children.push(kvRow("Reporting", ft.reporting_requirements));
    if (ft.ip_ownership) children.push(kvRow("IP ownership", ft.ip_ownership));
    if (ft.audit_requirement) children.push(kvRow("Audit", ft.audit_requirement));
    if ((ft.permitted_costs || []).length > 0) {
      children.push(label("Permitted costs"));
      for (const c of ft.permitted_costs) children.push(bullet(c, "16A34A"));
    }
    if ((ft.excluded_costs || []).length > 0) {
      children.push(label("Excluded costs"));
      for (const c of ft.excluded_costs) children.push(bullet(c, "DC2626"));
    }
  }

  // ── 9. Strategy ──
  children.push(divider(), heading("9. Strategic Analysis"));
  if (strat.strategic_angle) {
    children.push(label("Recommended angle for AltCarbon"));
    children.push(body(strat.strategic_angle));
  }
  if (strat.altcarbon_fit_verdict) children.push(kvRow("AltCarbon fit verdict", strat.altcarbon_fit_verdict.toUpperCase()));
  if (strat.strategic_note) {
    children.push(label("Strategic note"));
    children.push(body(strat.strategic_note));
  }
  if (strat.funder_context) {
    children.push(label("Funder background"));
    children.push(body(strat.funder_context));
  }
  if (strat.funder_pattern) {
    children.push(label("Funder pattern (who gets funded)"));
    children.push(body(strat.funder_pattern));
  }
  if ((strat.application_tips || []).length > 0) {
    children.push(label("Application tips"));
    for (const tip of strat.application_tips) children.push(bullet(tip, "5B21B6"));
  }

  // ── 10. Past Winners ──
  if ((pw.winners || []).length > 0) {
    children.push(divider(), heading("10. Past Winners Analysis"));
    if (pw.total_winners_found) children.push(kvRow("Total winners found", String(pw.total_winners_found)));
    if (pw.altcarbon_comparable_count) children.push(kvRow("AltCarbon-comparable", String(pw.altcarbon_comparable_count)));
    children.push(label("Winners"));
    for (const w of pw.winners) {
      const yr = w.year ? ` (${w.year})` : "";
      const country = w.country ? ` — ${w.country}` : "";
      const sim = w.altcarbon_similarity ? ` [${w.altcarbon_similarity} similarity]` : "";
      children.push(new Paragraph({
        bullet: { level: 0 },
        spacing: { after: 60 },
        children: [
          new TextRun({ text: `${w.name || "?"}${yr}${country}${sim}`, bold: true, size: 20 }),
          new TextRun({ text: w.project_brief ? `: ${w.project_brief}` : "", size: 20, color: "444444" }),
        ],
      }));
    }
  }

  // ── 11. Contact & Resources ──
  if (Object.values(contact).some((v) => (Array.isArray(v) ? v.length > 0 : !!v))) {
    children.push(divider(), heading("11. Contact Information"));
    if (contact.name) children.push(kvRow("Name", contact.name));
    if (contact.email) children.push(kvRow("Email", contact.email));
    for (const em of contact.emails_all || []) {
      if (em !== contact.email) children.push(kvRow("Also", em));
    }
    if (contact.phone) children.push(kvRow("Phone", contact.phone));
    if (contact.office) children.push(kvRow("Office", contact.office));
  }

  if (Object.values(resources).some((v) => (Array.isArray(v) ? v.length > 0 : !!v))) {
    children.push(divider(), heading("12. Resources & Links"));
    for (const url of resources.brochure_urls || []) children.push(bullet(`Brochure/guideline: ${url}`));
    for (const url of resources.info_session_urls || []) children.push(bullet(`Info session: ${url}`));
    for (const url of resources.template_urls || []) children.push(bullet(`Template: ${url}`));
    if (resources.faq_url) children.push(kvRow("FAQ", resources.faq_url));
    if (resources.guidelines_url) children.push(kvRow("Guidelines", resources.guidelines_url));
  }

  // ── Similar grants ──
  if ((data.similar_grants || []).length > 0) {
    children.push(label("Similar grants / previous rounds"));
    for (const sg of data.similar_grants) children.push(bullet(sg));
  }

  // ── Build document ──
  const section: ISectionOptions = { children: children as ISectionOptions["children"] };

  const doc = new Document({
    creator: "AltCarbon Grants Engine",
    title: `Intelligence Brief — ${ov.grant_name || grantTitle || "Grant"}`,
    description: "Comprehensive grant intelligence brief generated by AltCarbon Grants Engine",
    sections: [section],
  });

  const blob = await Packer.toBlob(doc);
  const filename = `${(ov.grant_name || grantTitle || "Grant").replace(/[^a-zA-Z0-9]+/g, "_")}_Intelligence_Brief.docx`;
  saveAs(blob, filename);
}
