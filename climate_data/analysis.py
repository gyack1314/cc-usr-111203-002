"""把读取、气候态、事件三个接口串成一次完整分析，输出可核对的JSON结构。"""
import datetime
from .climatology import build_climatology, day_values, cycle_label
from .events import detect_events


def _analysis_years(start, end):
    return set(range(start.year, end.year + 1))


def analyze(ds):
    """对数据集执行完整分析。

    基准年集合在分析前锁定；leave_one_year_out为真时，落在基准年内的分析日
    改用剔除该年后的逐年留一气候态，不借正在分析那一年的异常抬高自己的阈
    值，留一后支持不足照样不可估；非基准年的分析日始终用完整气候态。
    """
    config = ds['config']
    temps = ds['temperatures']
    start, end = config['analysis_window']
    full = build_climatology(temps, config)
    loo = {}
    if config['leave_one_year_out']:
        for y in sorted(set(config['baseline_years']) & _analysis_years(start, end)):
            loo[y] = build_climatology(temps, config, exclude_year=y)
    rows = []
    d = start
    while d <= end:
        clim = loo.get(d.year, full)
        threshold, mean = day_values(clim, d)
        rows.append({'date': d, 'temperature': temps.get(d),
                     'threshold': threshold, 'mean': mean,
                     'climatology': 'leave-one-year-out' if d.year in loo else 'full'})
        d += datetime.timedelta(days=1)
    found = detect_events(rows, config['min_duration'], config['max_gap'])
    daily = []
    for r in rows:
        daily.append({'day': r['date'].isoformat(),
                      'temperature': r['temperature'],
                      'cycle_day': cycle_label(r['date']),
                      'threshold': r['threshold'], 'mean': r['mean'],
                      'climatology': r['climatology'],
                      'exceeding': r['exceeding'],
                      'intensity': (r['temperature'] - r['mean']
                                    if r['available'] else None),
                      'event_id': r['event_id']})
    candidates = [{'id': c['id'], 'start': c['start'].isoformat(),
                   'end': c['end'].isoformat(),
                   'length_days': c['length_days'],
                   'event_id': c['event_id']} for c in found['candidates']]
    events = [{'id': e['id'], 'start': e['start'].isoformat(),
               'end': e['end'].isoformat(),
               'duration_days': e['duration_days'],
               'exceedance_days': e['exceedance_days'],
               'gap_days': e['gap_days'],
               'cumulative_intensity': e['cumulative_intensity'],
               'candidate_ids': e['candidate_ids'],
               'bridges': e['bridges']} for e in found['events']]
    result = {'config': {'baseline_years': config['baseline_years'],
                         'window': config['window'],
                         'quantile': config['quantile'],
                         'min_samples': config['min_samples'],
                         'smooth_width': config['smooth_width'],
                         'min_duration': config['min_duration'],
                         'max_gap': config['max_gap'],
                         'analysis_window': [start.isoformat(), end.isoformat()],
                         'leave_one_year_out': config['leave_one_year_out']},
              'climatology': {'days': full['days']},
              'daily': daily, 'candidates': candidates, 'events': events}
    if config['leave_one_year_out']:
        result['leave_one_year_out'] = {str(y): {'days': loo[y]['days']}
                                        for y in sorted(loo)}
    return result
