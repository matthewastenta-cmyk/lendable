#!/usr/bin/env python3
"""Weekly NYC lender refresh from ACRIS (NYC Open Data), Manhattan, Bronx, Brooklyn, Queens.

Financed closing =
  condo: a DEED (consideration >= $50k) on a residential condo unit (property type SC), with a MTGE
         on the same borough/block/lot recorded -10..+45 days from the deed.
  co-op: an RPTT filing (consideration >= $50k) on a co-op unit (SP), with an INIC (co-op UCC-1)
         on the same borough/block/lot/unit recorded -45..+60 days from the RPTT.
Lender = party 2 on that mortgage / UCC-1. MERS-only -> lender not identified. Individuals ->
"Private lender (individual)". Buyer/seller names are never read or stored.

Also: Bronx condo/co-op buildings from MapPLUTO are merged into buildings-db.json, tax lien sale
certificates (TLS) are counted per building, and a verification report vs. the previous lender data
(embedded in index.html) is written to /tmp/acris_report.txt.
"""
import os, json, re, sys, time, difflib, datetime as dt, urllib.request, urllib.parse, collections

B = 'https://data.cityofnewyork.us/resource/'
RP_MASTER, RP_LEGALS, RP_PARTIES = 'bnx9-e6tj', '8h5j-fqxa', '636b-3b5g'
PP_MASTER, PP_LEGALS, PP_PARTIES = 'sv7x-dduq', 'uqqa-hym2', 'nbbg-wtuz'
PLUTO = '64uk-42ks'
BOROS = ['Manhattan', 'Brooklyn', 'Queens', 'Bronx']          # app borough index order
ACRIS_BORO = {'1': 0, '3': 1, '4': 2, '2': 3}                    # ACRIS borough code -> app index
PLUTO_BORO = {'MN': 0, 'BK': 1, 'QN': 2, 'BX': 3}
MIN_PRICE = 50000
SUBSIDY = re.compile(r'HDFC|HOUSING DEVELOPMENT FUND|\bOWNERS\b|TENANTS CORP|APARTMENTS? CORP|APARTMENT OWNERS|^\s*\d[\d\- ]*.*\b(CORP|INC|LLC|OWNERS|HOUSING|REALTY|ASSOCIATES)\b|LENDER \d|HOUSING PRESERVATION|HOUSING DEVELOPMENT CORP|ENERGY EFFICIENCY|NYCEEC|HOUSING TRUST FUND|CITY OF NEW YORK|NEW YORK CITY HOUSING|\bHDC\b|\bHPD\b|DEPARTMENT OF HOUSING')
calls = 0

def log(*a):
    print(*a, flush=True)

def get(ds, params, tries=6):
    global calls
    u = B + ds + '.json?' + urllib.parse.urlencode(params)
    for i in range(tries):
        try:
            calls += 1
            with urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'pocketapproval-acris'}), timeout=180) as r:
                return json.load(r)
        except Exception as e:
            log('  retry', i + 1, ds, str(e)[:120]); time.sleep(5 * (i + 1))
    raise RuntimeError('failed ' + ds)

def paged(ds, where, select=None, order='document_id', page=50000):
    out, off = [], 0
    while True:
        p = {'$where': where, '$limit': page, '$offset': off, '$order': order}
        if select: p['$select'] = select
        rows = get(ds, p); out += rows; off += page
        if len(rows) < page: return out

def by_ids(ds, ids, extra='', select=None, n=150):
    ids = sorted(set(ids)); out = []
    for i in range(0, len(ids), n):
        w = 'document_id in(' + ','.join("'%s'" % x for x in ids[i:i + n]) + ')' + extra
        p = {'$where': w, '$limit': 50000}
        if select: p['$select'] = select
        out += get(ds, p)
    return out

def day(s): return (s or '')[:10]
def d(s): return dt.date.fromisoformat(s[:10])

# ---------------- address helpers ----------------
SUF = {'STREET': 'ST', 'AVENUE': 'AVE', 'AV': 'AVE', 'PLACE': 'PL', 'DRIVE': 'DR', 'ROAD': 'RD', 'BOULEVARD': 'BLVD', 'PARKWAY': 'PKWY',
       'TERRACE': 'TER', 'COURT': 'CT', 'LANE': 'LN', 'EAST': 'E', 'WEST': 'W', 'NORTH': 'N', 'SOUTH': 'S', 'CONCOURSE': 'CONC'}
