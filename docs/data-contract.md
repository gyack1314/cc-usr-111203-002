# 温度日历

day为公历日期，temperature为摄氏度，null表示明确缺测，完全缺少日期也不能补成普通日。baseline_years固定；day-of-year不能直接当365循环下标，2月29日单独处理。window是两侧各多少天，包含中心共2*window+1日；样本按实际非缺测基准观测汇集。

type-7分位采用h=(n-1)*p，取排序样本floor(h)和ceil(h)线性插值，n=1退化为唯一值；min_samples按原窗口值个数判断。smooth_width为正奇数且不超过365。候选连续段先按超过阈值及最小长度确定，再对相邻合格候选桥接；桥接间隔包含短超阈值碎段时，它们仍只作为有效间隔，不改变原合格候选的身份。累计强度单位是摄氏度日，日跨度含首末日期。

domain只核对日期和原温度，不生成分位数、平滑或事件。

# 分析配置

读取接口`climate_data.reading`要求顶层字段恰好为daily、baseline_years、window、quantile、min_samples、smooth_width、min_duration、max_gap、analysis_window、leave_one_year_out。baseline_years为唯一非空整数年列表，分析前锁定。window为0到182的整数。quantile取(0,1)内的有限数，或该范围内的整数、分数、小数字符串，字符串按精确有理数处理。min_samples、min_duration为正整数，max_gap为非负整数。analysis_window为起止两个YYYY-MM-DD日期，起点不晚于终点。leave_one_year_out为布尔值。逐日记录只含day与temperature，日期唯一。

# 循环气候态

气候态接口`climate_data.climatology`把公历日期按月日映射到365日循环轴：2月29日不进入基准样本，其他日期不因闰年平移。每个循环日汇集各基准年该日前后window天的实际非缺测温度，首尾循环，求type-7经验分位及算术均值；有效值不足min_samples的日子没有气候态。随后用smooth_width对365个阈值和均值做循环等权平滑，窗口含任一不可估日则平滑结果不可估，分母恒为smooth_width。分析中的2月29日气候态由相邻两循环日结果平均，时间序列本身保留该天。

# 事件与持续时间

事件接口`climate_data.events`在完整公历日轴上标记温度严格大于阈值的连续段，等于阈值不算超阈；不少于min_duration的段才成为候选。相邻候选间隔不超过max_gap且间隔中每日温度、均值、阈值都可用时合并；孤立短超阈值段不能先延长事件再凑够最短天数。缺日期、缺温度或不可估气候态都强制断开，跨年不强制断开。合并事件跨度含有效间隔，超阈值日数另列；逐日强度与累计强度取相对季节均值的实际值，间隔日不填零也不改成阈值。

# 留一与输出

leave_one_year_out为真时，落在基准年内的分析日改用剔除该年后的逐年留一气候态，不借正在分析那一年的异常抬高自己的阈值；留一后支持不足照样不可估。非基准年的分析日始终用完整气候态。`climate_data.analysis.analyze`输出配置回显、基准窗口样本数、未平滑和平滑气候态、逐日归属（温度、循环日、阈值、均值、气候态来源、是否超阈、强度、事件编号）、原候选段与合并桥接关系、事件跨度与累计强度；留一开启时附逐年留一气候态。逐日记录与基准年的书写顺序不影响任何结果。
