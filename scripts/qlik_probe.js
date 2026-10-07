// Probe DBPR's public Qlik Sense SIRS apps from inside a real browser session (anonymous access needs the page's cookies).
const { chromium } = require('playwright');
const HOST = 'dbpr-publicrecords.myfloridalicense.com';
const APPS = { pre2025: ['14f1ed21-7b21-4272-af14-9eaad7911440', 'mcprvJW'], post2025: ['d217126f-2edc-408b-bb98-2c355b6f0429', 'HUGAcyE'] };
(async () => {
  const b = await chromium.launch(); const p = await b.newPage();
  let lastWs='';p.on('websocket', ws => { if (ws.url().includes('csrf')) lastWs = ws.url(); });
  for (const [name, [app, sheet]] of Object.entries(APPS)) {
    await p.goto(`https://${HOST}/qpr/single/?appid=${app}&sheet=${sheet}&opt=ctxmenu&select=clearall`, { waitUntil: 'networkidle', timeout: 90000 }).catch(e => console.log('goto', e.message));
    await p.waitForTimeout(8000);
    const out = await p.evaluate(async ({ HOST, app, wsUrl }) => {
      const ws = new WebSocket(wsUrl);
      let id = 0; const pend = new Map();
      ws.onmessage = m => { const j = JSON.parse(m.data); if (j.id && pend.has(j.id)) { pend.get(j.id)(j); pend.delete(j.id); } };
      await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej('ws error'); setTimeout(() => rej('timeout'), 20000); });
      const call = (handle, method, params) => new Promise(res => { const i = ++id; pend.set(i, res); ws.send(JSON.stringify({ jsonrpc: '2.0', id: i, handle, method, params })); });
      const doc = await call(-1, 'OpenDoc', [app]);
      if (doc.error) return 'OpenDoc error ' + JSON.stringify(doc.error);
      const h = doc.result.qReturn.qHandle;
      const tk = await call(h, 'GetTablesAndKeys', [{ qcx: 1000, qcy: 1000 }, { qcx: 0, qcy: 0 }, 30, true, false]);
      if (tk.error) return 'GTK error ' + JSON.stringify(tk.error);
      return tk.result.qtr.map(t => t.qName + ' rows=' + t.qNoOfRows + ' :: ' + t.qFields.map(f => f.qName).join(' | ')).join('\n');
    }, { HOST, app, wsUrl: lastWs }).catch(e => 'eval fail ' + e);
    console.log('APP', name, '\n' + out);
  }
  await b.close(); process.exit(0);
})();
