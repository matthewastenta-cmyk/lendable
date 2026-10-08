"""Spend a few API units to see what a condo unit's Official Records look like (mortgages, lenders).
Picks recent qualified condo sales from the state sales file. Borrower names are masked in the log."""
import csv, io, json, os, re, sys, urllib.parse, urllib.request, zipfile
key = os.environ["CLERK_AUTH_KEY"].strip(); proxy = os.environ["CLERK_PROXY_URL"].strip()
direct = urllib.request.build_opener()
via = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
N = int(os.environ.get("N", "5"))
SDF = "https://floridarevenue.com/property/dataportal/Documents/PTO%20Data%20Portal/Tax%20Roll%20Data%20Files/SDF/2026P/Dade%2023%20Preliminary%20SDF%202026.zip"
z = zipfile.ZipFile(io.BytesIO(direct.open(urllib.request.Request(SDF, headers={"User-Agent": "Mozilla/5.0"}), timeout=300).read()))
rows = list(csv.DictReader(io.TextIOWrapper(z.open([n for n in z.namelist() if n.lower().endswith((".csv", ".txt"))][0]), encoding="latin-1")))
print("sdf columns:", list(rows[0].keys())[:30])
cands = [r for r in rows if (r.get("DOR_UC") or "").strip() in ("004", "04") and (r.get("QUAL_CD") or "").strip() in ("01", "1")
         and int(r.get("SALE_YR") or 0) >= 2026 and int(float(r.get("SALE_PRC") or 0)) > 400000]
print("candidate recent condo sales:", len(cands))
cands = [r for r in cands if 600000 < int(float(r["SALE_PRC"])) < 3000000]; cands.sort(key=lambda r: -int(float(r["SALE_PRC"])))
seen = 0
for r in cands[:N]:
    folio = r["PARCEL_ID"].strip()
    q = urllib.parse.urlencode({"parameter1": folio, "parameter2": "FN", "authKey": key})
    body = via.open(urllib.request.Request("https://www2.miamidadeclerk.gov/Developers/api/OfficialRecords?" + q, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"}), timeout=60).read().decode("utf-8", "replace")
    j = json.loads(body)
    if not seen:
        def shape(v, d=0):
            if isinstance(v, dict): return {k: shape(x, d+1) for k, x in list(v.items())[:40]} if d < 3 else "{...}"
            if isinstance(v, list): return [len(v), shape(v[0], d+1) if v else None]
            return type(v).__name__
        print("RAW SHAPE:", json.dumps(shape(j))[:3000])
    recs = j.get("OfficialRecordList") or []
    if isinstance(recs, dict): recs = next((v for v in recs.values() if isinstance(v, list)), [recs])
    print("\nfolio", folio[:9] + "....", "sale", r["SALE_YR"], r["SALE_MO"], r["SALE_PRC"], "| status", j.get("Status"), j.get("StatusDesc"), "| balance", j.get("UnitsBalance"), "| records", len(recs))
    if recs and not seen:
        print("fields:", sorted(recs[0].keys())); seen = 1
    for x in sorted(recs, key=lambda x: str(x.get("REC_DATE")), reverse=True)[:8]:
        dt = x.get("DOC_TYPE"); first = x.get("FIRST_PARTY") or ""; second = x.get("SECOND_PARTY") or ""
        if not re.search(r"MOR|MTG", str(dt), re.I):
            first = first[:3] + "***"  # mask names on non-mortgage docs
        else:
            first = first[:3] + "***"  # borrower on a mortgage is the first party; mask it
        print("  ", x.get("REC_DATE"), dt, "| 1st:", first, "| 2nd:", second[:60], "| amt:", x.get("CONSIDERATION_1") or x.get("CONSIDERATION") or x.get("DOCUMENTARY_STAMPS"))
