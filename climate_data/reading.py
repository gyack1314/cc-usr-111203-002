"""读取接口：核对热浪分析配置与逐日记录，产出可分析的数据集。

配置字段缺一不可且不接受额外字段；逐日记录只含day与temperature，
日期唯一，temperature为null表示明确缺测，完全缺少的日期保持缺席。
"""
from fractions import Fraction
from .io import date, number, integer, fraction, load

FIELDS = {'daily', 'baseline_years', 'window', 'quantile', 'min_samples',
          'smooth_width', 'min_duration', 'max_gap', 'analysis_window',
          'leave_one_year_out'}
MAX_WINDOW = 182  # 2*window+1不超过365日循环轴


def _check_quantile(x):
    """分位取(0,1)内的有限数，或该范围内的整数字符串/分数字符串。"""
    if isinstance(x, str):
        q = fraction(x)
    else:
        q = Fraction(number(x))
    if not 0 < q < 1:
        raise ValueError('分位需在(0,1)内')


def parse_config(v):
    """核对顶层字段与各项配置，返回规范化配置；analysis_window为日期对。"""
    if not isinstance(v, dict) or set(v) != FIELDS:
        raise ValueError('资料字段应为' + ','.join(sorted(FIELDS)))
    years = v['baseline_years']
    if not isinstance(years, list) or not years:
        raise ValueError('基准年需唯一且非空')
    for y in years:
        if type(y) is not int:
            raise ValueError('基准年需为整数')
    if len(set(years)) != len(years):
        raise ValueError('基准年需唯一且非空')
    window = integer(v['window'], 0)
    if window > MAX_WINDOW:
        raise ValueError('window过大，窗口超出365日循环轴')
    _check_quantile(v['quantile'])
    min_samples = integer(v['min_samples'], 1)
    smooth_width = integer(v['smooth_width'], 1)
    if smooth_width % 2 == 0 or smooth_width > 365:
        raise ValueError('smooth_width为正奇数且不超过365')
    min_duration = integer(v['min_duration'], 1)
    max_gap = integer(v['max_gap'], 0)
    span = v['analysis_window']
    if not isinstance(span, list) or len(span) != 2:
        raise ValueError('分析窗口需为起止两日')
    start, end = date(span[0]), date(span[1])
    if start > end:
        raise ValueError('分析窗口起点不能晚于终点')
    if type(v['leave_one_year_out']) is not bool:
        raise ValueError('leave_one_year_out需为布尔值')
    return {'baseline_years': list(years), 'window': window,
            'quantile': v['quantile'], 'min_samples': min_samples,
            'smooth_width': smooth_width, 'min_duration': min_duration,
            'max_gap': max_gap, 'analysis_window': (start, end),
            'leave_one_year_out': v['leave_one_year_out']}


def parse_records(v):
    """核对逐日记录，返回{公历日期: 温度或None}；记录顺序不影响结果。"""
    rows = v['daily']
    if not isinstance(rows, list):
        raise ValueError('daily应为记录列表')
    temps = {}
    for r in rows:
        if not isinstance(r, dict) or set(r) != {'day', 'temperature'}:
            raise ValueError('记录应含day与temperature')
        d = date(r['day'])
        if d in temps:
            raise ValueError('日期重复')
        t = r['temperature']
        temps[d] = None if t is None else number(t)
    return temps


def dataset(v):
    """由已解析的JSON对象构建数据集。"""
    return {'config': parse_config(v), 'temperatures': parse_records(v)}


def load_dataset(path):
    """读取文件并构建数据集，附来源字节SHA-256。"""
    v, digest = load(path)
    ds = dataset(v)
    ds['source_sha256'] = digest
    return ds
