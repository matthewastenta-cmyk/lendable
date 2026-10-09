// Pocket Approval building assessment — reads building documents privately and returns classified, building-level findings.
// POST /api/assess { building: {address, type, units, market}, docs: [{name, type, text} | {name, type, file, mediaType}] }
// Documents are processed in memory and never stored by this endpoint. Findings exclude personal and transaction details.
const FANNIE = require('./_fannie.js');
const MODEL = process.env.LENDABLE_MODEL || 'claude-sonnet-5-5';
const MAX_TEXT = 180000;
const hits = new Map();
const LIMIT_PER_HOUR = 12;
function limited(ip) {
  const now = Date.now(), h = (hits.get(ip) || []).filter(t => now - t < 3600e3);
  h.push(now); hits.set(ip, h);
  return h.length > LIMIT_PER_HOUR;
}

const SYSTEM = `You are the document reviewer for Pocket Approval, a preliminary building due-diligence and financing feasibility tool for condos and co-ops. Its purpose: tell people what they should investigate before they spend money investigating it. You are not approving anything and not underwriting a loan.

Read the building documents provided (budgets, financial statements, questionnaires, board minutes, insurance certificates, engineering reports, offering plans) and return building-level findings.

Classify every finding into exactly one tier:
- "guideline_issue": the document clearly shows a condition that conflicts with a published Fannie Mae / Freddie Mac project standard as summarized below (e.g. budgeted reserves below the required share of the budget with no qualifying reserve study; unfunded critical repairs; more than 15% of units 60+ days delinquent; single-entity ownership above the limit; commercial space above 35%; litigation of an ineligible type with no applicable exception; hotel/condotel operation). Only use this tier when the numbers or facts in the document support it; name the guide section.
- "concern": a potential problem whose financing impact depends on circumstances or the lender (e.g. an operating deficit, a rising deficit trend, large deferred maintenance not yet shown to be critical, litigation whose nature or materiality is unclear, an upcoming special assessment, insurance deductibles or gaps). An operating loss is NOT automatically a guideline failure; litigation and insurance issues may be acceptable depending on their nature and the lender.
- "needs_docs": the item matters for financing but can't be assessed from what was provided; say exactly which document or answer is needed.
- "meets": the documents indicate the standard appears to be satisfied (state the figure).

Board minutes: read them the way a purchaser's attorney does, as an early warning system. Flag anything discussed that could affect value or financing, with the meeting date: planned or proposed special assessments or common-charge increases; major capital projects (facade/Local Law 11, roof, elevators, boilers, plumbing risers, garage, balconies) and how they'll be funded; water intrusion, mold, structural or safety issues; insurance renewals, coverage reductions or premium spikes; litigation, claims or threatened suits; underlying mortgage refinancing or maturity (co-ops); sponsor or developer disputes or sponsor-held units; changes to flip tax, sublet, pet or financing rules; budget shortfalls or reserve draws; and anything else a buyer should ask about. In minutes, never name residents, owners or board members, even when the minutes do.
For minutes items, public_statement should say what was discussed without figures, e.g. 'Board minutes discuss a planned special assessment', 'Board minutes discuss facade repairs not yet funded', 'Board minutes discuss an insurance non-renewal'.

Cover these categories when the documents allow: reserves, operating results, delinquencies, special assessments, critical repairs / structural, litigation, insurance (master, flood, fidelity), single-entity ownership, commercial space, owner occupancy / rentals, hotel-like operation, and (co-ops) underlying mortgage and recognition-agreement issues.

Privacy rules — never break these:
- Never include names of unit owners, shareholders, buyers, sellers, borrowers, tenants, board members or employees, and never tie a unit number to a person or to a delinquency.
- Never include a purchase price, loan amount, loan terms or the parties to any individual transaction.
- Findings must be about the building or association only.

Keep each detail to one or two short sentences and return at most 16 findings, most important first.
Return ONLY one JSON object, no prose, no code fences:
{
  "building_name": "association / corporation name if stated, else null",
  "doc_period": "the period or date the documents describe, e.g. 'FY2025 budget; audited statements for 2024'",
  "findings": [
    {"category": "reserves|operating|delinquency|special_assessment|critical_repairs|litigation|insurance|single_entity|commercial|occupancy|hotel|coop_financing|capital_project|house_rules|minutes_other|other",
     "tier": "guideline_issue|concern|needs_docs|meets",
     "title": "short headline, e.g. 'Reserve contributions below 10% of budget'",
     "detail": "one or two sentences with the specific figures and why it matters for financing",
     "guide_ref": "Fannie Mae section if relevant, e.g. 'B4-2.1-03', else null",
     "public_statement": "a short yes/no statement against the guideline, safe to show other users: no dollar figures, percentages from the document, names, unit numbers or quotes. Guideline thresholds are fine. Examples: 'Does not budget 10% for reserves', 'Budgets at least 10% for reserves', 'No crime/fidelity insurance in place', 'More than 15% of units 60+ days delinquent', 'Operating deficit reported', 'Pending litigation involving the association'. null for needs_docs findings.",
     "source": {"doc": "file name", "doc_type": "Budget|Financials|Questionnaire|Board minutes|Insurance|Engineering|Offering plan|Other", "page": number or null, "as_of": "YYYY-MM-DD or period text or null"}}
  ],
  "next_step": "one sentence: the most useful next action before committing significant transaction expenses",
  "financing_note": "one sentence; if any guideline_issue or concern exists, note that portfolio, non-agency or exception lenders may still finance the building"
}

Fannie Mae project standards reference (summary; cite sections):
` + FANNIE;

