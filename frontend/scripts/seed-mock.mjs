/**
 * Seed mock grant data for local UI testing.
 * Usage: node scripts/seed-mock.mjs
 * Requires MONGODB_URI in frontend/.env.local
 */
import { MongoClient } from "mongodb";
import { readFileSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));

// Load .env.local manually
const envPath = resolve(__dirname, "../.env.local");
const envLines = readFileSync(envPath, "utf8").split("\n");
for (const line of envLines) {
  const [key, ...rest] = line.split("=");
  if (key && rest.length && !key.startsWith("#")) {
    process.env[key.trim()] = rest.join("=").trim();
  }
}

const uri = process.env.MONGODB_URI;
if (!uri) throw new Error("MONGODB_URI not set");

const client = new MongoClient(uri);
const db = client.db("altcarbon_grants");

const now = new Date().toISOString();
const days = (n) => new Date(Date.now() + n * 86400000).toISOString().slice(0, 10);

// ── Mock grants ──────────────────────────────────────────────────────────────
const grants = [
  {
    grant_name: "DST Clean Energy Research Initiative",
    title: "DST Clean Energy Research Initiative",
    funder: "Department of Science & Technology, India",
    status: "triage",
    weighted_total: 7.8,
    deadline_urgent: true,
    deadline: days(18),
    days_to_deadline: 18,
    geography: "India",
    eligibility: "Indian startups & research institutions working on clean energy solutions with at least 2 years operational history.",
    max_funding_usd: 150000,
    max_funding: 150000,
    themes_detected: ["climatetech", "ai_for_sciences"],
    recommended_action: "pursue",
    rationale: "Strong theme alignment with AltCarbon's carbon measurement stack. Eligibility confirmed. Timeline is tight but achievable.",
    scores: {
      theme_alignment: 9.0,
      eligibility_confidence: 8.5,
      funding_amount: 7.0,
      deadline_urgency: 6.0,
      geography_fit: 9.5,
      competition_level: 7.0,
    },
    grant_type: "R&D Grant",
    url: "https://dst.gov.in",
    scraped_at: now,
    scored_at: now,
    thread_id: "thread_mock_001",
  },
  {
    grant_name: "Bill & Melinda Gates Foundation — AgriTech Impact Grant",
    title: "Bill & Melinda Gates Foundation — AgriTech Impact Grant",
    funder: "Bill & Melinda Gates Foundation",
    status: "triage",
    weighted_total: 6.9,
    deadline_urgent: false,
    deadline: days(45),
    days_to_deadline: 45,
    geography: "Global",
    eligibility: "Non-profits and for-profits in developing countries working on smallholder farmer productivity and climate adaptation.",
    max_funding_usd: 500000,
    max_funding: 500000,
    themes_detected: ["agritech", "social_impact"],
    recommended_action: "watch",
    rationale: "High funding potential. Geography fits. Eligibility partially confirmed — need to verify smallholder focus requirement.",
    scores: {
      theme_alignment: 7.5,
      eligibility_confidence: 6.0,
      funding_amount: 9.5,
      deadline_urgency: 8.0,
      geography_fit: 8.0,
      competition_level: 5.0,
    },
    grant_type: "Impact Grant",
    url: "https://gatesfoundation.org",
    scraped_at: now,
    scored_at: now,
    thread_id: "thread_mock_002",
  },
  {
    grant_name: "ANRF — Applied Earth Sciences Program",
    title: "ANRF — Applied Earth Sciences Program",
    funder: "Anusandhan National Research Foundation",
    status: "pursue",
    weighted_total: 8.2,
    deadline_urgent: false,
    deadline: days(60),
    days_to_deadline: 60,
    geography: "India",
    eligibility: "Indian universities and research institutions. Startups may apply as industry partners.",
    max_funding_usd: 200000,
    max_funding: 200000,
    themes_detected: ["applied_earth_sciences", "climatetech"],
    recommended_action: "pursue",
    rationale: "Excellent fit — ANRF explicitly funds remote sensing and carbon cycle research. AltCarbon qualifies as industry partner.",
    scores: {
      theme_alignment: 9.5,
      eligibility_confidence: 8.0,
      funding_amount: 8.0,
      deadline_urgency: 8.5,
      geography_fit: 9.5,
      competition_level: 7.0,
    },
    grant_type: "Research Grant",
    url: "https://anrf.gov.in",
    scraped_at: now,
    scored_at: now,
    thread_id: "thread_mock_003",
  },
  {
    grant_name: "EU Horizon Europe — Green Deal Call",
    title: "EU Horizon Europe — Green Deal Call",
    funder: "European Commission",
    status: "watch",
    weighted_total: 6.2,
    deadline_urgent: false,
    deadline: days(90),
    days_to_deadline: 90,
    geography: "EU + Associated Countries",
    eligibility: "EU entities required. Indian partners eligible as third-country organisations. Min 3-consortium required.",
    max_funding_usd: 2000000,
    max_funding: 2000000,
    themes_detected: ["climatetech", "applied_earth_sciences"],
    recommended_action: "watch",
    rationale: "Massive funding potential but complex consortium requirement. AltCarbon would need an EU lead partner. Worth monitoring.",
    scores: {
      theme_alignment: 8.0,
      eligibility_confidence: 5.5,
      funding_amount: 10.0,
      deadline_urgency: 9.0,
      geography_fit: 4.0,
      competition_level: 3.5,
    },
    grant_type: "Research Grant",
    url: "https://ec.europa.eu/info/funding-tenders",
    scraped_at: now,
    scored_at: now,
    thread_id: "thread_mock_004",
  },
  {
    grant_name: "Climake Accelerator — Seed Grant",
    title: "Climake Accelerator — Seed Grant",
    funder: "Climake / Villgro",
    status: "pursue",
    weighted_total: 7.5,
    deadline_urgent: true,
    deadline: days(12),
    days_to_deadline: 12,
    geography: "India",
    eligibility: "Indian climate-tech startups at seed stage. Revenue < $1M. Team of at least 2 co-founders.",
    max_funding_usd: 50000,
    max_funding: 50000,
    themes_detected: ["climatetech", "social_impact"],
    recommended_action: "pursue",
    rationale: "Quick-apply grant with high probability of success. AltCarbon fits all criteria. Deadline is very close — prioritise.",
    scores: {
      theme_alignment: 9.0,
      eligibility_confidence: 9.0,
      funding_amount: 5.0,
      deadline_urgency: 3.0,
      geography_fit: 9.5,
      competition_level: 7.5,
    },
    grant_type: "Accelerator Grant",
    url: "https://villgro.org",
    scraped_at: now,
    scored_at: now,
    thread_id: "thread_mock_005",
  },
  {
    grant_name: "World Bank PROBLUE — Ocean Carbon Program",
    title: "World Bank PROBLUE — Ocean Carbon Program",
    funder: "World Bank Group",
    status: "triage",
    weighted_total: 5.8,
    deadline_urgent: false,
    deadline: days(120),
    days_to_deadline: 120,
    geography: "Global",
    eligibility: "Government agencies, IGOs, and NGOs primarily. Private sector participation requires government endorsement.",
    max_funding_usd: 1000000,
    max_funding: 1000000,
    themes_detected: ["applied_earth_sciences", "climatetech"],
    recommended_action: "watch",
    rationale: "High funding but eligibility is uncertain for a private company without government endorsement.",
    scores: {
      theme_alignment: 7.0,
      eligibility_confidence: 4.0,
      funding_amount: 9.5,
      deadline_urgency: 9.5,
      geography_fit: 7.0,
      competition_level: 4.0,
    },
    grant_type: "Program Grant",
    url: "https://worldbank.org/problue",
    scraped_at: now,
    scored_at: now,
    thread_id: "thread_mock_006",
  },
  {
    grant_name: "Google.org Impact Challenge — Tech for Social Good",
    title: "Google.org Impact Challenge — Tech for Social Good",
    funder: "Google.org",
    status: "drafting",
    weighted_total: 7.9,
    deadline_urgent: false,
    deadline: days(30),
    days_to_deadline: 30,
    geography: "Global",
    eligibility: "Registered non-profits and social enterprises using technology for climate or social impact.",
    max_funding_usd: 250000,
    max_funding: 250000,
    themes_detected: ["ai_for_sciences", "climatetech", "social_impact"],
    recommended_action: "pursue",
    rationale: "Strong fit with AltCarbon's AI-driven carbon intelligence. Social enterprise registration may be needed.",
    scores: {
      theme_alignment: 8.5,
      eligibility_confidence: 7.5,
      funding_amount: 8.5,
      deadline_urgency: 8.0,
      geography_fit: 9.0,
      competition_level: 6.0,
    },
    grant_type: "Innovation Grant",
    url: "https://impactchallenge.withgoogle.com",
    scraped_at: now,
    scored_at: now,
    thread_id: "thread_mock_007",
  },
  {
    grant_name: "SIDBI SPEED — Clean Energy MSME Loan-Grant",
    title: "SIDBI SPEED — Clean Energy MSME Loan-Grant",
    funder: "SIDBI",
    status: "passed",
    weighted_total: 4.5,
    deadline_urgent: false,
    deadline: days(200),
    days_to_deadline: 200,
    geography: "India",
    eligibility: "MSMEs in manufacturing sector with energy consumption > 100 kWh/day. Primarily for physical infrastructure.",
    max_funding_usd: 80000,
    max_funding: 80000,
    themes_detected: ["climatetech"],
    recommended_action: "pass",
    rationale: "Eligibility miss — SIDBI SPEED targets manufacturing MSMEs, not tech startups.",
    scores: {
      theme_alignment: 5.0,
      eligibility_confidence: 2.0,
      funding_amount: 6.0,
      deadline_urgency: 9.5,
      geography_fit: 9.0,
      competition_level: 6.0,
    },
    grant_type: "Loan-Grant Hybrid",
    url: "https://sidbi.in",
    scraped_at: now,
    scored_at: now,
    thread_id: "thread_mock_008",
  },
];

