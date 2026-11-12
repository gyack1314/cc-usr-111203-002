"""气候态接口：365日循环轴上的窗口样本、type-7分位、循环平滑与2月29日规则。

公历日期按月日映射到365日循环轴，2月29日不进入基准样本，其他日期不因
闰年平移。每个循环日汇集各基准年该日前后window天的实际非缺测温度，首尾
循环；有效值不足min_samples的日子没有气候态。平滑为正奇数宽度的循环等权
平均，窗口含任一不可估日则结果不可估，分母不缩减。分析中的2月29日气候态
由相邻两循环日结果平均，时间序列本身保留该天。
"""
import datetime
from fractions import Fraction
from .io import fraction

REFERENCE_YEAR = 2001  # 平年，仅用于月日到循环下标的映射
CYCLE_DAYS = 365


def _cycle_month_days():
    base = datetime.date(REFERENCE_YEAR, 1, 1)
    out = []
    for i in range(CYCLE_DAYS):
        d = base + datetime.timedelta(days=i)
        out.append((d.month, d.day))
    return out


CYCLE_MONTH_DAYS = _cycle_month_days()


def cycle_index(d):
    """公历日期在365日循环轴上的下标；2月29日不属于循环轴，返回None。"""
    if d.month == 2 and d.day == 29:
        return None
    ref = datetime.date(REFERENCE_YEAR, 1, 1)
    return (datetime.date(REFERENCE_YEAR, d.month, d.day) - ref).days


def cycle_label(d):
    """公历日期对应的月日标签，2月29日保留为'02-29'。"""
    ci = cycle_index(d)
    if ci is None:
        return '02-29'
    m, dd = CYCLE_MONTH_DAYS[ci]
    return '%02d-%02d' % (m, dd)


def quantile_fraction(config):
    """配置中的分位值化为精确有理数；字符串按分数或精确小数处理。"""
    x = config['quantile']
    return fraction(x) if isinstance(x, str) else Fraction(x)


def quantile_type7(samples, q):
    """type-7经验分位：h=(n-1)*p，排序样本floor(h)与ceil(h)线性插值。

    n=1退化为唯一值；q为Fraction时插值位置按精确有理数计算。
    """
    if not samples:
        raise ValueError('分位需要非空样本')
    if not isinstance(q, Fraction):
        q = Fraction(q)
    xs = sorted(samples)
    n = len(xs)
    if n == 1:
        return float(xs[0])
    h = (n - 1) * q
    lo = h.numerator // h.denominator
    hi = min(lo + 1, n - 1)
    weight = float(h - lo)
    return float(xs[lo]) + (float(xs[hi]) - float(xs[lo])) * weight


def window_samples(temps, years, ci, window):
    """汇集各基准年循环日ci前后window天的实际非缺测温度，首尾循环。"""
    out = []
    for y in years:
        for o in range(-window, window + 1):
            m, dd = CYCLE_MONTH_DAYS[(ci + o) % CYCLE_DAYS]
            t = temps.get(datetime.date(y, m, dd))
            if t is not None:
                out.append(t)
    return out


def _smooth(values, width):
    """循环等权平滑；窗口含任一不可估日则结果不可估，分母恒为width。"""
    half = width // 2
    out = []
    for c in range(CYCLE_DAYS):
        vals = [values[(c + o) % CYCLE_DAYS] for o in range(-half, half + 1)]
        out.append(None if any(x is None for x in vals) else sum(vals) / width)
    return out


def build_climatology(temps, config, exclude_year=None):
    """按基准年构建365日气候态；exclude_year用于留一，剔除后支持不足照样不可估。

    返回{'days', 'thresholds', 'means', 'exclude_year'}：days逐循环日列出
    样本数、未平滑(raw_*)与平滑(threshold/mean)结果，不可估为None。
    """
    years = [y for y in config['baseline_years'] if y != exclude_year]
    q = quantile_fraction(config)
    window = config['window']
    min_samples = config['min_samples']
    days = []
    for ci in range(CYCLE_DAYS):
        s = window_samples(temps, years, ci, window)
        n = len(s)
        if n >= min_samples:
            raw_threshold = quantile_type7(s, q)
            raw_mean = sum(s) / n
        else:
            raw_threshold = raw_mean = None
        m, dd = CYCLE_MONTH_DAYS[ci]
        days.append({'cycle_day': '%02d-%02d' % (m, dd), 'samples': n,
                     'raw_threshold': raw_threshold, 'raw_mean': raw_mean})
    width = config['smooth_width']
    thresholds = _smooth([d['raw_threshold'] for d in days], width)
    means = _smooth([d['raw_mean'] for d in days], width)
    for d, t, m in zip(days, thresholds, means):
        d['threshold'] = t
        d['mean'] = m
    return {'days': days, 'thresholds': thresholds, 'means': means,
            'exclude_year': exclude_year}


def day_values(clim, d):
    """某日可用的(阈值, 均值)；2月29日取相邻两循环日结果的平均。"""
    ci = cycle_index(d)
    if ci is not None:
        return clim['thresholds'][ci], clim['means'][ci]
    t = (clim['thresholds'][58], clim['thresholds'][59])
    m = (clim['means'][58], clim['means'][59])
    threshold = None if any(x is None for x in t) else sum(t) / 2
    mean = None if any(x is None for x in m) else sum(m) / 2
    return threshold, mean
