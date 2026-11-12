"""热浪识别、循环气候态与持续时间的日历口径核对。

小窗口手算分位数与事件累计量；演示跨年、闰日、阈值等号、缺测和短间断；
并证明输入乱序不会改变结论。
"""
import datetime
import json
import random
import unittest
from fractions import Fraction
from pathlib import Path
from climate_data.io import load
from climate_data.reading import dataset, load_dataset, parse_config, parse_records
from climate_data.climatology import (build_climatology, cycle_index, cycle_label,
                                      day_values, quantile_type7, window_samples)
from climate_data.analysis import analyze

D = datetime.date


def daily_rows(start, end, value):
    """生成[start,end]逐日记录，value为常量或按日期取值的函数。"""
    rows = []
    d = start
    while d <= end:
        rows.append({'day': d.isoformat(),
                     'temperature': value(d) if callable(value) else value})
        d += datetime.timedelta(days=1)
    return rows


def make(daily, *, baseline_years, start, end, window=0, quantile=0.5,
         min_samples=1, smooth_width=1, min_duration=1, max_gap=0, loo=False):
    v = {'daily': daily, 'baseline_years': baseline_years, 'window': window,
         'quantile': quantile, 'min_samples': min_samples,
         'smooth_width': smooth_width, 'min_duration': min_duration,
         'max_gap': max_gap, 'analysis_window': [start, end],
         'leave_one_year_out': loo}
    return dataset(v)


def constant_baseline_daily(analysis_daily, base=20.0, year=2001):
    """恒定基准年20℃加给定分析年记录的合成资料。"""
    return daily_rows(D(year, 1, 1), D(year, 12, 31), base) + analysis_daily


def day_map(result):
    return {r['day']: r for r in result['daily']}


class QuantileTests(unittest.TestCase):
    """type-7分位按手算值核对。"""

    def test_exact_hits(self):
        self.assertEqual(quantile_type7([5, 1, 3, 2, 4], Fraction(1, 2)), 3.0)
        self.assertEqual(quantile_type7([1, 2, 3, 4, 5], Fraction(1, 4)), 2.0)
        self.assertEqual(quantile_type7([1, 2, 3, 4, 5], Fraction(3, 4)), 4.0)
        self.assertEqual(quantile_type7([7], Fraction(9, 10)), 7.0)

    def test_interpolation(self):
        # n=4, h=(4-1)*1/2=1.5 → 排序后第2、3值的平均
        self.assertEqual(quantile_type7([4, 1, 3, 2], Fraction(1, 2)), 2.5)
        # n=2, h=1/4 → 0+0.25*(10-0)
        self.assertEqual(quantile_type7([10, 0], Fraction(1, 4)), 2.5)
        # n=5, h=4*0.1=0.4 → 1+0.4*(2-1)
        self.assertAlmostEqual(quantile_type7([1, 2, 3, 4, 5], 0.1), 1.4)

    def test_empty_rejected(self):
        with self.assertRaises(ValueError):
            quantile_type7([], Fraction(1, 2))


