# ============================================================
# 栗栗（Tamias）— PyInstaller 打包脚本
# ============================================================
# 将栗栗 Python 应用打包成独立的 Windows 文件夹，
# 供 Inno Setup 制作安装程序。
#
# 用法：
#   python build.py
#
# 输出：
#   dist/tamias/tamias.exe   （主程序）
#
# 合规要点（GPL-only Qt 模块的「源头堵」）：
#   PyInstaller 的 PySide6 hook 会「过度收集」——把 PySide6 安装目录里几乎全部
#   Qt6 DLL 塞进产物，包括 QtCharts/QtPdf/Quick3D 等 GPL-3.0-only（或商业授权）
#   模块。它们 LGPL 不覆盖，闭源商用不能随包分发；栗栗只 import
#   QtCore/QtGui/QtWidgets/QtSvg/QtWebEngine，从不碰这些。
#
#   这类 DLL 不是靠 `import PySide6.QtCharts` 收集的（那才会触发独立 hook），
#   而是被 QtQml/QtQuick 的 QML 插件收集机制连带塞进来的，所以 `--exclude-module`
#   排除不了它们（PyInstaller 维护者 rokm 在 Discussion #8673 确认）。
#   唯一可靠的「源头堵」是：在 spec 里、COLLECT 落盘之前，过滤 a.binaries/a.datas。
#   本脚本改成 spec 驱动，注入过滤逻辑；_strip_gpl_qt_modules 保留作事后兜底（双保险）。
# ============================================================

import subprocess
import sys
import shutil
from pathlib import Path


# ---------- 配置 ----------

# 项目根目录
PROJECT_DIR = Path(__file__).resolve().parent

# 入口文件
ENTRY_SCRIPT = PROJECT_DIR / "tamias" / "main.py"

# 输出目录
DIST_DIR = PROJECT_DIR / "dist"

# 应用名称
APP_NAME = "tamias"

# 图标文件（exe 文件图标；tamias.ico 由 tamias_icon.png 生成的多尺寸图标）
ICON_FILE = PROJECT_DIR / "tamias" / "resources" / "icon" / "tamias.ico"


