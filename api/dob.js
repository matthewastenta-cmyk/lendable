// Lendable DOB lookup — free NYC Open Data (Socrata), no Marketproof credits.
// GET /api/dob?bbl=1001700006            (10-digit borough-block-lot)
// GET /api/dob?address=108 Leonard Street&borough=Manhattan   (falls back to a PLUTO lookup)
// Optional env var: NYC_APP_TOKEN (free from data.cityofnewyork.us → Developer Settings) for higher rate limits.

const BASE = 'https://data.cityofnewyork.us/resource/';
const DS = {
  dob: '3h2n-5cm9',      // DOB violations
  ecb: '6bgk-3dad',      // DOB ECB violations
  fisp: 'xubg-57si',     // DOB NOW: Safety – Facades compliance filings (FISP / Local Law 11)
  vacate: 'tb8q-a3ar',   // HPD orders to repair/vacate
  litigation: '59kj-x8nc', // HPD housing litigations (housing court cases HPD brings against owners)
  pluto: '64uk-42ks',    // MapPLUTO (address → BBL fallback)
  footprints: '5zhs-2jue', // Building footprints (BBL → BIN, incl. condo billing lots)
};
const BORO_NAME = { 1: 'Manhattan', 2: 'Bronx', 3: 'Brooklyn', 4: 'Queens', 5: 'Staten Island' };
const BORO_CODE = { manhattan: 1, mn: 1, bronx: 2, bx: 2, brooklyn: 3, bk: 3, queens: 4, qn: 4, 'staten island': 5, si: 5 };
const PLUTO_BORO = { 1: 'MN', 2: 'BX', 3: 'BK', 4: 'QN', 5: 'SI' };

