# ============================================================
# 栗栗（Tamias）— 日志导出模块
# ============================================================
# 用户出问题时，把 logs/ 打包成 zip 存到桌面，方便用户邮件发给作者。
# 只打包崩溃日志 + 运行轨迹 + 系统信息，不含对话原文、不含 API Key。
# ============================================================

import platform
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from tamias import __version__
from tamias import app_paths
from tamias.app_log import get_logs_dir, mask_path
from tamias.ui_icons import apply_icon

# 反馈渠道：GitHub Issues（不对外公开邮箱）。
SUPPORT_LINK = "github.com/yuanqubeiding"


def _desktop_dir() -> Path:
    """用户桌面目录（英文 Desktop / 中文「桌面」都试，都找不到就退回用户主目录）。"""
    for name in ("Desktop", "桌面"):
        p = Path.home() / name
        if p.is_dir():
            return p
    return Path.home()


def _system_info() -> str:
    """生成一段系统环境摘要（诊断用，刻意不含 API Key / 对话原文）。"""
    lines = [
        "===== 栗栗 系统信息 =====",
        f"版本：v{__version__}",
        f"导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"操作系统：{platform.system()} {platform.release()}",
        f"Python：{sys.version.split()[0]}",
    ]
    if platform.system() == "Windows":
        lines.append(f"平台：{platform.platform()}")
    return "\n".join(lines) + "\n"


def _collect_dsh_sessions(zf: zipfile.ZipFile) -> None:
    """⚠️ 已默认停用（隐私）：不再被 export_logs 调用。
    把 dsh 已写盘的干活会话轨迹（session.jsonl / session.jsonl.zstd）收进导出。

    dsh 每个干活会话都把完整事件流追加写成 session.jsonl.zstd（zstd 压缩）——
    turn 起止（含结束原因 + 错误码 + 错误信息）、每次工具调用（工具名 + 参数）、
    工具结果、助手每条消息、seq 序号，全在里面。这是「问题出在 dsh 那边」时
    唯一能还原引擎真相的材料：run.log 只记了工具名，没有参数/正文/错误原因。

    路径结构 <DSH_HOME>/sessions/<项目目录编码>/<会话ID编码>/session.jsonl.zstd，
    原样收进 zip 的 dsh/sessions/ 下（二进制 zstd，不解压、不脱敏；作者用 node
    自带的 zlib 或 zstd 工具解压）。文件名经 dsh 的 encodeSegment 编码，ASCII 安全。
    """
    sessions_dir = app_paths.get_dsh_home() / "sessions"
    if not sessions_dir.is_dir():
        return
    for p in sorted(sessions_dir.rglob("session*.jsonl*")):
        if not p.is_file():
            continue
        rel = p.relative_to(sessions_dir)
        # as_posix 归一成 / 分隔，避免 Windows 反斜杠进 zip 导致跨平台解压错乱
        zf.write(str(p), arcname=f"dsh/sessions/{rel.as_posix()}")


def _scrub(text: str) -> str:
    """导出前最后一道脱敏：打码用户名 + 抹掉 API Key 串（sk- 开头）。"""
    import re
    text = mask_path(text)  # 打码 Windows 用户名（打包后路径含 C:\Users\<用户名>）
    # 抹掉形如 sk-xxxxxxxx 的 API Key（DeepSeek / OpenAI 都以 sk- 开头），
    # 兜底防止 dsh 引擎把请求/配置写进日志时 key 混进去
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{6,}\b", "sk-***", text)
    return text


def export_logs() -> str:
    """把 logs/ 打包成 zip 存到桌面，返回 zip 文件路径。"""
    logs_dir = get_logs_dir()
    desktop = _desktop_dir()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = desktop / f"栗栗日志_{stamp}.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # 系统信息（诊断用，不含敏感信息）
        zf.writestr("system_info.txt", _system_info())
        # 日志文件（crash.log / run.log / gate.log）；chat.log 刻意排除——
        # 对话原文可能含用户隐私，用户拍板「导出不含对话原文」。
        # 逐文件读出 → 脱敏 → 写入（不直接 zf.write 原文件，保证导出的都是脱敏后内容）
        if logs_dir.is_dir():
            for f in sorted(logs_dir.iterdir()):
                if f.is_file() and f.name != "chat.log":
                    try:
                        content = f.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
                    zf.writestr(f"logs/{f.name}", _scrub(content))
        # dsh 干活引擎日志（AppData\Tamias\dsh\dsh.log）：dsh 自启失败/干活失败时，
        # 引擎的真实报错只在这里（应用侧只有「结束原因：error」）。之前导出没带它，
        # 作者永远看不到引擎为什么挂。注意：引擎日志可能含干活命令输出，导出前
        # 同样过 _scrub 脱敏（打码用户名 + 抹 API Key），权衡后带上。
        dsh_log = app_paths.get_dsh_home() / "dsh.log"
        if dsh_log.is_file():
            try:
                content = dsh_log.read_text(encoding="utf-8", errors="replace")
            except OSError:
                content = ""
            zf.writestr("dsh/dsh.log", _scrub(content))
        # dsh 干活会话轨迹（session.jsonl.zstd）默认不导出：里面含工具参数/工具结果/
        # 助手消息，可能夹带用户对话与文件内容，导出会泄露用户隐私。作者如需排查
        # dsh 引擎问题，再指导用户单独手动导出该文件。

    return str(zip_path)


# 导出批次 0721C586Q0


def show_export_success(parent, zip_path):
    """导出成功弹窗：显示 zip 路径 + 反馈渠道，反馈链接可一键复制/选中复制。"""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QMessageBox
    from tamias.i18n import tr

    box = QMessageBox(parent)
    box.setWindowTitle(tr("栗栗"))
    box.setIcon(QMessageBox.Icon.Information)
    box.setText(tr(
        "日志已打包导出：\n{}\n\n日志只含运行记录和错误信息，不含聊天内容、也不含 API Key。\n请到 GitHub Issues 反馈并附上这份 zip：\n{}\n作者收到后会尽快帮你处理。",
        zip_path, SUPPORT_LINK))
    # 让整段文本（含邮箱、路径）能鼠标选中复制，别让用户手打
    box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    copy_btn = apply_icon(box.addButton(tr("📋 复制链接"), QMessageBox.ButtonRole.ActionRole), "clipboard", tr("📋 复制链接"))
    copy_btn.clicked.connect(lambda: QGuiApplication.clipboard().setText(SUPPORT_LINK))
    box.addButton(QMessageBox.StandardButton.Ok)
    box.exec()