def build():
    """
    执行 PyInstaller 打包（spec 驱动，源头过滤 GPL-only Qt 模块）。
    """
    print("=" * 60)
    print("  栗栗 — PyInstaller 打包")
    print("=" * 60)

    # ---------- 构造 spec 的 datas（原 --add-data，现改为元组列表） ----------

    datas = []

    # 注意：不打 config.yaml 进包。
    # config.yaml 是「用户配置」，打包后从 %APPDATA%\Tamias\ 读（app_paths.get_config_dir），
    # 首次运行由 settings.load() 用 DEFAULT_CONFIG 自动生成（first_run=true → 正常弹首次向导/条款）。
    # 之前这里把「开发机自己用过的 config.yaml」打进包（first_run=false + 开发机 work_dir/session），
    # 虽是死文件不会读，但含隐私路径、还容易误导，已移除。

    # VRM 资源文件夹（3D 模型 + HTML + JS）——已弃用走 Live2D，且 model/测试.vrm 元数据含作者用户名，不打包
    # vrm_dir = PROJECT_DIR / "tamias" / "resources" / "vrm"
    # if vrm_dir.exists():
    #     datas.append((str(vrm_dir), "tamias/resources/vrm"))

    # Live2D 资源文件夹（立绘模型 .moc3/.model3.json + 贴图 + HTML + JS，桌宠核心资源）
    live2d_dir = PROJECT_DIR / "tamias" / "resources" / "live2d"
    if live2d_dir.exists():
        datas.append((str(live2d_dir), "tamias/resources/live2d"))

    # 字体资源文件夹（中英鸿蒙 / 日文思源黑体 JP / 等宽 JetBrains Mono + 各自授权文件）
    fonts_dir = PROJECT_DIR / "tamias" / "resources" / "fonts"
    if fonts_dir.exists():
        datas.append((str(fonts_dir), "tamias/resources/fonts"))

    # 图标资源（tamias_icon.png + tamias.ico，托盘/窗口/任务栏共用）。
    # 之前漏打包 → 打包版 load_app_icon() 找不到 png，退回 QPainter 画的栗子假图标。
    icon_dir = PROJECT_DIR / "tamias" / "resources" / "icon"
    if icon_dir.exists():
        datas.append((str(icon_dir), "tamias/resources/icon"))

    # 界面小图标（Lucide SVG，ui_icons.py 运行时上色）。漏打包 → 按钮/菜单图标全空。
    ui_icons_dir = PROJECT_DIR / "tamias" / "resources" / "icons"
    if ui_icons_dir.exists():
        datas.append((str(ui_icons_dir), "tamias/resources/icons"))

    # 人设资源包（persona.yaml + phrases.yaml，聊天时栗栗的「皮」）。
    # 漏打包 → build_system_prompt 回退到内置兜底人设，聊天人设全错。
    persona_dir = PROJECT_DIR / "tamias" / "resources" / "persona"
    if persona_dir.exists():
        datas.append((str(persona_dir), "tamias/resources/persona"))

    # 精灵帧动画资源（打哈欠等 PNG 序列帧，空闲触发盖在 Live2D 上播）。
    # 漏打包 → 空闲打哈欠动画不播，静默跳过（不影响主功能）。
    animations_dir = PROJECT_DIR / "tamias" / "resources" / "animations"
    if animations_dir.exists():
        datas.append((str(animations_dir), "tamias/resources/animations"))

    # 多语言包（en/ja/zh-CN/zh-TW.json，漏打包 → 切非中文语言全部退回中文原文）
    i18n_dir = PROJECT_DIR / "tamias" / "i18n"
    if i18n_dir.exists():
        datas.append((str(i18n_dir), "tamias/i18n"))

    # dsh 干活引擎运行时（便携 node.exe + dsh 包/依赖），打包后栗栗自启 dsh 用。
    # runtime/ 是构建机本地准备的（gitignore），node.exe + 245MB dsh 依赖树都在里面。
    runtime_dir = PROJECT_DIR / "runtime"
    if runtime_dir.exists():
        datas.append((str(runtime_dir), "runtime"))

    # 门禁插件 + dsh profile 配置模板（yy-approval-gate.mjs 等 5 个文件，进 git 的正本）。
    # 首次运行时复制到 %APPDATA%\Tamias\dsh\，是「干活逐操作审批 + 回滚拍照」的安全核心。
    dsh_profile_dir = PROJECT_DIR / "tamias" / "resources" / "dsh-profile"
    if dsh_profile_dir.exists():
        datas.append((str(dsh_profile_dir), "tamias/resources/dsh-profile"))

    # LGPLv3 / GPLv3 许可证全文（PySide6/Qt 随包分发要求；LGPLv3 引用 GPLv3，故两份都带）
    licenses_dir = PROJECT_DIR / "tamias" / "resources" / "licenses"
    if licenses_dir.exists():
        datas.append((str(licenses_dir), "tamias/resources/licenses"))

    # 第三方字体授权声明（随包分发，满足鸿蒙「显著声明」+ OFL「随附协议」要求）
    notice_file = PROJECT_DIR / "NOTICE.txt"
    if notice_file.exists():
        datas.append((str(notice_file), "."))

    # 协议 / 隐私政策 / 使用说明文档（legal_viewer / usage_viewer 用「项目根/docs/」定位，必须随包）
    docs_legal_dir = PROJECT_DIR / "docs" / "legal"
    if docs_legal_dir.exists():
        datas.append((str(docs_legal_dir), "docs/legal"))
    docs_usage_dir = PROJECT_DIR / "docs" / "usage"
    if docs_usage_dir.exists():
        datas.append((str(docs_usage_dir), "docs/usage"))

    # 隐藏导入（PySide6 的隐式依赖；QtWebEngine 渲染 Live2D 立绘，PyInstaller 偶发漏检，显式声明）
    hidden_imports = [
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "PySide6.QtSvg",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineCore",
        "yaml",
        "requests",
    ]

    # 排除不需要的模块（减小体积）。注意：这只对 Python 模块有效，
    # 对 Qt 的二进制 DLL 无效（Qt DLL 靠 spec 里的 a.binaries/a.datas 过滤，见下）。
    excludes = [
        "tkinter",
        "unittest",
        "test",
        "pydoc",
        "distutils",
        "setuptools",
        "pip",
        "numpy",
        "pandas",
        "matplotlib",
        "scipy",
        "PIL",
    ]

    icon = str(ICON_FILE) if ICON_FILE and ICON_FILE.exists() else None

    # ---------- 生成 spec 文件 ----------
    spec_path = PROJECT_DIR / "tamias.spec"
    spec_path.write_text(
        _render_spec(ENTRY_SCRIPT, datas, hidden_imports, excludes, icon),
        encoding="utf-8",
    )

    # ---------- 执行打包 ----------
    print(f"\n入口：{ENTRY_SCRIPT}")
    print(f"输出：{DIST_DIR / APP_NAME}")
    print(f"spec：{spec_path.name}（含 GPL-only Qt 源头过滤）")
    print("\n正在打包...（可能需要几分钟）\n")

    try:
        result = subprocess.run(
            [
                sys.executable, "-m", "PyInstaller",
                "--clean",
                "--noconfirm",
                f"--distpath={DIST_DIR}",
                f"--workpath={PROJECT_DIR / 'build_temp'}",
                str(spec_path),
            ],
            cwd=str(PROJECT_DIR),
            check=False,
        )

        if result.returncode == 0:
            dist_root = DIST_DIR / APP_NAME
            exe_path = dist_root / f"{APP_NAME}.exe"
            # spec 已做源头过滤，这里 _strip 是兜底双保险：正常应删不到任何东西
            stripped = _strip_gpl_qt_modules(dist_root)
            print(f"\n[SUCCESS] 打包成功！")
            print(f"   EXE 位置：{exe_path}")
            if stripped:
                print(f"   ⚠ 兜底清理了 {stripped} 个 GPL 条目（说明 spec 源头过滤有漏，需检查）")
            else:
                print(f"   ✓ 源头过滤生效：dist 中已无 GPL-only Qt 模块")
            print(f"   文件夹大小：{_get_dir_size_mb(dist_root):.1f} MB")

            # 验证 EXE 存在
            if exe_path.exists():
                print(f"   EXE 文件：{exe_path.stat().st_size / (1024*1024):.1f} MB")
            return True
        else:
            print(f"\n[FAIL] 打包失败（退出码：{result.returncode}）")
            return False

    except Exception as e:
        print(f"\n[ERROR] 打包出错：{e}")
        return False

    finally:
        # 清理临时 spec（不进 git、不污染公开版目录）
        try:
            spec_path.unlink(missing_ok=True)
        except OSError:
            pass


