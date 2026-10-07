// Pull Florida DBPR's public SIRS (Structural Integrity Reserve Study) database for South Florida.
// The data sits in public Qlik Sense apps; anonymous access needs a real browser session, so this runs Playwright in GitHub Actions.
const { chromium } = require('playwright');
const fs = require('fs');
const HOST = 'dbpr-publicrecords.myfloridalicense.com';
const COUNTIES = /^(MIAMI-DADE|MIAMI DADE|DADE|BROWARD|PALM BEACH)$/i;
const APPS = [
  { name: 'pre2025', app: '14f1ed21-7b21-4272-af14-9eaad7911440', sheet: 'mcprvJW', table: 'CTMHSIRSForm51' },
  { name: 'post2025', app: 'd217126f-2edc-408b-bb98-2c355b6f0429', sheet: 'HUGAcyE', table: 'SIRS' },
];
const SKIP = /Contact|Signature/i; // leave out personal contact details

(async () => {
  const b = await chromium.launch(); const p = await b.newPage();
  let wsUrl = ''; p.on('websocket', ws => { if (ws.url().includes('csrf')) wsUrl = ws.url(); });
  const out = { source: 'Florida DBPR SIRS Reporting Database (public)', pulled: new Date().toISOString().slice(0, 10), pre2025: [], post2025: [] };
  for (const a of APPS) {
    wsUrl = '';
    await p.goto(`https://${HOST}/qpr/single/?appid=${a.app}&sheet=${a.sheet}&opt=ctxmenu&select=clearall`, { waitUntil: 'networkidle', timeout: 120000 }).catch(() => {});
    for (let i = 0; i < 20 && !wsUrl; i++) await p.waitForTimeout(1000);
    const res = await p.evaluate(async ({ app, wsUrl, table, skip }) => {
      const ws = new WebSocket(wsUrl); let id = 0; const pend = new Map();
      ws.onmessage = m => { const j = JSON.parse(m.data); if (j.id && pend.has(j.id)) { pend.get(j.id)(j); pend.delete(j.id); } };
      await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej('ws error'); setTimeout(() => rej('timeout'), 30000); });
      const call = (handle, method, params) => new Promise(res => { const i = ++id; pend.set(i, res); ws.send(JSON.stringify({ jsonrpc: '2.0', id: i, handle, method, params })); });
      const doc = (await call(-1, 'OpenDoc', [app])).result.qReturn.qHandle;
      const tk = (await call(doc, 'GetTablesAndKeys', [{ qcx: 1000, qcy: 1000 }, { qcx: 0, qcy: 0 }, 30, true, false])).result.qtr;
      const t = tk.find(x => x.qName === table);
      const fields = t.qFields.map(f => f.qName).filter(f => !new RegExp(skip, 'i').test(f));
      const def = { qInfo: { qType: 'lendable-cube' }, qHyperCubeDef: { qDimensions: fields.map(f => ({ qDef: { qFieldDefs: [f] }, qNullSuppression: false })), qMeasures: [], qSuppressZero: false, qSuppressMissing: false, qInitialDataFetch: [] } };
      const obj = (await call(doc, 'CreateSessionObject', [def])).result.qReturn.qHandle;
      const lay = (await call(obj, 'GetLayout', [])).result.qLayout;
      const total = lay.qHyperCube.qSize.qcy, w = fields.length, step = Math.floor(10000 / w);
      const rows = [];
      for (let top = 0; top < total; top += step) {
        const r = await call(obj, 'GetHyperCubeData', ['/qHyperCubeDef', [{ qTop: top, qLeft: 0, qWidth: w, qHeight: Math.min(step, total - top) }]]);
        for (const row of r.result.qDataPages[0].qMatrix) { const o = {}; row.forEach((c, i) => { if (!c.qIsNull && c.qText !== '-') o[fields[i]] = c.qText; }); rows.push(o); }
      }
      ws.close(); return { total, fields, rows };
    }, { app: a.app, wsUrl, table: a.table, skip: SKIP.source }).catch(e => ({ error: String(e) }));
    if (res.error) { console.error(a.name, res.error); continue; }
    const countyKey = res.fields.find(f => /County/i.test(f));
    const keep = res.rows.filter(r => COUNTIES.test(String(r[countyKey] || '').trim()));
    console.error(a.name, 'total', res.total, 'south florida', keep.length, 'fields', res.fields.join('|'));
    out[a.name] = keep;
  }
  await b.close();
  if (out.pre2025.length + out.post2025.length < 100) { console.error('too few rows; not writing'); process.exit(1); }
  fs.mkdirSync('data', { recursive: true });
  fs.writeFileSync('data/sirs.json', JSON.stringify(out));
  process.exit(0);
})();
