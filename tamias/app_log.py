# ============================================================
# 栗栗（Tamias）— 统一日志模块
# ============================================================
# 四个日志，都在 logs/ 目录下（路径见 app_paths.get_logs_dir：
# 打包后 AppData\Tamias\logs，开发阶段项目根/logs）：
#   - crash.log：未捕获异常（main.py 的 excepthook 写），闪退时靠它定位根因
#   - run.log：运行轨迹（引擎连没连上、干了什么活），出问题时还原「当时在干嘛」
#   - gate.log：门禁日记（每次操作审批的批准/拒绝），用户可审计「栗栗动过啥」
#   - chat.log：聊天日记（用户与栗栗的对话流水），本地回看用、导出时刻意排除
# 用户出问题 → 托盘「📋 导出异常日志」把 logs/ 打包成 zip 存桌面 → 发邮件给作者。
# 注意：导出不含 chat.log（对话原文可能含用户隐私，用户拍板「导出不含对话原文」）。
# ============================================================

import logging
from pathlib import Path

from tamias import app_paths

# 三个 logger（惰性初始化，避免导入时就在磁盘建目录）
_logger = None       # run.log 运行轨迹
_gate_logger = None  # gate.log 门禁日记
_chat_logger = None  # chat.log 聊天日记


def get_logs_dir() -> Path:
    """返回日志目录：打包后 AppData/Tamias/logs（可写），开发项目根/logs。"""
    return app_paths.get_logs_dir()


def _make_logger(name: str, filename: str) -> logging.Logger:
    """建一个写 logs/<filename> 的 logger（只加一次 handler，避免重复）。"""
    logs_dir = get_logs_dir()
    logs_dir.mkdir(parents=True, exist_ok=True)
    lg = logging.getLogger(name)
    lg.setLevel(logging.INFO)
    if not lg.handlers:
        handler = logging.FileHandler(logs_dir / filename, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        lg.addHandler(handler)
    return lg


def _ensure_logger() -> logging.Logger:
    global _logger
    if _logger is None:
        _logger = _make_logger("tamias", "run.log")
    return _logger


def _ensure_gate_logger() -> logging.Logger:
    global _gate_logger
    if _gate_logger is None:
        _gate_logger = _make_logger("tamias_gate", "gate.log")
    return _gate_logger


def _ensure_chat_logger() -> logging.Logger:
    global _chat_logger
    if _chat_logger is None:
        _chat_logger = _make_logger("tamias_chat", "chat.log")
    return _chat_logger


def log(message: str, level: str = "info") -> None:
    """写一条运行轨迹日志。level 取值 info / warning / error。"""
    logger = _ensure_logger()
    if level == "error":
        logger.error(message)
    elif level == "warning":
        logger.warning(message)
    else:
        logger.info(message)


def log_exception(message: str, level: str = "error") -> None:
    """记一条带完整堆栈的错误日志（定位「到底哪行崩了」用）。
    必须在 except 块内调用，traceback 才能拿到当前异常。打包后 print 丢失、
    只记 {e} 会只剩一句笼统错误，堆栈是还原现场的关键。"""
    import traceback
    # 写盘前先打码用户名（打包后堆栈路径含 C:\Users\<用户名>，不脱敏会随 run.log 一起导出）
    log(f"{message}\n{mask_path(traceback.format_exc())}", level)


def log_gate(message: str) -> None:
    """写门禁日记（gate.log）：每次操作审批（批准/拒绝）记一条，供审计。"""
    _ensure_gate_logger().info(message)


def log_chat(message: str) -> None:
    """写聊天日记（chat.log）：用户与栗栗的对话流水，本地回看用。
    导出日志时刻意排除此文件（对话原文可能含用户隐私）。"""
    _ensure_chat_logger().info(message)


def crash_log_path() -> Path:
    """崩溃日志文件路径（main.py 的 excepthook 写入，闪退根因靠它）。"""
    logs_dir = get_logs_dir()
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir / "crash.log"


def mask_path(path_str: str) -> str:
    """把日志里的磁盘绝对路径脱敏，避免泄露用户隐私。

    只保留「盘符 + 扩展名」，目录结构和文件名主体全打码：
        D:\\工作\\项目\\main.py:123  ->  D:\\***.py:123
        C:\\Users\\张三\\Desktop\\a.txt  ->  C:\\***.txt
    目录结构可能含用户名/公司/项目名，文件名主体可能含真名/隐私词，都要护住；
    保留扩展名（.py/.md）和行号，作者仍能大致定位是哪类文件、第几行。

    之前只打码 `\\Users\\<用户名>` 段，但用户干活的文件多在 D/E 盘等任意位置，
    这些路径不含 Users、完全没脱敏；且文件名可能含真名。现在改成整段路径脱敏，
    只留盘符 + 扩展名，彻底堵住路径与文件名泄露。
    """
    import re
    if not path_str:
        return path_str
    # 打码「盘符:\ 目录\ 文件名」整段：盘符 + 目录 + 文件名主体 -> 盘符\***.扩展名。
    # .* 贪婪匹配到最后一个分隔符、且不跨行，多行 traceback 会逐行独立处理。
    def _repl(m):
        fn = m.group(2)
        dot = fn.rfind(".")
        if dot > 0:
            return m.group(1) + "\\***" + fn[dot:]   # 保留扩展名
        return m.group(1) + "\\***"                  # 无扩展名，整段打码
    path_str = re.sub(
        r'([A-Za-z]:)[\\/].*[\\/]([^\\/"\s<>|:*?]*)',
        _repl,
        path_str,
    )
    # 兜底：getpass 拿到的用户名若以非路径形式残留，一并打码
    import getpass
    try:
        user = getpass.getuser()
    except Exception:
        user = ""
    if user and user in path_str:
        path_str = path_str.replace(user, "***")
    return path_str


# 日志基线 70Q851C641