class ClimatologyTests(unittest.TestCase):
    """小窗口手算循环气候态。"""

    def test_window_samples_wrap(self):
        # 温度取循环下标，window=1时1月1日的样本来自12月31日、1月1日、1月2日
        temps = {D(2001, 1, 1) + datetime.timedelta(days=i): float(i)
                 for i in range(365)}
        self.assertEqual(sorted(window_samples(temps, [2001], 0, 1)),
                         [0.0, 1.0, 364.0])
        self.assertEqual(sorted(window_samples(temps, [2001], 364, 1)),
                         [0.0, 363.0, 364.0])

    def test_hand_computed_threshold_and_mean(self):
        # 温度=循环下标+1000*(年-2001)，window=1，两年共6个样本
        daily = []
        for y in (2001, 2002):
            daily += daily_rows(D(y, 1, 1), D(y, 12, 31),
                                lambda d: cycle_index(d) + 1000 * (d.year - 2001))
        ds = make(daily, baseline_years=[2001, 2002], start='2003-01-01',
                  end='2003-01-01', window=1, min_samples=6)
        clim = build_climatology(ds['temperatures'], ds['config'])
        days = {d['cycle_day']: d for d in clim['days']}
        # 循环日100(4月11日)：样本{99,100,101,1099,1100,1101}，中位与均值都是600
        self.assertEqual(days['04-11']['samples'], 6)
        self.assertEqual(days['04-11']['raw_threshold'], 600.0)
        self.assertEqual(days['04-11']['raw_mean'], 600.0)
        # 循环日0跨首尾：样本{0,1,364,1000,1001,1364}，中位(364+1000)/2=682
        self.assertEqual(days['01-01']['raw_threshold'], 682.0)
        self.assertAlmostEqual(days['01-01']['raw_mean'], 3730 / 6)
        # 循环日364跨首尾：样本{0,363,364,1000,1363,1364}，中位682
        self.assertEqual(days['12-31']['raw_threshold'], 682.0)
        self.assertAlmostEqual(days['12-31']['raw_mean'], 4454 / 6)

    def test_min_samples_marks_unestimable(self):
        daily = daily_rows(D(2001, 1, 1), D(2001, 12, 31), 20.0)
        ds = make(daily, baseline_years=[2001], start='2003-01-01',
                  end='2003-01-01', window=1, min_samples=4)
        clim = build_climatology(ds['temperatures'], ds['config'])
        self.assertTrue(all(d['samples'] == 3 for d in clim['days']))
        self.assertTrue(all(d['raw_threshold'] is None for d in clim['days']))
        self.assertTrue(all(d['threshold'] is None for d in clim['days']))

    def test_leap_day_excluded_and_no_shift(self):
        # 2004为闰年：2月29日给极端值9999，不得进入任何基准样本；
        # 3月1日、3月2日的气候态仍取各自月日的值，不因闰年平移
        def value(d):
            if (d.month, d.day) == (2, 29):
                return 9999.0
            return float(cycle_index(d))
        daily = daily_rows(D(2004, 1, 1), D(2004, 12, 31), value)
        ds = make(daily, baseline_years=[2004], start='2005-01-01',
                  end='2005-01-01')
        clim = build_climatology(ds['temperatures'], ds['config'])
        days = {d['cycle_day']: d for d in clim['days']}
        self.assertTrue(all(d['samples'] == 1 for d in clim['days']))
        self.assertEqual(days['03-01']['raw_threshold'], 59.0)
        self.assertEqual(days['03-02']['raw_threshold'], 60.0)
        self.assertTrue(all(d['raw_threshold'] < 9999.0 for d in clim['days']))

    def test_leap_day_climatology_is_adjacent_average(self):
        # 2月28日20℃、3月1日22℃，2月29日气候态为两者平均21℃
        def value(d):
            return {(2, 28): 20.0, (3, 1): 22.0}.get((d.month, d.day), 10.0)
        daily = daily_rows(D(2001, 1, 1), D(2001, 12, 31), value)
        ds = make(daily, baseline_years=[2001], start='2004-02-28',
                  end='2004-03-01')
        clim = build_climatology(ds['temperatures'], ds['config'])
        self.assertEqual(day_values(clim, D(2004, 2, 29)), (21.0, 21.0))
        self.assertEqual(day_values(clim, D(2004, 2, 28)), (20.0, 20.0))
        self.assertEqual(day_values(clim, D(2004, 3, 1)), (22.0, 22.0))
        # 时间序列本身保留2月29日
        result = analyze(ds)
        self.assertEqual([r['day'] for r in result['daily']],
                         ['2004-02-28', '2004-02-29', '2004-03-01'])
        self.assertEqual(day_map(result)['2004-02-29']['cycle_day'], '02-29')

    def test_leap_day_unestimable_when_neighbour_unestimable(self):
        daily = daily_rows(D(2001, 1, 1), D(2001, 12, 31), 20.0)
        daily += [{'day': '2002-01-01', 'temperature': 20.0}]
        # 基准[2001,2002]、min_samples=2：仅1月1日有2个样本，其余不可估
        ds = make(daily, baseline_years=[2001, 2002], start='2004-02-29',
                  end='2004-02-29', min_samples=2)
        clim = build_climatology(ds['temperatures'], ds['config'])
        self.assertEqual(day_values(clim, D(2004, 2, 29)), (None, None))

    def test_smoothing_hand_computed_and_circular(self):
        # 温度=循环下标，smooth_width=3：内部日平滑后仍等于下标，
        # 循环日0跨首尾平滑为(364+0+1)/3
        daily = daily_rows(D(2001, 1, 1), D(2001, 12, 31),
                           lambda d: float(cycle_index(d)))
        ds = make(daily, baseline_years=[2001], start='2003-01-01',
                  end='2003-01-01', smooth_width=3)
        clim = build_climatology(ds['temperatures'], ds['config'])
        days = {d['cycle_day']: d for d in clim['days']}
        self.assertEqual(days['01-11']['threshold'], 10.0)
        self.assertAlmostEqual(days['01-01']['threshold'], 365 / 3)
        self.assertAlmostEqual(days['12-31']['threshold'], 727 / 3)

    def test_smoothing_propagates_unestimable(self):
        # 2002-01-10缺测使其循环日不可估；smooth_width=3时相邻三日也不可估，
        # 其余日子的平滑分母仍是3
        daily = daily_rows(D(2001, 1, 1), D(2001, 12, 31),
                           lambda d: float(cycle_index(d)))
        daily += daily_rows(D(2002, 1, 1), D(2002, 12, 31),
                            lambda d: 1000.0 + cycle_index(d))
        daily = [r for r in daily if r['day'] != '2002-01-10']
        daily.append({'day': '2002-01-10', 'temperature': None})
        ds = make(daily, baseline_years=[2001, 2002], start='2003-01-01',
                  end='2003-01-01', min_samples=2, smooth_width=3)
        clim = build_climatology(ds['temperatures'], ds['config'])
        days = {d['cycle_day']: d for d in clim['days']}
        self.assertIsNone(days['01-10']['raw_threshold'])
        for label in ('01-09', '01-10', '01-11'):
            self.assertIsNone(days[label]['threshold'], label)
        # 01-12的平滑窗口为01-11..01-13，均可估，分母不缩减
        self.assertEqual(days['01-12']['threshold'],
                         (510.0 + 511.0 + 512.0) / 3)