// ── Mock scout run ────────────────────────────────────────────────────────────
const scoutRuns = [
  {
    run_at: new Date(Date.now() - 2 * 86400000).toISOString(),
    total_found: 8,
    new_grants: 8,
    status: "complete",
    queries_run: 12,
    sources: ["tavily", "exa"],
  },
];

// ── Mock grants_raw (for activity chart) ─────────────────────────────────────
const grantsRaw = [];
for (let i = 29; i >= 0; i--) {
  const count = i < 3 ? 8 : Math.random() < 0.35 ? Math.ceil(Math.random() * 5) : 0;
  for (let j = 0; j < count; j++) {
    grantsRaw.push({
      title: `Mock Raw Grant ${i}-${j}`,
      url: `https://mock-grant-${i}-${j}.example.com`,
      url_hash: `mock_${i}_${j}_${Math.random().toString(36).slice(2)}`,
      scraped_at: new Date(Date.now() - i * 86400000).toISOString(),
      processed: true,
      source: "tavily",
    });
  }
}

// ── Mock pipeline + draft (for drafter view) ─────────────────────────────────
const draftingGrant = grants.find((g) => g.status === "drafting");
let pipelineId = null;
const pipelineRecord = draftingGrant
  ? {
      grant_id: null, // set after insert
      thread_id: draftingGrant.thread_id,
      status: "drafting",
      started_at: now,
      draft_started_at: now,
      current_draft_version: 1,
      final_draft_url: null,
    }
  : null;