def akey(num, street):
    s = (str(num or '') + ' ' + str(street or '')).upper()
    s = re.sub(r'[^A-Z0-9\- ]', ' ', s)
    w = [SUF.get(x, x) for x in s.split()]
    w = [re.sub(r'^(\d+)(ST|ND|RD|TH)$', r'\1', x) for x in w]
    return ' '.join(w)

def norm_js(s):  # mirror of index.html norm()
    s = str(s).lower()
    s = re.sub(r'\b(\d+)(st|nd|rd|th)\b', r'\1', s)
    s = re.sub(r'\bstreet\b', 'st', s); s = re.sub(r'\bavenue\b|\bav\b', 'ave', s); s = re.sub(r'\bplace\b', 'pl', s); s = re.sub(r'\bdrive\b', 'dr', s)
    s = re.sub(r'\beast\b', 'e', s); s = re.sub(r'\bwest\b', 'w', s); s = re.sub(r'\bnorth\b', 'n', s); s = re.sub(r'\bsouth\b', 's', s)
    return re.sub(r'[^a-z0-9]', '', s)

EXP = {'ST': 'Street', 'AVE': 'Avenue', 'AV': 'Avenue', 'PL': 'Place', 'DR': 'Drive', 'RD': 'Road', 'BLVD': 'Boulevard', 'PKWY': 'Parkway',
       'TER': 'Terrace', 'CT': 'Court', 'LN': 'Lane', 'E': 'East', 'W': 'West', 'N': 'North', 'S': 'South', 'CONC': 'Concourse', 'SQ': 'Square', 'HWY': 'Highway'}
def pretty(a):
    out = []
    for i, w in enumerate(str(a).upper().split()):
        if re.fullmatch(r'\d+', w) and i > 0:
            n = int(w); suf = 'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th'); out.append(w + suf)
        elif w in EXP and i > 0: out.append(EXP[w])
        elif re.fullmatch(r'[\d\-]+[A-Z]?', w): out.append(w)
        else: out.append(w.capitalize())
    return ' '.join(out)

# ---------------- lender names ----------------
DROP = {'BANK', 'N', 'A', 'NA', 'NATIONAL', 'ASSOCIATION', 'LLC', 'INC', 'CORP', 'CORPORATION', 'FSB', 'CO', 'COMPANY', 'THE', 'USA',
        'OF', 'ITS', 'SUCCESSORS', 'AND', 'OR', 'ASSIGNS', 'LTD', 'LP', 'F', 'S', 'B', 'DBA', 'D', 'A', 'AS', 'NOMINEE', 'FOR'}
BIZ = re.compile(r'\b(BANK|MORTGAGE|LENDING|LOAN|FUNDING|FINANCIAL|FINANCE|CAPITAL|CREDIT|SAVINGS|TRUST|LLC|INC|CORP|COMPANY|FEDERAL|ASSOCIATION|N\.?A\.?|FSB|HOME|GROUP|PARTNERS|FUND|HOLDINGS|REALTY|PROPERTIES|EQUITIES|LP|LTD|UNION|LOANS|BANC|BANCO|BANCORP|LENDER|LENDERS|MTG|FCU|CU|PLLC|ESTATE|TRUSTEE|INVESTMENTS?|VENTURES|SERVICES|CREDIT|BANK\w*|\w*BANK)\b')
ALIAS = {'JPMORGAN CHASE': 'JPMorgan Chase', 'CHASE': 'JPMorgan Chase', 'CITIBANK': 'Citibank', 'CITI': 'Citibank', 'WELLS FARGO': 'Wells Fargo',
         'QUICKEN LOANS': 'Rocket Mortgage', 'ROCKET MORTGAGE': 'Rocket Mortgage', 'UNITED WHOLESALE MORTGAGE': 'United Wholesale Mortgage',
         'MORGAN STANLEY PRIVATE': 'Morgan Stanley Private Bank', 'MORGAN STANLEY': 'Morgan Stanley Private Bank', 'HSBC': 'HSBC Bank USA',
         'TD': 'TD Bank', 'CITIZENS': 'Citizens Bank', 'BANK AMERICA': 'Bank of America', 'AMERICA': 'Bank of America', 'NATIONAL COOPERATIVE': 'National Cooperative Bank',
         'NCB': 'National Cooperative Bank', 'US': 'U.S. Bank', 'U S': 'U.S. Bank', 'FIRST REPUBLIC': 'First Republic Bank', 'PNC': 'PNC Bank',
         'GOLDMAN SACHS': 'Goldman Sachs Bank USA', 'GR AFFINITY': 'Guaranteed Rate Affinity', 'JP MORGAN CHASE': 'JPMorgan Chase', 'J P MORGAN CHASE': 'JPMorgan Chase', 'CROSS COUNTRY MORTGAGE': 'CrossCountry Mortgage', 'LOANDEPOT COM': 'loanDepot', 'STATE NEW YORK MORTGAGE AGENCY': 'SONYMA (State of New York Mortgage Agency)', 'CMG MORTGAGE': 'CMG Home Loans', 'BARRINGTON TRUST': 'Wintrust Mortgage (Barrington Bank & Trust)', 'FIRST CITIZENS': 'First Citizens Bank', 'BMO': 'BMO Bank', 'BMO HARRIS': 'BMO Bank', 'NEW YORK UNIVERSITY FEDERAL CREDIT UNION': 'NYU Federal Credit Union', 'UBS': 'UBS Bank USA', 'M T': 'M&T Bank', 'MANUFACTURERS TRADERS TRUST': 'M&T Bank'}
