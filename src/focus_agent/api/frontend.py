"""Compatibility shim.

Canonical import:
    from focus_agent.web.app_shell import render_chat_app_html
"""

from focus_agent.web.app_shell import render_branch_tree_html, render_chat_app_html

__all__ = ["render_chat_app_html", "render_branch_tree_html"]
