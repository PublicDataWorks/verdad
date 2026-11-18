import json, re, math, collections
from urllib.parse import urlparse
rows=json.load(open('parallel_rows.json'))
def rank(x):
    o=sorted(range(len(x)),key=lambda i:x[i]); r=[0]*len(x); i=0
    while i<len(o):
        j=i
        while j+1<len(o) and x[o[j+1]]==x[o[i]]: j+=1
        for k in range(i,j+1): r[o[k]]=(i+j)/2+1
        i=j+1
    return r
def pear(a,b):
    ma,mb=sum(a)/len(a),sum(b)/len(b); n=sum((x-ma)*(y-mb) for x,y in zip(a,b)); d=math.sqrt(sum((x-ma)**2 for x in a)*sum((y-mb)**2 for y in b)); return n/d if d else float('nan')
def spear(a,b): return pear(rank(a),rank(b))
def auc(p,y):
    pos=[a for a,b in zip(p,y) if b]; neg=[a for a,b in zip(p,y) if not b]
    if not pos or not neg: return float('nan')
    return sum((x>z)+0.5*(x==z) for x in pos for z in neg)/(len(pos)*len(neg))
def kappa(a,b):
    n=len(a); po=sum(x==y for x,y in zip(a,b))/n; pa=sum(a)/n; pb=sum(b)/n; pe=pa*pb+(1-pa)*(1-pb); return (po-pe)/(1-pe) if pe<1 else float('nan')
STA=re.compile(r'kviv|radio victoria|kyar|red-?c|kbic|radio vida|mcd|monte carlo|doualiya|streema|mytuner|radiostation|liveradio|fcc\.gov|wikipedia\.org/wiki/K',re.I)
MIS=re.compile(r'misinform|disinform|fact.?check|fake news|desinform|bulo|noticias falsas|verific|تضليل|أخبار كاذبة|تحقق|infodemic',re.I)
def script(t):
    ar=len(re.findall(r'[؀-ۿ]',t)); es=len(re.findall(r'\b(el|la|los|las|de|del|que|en|para|por|con|una|y)\b',t,re.I)); en=len(re.findall(r'\b(the|of|and|to|in|for|is|on|with)\b',t,re.I))
    if ar>=3: return 'ar'
    if es>en and es>=2: return 'es'
    return 'en'
out={}
for v in 'ABCD':
    p=[r[v]['p'] for r in rows]; prod=[r['prod'] for r in rows]
    yb=[x>=80 for x in prod]; pb=[x>=0.7 for x in p]
    tp=sum(a and b for a,b in zip(pb,yb)); fp=sum(a and not b for a,b in zip(pb,yb)); fn=sum((not a) and b for a,b in zip(pb,yb)); tn=sum((not a) and (not b) for a,b in zip(pb,yb))
    rr=[r for r in rows if r['rerun'] is not None]
    yr=[r['rerun']>=80 for r in rr]; pr=[r[v]['p']>=0.7 for r in rr]
    hum=[r for r in rows if r['hum']]
    cit=[c for r in rows for c in r[v]['cit']]
    n=len(cit); stat=sum(1 for c in cit if STA.search(c['url']+' '+(c.get('title') or '')))
    mis=sum(1 for c in cit if MIS.search((c.get('title') or '')+' '+c['url']))
    lang={}
    for L in ['Spanish','Arabic','English']:
        cs=[c for r in rows if r['lang']==L for c in r[v]['cit']]
        sc=collections.Counter(script((c.get('title') or '')+' '+' '.join(c['excerpts'])[:600]) for c in cs)
        lang[L]={k:round(sc[k]/len(cs),2) for k in ('ar','es','en')}
    doms=collections.Counter(urlparse(c['url']).netloc.replace('www.','') for c in cit)
    out[v]=dict(
      conf=(tp,fp,fn,tn), acc=(tp+tn)/38, kappa=kappa(pb,yb), spearman=spear(p,prod), pearson=pear(p,prod), auc=auc(p,yb),
      rerun=dict(n=len(rr),acc=sum(a==b for a,b in zip(pr,yr))/len(rr),kappa=kappa(pr,yr),spearman=spear([r[v]['p'] for r in rr],[r['rerun'] for r in rr])),
      human=dict(n=len(hum),hit=sum(r[v]['p']>=0.7 for r in hum),prod_hit=sum(r['prod']>=80 for r in hum),rerun_hit=sum((r['rerun'] or 0)>=80 for r in hum)),
      unlabelled=dict(hit=sum(r[v]['p']>=0.7 for r in rows if not r['hum']),n=sum(1 for r in rows if not r['hum']),prod_hit=sum(r['prod']>=80 for r in rows if not r['hum'])),
      cit_n=n, per_call=sum(len(r[v]['cit']) for r in rows)/38, station_share=round(stat/n,2), misinfo_title_share=round(mis/n,2), lang=lang,
      lat_mean=sum(r[v]['lat'] for r in rows)/38, lat_max=max(r[v]['lat'] for r in rows), lat_min=min(r[v]['lat'] for r in rows),
      tok_mean=sum(r[v]['tok'] for r in rows)/38, refusals=sum(len(r[v]['refs']) for r in rows), http_bad=sum(r[v]['http']!=200 for r in rows),
      mean_p=sum(p)/38, ge07=sum(x>=0.7 for x in p), ge03_lt07=sum(0.3<=x<0.7 for x in p),
      eq_mean=sum(r[v]['eq'] for r in rows if r[v]['eq'] is not None)/38,
      topdoms=doms.most_common(8))
print(json.dumps(out,indent=1,default=str))
json.dump(out,open('parallel_metrics.json','w'),default=str)
