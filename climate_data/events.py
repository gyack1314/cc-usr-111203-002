"""事件接口：超阈值连续段、最短持续、短间断桥接与强度累计。

在完整公历日轴上标记温度严格大于阈值的连续段，不少于min_duration的段才
成为候选。相邻候选间隔不超过max_gap且间隔中每日温度、均值、阈值都可用时
合并；间隔中的短超阈值碎段只算有效间隔，不改变候选身份，孤立短段不能先
延长事件再凑够最短天数。缺日期、缺温度或不可估气候态都强制断开，跨年不
强制断开。合并事件跨度含有效间隔，超阈值日数另列；逐日强度与累计强度取
相对季节均值的实际值，间隔日不填零也不改成阈值。
"""


def detect_events(rows, min_duration, max_gap):
    """rows按完整公历日轴排序，每项含date/temperature/threshold/mean。

    返回{'rows', 'candidates', 'events'}：rows逐项补充available、exceeding、
    event_id；candidates为原合格候选段；events为合并后事件，含跨度、超阈值
    日数、间隔日数、累计强度与桥接关系。
    """
    for r in rows:
        r['available'] = (r['temperature'] is not None
                          and r['threshold'] is not None
                          and r['mean'] is not None)
        r['exceeding'] = (r['available'] and r['temperature'] > r['threshold'])
        r['event_id'] = None
    candidates = []
    i = 0
    while i < len(rows):
        if rows[i]['exceeding']:
            j = i
            while j + 1 < len(rows) and rows[j + 1]['exceeding']:
                j += 1
            if j - i + 1 >= min_duration:
                candidates.append({'id': len(candidates),
                                   'start_index': i, 'end_index': j,
                                   'start': rows[i]['date'],
                                   'end': rows[j]['date'],
                                   'length_days': j - i + 1})
            i = j + 1
        else:
            i += 1
    groups = []
    for cand in candidates:
        if groups:
            prev = groups[-1]['candidates'][-1]
            gap = rows[prev['end_index'] + 1:cand['start_index']]
            if len(gap) <= max_gap and all(r['available'] for r in gap):
                groups[-1]['candidates'].append(cand)
                groups[-1]['bridges'].append({'left': prev['id'],
                                              'right': cand['id'],
                                              'gap_days': len(gap)})
                continue
        groups.append({'candidates': [cand], 'bridges': []})
    events = []
    for k, g in enumerate(groups):
        first, last = g['candidates'][0], g['candidates'][-1]
        span = rows[first['start_index']:last['end_index'] + 1]
        exceedance = sum(1 for r in span if r['exceeding'])
        event = {'id': k, 'start': span[0]['date'], 'end': span[-1]['date'],
                 'duration_days': len(span), 'exceedance_days': exceedance,
                 'gap_days': len(span) - exceedance,
                 'cumulative_intensity': sum(r['temperature'] - r['mean']
                                             for r in span),
                 'candidate_ids': [c['id'] for c in g['candidates']],
                 'bridges': g['bridges']}
        for c in g['candidates']:
            c['event_id'] = k
        for r in span:
            r['event_id'] = k
        events.append(event)
    return {'rows': rows, 'candidates': candidates, 'events': events}
