"""Build Lendable's Miami-Dade condo building list from Florida DOR tax roll files (NAL + SDF),
then attach SIRS reserve-study filings (data/sirs.json) and HUD FHA status (data/fha.json).
Runs in GitHub Actions. Writes data/miami.json. Owner names are never kept."""
import csv, io, json, re, sys, urllib.parse, urllib.request, zipfile
from collections import Counter, defaultdict

NOT_LENDER = re.compile(r"^MERS\b|MORTGAGE ELECTRONIC REGISTRATION|SECRETARY OF (HOUSING|VETERANS)|^HUD\b|DEPARTMENT OF HOUSING", re.I)  # nominees / government partial claims, not the lender
def attach_lenders(path="data/miami.json"):
    """Merge data/miami_mortgages.json into the building list: lenders seen in the last 12 months per building."""
    import datetime, os
    if not os.path.exists("data/miami_mortgages.json"):
        return
    d = json.load(open(path)); morts = json.load(open("data/miami_mortgages.json"))["mortgages"]
    cutoff = (datetime.date.today() - datetime.timedelta(days=365)).isoformat()
    by = {}
    for b in d["rows"]:
        for p in b.get("fp") or [b.get("f")]:
            if p: by[p.zfill(9)] = b
    hits = defaultdict(list)
    for m in morts:
        if m["date"] >= cutoff and m["lender"] and not NOT_LENDER.search(m["lender"]):
            b = by.get(m["folio"][:-4])
            if b is not None: hits[id(b)].append(m)
    bf = json.load(open("data/miami_backfill.json"))["sales"] if os.path.exists("data/miami_backfill.json") else {}
    fin = defaultdict(lambda: [0, 0])
    for folio, x in bf.items():
        b = by.get(folio[:-4])
        if b is None: continue
        fin[id(b)][0 if x["financed"] else 1] += 1
        for name in x["lenders"]:
            hits[id(b)].append({"lender": name, "date": x["rec"], "book": "bf", "page": folio + name})
    for b in d["rows"]:
        f = fin.get(id(b))
        if f: b["fc"] = f  # [financed, cash] among recent sales checked
        else: b.pop("fc", None)
        ms = hits.get(id(b), [])
        if ms:
            c = Counter(m["lender"] for m in ms)
            b["l"] = [[name, n, max(m["date"] for m in ms if m["lender"] == name)] for name, n in c.most_common()]
            b["lm"] = len({(m["book"], m["page"]) for m in ms})
        else:
            b.pop("l", None); b.pop("lm", None)
    d["meta"]["withLenders"] = sum(1 for b in d["rows"] if b.get("l"))
    d["meta"]["mortgagesSince"] = min((m["date"] for m in morts), default=None)
    json.dump(d, open(path, "w"), separators=(",", ":"))
    print("lenders attached:", d["meta"]["withLenders"], "buildings", file=sys.stderr)

if "--lenders-only" in sys.argv:
    attach_lenders(); raise SystemExit(0)

BASE = "https://floridarevenue.com/property/dataportal/Documents/PTO%20Data%20Portal/Tax%20Roll%20Data%20Files/"
def latest(kind):
    api = ("https://floridarevenue.com/property/dataportal/_api/web/GetFolderByServerRelativeUrl('"
           + urllib.parse.quote(f"/property/dataportal/Documents/PTO Data Portal/Tax Roll Data Files/{kind}") + "')?$expand=Folders/Files")
    j = json.load(urllib.request.urlopen(urllib.request.Request(api, headers={"Accept": "application/json;odata=nometadata", "User-Agent": "Mozilla/5.0"}), timeout=60))
    for folder in sorted(j["Folders"], key=lambda f: f["Name"], reverse=True):  # 2026F before 2026P
        for f in folder.get("Files", []):
            if f["Name"].startswith("Dade 23"):
                return BASE + kind + "/" + folder["Name"] + "/" + urllib.parse.quote(f["Name"]), folder["Name"]
    raise SystemExit("no Dade file for " + kind)

def read_zip_csv(url):
    print("download", url, file=sys.stderr)
    data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=600).read()
    z = zipfile.ZipFile(io.BytesIO(data))
    name = [n for n in z.namelist() if n.lower().endswith((".csv", ".txt"))][0]
    return csv.DictReader(io.TextIOWrapper(z.open(name), encoding="latin-1"))

SUFFIX = {"STREET": "ST", "AVENUE": "AVE", "AV": "AVE", "BOULEVARD": "BLVD", "DRIVE": "DR", "ROAD": "RD", "COURT": "CT", "PLACE": "PL", "TERRACE": "TER",
          "LANE": "LN", "CIRCLE": "CIR", "PARKWAY": "PKWY", "HIGHWAY": "HWY", "WAY": "WAY", "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W",
          "NORTHEAST": "NE", "NORTHWEST": "NW", "SOUTHEAST": "SE", "SOUTHWEST": "SW"}
def street_key(addr):
    a = re.sub(r"[^A-Z0-9 ]", " ", (addr or "").upper())
    a = re.sub(r"\b(UNIT|APT|STE|SUITE|PH|#|NO)\b.*$", "", a)
    w = [SUFFIX.get(x, x) for x in a.split()]
    w = [re.sub(r"^(\d+)(ST|ND|RD|TH)$", r"\1", x) for x in w]
    return " ".join(w).strip()
def unit_strip(addr):
    a = (addr or "").upper().strip()
    a = re.sub(r"\s+(UNIT|APT|STE|SUITE|#)\s*\S+$", "", a)
    a = re.sub(r"\s+#?\s*[A-Z]?\d{1,5}[A-Z]?$", "", a) if re.search(r"\d+\s+\S.*\s#?[A-Z]?\d{1,5}[A-Z]?$", a) and len(a.split()) > 3 else a
    return re.sub(r"\s+", " ", a).strip()