class EventTests(unittest.TestCase):
    """小窗口手算事件跨度、超阈值日数与累计强度。"""

    def merged_event_dataset(self, **kw):
        # 基准恒定20℃；分析段：01-10..12为21℃，01-13..14为19℃，
        # 01-15..18为22℃，01-19恰为阈值20℃，01-22..23为25℃孤立短段
        analysis = daily_rows(D(2002, 1, 1), D(2002, 1, 31), 19.0)
        for r in analysis:
            md = r['day'][5:]
            if '01-10' <= md <= '01-12':
                r['temperature'] = 21.0
            elif '01-15' <= md <= '01-18':
                r['temperature'] = 22.0
            elif md == '01-19':
                r['temperature'] = 20.0
            elif '01-22' <= md <= '01-23':
                r['temperature'] = 25.0
        opts = dict(baseline_years=[2001], start='2002-01-01',
                    end='2002-01-31', min_duration=3, max_gap=2)
        opts.update(kw)
        return make(constant_baseline_daily(analysis), **opts)

    def test_merged_event_quantities_by_hand(self):
        result = analyze(self.merged_event_dataset())
        self.assertEqual(len(result['events']), 1)
        e = result['events'][0]
        # 跨度含2天有效间隔：01-10..01-18共9天
        self.assertEqual((e['start'], e['end']), ('2002-01-10', '2002-01-18'))
        self.assertEqual(e['duration_days'], 9)
        # 超阈值日数另列：3+4=7
        self.assertEqual(e['exceedance_days'], 7)
        self.assertEqual(e['gap_days'], 2)
        # 累计强度含间隔日实际值：3*(21-20)+2*(19-20)+4*(22-20)=9℃·day
        self.assertEqual(e['cumulative_intensity'], 9.0)
        self.assertEqual(e['candidate_ids'], [0, 1])
        self.assertEqual(e['bridges'], [{'left': 0, 'right': 1, 'gap_days': 2}])
        days = day_map(result)
        self.assertEqual(days['2002-01-13']['intensity'], -1.0)
        self.assertEqual(days['2002-01-13']['event_id'], 0)
        # 阈值等号不超阈：01-19恰为20℃
        self.assertFalse(days['2002-01-19']['exceeding'])
        self.assertIsNone(days['2002-01-19']['event_id'])
        # 孤立短超阈值段(2天<min_duration)不能成为事件
        self.assertIsNone(days['2002-01-22']['event_id'])
        self.assertIsNone(days['2002-01-23']['event_id'])

    def test_gap_beyond_max_gap_not_merged(self):
        result = analyze(self.merged_event_dataset(max_gap=1))
        self.assertEqual([(e['start'], e['end']) for e in result['events']],
                         [('2002-01-10', '2002-01-12'),
                          ('2002-01-15', '2002-01-18')])

    def test_short_fragment_in_gap_stays_gap(self):
        # 间隔中的1天超阈值碎段只算有效间隔，不改变候选身份
        analysis = daily_rows(D(2002, 1, 1), D(2002, 1, 31), 19.0)
        for r in analysis:
            md = r['day'][5:]
            if '01-10' <= md <= '01-12':
                r['temperature'] = 21.0
            elif md == '01-14':
                r['temperature'] = 25.0
            elif '01-16' <= md <= '01-19':
                r['temperature'] = 22.0
        ds = make(constant_baseline_daily(analysis), baseline_years=[2001],
                  start='2002-01-01', end='2002-01-31',
                  min_duration=3, max_gap=3)
        result = analyze(ds)
        self.assertEqual(len(result['candidates']), 2)
        e, = result['events']
        self.assertEqual((e['start'], e['end']), ('2002-01-10', '2002-01-19'))
        self.assertEqual(e['duration_days'], 10)
        # 碎段当日确实超阈，计入超阈值日数：3+1+4=8
        self.assertEqual(e['exceedance_days'], 8)
        self.assertEqual(e['gap_days'], 2)
        # 累计：3*1 + (19-20) + (25-20) + (19-20) + 4*2 = 14
        self.assertEqual(e['cumulative_intensity'], 14.0)

    def test_isolated_short_runs_never_form_event(self):
        # 两段各2天的超阈值过程间隔1天：都不合格，不能先延长再凑够最短天数
        analysis = daily_rows(D(2002, 1, 1), D(2002, 1, 31), 19.0)
        for r in analysis:
            if r['day'][5:] in ('01-10', '01-11', '01-13', '01-14'):
                r['temperature'] = 25.0
        ds = make(constant_baseline_daily(analysis), baseline_years=[2001],
                  start='2002-01-01', end='2002-01-31',
                  min_duration=3, max_gap=2)
        result = analyze(ds)
        self.assertEqual(result['candidates'], [])
        self.assertEqual(result['events'], [])

    def test_year_boundary_does_not_break_event(self):
        analysis = daily_rows(D(2002, 12, 29), D(2003, 1, 4), 25.0)
        ds = make(constant_baseline_daily(analysis), baseline_years=[2001],
                  start='2002-12-29', end='2003-01-04', min_duration=3)
        result = analyze(ds)
        e, = result['events']
        self.assertEqual((e['start'], e['end']), ('2002-12-29', '2003-01-04'))
        self.assertEqual(e['duration_days'], 7)
        self.assertEqual(e['cumulative_intensity'], 35.0)

    def test_null_temperature_breaks_and_blocks_bridge(self):
        analysis = daily_rows(D(2002, 1, 10), D(2002, 1, 20), 25.0)
        for r in analysis:
            if r['day'] == '2002-01-15':
                r['temperature'] = None
        ds = make(constant_baseline_daily(analysis), baseline_years=[2001],
                  start='2002-01-10', end='2002-01-20',
                  min_duration=3, max_gap=2)
        result = analyze(ds)
        self.assertEqual([(e['start'], e['end']) for e in result['events']],
                         [('2002-01-10', '2002-01-14'),
                          ('2002-01-16', '2002-01-20')])
        self.assertIsNone(day_map(result)['2002-01-15']['temperature'])

    def test_absent_date_breaks_and_blocks_bridge(self):
        analysis = [r for r in daily_rows(D(2002, 1, 10), D(2002, 1, 20), 25.0)
                    if r['day'] != '2002-01-15']
        ds = make(constant_baseline_daily(analysis), baseline_years=[2001],
                  start='2002-01-10', end='2002-01-20',
                  min_duration=3, max_gap=2)
        result = analyze(ds)
        self.assertEqual([(e['start'], e['end']) for e in result['events']],
                         [('2002-01-10', '2002-01-14'),
                          ('2002-01-16', '2002-01-20')])
        # 缺席日期仍在公历日轴上，温度为空，不补成普通日
        self.assertIsNone(day_map(result)['2002-01-15']['temperature'])

    def test_unestimable_climatology_breaks_event(self):
        # 2001-01-15缺测使该循环日只剩1个样本<min_samples=2，不可估
        baseline = daily_rows(D(2001, 1, 1), D(2001, 12, 31), 20.0)
        baseline += daily_rows(D(2002, 1, 1), D(2002, 12, 31), 20.0)
        for r in baseline:
            if r['day'] == '2001-01-15':
                r['temperature'] = None
        analysis = daily_rows(D(2003, 1, 10), D(2003, 1, 20), 25.0)
        ds = make(baseline + analysis, baseline_years=[2001, 2002],
                  start='2003-01-10', end='2003-01-20',
                  min_samples=2, min_duration=3, max_gap=2)
        result = analyze(ds)
        self.assertIsNone(day_map(result)['2003-01-15']['threshold'])
        self.assertEqual([(e['start'], e['end']) for e in result['events']],
                         [('2003-01-10', '2003-01-14'),
                          ('2003-01-16', '2003-01-20')])

    def leap_day_equality_dataset(self, max_gap):
        # 2月28日20℃、3月1日22℃→2月29日阈值21℃；分析段跨闰日，
        # 其中2月29日恰为21℃不超阈
        def value(d):
            return {(2, 28): 20.0, (3, 1): 22.0}.get((d.month, d.day), 10.0)
        baseline = daily_rows(D(2001, 1, 1), D(2001, 12, 31), 10.0)
        for r in baseline:
            if r['day'] == '2001-02-28':
                r['temperature'] = 20.0
            elif r['day'] == '2001-03-01':
                r['temperature'] = 22.0
        analysis = daily_rows(D(2004, 2, 27), D(2004, 3, 2), 25.0)
        for r in analysis:
            if r['day'] == '2004-02-29':
                r['temperature'] = 21.0
        return make(baseline + analysis, baseline_years=[2001],
                    start='2004-02-27', end='2004-03-02',
                    min_duration=2, max_gap=max_gap)

    def test_leap_day_equality_breaks_run(self):
        result = analyze(self.leap_day_equality_dataset(max_gap=0))
        days = day_map(result)
        self.assertEqual(days['2004-02-29']['threshold'], 21.0)
        self.assertFalse(days['2004-02-29']['exceeding'])
        self.assertEqual([(e['start'], e['end']) for e in result['events']],
                         [('2004-02-27', '2004-02-28'),
                          ('2004-03-01', '2004-03-02')])

    def test_leap_day_gap_bridged_with_actual_values(self):
        # 闰日不超阈但温度、均值、阈值都可用：作为有效间隔桥接，
        # 累计强度含该日实际值21-21=0
        result = analyze(self.leap_day_equality_dataset(max_gap=2))
        e, = result['events']
        self.assertEqual((e['start'], e['end']), ('2004-02-27', '2004-03-02'))
        self.assertEqual(e['duration_days'], 5)
        self.assertEqual(e['exceedance_days'], 4)
        self.assertEqual(e['gap_days'], 1)
        # 手算：(25-10)+(25-20)+(21-21)+(25-22)+(25-10)=38℃·day
        self.assertEqual(e['cumulative_intensity'], 38.0)


