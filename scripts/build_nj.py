#!/usr/bin/env python3
"""Hoboken + Jersey City condo buildings -> data/nj.json (same row shape as data/miami.json, plus st='NJ').

Buildings: NJ parcel composite with MOD-IV attributes (NJOGIS). Every condo unit is its own record with a
'C' qualifier on the building's block/lot, so grouping units by block/lot gives the building, its unit count
and year built.
Sales: NJ Treasury SR-1A deed file (Sales<year>.zip + YTD file), last 12 months by recording date,
condo-qualified units, state-usable sales. Buyer/seller names are never read.
FHA: data/fha.json rows for NJ / Hudson County (pull_fha.py).
"""
import collections, datetime as dt, io, json, re, statistics, sys, time, urllib.parse, urllib.request, zipfile

UA = {'User-Agent': 'Mozilla/5.0 pocketapproval'}
FS = 'https://services2.arcgis.com/XVOqAjTOJ5P6ngMu/arcgis/rest/services/Parcels_Composite_NJ_WM/FeatureServer/0/query'
MUNS = {'0905': ('Hoboken', '05'), '0906': ('Jersey City', '06')}   # parcel PCL_MUN -> (city, SR-1A district in county 09)
SR1A = 'https://www.nj.gov/treasury/taxation/lpt/statdata/'

def log(*a): print(*a, file=sys.stderr, flush=True)

def get(u, tries=5):
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=300).read()
        except Exception as e:
            log('retry', i + 1, u[:90], e); time.sleep(5 * (i + 1))
    raise RuntimeError('failed ' + u)

SUF = {'STREET': 'ST', 'AVENUE': 'AVE', 'AV': 'AVE', 'PLACE': 'PL', 'DRIVE': 'DR', 'ROAD': 'RD', 'BOULEVARD': 'BLVD', 'TERRACE': 'TER',
       'COURT': 'CT', 'LANE': 'LN', 'PLAZA': 'PLZ', 'EAST': 'E', 'WEST': 'W', 'NORTH': 'N', 'SOUTH': 'S'}
def street_key(a):
    a = re.sub(r'[^A-Z0-9 ]', ' ', (a or '').upper())
    a = re.sub(r'\b(UNIT|APT|STE|SUITE|PH|#|NO)\b.*$', '', a)
    w = [SUF.get(x, x) for x in a.split()]
    return ' '.join(re.sub(r'^(\d+)(ST|ND|RD|TH)$', r'\1', x) for x in w).strip()

EXP = {'ST': 'Street', 'AVE': 'Avenue', 'AV': 'Avenue', 'PL': 'Place', 'DR': 'Drive', 'RD': 'Road', 'BLVD': 'Boulevard', 'TER': 'Terrace',
       'CT': 'Court', 'LN': 'Lane', 'PLZ': 'Plaza', 'HWY': 'Highway', 'PKWY': 'Parkway', 'SQ': 'Square'}
def pretty(a):
    out = []
    ws = re.sub(r'\.', ' ', str(a)).upper().split()
    for i, w in enumerate(ws):
        if w == 'ST' and i < len(ws) - 1 and i > 0: out.append('St.')   # Saint, e.g. St. Pauls Ave
        elif i > 0 and w in EXP: out.append(EXP[w])
        elif re.fullmatch(r'\d+(ST|ND|RD|TH)', w): out.append(w.lower())
        elif re.fullmatch(r'[\d\-]+[A-Z]?', w): out.append(w)
        else: out.append(w.capitalize())
    return ' '.join(out)

def addresses(loc):
    """'659 1ST/85-89 HARRISON ST' -> ['659 1st St', '85-89 Harrison Street', '85 Harrison Street'] (best effort)."""
    parts = [p.strip() for p in re.split(r'/|&|;', loc or '') if p.strip()]
    out = []
    for p in parts:
        if not re.match(r'^\d', p): continue
        out.append(p)
        m = re.match(r'^(\d+)-\d+\s+(.*)$', p)
        if m: out.append(m.group(1) + ' ' + m.group(2))
    return out

def blk(b, suf=''):
    b = (b or '').strip().lstrip('0') or '0'
    s = (suf or '').strip().strip('.').lstrip('0')
    return b + ('.' + s if s else '')

def pblk(x):
    x = (x or '').strip(); b, _, suf = x.partition('.')
    return blk(b, suf)

