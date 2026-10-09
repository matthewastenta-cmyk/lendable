// Lendable deal extraction — reads a purchase contract and returns structured deal data.
// POST /api/extract  { text: "<contract text>" }  or  { file: "<base64>", mediaType: "application/pdf" | "image/jpeg" | "image/png" | "image/webp" }
// The instructions live here on the server, so this endpoint can't be used as a general chatbot.

const MODEL = process.env.LENDABLE_MODEL || 'claude-sonnet-5-5';
const MAX_TEXT = 150000;
const hits = new Map();
const LIMIT_PER_HOUR = 30;
function limited(ip) {
  const now = Date.now(), h = (hits.get(ip) || []).filter(t => now - t < 3600e3);
  h.push(now); hits.set(ip, h);
  return h.length > LIMIT_PER_HOUR;
}

const SYSTEM = `You extract deal data from real estate documents (purchase contracts, riders, contracts of sale for condos and co-ops, term sheets, commitment letters) for a broker/loan officer tool.
Return ONLY one JSON object, no prose, no code fences, with this shape (use null when a value isn't in the document; never guess):
{
  "doc_type": "purchase contract" | "rider" | "commitment letter" | "other",
  "address": "street address of the property, e.g. 432 Park Avenue",
  "unit": "unit or apartment number",
  "city": "borough or city, e.g. Manhattan, Brooklyn, Miami",
  "property_type": "Condo" | "Co-op" | "Townhouse" | "Other" | null,
  "purchase_price": number,
  "deposit": number,
  "loan_amount": number,
  "contract_date": "YYYY-MM-DD",
  "closing_date": "YYYY-MM-DD (scheduled closing date; if only 'on or about' a date, use it)",
  "commitment_date": "YYYY-MM-DD (financing / mortgage commitment contingency deadline)",
  "financing_contingent": true | false | null,
  "lender": "lender name if named",
  "buyers": ["names"],
  "sellers": ["names"],
  "contacts": [
    {"role": "buyer_attorney" | "seller_attorney" | "buyer_broker" | "listing_broker" | "lender" | "escrow_agent" | "title" | "managing_agent" | "other",
     "name": "person", "firm": "firm or company", "phone": "as written", "email": "as written"}
  ],
  "notes": "one or two short lines on anything a loan officer should notice (contingencies, assessments, sponsor sale, board approval, unusual terms); null if nothing"
}
Rules: amounts are plain numbers in dollars. Dates as YYYY-MM-DD; if a date is blank on the form, use null. Include a contact only if at least a name or firm is present. Escrow agent is usually the seller's attorney in NY. Don't include buyers or sellers themselves in contacts.`;

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
  let content;
  if (typeof body.text === 'string' && body.text.trim().length > 50) {
    content = [{ type: 'text', text: 'Document text:\n\n' + body.text.slice(0, MAX_TEXT) }];
  } else if (typeof body.file === 'string' && body.file.length > 100) {
    const mt = String(body.mediaType || '');
    if (mt === 'application/pdf') content = [{ type: 'document', source: { type: 'base64', media_type: mt, data: body.file } }];
    else if (/^image\/(jpeg|png|webp|gif)$/.test(mt)) content = [{ type: 'image', source: { type: 'base64', media_type: mt, data: body.file } }];
    else return res.status(400).json({ error: 'unsupported_type' });
    content.push({ type: 'text', text: 'Extract the deal data from this document.' });
  } else return res.status(400).json({ error: 'bad_request' });

  try {
    const r = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: { 'x-api-key': key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json' },
      body: JSON.stringify({ model: MODEL, max_tokens: 4000, system: SYSTEM, messages: [{ role: 'user', content }] }),
    });
    const j = await r.json();
    if (!r.ok) {
      const code = r.status === 429 ? 'rate_limited' : r.status === 401 ? 'bad_key' : 'upstream_error';
      return res.status(r.status === 429 ? 429 : 502).json({ error: code, detail: j && j.error && j.error.message });
    }
    const text = (j.content || []).filter(b => b.type === 'text').map(b => b.text).join('');
    const m = text.match(/\{[\s\S]*\}/);
    let data = null;
    try { data = m ? JSON.parse(m[0]) : null; } catch (e) { data = null; }
    if (!data) return res.status(502).json({ error: 'unreadable', detail: text.slice(0, 200) });
    res.status(200).json({ data, usage: j.usage });
  } catch (e) {
    res.status(502).json({ error: 'upstream_error', detail: String(e && e.message || e) });
  }
};