class LeaveOneOutTests(unittest.TestCase):
    """基准年内的回看使用逐年留一气候态。"""

    def loo_dataset(self, *, loo, min_samples=1, start='2001-05-31',
                    end='2001-06-06'):
        baseline = daily_rows(D(2001, 1, 1), D(2001, 12, 31), 20.0)
        baseline += daily_rows(D(2002, 1, 1), D(2002, 12, 31), 20.0)
        for r in baseline:
            if '2001-06-01' <= r['day'] <= '2001-06-05':
                r['temperature'] = 26.0
        return make(baseline, baseline_years=[2001, 2002], start=start,
                    end=end, min_samples=min_samples, min_duration=3, loo=loo)

    def test_leave_one_out_uses_other_years_only(self):
        result = analyze(self.loo_dataset(loo=True))
        days = day_map(result)
        # 留一后2001-06-01的阈值只来自2002年：20℃
        self.assertEqual(days['2001-06-01']['threshold'], 20.0)
        self.assertEqual(days['2001-06-01']['climatology'], 'leave-one-year-out')
        e, = result['events']
        self.assertEqual((e['start'], e['end']), ('2001-06-01', '2001-06-05'))
        # 累计强度：5*(26-20)=30℃·day
        self.assertEqual(e['cumulative_intensity'], 30.0)
        self.assertEqual(set(result['leave_one_year_out']), {'2001'})

    def test_full_climatology_borrows_own_anomaly(self):
        # 不留一时，2001年异常抬高自己的阈值：中位(20,26)=23℃
        result = analyze(self.loo_dataset(loo=False))
        self.assertEqual(day_map(result)['2001-06-01']['threshold'], 23.0)
        e, = result['events']
        self.assertEqual(e['cumulative_intensity'], 15.0)
        self.assertNotIn('leave_one_year_out', result)

    def test_leave_one_out_insufficient_support_unestimable(self):
        result = analyze(self.loo_dataset(loo=True, min_samples=2))
        self.assertEqual(result['events'], [])
        self.assertTrue(all(r['threshold'] is None for r in result['daily']))

    def test_non_baseline_year_uses_full_climatology(self):
        result = analyze(self.loo_dataset(loo=True, start='2002-12-31',
                                          end='2003-01-02'))
        labels = {r['day']: r['climatology'] for r in result['daily']}
        self.assertEqual(labels['2002-12-31'], 'leave-one-year-out')
        self.assertEqual(labels['2003-01-01'], 'full')
        self.assertEqual(set(result['leave_one_year_out']), {'2002'})