const draftDoc = {
  pipeline_id: null, // set after insert
  version: 1,
  created_at: now,
  sections: {
    "Executive Summary": {
      content:
        "AltCarbon is an AI-driven climate intelligence platform that enables businesses to accurately measure, verify, and report their carbon footprint using satellite data and machine learning. This grant will fund the expansion of our remote sensing pipeline to cover smallholder agriculture across three Indian states, delivering verified carbon credits at 10x lower cost than traditional field audits.",
      approved: false,
      word_count: 62,
      revision_count: 0,
    },
    "Problem Statement": {
      content:
        "Over 600 million smallholder farmers in the Global South lack access to affordable carbon verification. Current MRV (Measurement, Reporting & Verification) methodologies require costly on-ground surveys — averaging $50/tonne CO2 — making carbon markets inaccessible to subsistence farmers. The result: a $1.2 trillion climate finance gap that disproportionately affects rural communities most vulnerable to climate change.",
      approved: false,
      word_count: 70,
      revision_count: 0,
    },
    "Solution Overview": {
      content:
        "AltCarbon's platform combines Sentinel-2 multispectral satellite imagery, LiDAR elevation data, and fine-tuned vision transformers to estimate soil organic carbon and above-ground biomass at 10m resolution. Our automated pipeline processes 50,000 km² per day at $0.30/tonne — a 99% cost reduction over field surveys. The system integrates with Verra's VCS standard and generates tamper-proof reports on a distributed ledger.",
      approved: true,
      word_count: 75,
      revision_count: 1,
    },
    "Impact & Theory of Change": {
      content:
        "By making carbon verification 100x more affordable, AltCarbon enables smallholder farmers to access carbon markets for the first time. Each verified project generates $8–15/tonne revenue for participating farmers — equivalent to a 20–40% income supplement. Over 5 years, we project reaching 2 million farmers across India, Indonesia, and Kenya, sequestering 15 MtCO2e annually and channelling $180M in climate finance to rural communities.",
      approved: false,
      word_count: 78,
      revision_count: 0,
    },
    "Team & Credentials": {
      content:
        "The AltCarbon team combines deep expertise in remote sensing, ML, and carbon markets. Our CTO holds a PhD in Earth Observation from IISc Bangalore and previously led satellite data processing at ISRO. Our CEO has 8 years of carbon market experience and managed a $50M REDD+ portfolio at a leading climate consultancy. We are backed by Villgro and Climate Capital and hold an ISO 14064-3 certification.",
      approved: false,
      word_count: 73,
      revision_count: 0,
    },
    "Budget": {
      content:
        "Total request: $250,000 over 18 months.\n\n• Satellite data acquisition & processing: $80,000 (32%)\n• ML model development & validation: $70,000 (28%)\n• Field validation partnerships: $40,000 (16%)\n• Platform engineering & API development: $35,000 (14%)\n• Regulatory & certification costs: $15,000 (6%)\n• Operational overhead: $10,000 (4%)\n\nAll expenditure complies with Google.org's financial reporting requirements.",
      approved: false,
      word_count: 78,
      revision_count: 0,
    },
  },
};