def _render_spec(entry_script: Path, datas, hidden_imports, excludes, icon) -> str:
    """生成 tamias.spec 文本。

    spec 里内联 GPL-only Qt 清单 + _is_gpl_qt 过滤函数，在 COLLECT 落盘前
    从 a.binaries/a.datas 剔除 GPL 模块——这是「源头堵」的核心，比 build.py
    事后删文件更靠前。清单与 _strip_gpl_qt_modules 共用同一组常量（repr 注入）。
    """
    template = '''# -*- mode: python ; coding: utf-8 -*-
# 由 build.py 自动生成（勿手改）。
# 含「源头堵」：在 COLLECT 落盘前，从 a.binaries/a.datas 剔除 GPL-only Qt 模块。

import os

_GPL_PREFIXES = {GPL_PREFIXES}
_GPL_PYD_MODULES = {GPL_PYD_MODULES}
_GPL_QML_DIRS = {GPL_QML_DIRS}
_GPL_PLUGIN_FILES = {GPL_PLUGIN_FILES}
_GPL_PLUGIN_DIRS = {GPL_PLUGIN_DIRS}

def _is_gpl_qt(relpath):
    p = relpath.replace(os.sep, "/")
    if not p.startswith("PySide6/"):
        return False
    rest = p[len("PySide6/"):]
    name = rest.rsplit("/", 1)[-1]
    if name.startswith(_GPL_PREFIXES):
        return True
    if name in [m + ".pyd" for m in _GPL_PYD_MODULES]:
        return True
    if rest.startswith("qml/"):
        qr = rest[len("qml/"):]
        for d in _GPL_QML_DIRS:
            if qr == d or qr.startswith(d + "/"):
                return True
    if rest.startswith("plugins/"):
        pr = rest[len("plugins/"):]
        if pr in _GPL_PLUGIN_FILES:
            return True
        for d in _GPL_PLUGIN_DIRS:
            if pr == d or pr.startswith(d + "/"):
                return True
    return False

a = Analysis(
    [{ENTRY}],
    pathex=[{PATHEX}],
    binaries=[],
    datas={DATAS},
    hiddenimports={HIDDEN},
    hookspath=[],
    runtime_hooks=[],
    excludes={EXCLUDES},
    noarchive=False,
)

# 源头堵：COLLECT 落盘前剔除 GPL-only Qt 模块
a.binaries = [b for b in a.binaries if not _is_gpl_qt(b[0])]
a.datas = [d for d in a.datas if not _is_gpl_qt(d[0])]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name={NAME},
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon={ICON},
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name={NAME},
)
'''
    return template.format(
        GPL_PREFIXES=repr(_GPL_ONLY_QT_PREFIXES),
        GPL_PYD_MODULES=repr(_GPL_ONLY_QT_PYD_MODULES),
        GPL_QML_DIRS=repr(_GPL_ONLY_QT_QML_DIRS),
        GPL_PLUGIN_FILES=repr(_GPL_ONLY_QT_PLUGIN_FILES),
        GPL_PLUGIN_DIRS=repr(_GPL_ONLY_QT_PLUGIN_DIRS),
        ENTRY=repr(str(entry_script)),
        PATHEX=repr(str(PROJECT_DIR)),
        DATAS=repr(datas),
        HIDDEN=repr(hidden_imports),
        EXCLUDES=repr(excludes),
        NAME=repr(APP_NAME),
        ICON=repr(icon),
    )


