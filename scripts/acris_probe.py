import json, urllib.request, urllib.parse, sys
B='https://data.cityofnewyork.us/resource/'
def q(ds, **p):
    u=B+ds+'.json?'+urllib.parse.urlencode(p)
    with urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'pocketapproval-probe'}),timeout=120) as r: return json.load(r)
def show(name, ds, **p):
    try:
        x=q(ds, **p); print('==',name,ds,p,'->',len(x)); 
        for r in x[:3]: print(json.dumps(r)[:700])
    except Exception as e: print('==',name,'ERR',e)
show('RP master','bnx9-e6tj',**{'$limit':2,'$where':"doc_type='DEED' AND recorded_datetime>'2026-09-01'"})
show('RP master rptt','bnx9-e6tj',**{'$select':'doc_type,count(*)','$group':'doc_type','$where':"recorded_datetime>'2026-09-01'",'$order':'count(*) desc','$limit':40})
show('RP legals','8h5j-fqxa',**{'$limit':2,'$where':"property_type='SP' AND document_id>'2026090'"})
show('RP legals ptypes','8h5j-fqxa',**{'$select':'property_type,count(*)','$group':'property_type','$where':"document_id>'2026090'",'$order':'count(*) desc','$limit':30})
show('RP parties','636b-3b5g',**{'$limit':2,'$where':"document_id>'2026090' AND party_type='2'"})
show('PP master','sv7x-dduq',**{'$select':'doc_type,count(*)','$group':'doc_type','$where':"recorded_datetime>'2026-09-01'",'$order':'count(*) desc','$limit':30})
show('PP master row','sv7x-dduq',**{'$limit':2,'$where':"doc_type='INIC' AND recorded_datetime>'2026-09-01'"})
show('PP legals','uqqa-hym2',**{'$limit':3,'$where':"document_id>'2026090'"})
show('PP parties','nbbg-wtuz',**{'$limit':3,'$where':"document_id>'2026090' AND party_type='2'"})
show('PLUTO bx','64uk-42ks',**{'$limit':2,'$where':"borough='BX' AND bldgclass like 'R%'"})
show('PLUTO bx count','64uk-42ks',**{'$select':'bldgclass,count(*)','$group':'bldgclass','$where':"borough='BX' AND (bldgclass like 'R%' OR bldgclass in('D4','C6','D0','C8'))",'$limit':50})
# co-op RPTT joined example
x=q('bnx9-e6tj',**{'$limit':5,'$where':"doc_type in('RPTT','RPTT&RET') AND recorded_datetime>'2026-09-15'"})
ids=[r['document_id'] for r in x]
show('legals of RPTT','8h5j-fqxa',**{'$where':'document_id in('+','.join("'%s'"%i for i in ids)+')'})
