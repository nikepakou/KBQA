"""Prompt 模板加载器

使用 Jinja2 管理 system / user / fewshot 三类提示词模板，实现提示词与代码分离。

目录结构：
    src/prompt/
    ├── system/    系统角色提示词（角色定义、规则、输出格式）
    ├── user/      用户消息模板（含动态数据）
    └── fewshot/   few-shot 示例

使用方式：
    from prompt.loader import render_system, render_user, render_fewshot

    prompt = render_system("planner_initial", tools="rag_search, data_analyze")
    user_msg = render_user("planner_initial_user", user_goal="统计用户数量")
    example = render_fewshot("query_plan_example")
"""

from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

# 模板根目录（src/prompt）
_TEMPLATE_ROOT = Path(__file__).parent

# 共享 Jinja2 环境
# - autoescape 关闭：提示词不需要 HTML 转义
# - trim_blocks / lstrip_blocks：去除模板控制行尾换行与行首空白，避免多余空行
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_ROOT)),
    autoescape=select_autoescape([]),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=False,
)


@lru_cache(maxsize=None)
def _get_template(name: str):
    """获取模板对象（带缓存）"""
    return _env.get_template(name)


def render(template_path: str, **kwargs) -> str:
    """渲染指定模板。

    Args:
        template_path: 相对 src/prompt 的路径，例如 "system/rag_qa.j2"
        **kwargs: 模板变量

    Returns:
        渲染后的字符串
    """
    return _get_template(template_path).render(**kwargs)


def render_system(name: str, **kwargs) -> str:
    """渲染 system 角色提示词。

    Args:
        name: 模板名（不含扩展名），对应 system/<name>.j2
        **kwargs: 模板变量
    """
    return render(f"system/{name}.j2", **kwargs)


def render_user(name: str, **kwargs) -> str:
    """渲染 user 角色提示词。

    Args:
        name: 模板名（不含扩展名），对应 user/<name>.j2
        **kwargs: 模板变量
    """
    return render(f"user/{name}.j2", **kwargs)


def render_fewshot(name: str, **kwargs) -> str:
    """渲染 few-shot 示例。

    Args:
        name: 模板名（不含扩展名），对应 fewshot/<name>.j2
        **kwargs: 模板变量
    """
    return render(f"fewshot/{name}.j2", **kwargs)