def core(n):
    s = str(n).upper()
    s = re.sub(r'\b(DBA|D/B/A|AKA|F/K/A|FKA|I/L/T/L/N|I/L/T/N|ISAOA|ATIMA|ITS SUCCESSORS)\b.*$', '', s)
    s = re.sub(r'[^A-Z0-9 ]', ' ', s.replace('&', ' '))
    return ' '.join(w for w in s.split() if w not in DROP)

def build_namer(canon):
    table = {}
    for c in canon: table.setdefault(core(c), c)
    for k, v in ALIAS.items(): table[core(k) if core(k) else k] = v
    keys = sorted(table, key=len, reverse=True)
    def name(raw):
        r = str(raw).upper()
        if 'ELECTRONIC REGISTRATION' in r or re.fullmatch(r'\s*MERS\b.*', r): return None
        if ('SECRETARY OF HOUSING' in r or 'HOUSING AND URBAN' in r): return None
        c = core(r)
        if c in table: return table[c]
        for k in keys:
            if k and (c.startswith(k + ' ') or c == k): return table[k]
        for k in keys:
            if len(c) >= 5 and k.startswith(c + ' '): return table[k]
        best = difflib.get_close_matches(c, keys, n=1, cutoff=0.88) if len(c) >= 6 else []
        if best: return table[best[0]]
        if not BIZ.search(r) and (',' in r or (2 <= len(r.split()) <= 4 and not re.search(r'\d', r))): return 'Private lender (individual)'
        r = re.sub(r'\s*\b(DBA|D/B/A|I/L/T/L/N|I/L/T/N|ISAOA|ATIMA)\b.*$', '', r).strip(' ,.')
        r2 = re.sub(r'[,.]?\s*\b(N\.?A\.?|ISAOA.*|ATIMA.*|INC\.?|CORP\.?|CORPORATION|L\.?L\.?C\.?)\s*$', '', r.strip()).strip(' ,.')
        return ' '.join(w if w in ('USA', 'CMG', 'NYC', 'NY') else w.capitalize() for w in r2.split())
    return name