module.exports = async (req, res) => {
  res.setHeader('Cache-Control', 'no-store');
  const key = process.env.ANTHROPIC_API_KEY || process.env.anthropic_api_key;
  if (req.method !== 'POST') return res.status(405).json({ error: 'method_not_allowed' });
  if (!key) return res.status(503).json({ error: 'not_configured' });
  const ip = String(req.headers['x-forwarded-for'] || '').split(',')[0].trim() || 'unknown';
  if (limited(ip)) return res.status(429).json({ error: 'rate_limited' });
  let body = req.body;
  if (typeof body === 'string') { try { body = JSON.parse(body); } catch { body = {}; } }
  body = body || {};
  const docs = Array.isArray(body.docs) ? body.docs.slice(0, 8) : [];
  if (!docs.length) return res.status(400).json({ error: 'no_documents' });
  const b = body.building || {};
  const content = [{ type: 'text', text: 'Building: ' + [b.address, b.type, b.units ? b.units + ' units' : '', b.market].filter(Boolean).join(' · ') }];
  let budget = MAX_TEXT, files = 0;
  for (const d of docs) {
    const head = '\n\n=== Document: ' + String(d.name || 'document').slice(0, 120) + ' (' + String(d.type || 'Other').slice(0, 40) + ') ===\n';
    if (typeof d.text === 'string' && d.text.trim().length > 50 && budget > 2000) {
      const t = d.text.slice(0, budget); budget -= t.length;
      content.push({ type: 'text', text: head + t });
    } else if (typeof d.file === 'string' && d.file.length > 100 && files < 2) {
      const mt = String(d.mediaType || '');
      content.push({ type: 'text', text: head + '(attached)' });
      if (mt === 'application/pdf') content.push({ type: 'document', source: { type: 'base64', media_type: mt, data: d.file } });
      else if (/^image\/(jpeg|png|webp|gif)$/.test(mt)) content.push({ type: 'image', source: { type: 'base64', media_type: mt, data: d.file } });
      else continue;
      files++;
    }
  }
  if (content.length < 2) return res.status(400).json({ error: 'unreadable_documents' });
  content.push({ type: 'text', text: 'Review these documents and return the JSON findings.' });
  try {
    const r = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: { 'x-api-key': key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json' },
      body: JSON.stringify({ model: MODEL, max_tokens: 8000, system: SYSTEM, messages: [{ role: 'user', content }] }),
    });
    const j = await r.json();
    if (!r.ok) {
      const code = r.status === 429 ? 'rate_limited' : r.status === 401 ? 'bad_key' : 'upstream_error';
      return res.status(r.status === 429 ? 429 : 502).json({ error: code, detail: j && j.error && j.error.message });
    }
    const text = (j.content || []).filter(x => x.type === 'text').map(x => x.text).join('');
    const m = text.match(/\{[\s\S]*\}/);
    let data = null;
    try { data = m ? JSON.parse(m[0]) : null; } catch (e) { data = null; }
    if (!data && text.includes('"findings"')) {
      // response was cut off: keep every complete finding
      const cut = text.slice(text.indexOf('{'), text.lastIndexOf('}') + 1);
      for (const tail of [']}', ']\n}', '}]}']) { try { data = JSON.parse(cut + tail); break; } catch (e) {} }
    }
    if (!data || !Array.isArray(data.findings)) return res.status(502).json({ error: 'unreadable', detail: 'stop=' + j.stop_reason + ' ' + text.slice(0, 160) });
    const TIERS = ['guideline_issue', 'concern', 'needs_docs', 'meets'];
    data.findings = data.findings.filter(f => f && TIERS.includes(f.tier) && f.title).slice(0, 20).map(f => ({
      category: String(f.category || 'other').slice(0, 30), tier: f.tier, title: String(f.title).slice(0, 120), detail: String(f.detail || '').slice(0, 400),
      guide_ref: f.guide_ref ? String(f.guide_ref).slice(0, 30) : null,
      public_statement: f.public_statement && f.tier !== 'needs_docs' ? String(f.public_statement).replace(/\$[\d,.]+[kKmM]?/g, '').replace(/\b(\d+(?:\.\d+)?)\s?%/g, (m, n) => ['10','15','20','25','35','50'].includes(n) ? n + '%' : '').replace(/\s{2,}/g, ' ').trim().slice(0, 120) : null,
      source: { doc: String((f.source && f.source.doc) || '').slice(0, 120), doc_type: String((f.source && f.source.doc_type) || '').slice(0, 30), page: (f.source && Number.isFinite(+f.source.page)) ? +f.source.page : null, as_of: (f.source && f.source.as_of) ? String(f.source.as_of).slice(0, 40) : null } }));
    res.status(200).json({ data, usage: j.usage });
  } catch (e) {
    res.status(502).json({ error: 'upstream_error', detail: String(e && e.message || e) });
  }
};
