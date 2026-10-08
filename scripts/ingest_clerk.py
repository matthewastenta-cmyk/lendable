"""Daily: pull new files from the Clerk's Official Records bulk folder (through the Fixie static-IP proxy),
keep mortgages on condo units, and accumulate them in data/miami_mortgages.json.
Needs secrets CLERK_AUTH_KEY, CLERK_PROXY_URL and the folder name in CLERK_FOLDER (repo variable or secret).
Borrower names are never stored; only lender, date, amount, folio and book/page."""
import csv, io, json, os, re, sys, urllib.parse, urllib.request, zipfile
import xml.etree.ElementTree as ET

KEY = os.environ["CLERK_AUTH_KEY"].strip()
PROXY = os.environ["CLERK_PROXY_URL"].strip()
FOLDER_ENV = os.environ.get("CLERK_FOLDER", "").strip()
API = "https://www2.miamidadeclerk.gov/Developers/api/FTPapi"
opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
def get(params, accept="application/xml"):
    q = urllib.parse.urlencode({**params, "AuthKey": KEY})
    try:
        return opener.open(urllib.request.Request(API + "?" + q, headers={"Accept": accept, "User-Agent": "Mozilla/5.0"}), timeout=300).read()
    except urllib.error.HTTPError as e:
        return ("HTTP %s " % e.code).encode() + e.read()

def list_folder(name):
    xml = get({"folderListName": name}).decode("utf-8", "replace")
    try:
        root = ET.fromstring(xml.encode("utf-8"))
    except ET.ParseError:
        return None, xml
    status = next((e.text for e in root.iter() if e.tag.split("}")[-1] == "Status"), "")
    if status != "Success":
        return None, xml
    files = []
    for f in root.iter():
        if f.tag.split("}")[-1] == "FileinFolder":
            d = {c.tag.split("}")[-1]: (c.text or "").strip() for c in f}
            if d.get("Name"):
                files.append((d["Name"], d.get("Extension", "")))
    return sorted(set(files)), xml

FOLDER, names = None, None
for cand in [FOLDER_ENV, "Records"]:
    if not cand: continue
    names, raw = list_folder(cand)
    print("folder", repr(cand) if cand == "Records" else "(from setting)", "->", "ok" if names is not None else re.sub(r"\s+", " ", raw.replace(KEY, "***"))[:250])
    if names is not None:
        FOLDER = cand; break
if FOLDER is None:
    sys.exit("no accessible folder")

state_path = "data/miami_mortgages.json"
state = json.load(open(state_path)) if os.path.exists(state_path) else {"files": [], "mortgages": []}
MAXNEW = int(os.environ.get("MAXNEW", "40"))
print("files in folder:", len(names), names[:3])
new = [n for n in names if n[0] not in state["files"]][:MAXNEW]
print("new files:", len(new))

MORT = re.compile(r"^(MOR|MTG|MORT|MORTGAGE)$", re.I)
def rows_from(blob, name):
    if blob[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(blob))
        for inner in z.namelist():
            yield from rows_from(z.read(inner), inner)
        return
    text = blob.decode("latin-1")
    if text.lstrip().startswith("<"):
        root = ET.fromstring(text)
        for el in root.iter():
            kids = list(el)
            if kids and all(len(k) == 0 for k in kids):
                yield {k.tag.split("}")[-1].upper(): (k.text or "").strip() for k in kids}
        return
    lines = text.splitlines()
    if sum("^" in ln for ln in lines[:5]) >= 2:
        # Clerk daily export: caret-delimited, no header. Positions confirmed from the 09/2026 files.
        for ln in lines:
            f = [x.strip() for x in ln.split("^")]
            if len(f) < 23:
                continue
            yield {"CFN_YEAR": f[0], "CFN_SEQ": f[1], "REC_DATE": f[3][4:8] + "-" + f[3][0:2] + "-" + f[3][2:4] if len(f[3]) == 8 else f[3],
                   "BOOK_PAGE": f[5] + "/" + f[6], "DOC_TYPE": f[10], "DOC_DESC": f[11], "PARTY": f[13], "PARTY_CODE": f[14], "OTHER": f[15],
                   "AMOUNTS": "|".join(f[16:20]), "SUBDIV_NAME": f[21], "FOLIO_NUMBER": f[22], "LEGAL": f[23] if len(f) > 23 else "", "RAW": f}
        return
    first = lines[0] if lines else ""
    if not getattr(rows_from, "shown", False):
        rows_from.shown = True
        print("inner file:", name, "lines:", text.count("\n"))
        for ln in text.splitlines()[:4]:
            print("   |", re.sub(r"[A-Z][A-Z ,.&'-]{3,}(?=\|)", lambda m: m.group(0) if re.search(r"BANK|MORTGAGE|LENDING|LOAN|CREDIT|FUND|TRUST|FINANCIAL|LLC|INC|CONDO|ASSOC", m.group(0)) else m.group(0)[:2] + "*", ln)[:600])
    delim = "|" if first.count("|") > first.count(",") else ("\t" if "\t" in first else ",")
    for r in csv.DictReader(io.StringIO(text), delimiter=delim):
        yield {(k or "").strip().upper(): (v if isinstance(v, str) else "|".join(v or [])).strip() for k, v in r.items()}

