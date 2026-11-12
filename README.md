# 海洋热浪的循环气候态与事件归属

这是独立的气候资料Python项目。`data/`保存合成资料，`climate_data.io`负责严格读取、公历日期和来源字节摘要，`climate_data.domain`提供现有描述统计，`climate_data.cli`将摘要输出为JSON。所有观测值、站点、人群、情景与金额都是虚构。字段和研究约定见[资料约定](docs/data-contract.md)。

热浪分析保留三个可独立核对的接口：`climate_data.reading`核对配置与逐日记录，`climate_data.climatology`在365日循环轴上求type-7分位阈值与均值并做循环平滑，`climate_data.events`在完整公历日轴上识别超阈值事件并桥接短间断。`climate_data.analysis`把三者串成完整分析。热浪识别、季节阈值和持续时间使用同一套日历口径：2月29日不进入基准样本也不使其他日期平移，分析中该天气候态取相邻两日平均；缺日期、缺温度或不可估气候态强制断开，跨年不强制断开；间隔日强度取实际值。

当前Python 3.11及以上可直接使用，没有第三方Python依赖。项目根目录运行：

```sh
python -m unittest discover -s tests -v
python -m compileall -q climate_data tests
python -m climate_data.cli inspect data/normal.json
python -m climate_data.cli analyze data/normal.json
```

`inspect`显示当前原始摘要，不覆盖资料。`analyze`输出配置回显、基准窗口样本数、未平滑和平滑气候态、逐日归属、原候选段与合并关系、事件跨度与累计强度，留一开启时附逐年留一气候态。`invalid-`前缀文件为不合法资料，其他变体使用相同字段保留业务边界。来源字节SHA-256随摘要输出，后续结果应同时标明输入身份、量纲和适用范围。

容器使用固定基础镜像，可运行`docker build -t climate-material .`，随后`docker run --rm climate-material`检查资料。`docker run --rm climate-material python -m unittest discover -s tests -v`执行已有检查。运行不依赖远端账号或实时服务。