class OrderInvarianceTests(unittest.TestCase):
    """输入乱序不会改变结论。"""

    def test_shuffled_records_same_result(self):
        analysis = daily_rows(D(2002, 1, 1), D(2002, 1, 31), 19.0)
        for r in analysis:
            if '01-10' <= r['day'][5:] <= '01-12':
                r['temperature'] = 21.0
        daily = constant_baseline_daily(analysis)
        shuffled = daily[:]
        random.Random(2024).shuffle(shuffled)
        kwargs = dict(baseline_years=[2001], start='2002-01-01',
                      end='2002-01-31', min_duration=3, max_gap=2)
        self.assertEqual(analyze(make(daily, **kwargs)),
                         analyze(make(shuffled, **kwargs)))

    def test_shuffled_material_same_result(self):
        v, _ = load('data/normal.json')
        shuffled = json.loads(json.dumps(v))
        random.Random(7).shuffle(shuffled['daily'])
        self.assertEqual(analyze(dataset(v)), analyze(dataset(shuffled)))

    def test_baseline_year_order_same_climatology(self):
        daily = daily_rows(D(2001, 1, 1), D(2001, 12, 31),
                           lambda d: float(cycle_index(d)))
        daily += daily_rows(D(2002, 1, 1), D(2002, 12, 31),
                            lambda d: 1000.0 + cycle_index(d))
        a = analyze(make(daily, baseline_years=[2001, 2002],
                         start='2003-01-01', end='2003-01-01'))
        b = analyze(make(daily, baseline_years=[2002, 2001],
                         start='2003-01-01', end='2003-01-01'))
        self.assertEqual(a['climatology'], b['climatology'])
        self.assertEqual(a['events'], b['events'])


