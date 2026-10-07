import json, sys, urllib.parse, urllib.request
B = "https://floridarevenue.com/property/dataportal"
P = "/property/dataportal/Documents/PTO Data Portal/Tax Roll Data Files"
for sub in ["", "/NAL", "/SDF", "/NAL/2026F", "/NAL/2026P", "/SDF/2026F", "/SDF/2026P", "/NAL/2025F", "/SDF/2025F"]:
    u = B + "/_api/web/GetFolderByServerRelativeUrl('" + urllib.parse.quote(P + sub) + "')?$expand=Folders,Files"
    print("==", sub)
    try:
        j = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"Accept": "application/json;odata=nometadata", "User-Agent": "Mozilla/5.0"}), timeout=60))
        print("folders:", [f["Name"] for f in j.get("Folders", [])])
        print("files:", [(f["Name"], f.get("Length")) for f in j.get("Files", []) if "23" in f["Name"] or "Dade" in f["Name"] or len(j.get("Files", [])) < 10][:20])
    except Exception as e:
        print("err", e)
