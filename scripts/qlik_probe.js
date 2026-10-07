// Probe DBPR's public Qlik Sense apps (SIRS database) and list their tables/fields.
const WebSocket = require('ws');
const HOST = 'dbpr-publicrecords.myfloridalicense.com';
const APPS = { pre2025: '14f1ed21-7b21-4272-af14-9eaad7911440', post2025: 'd217126f-2edc-408b-bb98-2c355b6f0429' };
async function cookie() {
  const r = await fetch(`https://${HOST}/qpr/single/?appid=${APPS.post2025}&sheet=HUGAcyE`, { redirect: 'manual' });
  const sc = r.headers.getSetCookie ? r.headers.getSetCookie() : [];
  console.log('page', r.status, r.headers.get('location'), sc.map(c => c.split(';')[0].split('=')[0]));
  return sc.map(c => c.split(';')[0]).join('; ');
}
function rpc(ws) { let id = 0; const pend = new Map();
  ws.on('message', m => { const j = JSON.parse(m); if (j.id && pend.has(j.id)) { const [res, rej] = pend.get(j.id); pend.delete(j.id); j.error ? rej(new Error(JSON.stringify(j.error))) : res(j.result); } else if (!j.id) console.log('notice', JSON.stringify(j).slice(0, 300)); });
  return (handle, method, params) => new Promise((res, rej) => { const i = ++id; pend.set(i, [res, rej]); ws.send(JSON.stringify({ jsonrpc: '2.0', id: i, handle, method, params })); }); }
(async () => {
  const ck = await cookie();
  for (const [name, app] of Object.entries(APPS)) {
    for (const prefix of ['qpr', '']) {
      const url = `wss://${HOST}${prefix ? '/' + prefix : ''}/app/${app}`;
      try {
        const ws = new WebSocket(url, { headers: { Cookie: ck, Origin: `https://${HOST}` } });
        await new Promise((res, rej) => { ws.on('open', res); ws.on('error', rej); setTimeout(() => rej(new Error('timeout')), 20000); });
        const call = rpc(ws);
        const doc = await call(-1, 'OpenDoc', [app]);
        const h = doc.qReturn.qHandle;
        const tk = await call(h, 'GetTablesAndKeys', [{ qcx: 1000, qcy: 1000 }, { qcx: 0, qcy: 0 }, 30, true, false]);
        console.log('APP', name, 'via', url);
        for (const t of tk.qtr) console.log(' table', t.qName, t.qNoOfRows, t.qFields.map(f => f.qName).join(' | '));
        ws.close(); break;
      } catch (e) { console.log('fail', name, url, String(e.message).slice(0, 200)); }
    }
  }
  process.exit(0);
})();
