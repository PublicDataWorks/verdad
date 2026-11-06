import json, os, re, math, collections
from urllib.parse import urlparse
HERE=os.path.dirname(os.path.abspath(__file__))
sel=json.load(open(f'{HERE}/snippets/selection.json'))
def R(sid,v):
    return json.load(open(f'{HERE}/results_parallel/{sid}.{v}.json'))
def p3(sid):
    return json.load(open(f'{HERE}/results_stage3/gemini-2.5-pro/{sid}.json'))
def dom(u): 
    d=urlparse(u).netloc.lower(); return d[4:] if d.startswith('www.') else d
rows=[]
for s in sel:
    sid=s['snippet_id']; row={'sid':sid,'title':s['title'],'lang':s['lang'],'hum':bool(s['human_labels']),'prod':s['overall'],'cats':[c['english'] for c in s['categories']]}
    try: row['rerun']=p3(sid)['overall']
    except Exception: row['rerun']=None
    for v in 'ABCD':
        r=R(sid,v); b=r['raw']; row[v]={'lat':r['latency_s'],'http':r['http']}
        if b:
            a=b['answers']; f=a['is_false']
            row[v]['ref']=f['type']=='refusal'; row[v]['p']=f.get('noul')
            row[v]['cat']=a['category'].get('choice'); row[v]['catp']=max(a['category'].get('probabilities',{'x':0}).values()) if a['category']['type']!='refusal' else None
            e=a['evidence_quality']; row[v]['eq']=(e['score']/4*100) if e['type']!='refusal' else None
            row[v]['refs']=[k for k,x in a.items() if x['type']=='refusal']
            row[v]['cit']=b['citations']; row[v]['tok']=b['usage']['input_tokens']
    rows.append(row)
json.dump(rows,open(f'{HERE}/parallel_rows.json','w'),ensure_ascii=False)
if __name__=='__main__':
    for r in rows:
        print(r['sid'][:8],r['lang'][:2],'H' if r['hum'] else '-',r['prod'],r['rerun'],'|',' '.join(f"{v}:{r[v].get('p',0):.2f}/{len(r[v].get('cit',[]))}" for v in 'ABCD'),'|',r['title'][:50])
