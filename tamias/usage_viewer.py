# ============================================================
# 栗栗（Tamias）— 使用说明查看器
# ============================================================
# 把 docs/usage/使用说明.md 渲染成可滚动阅读的对话框，给新用户
# 一个「看不懂栗栗能干嘛」时随时可回看的入口。
#
# 复用 legal_viewer.py 的 LegalTextViewer（它本质就是个 Markdown
# 阅读器：QTextBrowser.setMarkdown() 直接渲染标题/加粗/表格/列表），
# 不重复造轮子，只换文档来源和标题。
# ============================================================

from pathlib import Path

from tamias.legal_viewer import LegalTextViewer
from tamias.i18n import tr, current_language


# 使用说明文档目录：项目根/docs/usage/（打包时需把 docs/usage/ 一起带上）
USAGE_DIR = Path(__file__).resolve().parent.parent / "docs" / "usage"

# 文档名（中文原文 = i18n key）→ 相对 USAGE_DIR 的文件名
USAGE_FILES = {
    "使用说明": "使用说明.md",
}


def usage_markdown() -> str:
    """按当前界面语言返回使用说明正文：英文界面读英文版，其余读中文版（缺英文回中文）。"""
    filename = "使用说明.en.md" if current_language() == "en" else "使用说明.md"
    path = USAGE_DIR / filename
    if not path.exists():
        path = USAGE_DIR / "使用说明.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return tr("文档读取失败：{}", str(path))


def show_usage_guide(title: str = "使用说明", parent=None):
    """打开「使用说明」阅读对话框。

    Args:
        title: 文档名（中文原文当 i18n key，默认「使用说明」）。
        parent: 父窗口（设置窗/桌宠窗等），用于对话框定位。
    """
    dlg = LegalTextViewer(title, usage_markdown(), parent=parent)
    dlg.exec()
