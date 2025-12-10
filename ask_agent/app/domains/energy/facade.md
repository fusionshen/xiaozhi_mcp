我们将 domains.energy 做一个统一入口类 EnergyDomain，让所有能源相关 LLM、API、Pipeline 都通过一个门面（Facade）暴露。

最终你可以这样用：

from domains import energy

energy.llm.parse_user_input(...)
energy.pipeline.process_message(...)
energy.api.platform.query(...)


或者：

from domains.energy import EnergyDomain

energy = EnergyDomain()
energy.llm.parse_user_input(...)
energy.api.platform.call(...)


非常干净、专业。

✅ 第一步：目录结构（无需移动现有文件）

你的结构会变成：

domains/
  energy/
    __init__.py
    domain.py          ← 统一出口（我们要创建）
    llm/
       __init__.py
       llm_energy_indicator_parser.py
       llm_compare_analyzer.py
       llm_indicator_expander.py
       llm_time_range_normalizer.py
       llm_trend_analyzer.py
    pipeline/
       __init__.py
       pipeline.py
    api/
       __init__.py
       formula_api.py
       platform_api.py


（如果现在没有 api 子目录，我可以帮你生成迁移脚本）

✅ 第二步：整理子模块的出口（必要）
domains/energy/llm/init.py
from .llm_energy_indicator_parser import parse_user_input
from .llm_compare_analyzer import call_compare_llm
from .llm_indicator_expander import expand_indicator_candidates
from .llm_time_range_normalizer import normalize_time_range
from .llm_trend_analyzer import call_trend_llm

__all__ = [
    "parse_user_input",
    "call_compare_llm",
    "expand_indicator_candidates",
    "normalize_time_range",
    "call_trend_llm",
]

domains/energy/pipeline/init.py
from .pipeline import process_message

__all__ = ["process_message"]

domains/energy/api/init.py
from .formula_api import FormulaAPI
from .platform_api import PlatformAPI

__all__ = ["FormulaAPI", "PlatformAPI"]

✅ 第三步：创建 EnergyDomain（统一入口）

domains/energy/domain.py

from . import llm
from . import pipeline
from . import api


class EnergyDomain:
    """
    统一能源领域入口，让所有功能都从 domain.energy 访问。
    用法：
        energy = EnergyDomain()
        energy.llm.parse_user_input(...)
        energy.pipeline.process_message(...)
        energy.api.FormulaAPI(...)
    """
    
    def __init__(self):
        self.llm = llm
        self.pipeline = pipeline
        self.api = api


__all__ = ["EnergyDomain"]

✅ 第四步：让 domains.energy 暴露 EnergyDomain

domains/energy/init.py

from .domain import EnergyDomain

# 也可以按需暴露常用 API
from .llm import (
    parse_user_input,
    call_compare_llm,
    expand_indicator_candidates,
    normalize_time_range,
    call_trend_llm,
)

from .pipeline import process_message

__all__ = [
    "EnergyDomain",
    "parse_user_input",
    "call_compare_llm",
    "expand_indicator_candidates",
    "normalize_time_range",
    "call_trend_llm",
    "process_message",
]

🎉 最终使用方式（非常简洁）
方式 1：统一实例入口（推荐）
from domains.energy import EnergyDomain

energy = EnergyDomain()

energy.llm.parse_user_input("高炉能耗是多少？")
energy.pipeline.process_message(...)
energy.api.FormulaAPI.call(...)

方式 2：模块级调用（依然可用）
from domains.energy import parse_user_input, process_message

方式 3：分模块调用（更清晰）
from domains import energy

energy.llm.parse_user_input(...)
energy.api.FormulaAPI(...)

🔥 Bonus：你后续加功能也不需要动 import

例如未来加入：

domains/energy/report/
domains/energy/rules/
domains/energy/validation/


只需要在 domain.py 加：

from . import report
self.report = report


外部所有人立即可用，无需修改任何路径。

这是 真正的领域门面（Domain Facade），DDD/分层架构项目最佳实践。


下面这段写法其实已经 非常优雅、清晰、Pythonic：

from .handlers import (
    handle_single_query,
    handle_compare,
    handle_analysis,
    handle_slot_fill,
    handle_list_query,
    handle_clarify,
)


但如果你希望进一步提升 简洁度、隔离度、可维护性，有下面几种更“专业级”的结构方式（推荐 1 和 2）。

✅ 方案 1：在 handlers/init.py 中集中导出 API（最推荐）
目录结构不变：
handlers/
    analysis_handler.py
    classify_handler.py
    common.py
    compare_handler.py
    list_query_handler.py
    single_query_handler.py
    time_slot_fill_handler.py
    __init__.py

编辑 handlers/init.py：
from .single_query_handler import handle_single_query
from .compare_handler import handle_compare
from .analysis_handler import handle_analysis
from .time_slot_fill_handler import handle_slot_fill
from .list_query_handler import handle_list_query
from .clasify_handler import handle_clarify

__all__ = [
    "handle_single_query",
    "handle_compare",
    "handle_analysis",
    "handle_slot_fill",
    "handle_list_query",
    "handle_clarify",
]

然后 pipeline.py 里就可以写成：
from .handlers import *


或者你想更明确：

from .handlers import (
    handle_single_query,
    handle_compare,
    handle_analysis,
    handle_slot_fill,
    handle_list_query,
    handle_clarify,
)


这样做有三个好处：

✔ 让 pipeline.py 保持简洁
✔ handlers 的对外 API 集中管理
✔ 避免 pipeline.py 对具体文件名产生依赖（以后改名不影响外部）
✅ 方案 2：创建一个“调度器”handlers/dispatcher.py

如果你想更“框架化”，可以做一个统一的 handler 路由器：

handlers/dispatcher.py：
from .single_query_handler import handle_single_query
from .compare_handler import handle_compare
from .analysis_handler import handle_analysis
from .time_slot_fill_handler import handle_slot_fill
from .list_query_handler import handle_list_query
from .clasify_handler import handle_clarify

HANDLER_MAP = {
    "single_query": handle_single_query,
    "compare": handle_compare,
    "analysis": handle_analysis,
    "slot_fill": handle_slot_fill,
    "list": handle_list_query,
    "clarify": handle_clarify,
}

pipeline.py：
from .handlers.dispatcher import HANDLER_MAP


更高级：pipeline 内只管调度，不管具体实现。

🟩 方案 3：handlers 变成一个 Package + 统一前缀命名

例如：

handlers/
    single.py
    compare.py
    analysis.py
    ...


然后：

from .handlers.single import handle as handle_single_query
from .handlers.compare import handle as handle_compare


这种适合更“微内核架构”，不一定是你当前需要的。

🟦 方案 4：自动发现 handlers（插件机制）

适用于未来领域更多、handler 动态扩展：

使用 importlib

handler 都有 HANDLE_NAME 和 handle() 方法

pipeline 自动遍历 handlers 文件夹加载

如果你想要这种插件式架构，我可以给你完整代码。

🔥 最终建议（结合你现在的架构）

你的项目主要面向“能源领域意图解析 + 查询流程”，属于业务逻辑密集型，不用太复杂。

👉 选方案 1（handlers/init.py 作为统一出口）最优雅，也最符合你的当前规模。