def _get_dir_size_mb(path: Path) -> float:
    """计算文件夹大小（MB）"""
    if not path.exists():
        return 0.0
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total / (1024 * 1024)


# ============================================================
# GPL-only Qt 模块清单
# ============================================================
# 这些是 PyInstaller 的 PySide6 hook「过度收集」进来的 GPL-3.0-only（或商业授权）
# 模块，LGPL 不覆盖，闭源商用不能随包分发。栗栗从不 import 它们，删掉/过滤掉即可。
# 清单在 spec 源头过滤（_render_spec）和事后兜底（_strip_gpl_qt_modules）两处共用。
_GPL_ONLY_QT_PREFIXES = (
    "Qt6Charts",             # Qt Charts
    "Qt6DataVisualization",  # Qt Data Visualization
    "Qt6Graphs",             # Qt Graphs（DataVis 继任者）
    "Qt6Quick3D",            # Qt Quick 3D
    "Qt6VirtualKeyboard",    # Qt Virtual Keyboard
    "Qt6Scxml",              # Qt SCXML
    "Qt6Lottie",             # Qt Lottie（含 VectorImageGenerator/Helpers 变体）
    "Qt6NetworkAuth",        # Qt Network Authorization（OAuth）
    "Qt6HttpServer",         # Qt HTTP Server
    "Qt6SerialBus",          # Qt Serial Bus（CAN 总线）
    # 防御性：Qt for Automation 三件套 PySide6 主 wheel 目前不带（需 PySide6-Addons），
    # 同属 GPL-only，将来被打包进来也一并清掉
    "Qt6Mqtt",               # Qt MQTT
    "Qt6Coap",               # Qt CoAP
    "Qt6OpcUa",              # Qt OPC UA
    "Qt6Pdf",                # Qt PDF（GPL-only，绑定 PDFium；覆盖 Qt6Pdf/Qt6PdfWidgets/Qt6PdfQuick）
)