def main():
    t0 = time.time()
    html = open('index.html', encoding='utf-8').read()
    m = re.search(r'<script id="buildings-data" type="application/json">(.*?)</script>', html, re.S)
    OLD = json.loads(m.group(1)) if m else {'lenders': [], 'rows': []}
    namer = build_namer(OLD.get('lenders', []))

    # ---- window: last 24 months (WINDOW_DAYS) of what ACRIS has published ----
    latest = get(RP_MASTER, {'$select': 'max(recorded_datetime) as m', '$where': "doc_type='DEED'"})[0]['m'][:10]
    end = d(latest); start = end - dt.timedelta(days=int(os.environ.get('WINDOW_DAYS', '730'))); pre = start - dt.timedelta(days=60)
    log('ACRIS published through', latest, '| window', start, '->', end)
    idlo = pre.strftime('%Y%m%d')

    # ---- PLUTO: condo + co-op buildings in the four boroughs ----
    sel = 'borough,block,lot,bbl,address,zipcode,bldgclass,numfloors,unitsres,yearbuilt,histdist,landmark,ownername'
    pl = paged(PLUTO, "borough in('MN','BK','QN','BX') AND (bldgclass like 'R%' OR bldgclass in('D4','C6','D0','C8','D9','D7'))", select=sel, order='bbl')
    log('PLUTO condo/co-op lots', len(pl))
    # ---- flags from the tax-lot owner: HDFC co-ops and land held by a ground lessor ----
    HDFC_RX = re.compile(r'HOUS\w*\.?\s+DEV\w*\.?\s+F(UN)?D|\bH\.?\s?D\.?\s?F\.?\s?C\b|HSG\.?\s+DEV\w*\.?\s+F(UN)?D', re.I)
    LESSORS = [(re.compile(rx, re.I), nm) for rx, nm in [
        (r'BATTERY PARK CITY|HUGH L\.? CAREY', 'Battery Park City Authority'),
        (r'ROOSEVELT IS(LAND)?\b|\bRIOC\b', 'Roosevelt Island Operating Corporation'),
        (r'URBAN DEV(ELOPMENT)? CORP|NYS URBAN DEV|EMPIRE STATE DEV', 'NYS Urban Development Corporation'),
        (r'HUDSON RIVER PARK', 'Hudson River Park Trust'),
        (r'BROOKLYN BRIDGE PARK', 'Brooklyn Bridge Park Corporation'),
        (r'QUEENS WEST DEV', 'Queens West Development Corporation'),
    ]]
    flags = {}
    for p in pl:
        own = (p.get('ownername') or '').strip()
        f = {}
        if HDFC_RX.search(own): f['h'] = 1
        for rx, nm in LESSORS:
            if rx.search(own): f['g'] = nm; break
        blk = (p['borough'], int(p['block']))
        if blk == ('MN', 16): f['g'] = 'Battery Park City Authority'
        elif blk == ('MN', 1373): f['g'] = 'Roosevelt Island Operating Corporation'
        if f: flags[str(int(float(p['bbl'])))] = f
    log('flags: HDFC', sum(1 for v in flags.values() if v.get('h')), '| land owner / ground lessor', sum(1 for v in flags.values() if v.get('g')),
        collections.Counter(v['g'] for v in flags.values() if v.get('g')).most_common())
    byblock = collections.defaultdict(list); bybbl = {}
    for p in pl:
        bi = PLUTO_BORO[p['borough']]; p['_b'] = bi; p['_k'] = akey('', p.get('address', ''))
        byblock[(bi, int(p['block']))].append(p); bybbl[(bi, int(p['block']), int(p['lot']))] = p

    def building_for(bi, block, lot, num, street):
        p = bybbl.get((bi, block, lot))
        if p: return p
        if lot < 1001: return None   # block fallback only for condo unit lots
        c = byblock.get((bi, block)) or []
        cc = [x for x in c if x['bldgclass'].startswith('R')]
        if len(cc) == 1: return cc[0]
        k = akey(num, street)
        for x in cc:
            if x['_k'] == k: return x
        if k:
            for x in cc:
                if x['_k'].split(' ', 1)[-1] == k.split(' ', 1)[-1] and x['_k'].split(' ')[0] == k.split(' ')[0]: return x
        return None

    # ---- ground leases recorded in ACRIS: leases / memoranda of lease where the building's co-op or condo is the tenant ----
    try:
        RES_LESSEE = re.compile(r'OWNERS\s+(CORP|INC|ASSOC)|APARTMENT\s+OWNERS|APARTMENTS?\s+(CORP|INC|OWNERS)|TENANTS?\s+(CORP|INC)|HOUSING\s+CORP|COOPERATIVE|CO-?OP\b|CONDOMINIUM|BOARD OF MANAGERS|HOUSING DEV\w*\s+FUND|\bHDFC\b|MUTUAL\s+(HOUSING|REDEVELOPMENT)', re.I)
        lm = paged(RP_MASTER, "doc_type in('LEAS','MLEA')", select='document_id,doc_type,document_date,recorded_datetime')
        log('ACRIS leases / memoranda of lease', len(lm))
        lmm = {r['document_id']: r for r in lm}
        ll = by_ids(RP_LEGALS, list(lmm), select='document_id,borough,block,lot,street_number,street_name', n=200)
        hit = collections.defaultdict(set)
        for r in ll:
            bi = ACRIS_BORO.get(str(r.get('borough')))
            if bi is None: continue
            try: blk, lot = int(r['block']), int(r['lot'])
            except Exception: continue
            pp = building_for(bi, blk, lot, r.get('street_number'), r.get('street_name'))
            if pp and (pp['bldgclass'][:1] in 'RCD'): hit[str(int(float(pp['bbl'])))].add(r['document_id'])
        ids = sorted({x for v in hit.values() for x in v})
        log('lease docs on condo/co-op lots', len(ids), 'buildings', len(hit))
        pts = by_ids(RP_PARTIES, ids, select='document_id,party_type,name', n=200) if ids else []
        lessor, lessee = collections.defaultdict(list), collections.defaultdict(list)
        for r in pts:
            (lessor if str(r.get('party_type')) == '1' else lessee)[r['document_id']].append((r.get('name') or '').strip())
        gl = 0
        for bbl, docs in hit.items():
            best = None
            for did in docs:
                tenants = lessee.get(did, []); owners = lessor.get(did, [])
                if not any(RES_LESSEE.search(t) for t in tenants): continue        # a store or office lease, not the building
                if any(RES_LESSEE.search(o) for o in owners) and not any(not RES_LESSEE.search(o) for o in owners): continue   # building leasing out its own space
                dd = (lmm[did].get('document_date') or lmm[did].get('recorded_datetime') or '')[:4]
                if not best or dd > best[1]: best = (owners[0] if owners else 'a separate land owner', dd)
            if best:
                f = flags.setdefault(bbl, {})
                if not f.get('g'): f['g'] = ' '.join(w.capitalize() if not re.fullmatch(r'(LLC|LP|L\.P\.|INC|CORP|II|III|NY|NYC)', w) else w for w in best[0].split()); f['gy'] = best[1]; f['gs'] = 'acris'; gl += 1
        log('ground leases from ACRIS', gl)
    except Exception as e:
        log('ground lease scan skipped:', str(e)[:200])
    json.dump({'source': 'NYC MapPLUTO owner names; ACRIS leases and memoranda of lease', 'asOf': dt.date.today().isoformat(), 'flags': flags}, open('data/nyc_flags.json', 'w'), separators=(',', ':'))

    # ---- real property: sales + mortgages + tax lien sale certs ----
    where = "recorded_datetime >= '%s' AND recorded_datetime <= '%sT23:59:59' AND doc_type in('DEED','MTGE','RPTT','RPTT&RET','TLS')" % (pre, end)
    master = paged(RP_MASTER, where, select='document_id,doc_type,document_amt,recorded_datetime')
    mm = {r['document_id']: r for r in master}
    log('RP master docs', len(master), collections.Counter(r['doc_type'] for r in master))
    leg = paged(RP_LEGALS, "property_type in('SC','SP') AND document_id >= '%s' AND document_id < '3'" % idlo,
                select='document_id,borough,block,lot,property_type,street_number,street_name,unit')
    log('RP legals SC/SP', len(leg))
    tls_ids = [i for i, r in mm.items() if r['doc_type'] == 'TLS']
    tls_leg = by_ids(RP_LEGALS, tls_ids, select='document_id,borough,block,lot') if tls_ids else []
    log('TLS docs', len(tls_ids), 'legals', len(tls_leg))

    sales, mtg = [], collections.defaultdict(list)
    seen_sale = set()
    for L in leg:
        r = mm.get(L['document_id'])
        if not r or L.get('borough') not in ACRIS_BORO: continue
        bi = ACRIS_BORO[L['borough']]; blk = int(L['block'] or 0); lot = int(L['lot'] or 0)
        unit = re.sub(r'[^A-Z0-9]', '', str(L.get('unit') or '').upper()).replace('APT', '')
        rec = day(r['recorded_datetime']); amt = float(r.get('document_amt') or 0)
        if r['doc_type'] == 'MTGE' and L['property_type'] == 'SC':
            mtg[(bi, blk, lot)].append((rec, L['document_id']))
        elif (r['doc_type'] == 'DEED' and L['property_type'] == 'SC') or (r['doc_type'] in ('RPTT', 'RPTT&RET') and L['property_type'] == 'SP'):
            if amt < MIN_PRICE or d(rec) < start: continue
            key = (L['document_id'])
            if key in seen_sale: continue
            seen_sale.add(key)
            sales.append(dict(id=L['document_id'], bi=bi, blk=blk, lot=lot, unit=unit, rec=rec, amt=amt, coop=L['property_type'] == 'SP',
                              num=L.get('street_number'), st=L.get('street_name')))
    log('sales in window', len(sales), 'condo', sum(not s['coop'] for s in sales), 'co-op', sum(s['coop'] for s in sales))

    # ---- personal property: co-op UCC-1s ----
    pm = paged(PP_MASTER, "recorded_datetime >= '%s' AND recorded_datetime <= '%sT23:59:59' AND doc_type='INIC'" % (pre, end + dt.timedelta(days=60)),
               select='document_id,recorded_datetime')
    pmm = {r['document_id']: day(r['recorded_datetime']) for r in pm}
    pleg = paged(PP_LEGALS, "property_type='SP' AND document_id >= '%s' AND document_id < '3'" % idlo,
                 select='document_id,borough,block,lot,addr_unit')
    ucc = collections.defaultdict(list)
    for L in pleg:
        if L['document_id'] not in pmm or L.get('borough') not in ACRIS_BORO: continue
        unit = re.sub(r'[^A-Z0-9]', '', str(L.get('addr_unit') or '').upper()).replace('APT', '')
        ucc[(ACRIS_BORO[L['borough']], int(L['block'] or 0), int(L['lot'] or 0), unit)].append((pmm[L['document_id']], L['document_id']))
    log('co-op UCC1s', len(pm), 'with SP legal', sum(len(v) for v in ucc.values()))

    # ---- match sales to financing ----
    need_rp, need_pp = set(), set()
    for s in sales:
        c = []
        if s['coop']:
            for rec, i in ucc.get((s['bi'], s['blk'], s['lot'], s['unit']), []):
                dd = (d(rec) - d(s['rec'])).days
                if -45 <= dd <= 60: c.append((abs(dd), i))
            need_pp.update(i for _, i in c)
        else:
            for rec, i in mtg.get((s['bi'], s['blk'], s['lot']), []):
                dd = (d(rec) - d(s['rec'])).days
                if -10 <= dd <= 45: c.append((abs(dd), i))
            need_rp.update(i for _, i in c)
        s['fin'] = [i for _, i in sorted(c)] or None
    log('financed', sum(1 for s in sales if s['fin']), 'of', len(sales))

    def lenders_of(ds, ids):
        out = collections.defaultdict(list)
        for p in by_ids(ds, ids, extra=" AND party_type='2'", select='document_id,name'):
            out[p['document_id']].append(p.get('name', ''))
        return out
    lp = lenders_of(RP_PARTIES, need_rp); lp.update(lenders_of(PP_PARTIES, need_pp))
    raw_seen = collections.Counter()
    def lender(ids):
        # first identified purchase lender among the matching filings, nearest first; skip subsidy / energy / agency liens
        for i in ids:
            for n in lp.get(i, []):
                nm = namer(n); raw_seen[(n.upper().strip(), nm)] += 1
                if nm and not SUBSIDY.search(n.upper()): return nm
        return None

    # ---- aggregate per building ----
    agg = {}
    synth = {}
    unmapped = 0; um = collections.Counter(); um_s = []
    for s in sales:
        p = building_for(s['bi'], s['blk'], s['lot'], s['num'], s['st'])
        if not p and s.get('num') and s.get('st'):
            ak = akey(s['num'], s['st'])
            p = synth.setdefault((s['bi'], ak), {'_b': s['bi'], 'block': s['blk'], 'lot': 'A:' + ak, 'bbl': '0', 'address': ak,
                                                 'bldgclass': 'D4' if s['coop'] else 'RM', '_synth': True})
        if not p:
            unmapped += 1; um[s['bi']] += 1
            if len(um_s) < 15: um_s.append('%s %s/%s %s %s' % (BOROS[s['bi']], s['blk'], s['lot'], s.get('num'), s.get('st')))
            continue
        k = (p['_b'], int(p['block']), p['lot'] if p.get('_synth') else int(p['lot']))
        a = agg.setdefault(k, dict(p=p, sales=0, fin=0, unknown=0, latest='', lenders=collections.Counter(), coop=s['coop']))
        a['sales'] += 1
        if s.get('num') and s.get('st'): a.setdefault('al', collections.Counter())[akey(s['num'], s['st'])] += 1
        if s['fin']:
            a['fin'] += 1; a['latest'] = max(a['latest'], s['rec'])
            ln = lender(s['fin'])
            if ln: a['lenders'][ln] += 1
            else: a['unknown'] += 1
    tls = collections.Counter(); tls_last = {}
    for L in tls_leg:
        if L.get('borough') not in ACRIS_BORO: continue
        bi = ACRIS_BORO[L['borough']]; p = building_for(bi, int(L['block'] or 0), int(L['lot'] or 0), None, None)
        if not p: continue
        k = (p['_b'], int(p['block']), int(p['lot'])); tls[k] += 1
        tls_last[k] = max(tls_last.get(k, ''), day(mm[L['document_id']]['recorded_datetime']))
    log('sales mapped by ACRIS address only (no PLUTO lot)', sum(1 for _ in synth), 'buildings | unmapped', unmapped, dict(um)); log('  e.g.', um_s)

    # ---- addresses: reuse buildings-db.json naming, add Bronx rows ----
    db = json.load(open('buildings-db.json'))
    if 'Bronx' not in db['boroughs']: db['boroughs'].append('Bronx')
    hist = db['hist']
    db['rows'] = [r for r in db['rows'] if r[1] != 3]
    addr_by_bbl = {int(r[10]): r[0] for r in db['rows'] if r[10]}
    bx = 0
    for p in pl:
        if p['borough'] != 'BX' or p.get('bldgclass') not in ('R1', 'R2', 'R3', 'R4', 'R6', 'R9', 'RD', 'RM', 'RR', 'RX', 'RZ', 'D4', 'C6', 'D0', 'C8'): continue
        units = int(float(p.get('unitsres') or 0))
        if units < 3 or not p.get('address'): continue
        cls = p['bldgclass']; fl = int(float(p.get('numfloors') or 0)) or None
        elev = 1 if cls[0] == 'D' or cls == 'R4' else 0 if cls[0] == 'C' or cls == 'R2' else (1 if (fl or 0) >= 6 else None)
        h = p.get('histdist')
        if h and h not in hist: hist.append(h)
        db['rows'].append([pretty(p['address']), 3, int(p.get('zipcode') or 0), 0 if cls[0] == 'R' else 1, elev, fl, units,
                           int(p.get('yearbuilt') or 0) or None, hist.index(h) if h else -1, 1 if p.get('landmark') else 0, int(float(p['bbl'])), cls])
        bx += 1
    BXZ = {'10451': 'Concourse', '10452': 'Highbridge', '10453': 'Morris Heights', '10454': 'Mott Haven', '10455': 'Longwood', '10456': 'Morrisania',
           '10457': 'Tremont', '10458': 'Fordham', '10459': 'Longwood', '10460': 'West Farms', '10461': 'Westchester Square', '10462': 'Parkchester',
           '10463': 'Kingsbridge', '10464': 'City Island', '10465': 'Throgs Neck', '10466': 'Wakefield', '10467': 'Norwood', '10468': 'University Heights',
           '10469': 'Pelham Gardens', '10470': 'Woodlawn', '10471': 'Riverdale', '10472': 'Soundview', '10473': 'Clason Point', '10474': 'Hunts Point', '10475': 'Co-op City'}
    db['zipNames'].update({k: v for k, v in BXZ.items() if k not in db['zipNames']})
    db['source'] = db.get('source', 'NYC Department of City Planning MapPLUTO')
    for r in db['rows']:
        if r[10]: addr_by_bbl[int(r[10])] = r[0]
    json.dump(db, open('buildings-db.json', 'w'), separators=(',', ':'))
    log('Bronx condo/co-op buildings added', bx, '| total rows', len(db['rows']))

    # ---- output in the app's lender format ----
    names = []; idx = {}
    def li(n):
        if n not in idx: idx[n] = len(names); names.append(n)
        return idx[n]
    rows = []
    for k, a in agg.items():
        p = a['p']; bbl = int(float(p['bbl']))
        if a['fin'] == 0 and not tls.get(k): continue
        addr = addr_by_bbl.get(bbl) or pretty(p.get('address', ''))
        typ = 1 if p['bldgclass'][0] in 'CD' else 0
        rows.append([addr, p['_b'], typ, a['fin'], a['latest'] or '—', [[li(n), c] for n, c in a['lenders'].most_common()], a['unknown'], a['sales'],
                     [tls[k], tls_last[k]] if tls.get(k) else 0, bbl,
                     [pretty(x) for x, _ in a.get('al', collections.Counter()).most_common(4) if norm_js(pretty(x)) != norm_js(addr)][:3]])
    for k in tls:
        if k not in agg:
            p = bybbl.get(k)
            if p: rows.append([addr_by_bbl.get(int(float(p['bbl']))) or pretty(p.get('address', '')), p['_b'], 1 if p['bldgclass'][0] in 'CD' else 0, 0, '—', [], 0, 0, [tls[k], tls_last[k]], int(float(p['bbl'])), []])
    rows.sort(key=lambda r: (r[1], r[0]))
    mon = lambda x: x.strftime('%b %-d, %Y')
    out = {'source': 'NYC ACRIS via NYC Open Data', 'asOf': latest, 'window': mon(start) + ' – ' + mon(end), 'boroughs': BOROS,
           'cols': ['address', 'borough', 'type', 'financedClosings', 'latest', 'lenders[[i,count]]', 'lenderUnknown', 'salesChecked', 'taxLienSale[count,latest]|0', 'bbl', 'aliases'],
           'lenders': names, 'rows': rows}
    json.dump(out, open('data/nyc_lenders.json', 'w'), separators=(',', ':'))
    # refresh the copy embedded in index.html (the app reads it at startup)
    h = open('index.html', encoding='utf-8').read()
    blob = json.dumps(out, separators=(',', ':')).replace('</', '<\\/')
    h2 = re.sub(r'(<script id="buildings-data" type="application/json">)(.*?)(</script>)', lambda m_: m_.group(1) + blob + m_.group(3), h, count=1, flags=re.S)
    if h2 != h and len(rows) > 3000: open('index.html', 'w', encoding='utf-8').write(h2)
    log('wrote data/nyc_lenders.json', len(rows), 'buildings,', sum(r[3] for r in rows), 'financed closings,', len(names), 'lender names', '| calls', calls, '| %.0fs' % (time.time() - t0))

    # ---- verification vs previous data ----
    R = []
    R.append('ACRIS vs. previous lender data (Marketproof export)')
    R.append('ACRIS window: %s (published through %s)  | previous window: %s' % (out['window'], latest, OLD.get('window')))
    new = {}
    for r in rows:
        for a_ in [r[0]] + r[10]: new.setdefault(norm_js(a_), r)
    old = [r for r in OLD.get('rows', [])]
    found = [r for r in old if norm_js(r[0]) in new]
    R.append('Previous buildings: %d | found in ACRIS output: %d (%.1f%%)' % (len(old), len(found), 100 * len(found) / max(1, len(old))))
    for b in range(3):
        o = [r for r in old if r[1] == b]; f = [r for r in o if norm_js(r[0]) in new]
        oc = sum(r[3] for r in o); nc = sum(new[norm_js(r[0])][3] for r in f)
        R.append('  %-9s prev %5d bldgs / %5d closings | ACRIS found %5d bldgs, %5d closings on them | ACRIS total in boro: %5d bldgs, %5d closings' %
                 (BOROS[b], len(o), oc, len(f), nc, sum(1 for r in rows if r[1] == b and r[3]), sum(r[3] for r in rows if r[1] == b)))
    R.append('  Bronx     (new)  ACRIS: %d bldgs, %d closings' % (sum(1 for r in rows if r[1] == 3 and r[3]), sum(r[3] for r in rows if r[1] == 3)))
    agree = tot = 0; diffs = []
    for r in found:
        n = new[norm_js(r[0])]
        ol = {OLD['lenders'][i] for i, c in r[5]}; nl = {names[i] for i, c in n[5]}
        if not ol: continue
        tot += 1; inter = ol & nl
        if inter: agree += 1
        elif len(diffs) < 25: diffs.append('  %s | prev: %s | ACRIS: %s' % (r[0], ', '.join(sorted(ol)), ', '.join(sorted(nl)) or '(none identified)'))
    R.append('Lender agreement (buildings where previous data named a lender): at least one same lender in %d of %d (%.1f%%)' % (agree, tot, 100 * agree / max(1, tot)))
    R.append('Sample disagreements:'); R += diffs
    miss = [r for r in old if norm_js(r[0]) not in new][:25]
    R.append('Sample previous buildings not found in ACRIS output:'); R += ['  %s (%s) %d closings, latest %s' % (r[0], BOROS[r[1]], r[3], r[4]) for r in miss]
    R.append('Top raw lender names -> display name:')
    tops = collections.Counter()
    for (raw, nm), c in raw_seen.items(): tops[(raw, nm)] += c
    R += ['  %5d  %s  ->  %s' % (c, '(individual, name withheld)' if nm == 'Private lender (individual)' else raw[:60], nm) for (raw, nm), c in tops.most_common(60)]
    open('/tmp/acris_report.txt', 'w').write('\n'.join(R) + '\n')
    log('\n'.join(R[:12]))

if __name__ == '__main__':
    main()
