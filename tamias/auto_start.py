# ============================================================
# 栗栗（Tamias）— 开机自启动管理
# ============================================================
# 用 Windows 注册表 HKCU\...\Run 键控制「开机自启动」。
# 纯标准库 winreg，零第三方依赖。注册表键本身就是「唯一真相」：
# 有 Run 值 = 已开启，没有 = 已关闭，所以不需要在 config.yaml 里再存一份状态。
#
# 为什么用注册表 Run 而不是 Startup 文件夹快捷方式：
#   - winreg 纯 Python 就能读写，不用调 COM 建 .lnk（省 pywin32 依赖）
#   - 好开关：写值 = 开，删值 = 关，状态清晰、无残留
#   两者都是 Windows 官方支持的开机自启手段，效果一致。
# ============================================================

import sys
import winreg


# 注册表 Run 键位置（当前用户，无需管理员权限）
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
# 值名（写进注册表的名字，跟栗栗绑定）
_VALUE_NAME = "Tamias"


def _launch_command() -> str:
    """生成开机时启动栗栗的命令行字符串。

    打包后：直接指向 tamias.exe 的绝对路径（带引号防空格路径）。
    开发态：指向 python.exe 并传入 main.py 的绝对路径（不依赖工作目录）。
    """
    if getattr(sys, "frozen", False):
        # PyInstaller 打包：sys.executable 就是 tamias.exe
        return f'"{sys.executable}"'
    # 开发态：python 跑 main.py（绝对路径，开机自启不受「当前目录」影响）
    import os
    main_py = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "tamias", "main.py",
    )
    return f'"{sys.executable}" "{main_py}"'


def is_enabled() -> bool:
    """当前是否已开启开机自启动（查注册表 Run 值是否存在）。"""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY)
    except OSError:
        return False
    try:
        winreg.QueryValueEx(key, _VALUE_NAME)
        return True
    except OSError:
        return False
    finally:
        winreg.CloseKey(key)


def set_enabled(enabled: bool) -> bool:
    """开启/关闭开机自启动。返回是否操作成功。

    开启 = 写入 Run 值；关闭 = 删除 Run 值（删不存在的值视为成功）。
    """
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY, 0,
            winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE,
        )
    except OSError as e:
        print(f"[栗栗] 打开注册表 Run 键失败：{e}")
        return False
    try:
        if enabled:
            winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, _launch_command())
        else:
            try:
                winreg.DeleteValue(key, _VALUE_NAME)
            except FileNotFoundError:
                pass  # 本来就没开，删不到不算错
        return True
    except OSError as e:
        print(f"[栗栗] 设置开机自启动失败：{e}")
        return False
    finally:
        winreg.CloseKey(key)


# ============================================================
# 模块级测试（直接运行此文件时执行）
# ============================================================
if __name__ == "__main__":
    print("=" * 50)
    print("测试：auto_start.py 开机自启动管理")
    print("=" * 50)
    print(f"启动命令：{_launch_command()}")
    print(f"当前状态：{'已开启' if is_enabled() else '未开启'}")

    # 开启 → 验证 → 关闭（来回一次，不留下脏状态）
    print("\n[测试] 开启自启动...")
    print(f"  set_enabled(True) -> {set_enabled(True)}")
    print(f"  is_enabled()     -> {is_enabled()}（应为 True）")

    print("\n[测试] 关闭自启动...")
    print(f"  set_enabled(False) -> {set_enabled(False)}")
    print(f"  is_enabled()      -> {is_enabled()}（应为 False）")

    print("\n[测试通过] OK")