class ReadingTests(unittest.TestCase):
    """读取接口的严格核对。"""

    def valid(self, **overrides):
        v = {'daily': [{'day': '2001-01-01', 'temperature': 20.0}],
             'baseline_years': [2001], 'window': 0, 'quantile': 0.5,
             'min_samples': 1, 'smooth_width': 1, 'min_duration': 1,
             'max_gap': 0, 'analysis_window': ['2002-01-01', '2002-01-02'],
             'leave_one_year_out': False}
        v.update(overrides)
        return v

    def test_field_set_strict(self):
        v = self.valid()
        del v['window']
        with self.assertRaises(ValueError):
            parse_config(v)
        with self.assertRaises(ValueError):
            parse_config(self.valid(extra=1))

    def test_quantile_rules(self):
        for q in (0, 1, 1.5, -0.1, '1/0', '3/2', True, None):
            with self.assertRaises((ValueError, TypeError)):
                parse_config(self.valid(quantile=q))
        self.assertEqual(parse_config(self.valid(quantile='9/10'))['quantile'],
                         '9/10')
        self.assertEqual(parse_config(self.valid(quantile=0.9))['quantile'], 0.9)

    def test_integer_rules(self):
        for key, bad in (('window', 183), ('window', -1),
                         ('smooth_width', 4), ('smooth_width', 0),
                         ('smooth_width', 367), ('min_samples', 0),
                         ('min_duration', 0), ('max_gap', -1)):
            with self.assertRaises(ValueError, msg=key):
                parse_config(self.valid(**{key: bad}))
        parse_config(self.valid(smooth_width=365, window=182))

    def test_baseline_years_rules(self):
        for years in ([], [2001, 2001], [2001.5], ['2001'], None):
            with self.assertRaises((ValueError, TypeError)):
                parse_config(self.valid(baseline_years=years))

    def test_analysis_window_rules(self):
        with self.assertRaises(ValueError):
            parse_config(self.valid(analysis_window=['2002-01-02', '2002-01-01']))
        with self.assertRaises(ValueError):
            parse_config(self.valid(analysis_window=['2002-01-01']))
        with self.assertRaises(ValueError):
            parse_config(self.valid(leave_one_year_out=1))

    def test_record_rules(self):
        with self.assertRaises(ValueError):
            parse_records(self.valid(daily=[{'day': '2001-01-01',
                                             'temperature': 1.0,
                                             'note': 'x'}]))
        dup = [{'day': '2001-01-01', 'temperature': 1.0}] * 2
        with self.assertRaises(ValueError):
            parse_records(self.valid(daily=dup))
        with self.assertRaises(ValueError):
            parse_records(self.valid(daily=[{'day': '2001-01-01',
                                             'temperature': '20'}]))
        ds = dataset(self.valid(daily=[{'day': '2001-01-01',
                                        'temperature': None}]))
        self.assertEqual(ds['temperatures'], {D(2001, 1, 1): None})


