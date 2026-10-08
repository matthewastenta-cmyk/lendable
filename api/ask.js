// Lendable AI — answers realtor questions with Claude via the Anthropic API.
// POST /api/ask  { system: "<Lendable instructions + Fannie Mae rules>", context: "<building data>", messages: [{role, content}] }
// GET  /api/ask  → { configured: true|false }
// Env vars: ANTHROPIC_API_KEY (required), LENDABLE_MODEL (optional, default claude-sonnet-5-5).
// Set a monthly spend limit in console.anthropic.com → Settings → Limits as the hard cap.

const MODEL = process.env.LENDABLE_MODEL || 'claude-sonnet-5-5';
const MAX_SYSTEM = 24000, MAX_CONTEXT = 12000, MAX_MSG = 4000, MAX_TURNS = 12;
const hits = new Map(); // best-effort per-IP limit (resets when the function cold-starts)
const LIMIT_PER_HOUR = 60;

function limited(ip) {
  const now = Date.now(), h = hits.get(ip) || [];
  const recent = h.filter(t => now - t < 3600e3);
  recent.push(now); hits.set(ip, recent);
  return recent.length > LIMIT_PER_HOUR;
}

module.exports = async (req, res) => {
  res.setHeader('Cache-Control', 'no-store');
  const key = process.env.ANTHROPIC_API_KEY || process.env.anthropic_api_key;
  if (req.method === 'GET') return res.status(200).json({ configured: !!key, model: MODEL });
  if (req.method !== 'POST') return res.status(405).json({ error: 'method_not_allowed' });
  if (!key) return res.status(503).json({ error: 'not_configured' });

  const ip = String(req.headers['x-forwarded-for'] || '').split(',')[0].trim() || 'unknown';
  if (limited(ip)) return res.status(429).json({ error: 'rate_limited' });

  let body = req.body;
  if (typeof body === 'string') { try { body = JSON.parse(body); } catch { body = {}; } }
  const system = String(body && body.system || '');
  const context = String(body && body.context || '').slice(0, MAX_CONTEXT);
  // Only accept Lendable's own instructions, so the endpoint can't be used as a general-purpose chatbot.
  if (!(system.startsWith('You are Pocket Approval') || system.startsWith('You are Lendable')) || system.length > MAX_SYSTEM) return res.status(400).json({ error: 'bad_request' });
  let messages = Array.isArray(body.messages) ? body.messages : [];
  messages = messages
    .filter(m => m && (m.role === 'user' || m.role === 'assistant') && typeof m.content === 'string')
    .slice(-MAX_TURNS)
    .map(m => ({ role: m.role, content: m.content.slice(0, MAX_MSG) }));
  while (messages.length && messages[0].role !== 'user') messages.shift();
  if (!messages.length || messages[messages.length - 1].role !== 'user') return res.status(400).json({ error: 'bad_request' });

  try {
    const r = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: { 'x-api-key': key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json' },
      body: JSON.stringify({
        model: MODEL,
        max_tokens: 900,
        system: [
          { type: 'text', text: system, cache_control: { type: 'ephemeral' } }, // same on every question → cached at ~10% of the price
          { type: 'text', text: context || 'No building selected.' },
        ],
        messages,
      }),
    });
    const j = await r.json();
    if (!r.ok) {
      const code = r.status === 429 ? 'rate_limited' : r.status === 401 ? 'bad_key' : 'upstream_error';
      return res.status(r.status === 429 ? 429 : 502).json({ error: code, detail: j && j.error && j.error.message });
    }
    const text = (j.content || []).filter(b => b.type === 'text').map(b => b.text).join('');
    res.status(200).json({ text, truncated: j.stop_reason === 'max_tokens', usage: j.usage });
  } catch (e) {
    res.status(502).json({ error: 'upstream_error', detail: String(e && e.message || e) });
  }
};
