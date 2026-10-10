#!/usr/bin/env python3
"""Philadelphia condo buildings + lenders -> data/philly.json (Miami row shape, st='PA').

Source: City of Philadelphia Department of Records, RTT_SUMMARY (every recorded document since 1999) via the
public Carto SQL API. Condo units carry a unit number on deeds and mortgages, so grouping by street address
gives the building; MORTGAGE grantees are the lenders. Blanket loans (one mortgage on many units) are skipped.
"""
import collections, datetime as dt, json, re, statistics, sys, time, urllib.parse, urllib.request

API = 'https://phl.carto.com/api/v2/sql?q='
DAYS = 730
def log(*a): print(*a, file=sys.stderr, flush=True)

def sql(q, tries=5):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(API + urllib.parse.quote(q), headers={'User-Agent': 'pocketapproval'}), timeout=300) as r:
                return json.load(r)['rows']
        except Exception as e:
            log('retry', i + 1, str(e)[:120]); time.sleep(5 * (i + 1))
    raise RuntimeError('carto failed')

SUF = {'STREET': 'ST', 'AVENUE': 'AVE', 'PLACE': 'PL', 'DRIVE': 'DR', 'ROAD': 'RD', 'BOULEVARD': 'BLVD', 'LANE': 'LN', 'TERRACE': 'TER', 'SQUARE': 'SQ', 'PARKWAY': 'PKWY'}
EXP = {'ST': 'Street', 'AVE': 'Avenue', 'PL': 'Place', 'DR': 'Drive', 'RD': 'Road', 'BLVD': 'Boulevard', 'LN': 'Lane', 'TER': 'Terrace', 'SQ': 'Square', 'PKWY': 'Parkway', 'CT': 'Court', 'WAY': 'Way'}
DIRS = {'N': 'North', 'S': 'South', 'E': 'East', 'W': 'West'}
def bkey(r):
    n = r.get('address_low'); s = (r.get('street_name') or '').strip().upper()
    if not n or not s: return None
    return ' '.join(x for x in [str(int(n)), (r.get('street_predir') or '').strip().upper(), s, SUF.get((r.get('street_suffix') or '').strip().upper(), (r.get('street_suffix') or '').strip().upper())] if x)
def pretty_addr(k):
    w = k.split(); out = [w[0]]
    for i, x in enumerate(w[1:], 1):
        if x in DIRS and i == 1: out.append(DIRS[x])
        elif re.fullmatch(r'\d+(ST|ND|RD|TH)', x): out.append(x.lower())
        elif i == len(w) - 1 and x in EXP: out.append(EXP[x])
        else: out.append(x.capitalize())
    return ' '.join(out)

CORP = re.compile(r'\b(BANK|BANCORP|SAVINGS|CREDIT UNION|FCU|MORTGAGE|LENDING|LOANS?|FUND(ING)?|FINANCIAL|FINANCE|CAPITAL|TRUST|LLC|L L C|INC|CORP|CO|COMPANY|LP|L P|N\s?A|FSB|ASSOCIATION|AGENCY|AUTHORITY|HOUSING|INVEST\w*|PARTNERS|HOLDINGS|GROUP|SERVICES|ENTERPRISES|ESTATE)\b')
NICE = {'JPMORGAN CHASE BANK': 'JPMorgan Chase', 'WELLS FARGO BANK': 'Wells Fargo', 'CITIBANK': 'Citibank', 'CITIZENS BANK': 'Citizens Bank', 'PNC BANK': 'PNC Bank',
        'TD BANK': 'TD Bank', 'BANK OF AMERICA': 'Bank of America', 'TRUIST BANK': 'Truist Bank', 'US BANK': 'U.S. Bank', 'U S BANK': 'U.S. Bank', 'ROCKET MORTGAGE': 'Rocket Mortgage',
        'UNITED WHOLESALE MORTGAGE': 'United Wholesale Mortgage', 'LOANDEPOTCOM': 'loanDepot', 'LOANDEPOT COM': 'loanDepot', 'WILMINGTON SAVINGS FUND SOCIETY': 'WSFS Bank', 'M&T BANK': 'M&T Bank', 'MANUFACTURERS AND TRADERS TRUST': 'M&T Bank',
        'SANTANDER BANK': 'Santander Bank', 'FULTON BANK': 'Fulton Bank', 'FIRST NATIONAL BANK OF PENNSYLVANIA': 'First National Bank of Pennsylvania'}