# GPL-only Qt 的 Python 扩展模块名（.pyd 文件，不带 Qt6 前缀）。
# 顶层 Qt6*.dll 用 _GPL_ONLY_QT_PREFIXES 匹配；这里匹配 QtCharts.pyd / QtPdf.pyd 这类
# shiboken 生成的 Python 绑定扩展，防止被 QML 链连带收集时漏掉（文件名无 Qt6 前缀）。
_GPL_ONLY_QT_PYD_MODULES = (
    "QtCharts", "QtDataVisualization", "QtGraphs", "QtQuick3D",
    "QtVirtualKeyboard", "QtScxml", "QtLottie", "QtNetworkAuth",
    "QtHttpServer", "QtSerialBus", "QtMqtt", "QtCoap", "QtOpcUa",
    "QtPdf", "QtPdfWidgets", "QtPdfQuick",
)

# GPL-only Qt 的 QML 插件目录（相对 _internal/PySide6/qml/）。
# PyInstaller 打包 PySide6 会「过度收集」：把没用到的 GPL 模块的 QML 插件也塞进 qml/ 子目录，
# 这些插件文件名不带「Qt6」前缀，顶层 DLL 的 glob 逻辑漏不到，必须按目录单独删。
# 注意：qml/QtQuick 本身是 LGPL（合法，不能删），但 qml/QtQuick/VirtualKeyboard 是 GPL，只删这个子目录。
_GPL_ONLY_QT_QML_DIRS = (
    "QtCharts",                        # Qt Charts
    "QtDataVisualization",             # Qt Data Visualization
    "QtGraphs",                        # Qt Graphs（DataVis 继任者）
    "QtQuick3D",                       # Qt Quick 3D
    "QtScxml",                         # Qt SCXML
    "QtQuick/VirtualKeyboard",         # Qt Virtual Keyboard（QML 插件藏在 QtQuick 下）
    "QtPdf",                           # Qt PDF（QML 的 Pdf 组件）
    # 防御性：以下 QML 目录当前 PySide6 主 wheel 不带，同属 GPL-only，将来收集到也删
    "QtLottie",                        # Qt Lottie QML
    "QtMqtt",                          # Qt MQTT QML
    "QtCoap",                          # Qt CoAP QML
    "QtOpcUa",                         # Qt OPC UA QML
    "QtSerialBus",                     # Qt Serial Bus QML
)

# GPL-only Qt 的个别插件文件（相对 _internal/PySide6/plugins/），顶层/QML 目录逻辑都覆盖不到。
_GPL_ONLY_QT_PLUGIN_FILES = (
    "platforminputcontexts/qtvirtualkeyboardplugin.dll",  # Virtual Keyboard 输入插件
    "qmltooling/qmldbg_quick3dprofiler.dll",              # Qt Quick 3D 调试器
    "vectorimageformats/qlottievectorimage.dll",          # Qt Lottie 矢量图像格式插件
)

