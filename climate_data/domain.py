"""按原日期检查温度记录，列出缺测数量。"""
from collections import Counter
from .io import date,number

def summarize(v):
    seen=set();counts=Counter();missing=Counter()
    for r in v['daily']:
        day=date(r['day'])
        if day in seen:raise ValueError('日期重复')
        seen.add(day);counts[day.year]+=1
        if r['temperature'] is None:missing[day.year]+=1
        else:number(r['temperature'])
    if not v['baseline_years'] or len(set(v['baseline_years']))!=len(v['baseline_years']):raise ValueError('基准年需唯一且非空')
    return {'years':[{'year':y,'records':counts[y],'missing_values':missing[y]} for y in sorted(counts)],'first':min(seen).isoformat() if seen else None,'last':max(seen).isoformat() if seen else None}