def lender(raw):
    names = [x.strip() for x in (raw or '').split(';') if x.strip()]
    names = [x for x in names if 'MORTGAGE ELECTRONIC REGISTRATION' not in x.upper()]
    if not names: return 'Lender not identified (MERS)'
    n = re.sub(r'[.,]', ' ', names[0].upper()); n = re.sub(r'\s+', ' ', n).strip()
    if not CORP.search(n): return 'Private lender (individual)'
    base = re.sub(r'\b(N A|NA|NATIONAL ASSOCIATION|LLC|L L C|INC|CORP|CORPORATION|FSB|THE)\b', '', n).strip()
    base = re.sub(r'\s+', ' ', base)
    for k, v in NICE.items():
        if base.startswith(k): return v
    return ' '.join(w.capitalize() if len(w) > 3 or w in ('BANK',) else (w if w in ('PNC', 'TD', 'WSFS', 'FCU', 'USA', 'PA') else w.capitalize()) for w in base.split())

def main():
    since = (dt.date.today() - dt.timedelta(days=DAYS)).isoformat()
    cols = "document_id,document_type,recording_date,address_low,street_predir,street_name,street_suffix,unit_num,condo_name,zip_code,grantees,total_consideration,property_count"
    rows, off = [], 0
    while True:
        q = ("SELECT %s FROM rtt_summary WHERE recording_date >= '%s' AND document_type IN ('DEED','MORTGAGE') "
             "AND (unit_num IS NOT NULL OR condo_name IS NOT NULL) ORDER BY cartodb_id LIMIT 20000 OFFSET %d") % (cols, since, off)
        page = sql(q); rows += page; off += 20000
        log('rows', len(rows))
        if len(page) < 20000: break
    B = collections.defaultdict(lambda: {'units': set(), 'deeds': [], 'mtg': [], 'zips': collections.Counter(), 'names': collections.Counter()})
    for r in rows:
        k = bkey(r)
        if not k: continue
        b = B[k]; u = (r.get('unit_num') or '').strip().upper()
        if u: b['units'].add(u)
        if r.get('zip_code'): b['zips'][str(r['zip_code'])[:5]] += 1
        if r.get('condo_name'): b['names'][r['condo_name'].strip()] += 1
        d = (r.get('recording_date') or '')[:10]
        if r['document_type'] == 'DEED':
            p = float(r.get('total_consideration') or 0)
            if p >= 50000: b['deeds'].append((d, u, p))
        elif (r.get('property_count') or 1) <= 2:
            b['mtg'].append((d, u, lender(r.get('grantees'))))
    out = []
    for k, b in B.items():
        if len(b['units']) < 3: continue
        lend = collections.Counter(l for _, _, l in b['mtg'])
        fin = cash = 0
        for d, u, p in b['deeds']:
            dd = dt.date.fromisoformat(d)
            if any(mu == u and -10 <= (dt.date.fromisoformat(md) - dd).days <= 45 for md, mu, _ in b['mtg']): fin += 1
            else: cash += 1
        name = b['names'].most_common(1)[0][0].title() if b['names'] else ''
        row = {'a': pretty_addr(k), 'aa': [name] if name else [], 'c': 'Philadelphia', 'z': b['zips'].most_common(1)[0][0] if b['zips'] else '',
               'u': len(b['units']), 'y': None, 't': 'Condo', 'st': 'PA', 's': len(b['deeds']),
               'sp': int(statistics.median(p for _, _, p in b['deeds'])) if b['deeds'] else None,
               'sl': max((d[:7] for d, _, _ in b['deeds']), default=None),
               'l': [[n, c] for n, c in lend.most_common()], 'fc': [fin, cash] if b['deeds'] else None}
        out.append(row)
    out.sort(key=lambda r: -r['u'])
    meta = {'source': 'City of Philadelphia Department of Records (RTT summary via OpenDataPhilly)', 'count': len(out), 'mortgagesSince': since,
            'withLenders': sum(1 for r in out if r['l']), 'docs': len(rows)}
    json.dump({'meta': meta, 'rows': out}, open('data/philly.json', 'w'), separators=(',', ':'))
    log('wrote data/philly.json', meta)
    for r in out[:15]: log(' ', r['a'], r['aa'], r['u'], 'units', 'sales', r['s'], r['fc'], r['l'][:4])
    log('top lenders', collections.Counter(n for r in out for n, c in r['l'] for _ in range(c)).most_common(25))

if __name__ == '__main__':
    main()