nal_url, nal_roll = latest("NAL")
sdf_url, _ = latest("SDF")
units = defaultdict(list)
for r in read_zip_csv(nal_url):
    uc = (r.get("DOR_UC") or "").strip()
    if uc not in ("004", "04", "4", "005", "05"):  # 004 condominium, 005 co-op
        continue
    a1 = (r.get("PHY_ADDR1") or "").strip()
    if not a1:
        continue
    b = unit_strip(a1)
    units[(street_key(b), (r.get("PHY_ZIPCD") or "")[:5])].append({
        "folio": (r.get("PARCEL_ID") or "").strip(), "addr": b, "city": (r.get("PHY_CITY") or "").strip().title(),
        "yr": (r.get("ACT_YR_BLT") or "").strip(), "type": "Co-op" if uc.endswith("5") else "Condo",
        "jv": int(float(r.get("JV") or 0) or 0)})
print("condo/co-op parcels grouped into", len(units), "address groups", file=sys.stderr)

sales = defaultdict(list)
for r in read_zip_csv(sdf_url):
    pid = (r.get("PARCEL_ID") or "").strip()
    try:
        price = int(float(r.get("SALE_PRC") or 0)); yr = int(r.get("SALE_YR") or 0); mo = int(r.get("SALE_MO") or 0)
    except ValueError:
        continue
    if price < 10000:
        continue
    sales[pid].append({"y": yr, "m": mo, "p": price, "q": (r.get("QUAL_CD") or "").strip(), "book": (r.get("OR_BOOK") or "").strip(), "page": (r.get("OR_PAGE") or "").strip(), "clerk": (r.get("CLERK_NO") or "").strip()})

sirs = json.load(open("data/sirs.json"))
pre = defaultdict(list)
for s in sirs["pre2025"]:
    pre[(street_key(s.get("BuildingAddress")), (s.get("UPPER (ZIP)") or "")[:5])].append(s)
post = defaultdict(list)
for s in sirs["post2025"]:
    post[((s.get("PROJECT_STREET_NUMBER") or "").strip(), (s.get("PROJECT_ZIPCODE") or "")[:5])].append(s)
fha = defaultdict(list)
for f in json.load(open("data/fha.json"))["rows"]:
    if f["state"] == "FL":
        for part in re.split(r",|&", f["street"]):
            fha[(street_key(part), f["zip"])].append(f)

def money(x):
    try: return round(float(x))
    except Exception: return None
def mdy(x):
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", x or "")
    return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}" if m else ""

out = []
for (key, zipc), us in units.items():
    if len(us) < 3:
        continue  # skip tiny groups (likely mis-grouped addresses)
    yrs = Counter(u["yr"] for u in us if u["yr"] and u["yr"] != "0")
    first = Counter(u["addr"] for u in us).most_common(1)[0][0]
    rec_sales = [s for u in us for s in sales.get(u["folio"], [])]
    b = {"a": first.title(), "c": Counter(u["city"] for u in us).most_common(1)[0][0], "z": zipc, "u": len(us),
         "y": int(yrs.most_common(1)[0][0]) if yrs else None, "t": Counter(u["type"] for u in us).most_common(1)[0][0],
         "f": us[0]["folio"][:-4] if len(us[0]["folio"]) >= 13 else us[0]["folio"],
         "fp": sorted({u["folio"][:-4] for u in us if len(u["folio"]) >= 13}),
         "s": len(rec_sales), "sq": sum(1 for s in rec_sales if s["q"] in ("01", "1")),
         "sp": int(sorted(s["p"] for s in rec_sales)[len(rec_sales) // 2]) if rec_sales else None,
         "sl": max((f"{s['y']}-{s['m']:02d}" for s in rec_sales), default=None)}
    m = pre.get((key, zipc)) or []
    num = key.split(" ")[0] if key else ""
    m2 = post.get((num, zipc)) or []
    if m:
        s = sorted(m, key=lambda x: mdy(x.get("SIRSCompletedDate")), reverse=True)[0]
        b["sirs"] = {"name": (s.get("UPPER(ProjectName)") or "").title(), "done": mdy(s.get("SIRSCompletedDate")), "by": s.get("SIRSCompany") or "",
                     "assess": s.get("SIRSAssessmentIndicator") == "Yes", "assessTotal": money(s.get("SIRSAssessmentCost")), "assessPerUnit": money(s.get("SIRSAssessmentCostPerUnit")),
                     "file": s.get("SIRSFile") or "", "lic": s.get("ProjectLicense") or ""}
    elif m2:
        s = m2[0]
        b["sirs"] = {"name": (s.get("PROJECT_NAME") or "").title(), "filed": True, "match": "street number + ZIP"}
    f = fha.get((key, zipc))
    if f:
        f = sorted(f, key=lambda r: r["statusDate"], reverse=True)[0]
        b["fha"] = {"id": f["id"], "status": f["status"], "method": f["method"], "exp": f["expires"], "date": f["statusDate"]}
    out.append(b)

out.sort(key=lambda b: -b["u"])
meta = {"source": "Florida DOR tax roll (" + nal_roll + ") for Miami-Dade, DBPR SIRS database, HUD FHA condo list", "count": len(out),
        "withSirs": sum(1 for b in out if "sirs" in b), "withFha": sum(1 for b in out if "fha" in b)}
json.dump({"meta": meta, "rows": out}, open("data/miami.json", "w"), separators=(",", ":"))
print(meta, file=sys.stderr)
attach_lenders()