// ── Knowledge chunks (for knowledge view) ────────────────────────────────────
const knowledgeChunks = [];
const docTypes = ["company_overview", "past_grant_application", "technical_report", "product_spec"];
const sources = ["notion", "drive", "notion", "drive", "notion"];
for (let i = 0; i < 120; i++) {
  knowledgeChunks.push({
    source: sources[i % sources.length],
    doc_type: docTypes[i % docTypes.length],
    themes: ["climatetech", "agritech"].slice(0, (i % 2) + 1),
    content: `Mock knowledge chunk ${i}`,
    embedding: null,
    synced_at: now,
  });
}

const syncLog = {
  source: "notion+drive",
  chunks_added: 120,
  chunks_updated: 0,
  synced_at: now,
  status: "success",
};

// ── Insert ────────────────────────────────────────────────────────────────────
async function seed() {
  console.log("Connecting to MongoDB Atlas…");
  await client.connect();

  // Clear existing mock data
  await Promise.all([
    db.collection("grants_scored").deleteMany({}),
    db.collection("grants_raw").deleteMany({}),
    db.collection("scout_runs").deleteMany({}),
    db.collection("grants_pipeline").deleteMany({}),
    db.collection("grant_drafts").deleteMany({}),
    db.collection("knowledge_chunks").deleteMany({}),
    db.collection("knowledge_sync_logs").deleteMany({}),
  ]);
  console.log("Cleared existing data");

  // Insert grants
  const grantResult = await db.collection("grants_scored").insertMany(grants);
  console.log(`Inserted ${Object.keys(grantResult.insertedIds).length} grants`);

  // Insert raw grants (activity chart)
  if (grantsRaw.length > 0) {
    await db.collection("grants_raw").insertMany(grantsRaw);
    console.log(`Inserted ${grantsRaw.length} raw grants`);
  }

  // Scout runs
  await db.collection("scout_runs").insertMany(scoutRuns);
  console.log("Inserted scout run log");

  // Pipeline + draft
  if (pipelineRecord && draftingGrant) {
    const grantId = grantResult.insertedIds[grants.indexOf(draftingGrant)].toString();
    pipelineRecord.grant_id = grantId;
    const pRes = await db.collection("grants_pipeline").insertOne(pipelineRecord);
    pipelineId = pRes.insertedId.toString();
    draftDoc.pipeline_id = pipelineId;
    await db.collection("grant_drafts").insertOne(draftDoc);
    console.log("Inserted pipeline record + draft");
  }

  // Knowledge chunks
  await db.collection("knowledge_chunks").insertMany(knowledgeChunks);
  await db.collection("knowledge_sync_logs").insertOne(syncLog);
  console.log(`Inserted ${knowledgeChunks.length} knowledge chunks`);

  console.log("\n✅ Seed complete! Restart `npm run dev` and visit http://localhost:3000");
  await client.close();
}

seed().catch((e) => {
  console.error("Seed failed:", e);
  process.exit(1);
});