class MaterialTests(unittest.TestCase):
    """随附合成资料的端到端核对。"""

    def analyze_file(self, name):
        return analyze(load_dataset(str(Path('data') / name)))

    def test_normal_year_crossing_single_event(self):
        result = self.analyze_file('normal.json')
        spans = [(e['start'], e['end']) for e in result['events']]
        self.assertEqual(spans, [('2020-02-10', '2020-05-08'),
                                 ('2020-08-31', '2021-12-31')])
        e = result['events'][1]
        # 元旦前后的暖水过程是同一事件，跨年不强制断开
        self.assertEqual(e['duration_days'], 488)
        self.assertEqual(e['exceedance_days'], 488)
        self.assertEqual(e['gap_days'], 0)
        days = day_map(result)
        self.assertEqual(days['2020-12-31']['event_id'],
                         days['2021-01-01']['event_id'])
        # 2月29日保留在序列中并归属同一事件
        self.assertEqual(days['2020-02-29']['event_id'],
                         days['2020-02-28']['event_id'])

    def test_missing_year_boundary_date_breaks_event(self):
        result = self.analyze_file('missing-year-boundary.json')
        spans = [(e['start'], e['end']) for e in result['events']]
        # 2020-12-31完全缺席：事件在此断开，短间断不能用缺席日桥接
        self.assertEqual(spans, [('2020-02-10', '2020-05-08'),
                                 ('2020-08-31', '2020-12-30'),
                                 ('2021-01-01', '2021-12-31')])
        days = day_map(result)
        self.assertIsNone(days['2020-12-31']['temperature'])
        self.assertIsNone(days['2020-12-31']['event_id'])

    def test_missing_leap_day_breaks_event(self):
        result = self.analyze_file('missing-leap-day.json')
        spans = [(e['start'], e['end']) for e in result['events']]
        # 2020-02-29缺测(null)：事件在此断开，缺测日不当作普通降温填进事件
        self.assertEqual(spans, [('2020-02-10', '2020-02-28'),
                                 ('2020-03-01', '2020-05-08'),
                                 ('2020-08-31', '2021-12-31')])
        self.assertIsNone(day_map(result)['2020-02-29']['temperature'])

    def test_leave_one_baseline_year_unestimable(self):
        result = self.analyze_file('leave-one-baseline-year.json')
        # 留一后每个循环日只剩11个样本<min_samples=15，全部不可估
        self.assertEqual(result['events'], [])
        self.assertTrue(all(r['threshold'] is None for r in result['daily']))
        self.assertEqual(set(result['leave_one_year_out']), {'2018', '2019'})
        for year in result['leave_one_year_out'].values():
            self.assertTrue(all(d['threshold'] is None for d in year['days']))

    def test_invalid_material_rejected(self):
        for p in Path('data').glob('invalid-*.json'):
            with self.subTest(file=p.name):
                with self.assertRaises((ValueError, KeyError, TypeError)):
                    load_dataset(p)


if __name__ == '__main__':
    unittest.main()