const q = s => "'" + String(s).replace(/'/g, "''") + "'";
const pad = (v, n) => String(v).padStart(n, '0');

async function soql(ds, params) {
  const url = BASE + ds + '.json?' + new URLSearchParams(params).toString();
  const headers = { Accept: 'application/json' };
  if (process.env.NYC_APP_TOKEN) headers['X-App-Token'] = process.env.NYC_APP_TOKEN;
  const r = await fetch(url, { headers });
  if (!r.ok) throw new Error(ds + ' ' + r.status + ': ' + (await r.text()).slice(0, 200));
  return r.json();
}
async function count(ds, where) {
  const rows = await soql(ds, { $select: 'count(*) as n', $where: where });
  return Number(rows[0] && rows[0].n) || 0;
}
const ymd = s => (s && /^\d{8}$/.test(s) ? s.slice(0, 4) + '-' + s.slice(4, 6) + '-' + s.slice(6, 8) : s ? String(s).slice(0, 10) : '');
const clean = s => String(s || '').replace(/\s+/g, ' ').trim();

async function bblFromAddress(address, borough) {
  const code = BORO_CODE[String(borough || '').toLowerCase()];
  const a = clean(address).toUpperCase()
    .replace(/\b(\d+)(ST|ND|RD|TH)\b/g, '$1')
    .replace(/\bSTREET\b/g, 'STREET').replace(/\bST\b$/, 'STREET').replace(/\bAVE\b/g, 'AVENUE');
  const where = 'upper(address) like ' + q(a.split(' ').slice(0, 2).join(' ') + '%') + (code ? ' AND borough=' + q(PLUTO_BORO[code]) : '');
  const rows = await soql(DS.pluto, { $select: 'bbl,address,borough', $where: where, $limit: 5 });
  const exact = rows.find(r => clean(r.address).toUpperCase() === a) || rows[0];
  return exact ? String(Math.round(Number(exact.bbl))) : null;
}

module.exports = async (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Cache-Control', 's-maxage=86400, stale-while-revalidate=3600'); // cache each building for a day at the edge
  try {
    let bbl = String(req.query.bbl || '').replace(/\D/g, '');
    if (bbl.length !== 10 && req.query.address) bbl = (await bblFromAddress(req.query.address, req.query.borough)) || '';
    if (bbl.length !== 10) return res.status(200).json({ found: false, reason: 'No tax lot (BBL) found for this address.' });

    const boro = Number(bbl[0]), block = Number(bbl.slice(1, 6)), lot = Number(bbl.slice(6));
    // Resolve BINs first: condos are billed on 75xx lots while DOB often files on the base lot, so BIN is the reliable key.
    let bins = [];
    try {
      const fp = await soql(DS.footprints, { $select: 'bin', $where: `mappluto_bbl=${q(bbl)} OR base_bbl=${q(bbl)}`, $limit: 50 });
      bins = [...new Set(fp.map(r => r.bin).filter(b => b && !/^\d000000$/.test(b)))];
    } catch (e) { /* fall back to BBL matching below */ }
    const binIn = bins.length ? 'bin in(' + bins.map(q).join(',') + ')' : null;
    const dobWhere = binIn || `boro=${q(boro)} AND block=${q(pad(block, 5))} AND lot=${q(pad(lot, 5))}`;
    const ecbWhere = binIn || `boro=${q(boro)} AND block=${q(pad(block, 5))} AND (lot=${q(pad(lot, 4))} OR lot=${q(pad(lot, 5))})`;
    const fispWhere = binIn || `borough=${q(BORO_NAME[boro])} AND block=${q(block)} AND lot=${q(lot)}`;
    const vacWhere = (binIn ? '(' + binIn + ` OR bbl=${q(bbl)})` : `bbl=${q(bbl)}`) + ' AND actual_rescind_date IS NULL';
    const litBase = binIn ? '(' + binIn + ` OR bbl=${q(bbl)})` : `bbl=${q(bbl)}`;
    const LIT_OPEN = " AND upper(casestatus) not like 'CLOSED%' AND upper(casetype) not like 'CONH%'";
    const fiveYrs = new Date(Date.now() - 5 * 365 * 864e5).toISOString().slice(0, 10);
    const DOB_OPEN = " AND upper(violation_category) like '%ACTIVE%'";

    const settled = await Promise.allSettled([
      count(DS.dob, '(' + dobWhere + ')' + DOB_OPEN),
      soql(DS.dob, { $where: '(' + dobWhere + ')' + DOB_OPEN, $order: 'issue_date DESC', $limit: 5 }),
      count(DS.ecb, '(' + ecbWhere + ") AND ecb_violation_status='ACTIVE'"),
      soql(DS.ecb, { $where: '(' + ecbWhere + ") AND ecb_violation_status='ACTIVE'", $order: 'issue_date DESC', $limit: 5 }),
      soql(DS.fisp, { $where: fispWhere, $limit: 50 }),
      soql(DS.vacate, { $where: vacWhere, $order: 'vacate_effective_date DESC', $limit: 5 }),
      count(DS.litigation, litBase + LIT_OPEN),
      soql(DS.litigation, { $where: litBase + ` AND caseopendate >= '${fiveYrs}' AND upper(casetype) not like 'CONH%'`, $order: 'caseopendate DESC', $limit: 6 }),
    ]);
    const val = (i, d) => (settled[i].status === 'fulfilled' ? settled[i].value : d);
    const errors = settled.map((s, i) => (s.status === 'rejected' ? String(s.reason && s.reason.message || s.reason) : null)).filter(Boolean);

    const dobItems = val(1, []).map(r => ({
      source: 'DOB', date: ymd(r.issue_date), type: clean(r.violation_type).replace(/^\w-/, '') || 'DOB violation',
      status: 'open', description: clean(r.description), bin: r.bin || null,
    }));
    const ecbItems = val(3, []).map(r => ({
      source: 'ECB', date: ymd(r.issue_date), type: clean(r.violation_type) || 'ECB violation', severity: clean(r.severity),
      status: clean(r.hearing_status).toLowerCase(), description: clean(r.violation_description || r.section_law_description1),
      balance_due: Number(r.balance_due) || 0, bin: r.bin || null,
    }));
    const fisp = val(4, []).slice().sort((a, b) => (Number(b.cycle) || 0) - (Number(a.cycle) || 0) || String(b.filing_date || b.submitted_on || '').localeCompare(String(a.filing_date || a.submitted_on || '')));
    const latest = fisp[0] || null;
    const facade = latest ? {
      status: clean(latest.current_status || latest.filing_status), cycle: latest.cycle || null,
      filed: ymd(latest.filing_date || latest.submitted_on), bin: latest.bin || null,
    } : null;
    const vacates = val(5, []).map(r => ({
      date: ymd(r.vacate_effective_date), type: clean(r.vacate_type), reason: clean(r.primary_vacate_reason), units: Number(r.number_of_vacated_units) || null,
    }));
    const litigation = val(7, []).map(r => ({
      date: ymd(r.caseopendate), type: clean(r.casetype), status: clean(r.casestatus), judgement: clean(r.casejudgement), respondent: clean(r.respondent),
    }));
    if (!bins.length) bins = [...new Set([...dobItems, ...ecbItems].map(x => x.bin).concat(facade && facade.bin).filter(Boolean))];
    const fs = facade ? facade.status.toUpperCase() : '';

    res.status(200).json({
      found: true, source: 'NYC Open Data', bbl, bins,
      openDob: val(0, null), openEcb: val(2, null),
      items: [...ecbItems, ...dobItems].sort((a, b) => String(b.date).localeCompare(String(a.date))).slice(0, 8),
      facade, vacates, litigation, openLitigation: val(6, null),
      flags: {
        unsafeFacade: fs === 'UNSAFE',
        facadeRepairs: fs === 'SWARMP',
        facadeNotFiled: /NO REPORT/.test(fs),
        vacateOrder: vacates.length > 0,
        openLitigation: (val(6, 0) || 0) > 0,
        openViolations: (val(0, 0) || 0) + (val(2, 0) || 0),
      },
      errors, checkedAt: new Date().toISOString(),
    });
  } catch (e) {
    res.status(502).json({ found: false, error: String(e && e.message || e) });
  }
};