added = 0
for n, ext in new:
    blob = get({"fileName": n + ("." + ext.lower() if ext else ""), "folderName": FOLDER}, accept="application/octet-stream")
    if blob[:2] != b"PK":
        b2 = get({"fileName": n, "folderName": FOLDER}, accept="application/octet-stream")
        if b2[:2] == b"PK" or len(b2) > len(blob): blob = b2
    print(n, "bytes:", len(blob), "head:", re.sub(r"\s+", " ", blob[:160].decode("latin-1").replace(KEY, "***")) if blob[:2] != b"PK" else "zip")
    cols = None; kept = 0; shown = 0
    for r in rows_from(blob, n):
        cols = cols or list(r.keys())
        if not MORT.match(r.get("DOC_TYPE", "")):
            continue
        if "RAW" in r:
            if shown < 4:
                f = r["RAW"]; shown += 1
                print("   MOR sample:", " ^ ".join((x if i not in (13, 15) or r["PARTY_CODE"] == "R" and i == 13 else x[:2] + "*") for i, x in enumerate(f[:24]))[:700])
            if r["PARTY_CODE"] != "R":
                continue  # the R (reverse/grantee) party on a mortgage is the lender
            folio = re.sub(r"\D", "", r["FOLIO_NUMBER"])[-13:]
            if not folio.strip("0"):
                continue
            state["mortgages"].append({"folio": folio, "lender": r["PARTY"], "date": r["REC_DATE"], "amt": r["AMOUNTS"],
                                       "book": r["CFN_YEAR"], "page": r["CFN_SEQ"], "condo": r["SUBDIV_NAME"], "legal": r["LEGAL"][:40]})
            kept += 1
            continue
        folio = re.sub(r"\D", "", r.get("FOLIO_NUMBER", "") or r.get("FOLIO", ""))
        if not folio:
            continue
        lender = r.get("SECOND_PARTY", "") if r.get("PARTY_CODE", "") in ("", "D", "R") else r.get("FIRST_PARTY", "")
        state["mortgages"].append({"folio": folio.zfill(13), "lender": lender, "date": (r.get("REC_DATE", "") or "")[:10],
                                   "amt": r.get("CONSIDERATION_1", "") or r.get("CONSIDERATION", ""), "book": r.get("REC_BOOK", ""), "page": r.get("REC_PAGE", ""),
                                   "condo": r.get("SUBDIV_NAME", "")})
        kept += 1
    print(n, "columns:", (cols or [])[:25], "mortgages kept:", kept)
    state["files"].append(n); added += kept

# de-duplicate (one mortgage can have several party rows)
seen, out = set(), []
for m in state["mortgages"]:
    k = (m["folio"], m["book"], m["page"], m["lender"])
    if k not in seen:
        seen.add(k); out.append(m)
state["mortgages"] = out
os.makedirs("data", exist_ok=True)
json.dump(state, open(state_path, "w"), separators=(",", ":"))
print("added", added, "total mortgages", len(out))
