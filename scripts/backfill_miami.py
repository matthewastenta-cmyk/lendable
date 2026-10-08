"""One-time, budget-capped backfill: for the busiest condo buildings in chosen ZIPs, look up the most recent
sold units with the Clerk's per-folio API ($0.20 each) and record whether each sale was financed and by whom.
Writes data/miami_backfill.json. Borrower/buyer names are never stored."""
import csv, datetime, io, json, os, re, sys, urllib.parse, urllib.request, zipfile
import xml.etree.ElementTree as ET

KEY = os.environ["CLERK_AUTH_KEY"].strip(); PROXY = os.environ["CLERK_PROXY_URL"].strip()
ZIPS = os.environ.get("ZIPS", "33131,33129,33130,33132,33137").split(",")
BUILDINGS = int(os.environ.get("BUILDINGS", "50")); PER = int(os.environ.get("PER_BUILDING", "5")); BUDGET = int(os.environ.get("MAX_LOOKUPS", "250"))
via = urllib.request.build_opener(urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
NOT_LENDER = re.compile(r"^MERS\b|MORTGAGE ELECTRONIC REGISTRATION|SECRETARY OF (HOUSING|VETERANS)|DEPARTMENT OF HOUSING", re.I)

out_path = "data/miami_backfill.json"
state = json.load(open(out_path)) if os.path.exists(out_path) else {"sales": {}}
miami = json.load(open("data/miami.json"))["rows"]
SDF = "https://floridarevenue.com/property/dataportal/Documents/PTO%20Data%20Portal/Tax%20Roll%20Data%20Files/SDF/2026P/Dade%2023%20Preliminary%20SDF%202026.zip"
z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(urllib.request.Request(SDF, headers={"User-Agent": "Mozilla/5.0"}), timeout=300).read()))
sales = [r for r in csv.DictReader(io.TextIOWrapper(z.open([n for n in z.namelist() if n.lower().endswith((".csv", ".txt"))][0]), encoding="latin-1"))
         if (r.get("QUAL_CD") or "").strip() in ("01", "1") and int(float(r.get("SALE_PRC") or 0)) >= 100000]
print("qualified sales in file:", len(sales), "range", min(r["SALE_YR"] + "-" + r["SALE_MO"].zfill(2) for r in sales), "to", max(r["SALE_YR"] + "-" + r["SALE_MO"].zfill(2) for r in sales))
by_prefix = {}
for r in sales:
    by_prefix.setdefault(r["PARCEL_ID"].strip()[:-4], []).append(r)

targets = sorted([b for b in miami if b["z"] in ZIPS and b["u"] >= 20], key=lambda b: -b.get("sq", 0))[:BUILDINGS]
queue = []
for b in targets:
    ss = [s for p in (b.get("fp") or [b["f"]]) for s in by_prefix.get(p, [])]
    ss.sort(key=lambda s: (s["SALE_YR"], s["SALE_MO"].zfill(2)), reverse=True)
    picked = [s for s in ss if s["PARCEL_ID"].strip() not in state["sales"]][:PER]
    queue += [(b, s) for s in picked]
print("buildings:", len(targets), "lookups queued:", len(queue), "budget:", BUDGET)

def lookup(folio):
    q = urllib.parse.urlencode({"parameter1": folio, "parameter2": "FN", "authKey": KEY})
    body = via.open(urllib.request.Request("https://www2.miamidadeclerk.gov/Developers/api/OfficialRecords?" + q, headers={"Accept": "application/xml", "User-Agent": "Mozilla/5.0"}), timeout=60).read()
    root = ET.fromstring(body); strip = lambda t: t.split("}")[-1]
    top = {strip(c.tag): (c.text or "") for c in root if len(c) == 0}
    recs = [{strip(k.tag): (k.text or "").strip() for k in el} for el in root.iter() if list(el) and all(len(k) == 0 for k in el) and any(strip(k.tag) == "DOC_TYPE" for k in el)]
    return top, recs

done = 0; balance = None
for b, s in queue:
    if done >= BUDGET or (balance is not None and balance < 2):
        print("stopping: budget/balance"); break
    folio = s["PARCEL_ID"].strip()
    try:
        top, recs = lookup(folio)
    except Exception as e:
        print("lookup failed", type(e).__name__); continue
    done += 1
    try: balance = int(top.get("UnitsBalance") or 0)
    except ValueError: pass
    if top.get("Status") != "Successful":
        print("status", top.get("Status"), top.get("StatusDesc")); 
        if "unit" in (top.get("StatusDesc") or "").lower(): break
        continue
    ym = s["SALE_YR"] + "-" + s["SALE_MO"].zfill(2)
    # the sale's deed: a deed recorded in (or just after) the sale month
    deeds = sorted({r["REC_DATE"][:10] for r in recs if r["DOC_TYPE"] in ("DEE", "WD", "SWD", "CTD") and r["REC_DATE"][:7] >= ym}, key=str)
    sale_rec = deeds[0] if deeds else ym + "-15"
    d0 = datetime.date.fromisoformat(sale_rec)
    lenders = []
    for r in recs:
        if r["DOC_TYPE"] != "MOR" or not r["REC_DATE"]:
            continue
        dd = (datetime.date.fromisoformat(r["REC_DATE"][:10]) - d0).days
        if -10 <= dd <= 45:
            name = r["SECOND_PARTY"] if r.get("PARTY_CODE") == "D" else r["FIRST_PARTY"]
            if name and not NOT_LENDER.search(name) and name not in lenders:
                lenders.append(name)
    state["sales"][folio] = {"b": b["a"], "z": b["z"], "ym": ym, "price": int(float(s["SALE_PRC"])), "rec": sale_rec,
                             "financed": bool(lenders), "lenders": lenders}
    print(b["a"][:28].ljust(28), ym, "financed" if lenders else "cash", lenders[:2])
os.makedirs("data", exist_ok=True)
json.dump(state, open(out_path, "w"), separators=(",", ":"))
print("lookups:", done, "balance now:", balance, "sales recorded:", len(state["sales"]))