def main():
    # ---- condo units from the parcel composite ----
    units = collections.defaultdict(list)
    for mun in MUNS:
        off = 0
        while True:
            p = {'where': "PCL_MUN='%s' AND PCLQCODE LIKE 'C%%' AND PROP_CLASS='2'" % mun,
                 'outFields': 'PCLBLOCK,PCLLOT,PCLQCODE,PROP_LOC,YR_CONSTR,ZIP5,SALE_PRICE,DEED_DATE',
                 'orderByFields': 'OBJECTID', 'resultOffset': off, 'resultRecordCount': 2000, 'returnGeometry': 'false', 'f': 'json'}
            r = json.loads(get(FS + '?' + urllib.parse.urlencode(p)))
            feats = r.get('features', [])
            for f in feats:
                a = f['attributes']
                units[(mun, pblk(a['PCLBLOCK']), pblk(a['PCLLOT']))].append(a)
            off += len(feats)
            if not feats or not r.get('exceededTransferLimit') and len(feats) < 2000: break
        log(MUNS[mun][0], 'condo units so far', sum(len(v) for k, v in units.items() if k[0] == mun))

    # ---- SR-1A sales, last 12 months ----
    today = dt.date.today(); since = today - dt.timedelta(days=365)
    files = ['Sales%d.zip' % (today.year - 1), 'Sales%d.zip' % today.year, 'YTDSR1A%d.zip' % today.year]
    seen = set()
    sales = collections.defaultdict(list); latest_rec = ''; dbg = []; dbg_done = False
    dist = {v[1]: k for k, v in MUNS.items()}
    for fn in files:
        try:
            z = zipfile.ZipFile(io.BytesIO(get(SR1A + fn)))
        except Exception as e:
            log('skip', fn, e); continue
        for name in z.namelist():
            for line in z.read(name).decode('latin-1').splitlines():
                if line[0:2] != '09' or line[2:4] not in dist: continue
                q = line[619:624].strip()
                if not q.upper().startswith('C') or line[626:628].strip() != '2': continue
                rec = line[344:350]
                try: rd = dt.date(2000 + int(rec[0:2]), int(rec[2:4]), int(rec[4:6]))   # YYMMDD
                except ValueError: continue
                if rd < since: continue
                try: price = int(line[37:46] or 0)
                except ValueError: continue
                usable = line[33:34] == 'U'
                if price < 50000: continue
                key = (dist[line[2:4]], blk(line[350:355], line[355:359]), blk(line[359:364], line[364:368]))
                sig = (key, q, rd, price)
                if sig in seen: continue
                seen.add(sig)
                sales[key].append({'p': price, 'd': rd.isoformat(), 'u': usable, 'q': q})
                latest_rec = max(latest_rec, rd.isoformat())
    log('SR-1A condo sales in window', sum(len(v) for v in sales.values()), 'latest recorded', latest_rec)

    # ---- HUD FHA (NJ) ----
    fha = collections.defaultdict(list)
    try:
        for f in json.load(open('data/fha.json'))['rows']:
            if f.get('state') == 'NJ':
                for part in re.split(r',|&', f['street']): fha[(street_key(part), f['zip'])].append(f)
    except Exception as e:
        log('no fha', e)

    out = []
    for key, us in units.items():
        if len(us) < 3: continue
        mun, b_, l_ = key
        locs = collections.Counter((u.get('PROP_LOC') or '').strip() for u in us if u.get('PROP_LOC'))
        loc = locs.most_common(1)[0][0] if locs else ''
        addrs = addresses(loc) or ([loc] if loc else [])
        if not addrs: continue
        zips = collections.Counter(u.get('ZIP5') for u in us if (u.get('ZIP5') or '').startswith('07'))
        z = zips.most_common(1)[0][0] if zips else ''
        yrs = collections.Counter(u.get('YR_CONSTR') for u in us if u.get('YR_CONSTR'))
        ss = sales.get(key, [])
        us_ = [s for s in ss if s['u']] or ss
        row = {'a': pretty(addrs[0]), 'aa': [pretty(x) for x in addrs[1:4]], 'c': MUNS[mun][0], 'z': z, 'u': len(us),
               'y': yrs.most_common(1)[0][0] if yrs else None, 't': 'Condo', 'st': 'NJ', 'blk': b_, 'lot': l_,
               's': len(ss), 'sq': sum(1 for s in ss if s['u']),
               'sp': int(statistics.median(s['p'] for s in us_)) if us_ else None,
               'sl': max((s['d'][:7] for s in ss), default=None)}
        for a in addrs:
            f = fha.get((street_key(a), z))
            if f:
                f = sorted(f, key=lambda r: r['statusDate'], reverse=True)[0]
                row['fha'] = {'id': f['id'], 'status': f['status'], 'method': f['method'], 'exp': f['expires'], 'date': f['statusDate']}
                break
        out.append(row)
    out.sort(key=lambda r: -r['u'])
    meta = {'source': 'NJ parcels with MOD-IV tax list (NJOGIS), NJ Treasury SR-1A deed file, HUD FHA condo list',
            'count': len(out), 'withFha': sum(1 for r in out if 'fha' in r), 'salesSince': since.isoformat(), 'salesThrough': latest_rec,
            'byCity': dict(collections.Counter(r['c'] for r in out))}
    json.dump({'meta': meta, 'rows': out}, open('data/nj.json', 'w'), separators=(',', ':'))
    log('wrote data/nj.json', meta)
    for r in out[:15]: log(' ', r['a'], r['c'], r['z'], r['u'], 'units', r['y'], 'sales', r['s'], r['sp'], r.get('fha', {}).get('status'))

if __name__ == '__main__':
    main()
