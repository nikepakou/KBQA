"""Prompt 模板包

提供 Jinja2 模板加载与渲染能力，将提示词与代码分离。

子目录：
    system/    系统角色提示词
    user/      用户消息模板
    fewshot/   few-shot 示例
"""

from prompt.loader import render, render_system, render_user, render_fewshot

__all__ = ["render", "render_system", "render_user", "render_fewshot"]
