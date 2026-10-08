import json, re, urllib.request, urllib.parse, io, zipfile, collections
UA={'User-Agent':'Mozilla/5.0 pocketapproval'}
def get(u, data=None):
    return urllib.request.urlopen(urllib.request.Request(u, data=data, headers=UA), timeout=300).read()
for svc in ['Parcels_Composite_NJ_WM','Parcels_MODIV_NJ_WM']:
    base='https://services2.arcgis.com/XVOqAjTOJ5P6ngMu/arcgis/rest/services/%s/FeatureServer/0/query'%svc
    for w in ["1=1","MUN_NAME='HOBOKEN CITY'","COUNTY='HUDSON'"]:
        try:
            r=json.loads(get(base+'?'+urllib.parse.urlencode({'where':w,'returnCountOnly':'true','f':'json'})))
            print(svc,w,r)
        except Exception as e: print(svc,w,'ERR',e)
    try:
        r=json.loads(get(base+'?'+urllib.parse.urlencode({'where':"MUN_NAME='HOBOKEN CITY'",'outFields':'MUN_NAME,PCL_MUN,PCLBLOCK,PCLLOT,PCLQCODE,PROP_CLASS,PROP_LOC,BLDG_DESC,YR_CONSTR,DWELL,SALE_PRICE,DEED_DATE,ZIP5','resultRecordCount':'6','f':'json'})))
        print(svc,'sample',[f['attributes'] for f in r.get('features',[])][:6], r.get('error'))
    except Exception as e: print(svc,'ERR',e)
# SR1A 2026 YTD: Hudson = county 09
z=zipfile.ZipFile(io.BytesIO(get('https://www.nj.gov/treasury/taxation/lpt/statdata/YTDSR1A2026.zip')))
print('zip files', z.namelist())
data=z.read(z.namelist()[0]).decode('latin-1').splitlines()
print('lines', len(data), 'len0', len(data[0]))
hud=[l for l in data if l[0:2]=='09']
print('hudson', len(hud), collections.Counter(l[2:4] for l in hud))
c=[l for l in hud if l[648:649]=='Y']
print('hudson condo', len(c), collections.Counter(l[2:4] for l in c))
for l in c[:12]:
    print(l[2:4], '|blk', l[350:359].strip(), '|lot', l[359:368].strip(), '|q', l[619:624].strip(), '|cls', l[626:628], '|loc', l[297:322].strip(), '|price', l[37:46].strip(), '|deed', l[338:344], '|rec', l[344:350], '|U/N', l[33:37])