# GPL-only Qt 的插件子目录（相对 _internal/PySide6/plugins/），整目录都是 GPL 模块专属，直接 rmtree。
_GPL_ONLY_QT_PLUGIN_DIRS = (
    "canbus",            # Qt Serial Bus CAN 插件
    "scxmldatamodel",    # Qt SCXML 数据模型插件
    "assetimporters",    # Qt Quick 3D 资产导入（assimp）
    "geometryloaders",   # Qt Quick 3D 几何加载器
    "renderplugins",     # Qt Quick 3D 渲染插件（scene2d）
    "sceneparsers",      # Qt Quick 3D 场景解析器（gltf/assimp）
)


def _strip_gpl_qt_modules(dist_root: Path) -> int:
    """删掉 PyInstaller 误打包进来的 GPL-only Qt 模块，让产物跟 NOTICE 声明一致。
    这是 spec 源头过滤（_render_spec）之后的兜底双保险：正常应删不到任何东西，
    若删到东西说明源头过滤有漏。删五类：① 顶层 Qt6*.dll；② GPL 的 .pyd；
    ③ GPL 的 QML 子目录；④ 个别 GPL 插件文件；⑤ GPL 插件子目录。
    不碰 QtWebEngine / Qt Quick / Qt 3D 等 LGPL 模块的依赖。返回删除的条目数。"""
    pyside_dir = dist_root / "_internal" / "PySide6"
    if not pyside_dir.is_dir():
        return 0
    removed = 0

    # ① 顶层 GPL-only DLL（Qt6Charts.dll 等，文件名带 Qt6 前缀）
    for f in sorted(pyside_dir.glob("*.dll")):
        if f.name.startswith(_GPL_ONLY_QT_PREFIXES):
            try:
                f.unlink()
                removed += 1
                print(f"    [合规清理] 删除 DLL {f.name}")
            except OSError as e:
                print(f"    [警告] 删不掉 {f.name}：{e}")

    # ② GPL-only 的 Python 扩展 .pyd（QtPdf.pyd 等，文件名无 Qt6 前缀，① 漏不到）
    for f in sorted(pyside_dir.glob("*.pyd")):
        if f.stem in _GPL_ONLY_QT_PYD_MODULES:
            try:
                f.unlink()
                removed += 1
                print(f"    [合规清理] 删除 .pyd {f.name}")
            except OSError as e:
                print(f"    [警告] 删不掉 {f.name}：{e}")

    # ③ GPL-only QML 子目录（qml/QtCharts/ 等；文件名不带 Qt6 前缀，顶层 glob 漏不到）
    qml_dir = pyside_dir / "qml"
    for rel in _GPL_ONLY_QT_QML_DIRS:
        d = qml_dir / rel
        if d.is_dir():
            try:
                shutil.rmtree(d)
                removed += 1
                print(f"    [合规清理] 删除 QML 目录 {rel}")
            except OSError as e:
                print(f"    [警告] 删不掉 {rel}：{e}")

    # ④ 个别 GPL 插件文件（virtualkeyboard 输入插件、Quick3D 调试器）
    plugins_dir = pyside_dir / "plugins"
    for rel in _GPL_ONLY_QT_PLUGIN_FILES:
        p = plugins_dir / rel
        if p.exists():
            try:
                p.unlink()
                removed += 1
                print(f"    [合规清理] 删除插件 {rel}")
            except OSError as e:
                print(f"    [警告] 删不掉 {rel}：{e}")

    # ⑤ GPL-only 插件子目录（Quick3D 的 assetimporters/geometryloaders 等，整目录专属）
    for rel in _GPL_ONLY_QT_PLUGIN_DIRS:
        d = plugins_dir / rel
        if d.is_dir():
            try:
                shutil.rmtree(d)
                removed += 1
                print(f"    [合规清理] 删除插件目录 {rel}")
            except OSError as e:
                print(f"    [警告] 删不掉 {rel}：{e}")

    return removed


# ============================================================
# 主入口
# ============================================================
if __name__ == "__main__":
    success = build()
    sys.exit(0 if success else 1)
