# ============================================================
# 栗栗（Tamias）— dsh 干活引擎自启模块
# ============================================================
# 负责「把 dsh 引擎拉起来」：打包后普通用户没装 Node/dsh，栗栗自带便携
# node.exe + dsh 依赖树，启动时自动 subprocess 拉起 dsh web，用户无感。
#
# 主流程（start_dsh）：
#   1. 先探测上次记录的端口（自己上次残留的 dsh 还在跑 → 复用）
#   2. 没有 → 从 3080 找第一个空闲端口
#   3. 首次把门禁插件 + profile 模板复制到 %APPDATA%\Tamias\dsh\
#   4. subprocess 拉起 node.exe bin.js web --port <port>（设 DSH_HOME）
#   5. 轮询 session_list 直到就绪，把端口写回 config.yaml 供下次复用
#
# 防冲突三原则：
#   - Node 隔离：只用自带便携 node，绝不依赖系统 PATH 里的 node
#   - 端口冲突：探测 3080 起，被占就换下一个
#   - 凭据/门禁冲突：只复用「自己记录的端口」，别人的 dsh 不碰
# ============================================================

import json
import os
import re
import shutil
import socket
import subprocess
import time
from typing import Optional

from tamias import app_paths
from tamias.app_log import log
from tamias.api.dsh_client import DshClient


# 栗栗自己拉起的 dsh 进程句柄（复用别人的 dsh 时不设，退出时不误杀）
_dsh_process = None

# dsh home 里 profile 的 5 个文件（门禁插件 + 配置），首次复制用
_PROFILE_FILES = [
    "cordis.patch.yml",
    "cordis.yml",
    "package.json",
    "pnpm-workspace.yaml",
    "yy-approval-gate.mjs",
]


def _resolve_runtime():
    """定位便携 node.exe 和 dsh 的 bin.js（打包后 _internal/runtime，开发项目根/runtime）"""
    runtime = app_paths.get_runtime_dir()
    node_exe = runtime / "node" / "node.exe"
    bin_js = runtime / "dsh" / "lib" / "bin.js"
    if node_exe.exists() and bin_js.exists():
        return node_exe, bin_js
    return None, None


def _remove_junction(link):
    """删掉失效的 node_modules junction（只删联接本身，绝不穿透删目标）。
    用 os.rmdir（Windows RemoveDirectory 不跟随重解析点）而非 shutil.rmtree——
    rmtree 可能跟随 junction 把 245MB 依赖树也删掉。"""
    try:
        if os.name == "nt":
            os.rmdir(link)
        else:
            os.unlink(link)
    except OSError:
        pass


def _create_junction(link, target) -> bool:
    """在 link 处建指向 target 的 junction（mklink /J 免管理员权限）。失败返回 False。"""
    try:
        if os.name == "nt":
            r = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=15,
            )
            return r.returncode == 0
        os.symlink(target, link, target_is_directory=True)
        return True
    except Exception:
        return False


def _ensure_dsh_node_modules(dsh_home):
    """把 dsh 依赖树软链到 dsh home（Junction 目录联接），修「plugin tree failed」。

    背景：profile 的 package.json 声明依赖 @deepseek-ai/dsh-base
    + dsh-web-app 等 250+ 个包，Node 按 ESM 规则从 profile 目录往上找 node_modules；
    依赖全在安装目录 runtime/dsh/node_modules（254 个包），AppData 的 dsh home 这边
    没有 → 干净装机报 ERR_MODULE_NOT_FOUND → plugin tree failed。dev 机能跑是碰巧
    （8/22 联网 pnpm 在 profiles/node_modules 生成了 252 个指向 dev 机绝对路径的软链）。

    解法：mklink /J 建目录联接（Junction 免管理员权限，symlink 才需要），把
    dsh_home/node_modules 软链到 runtime/dsh/node_modules。不额外占 245MB、首启不卡。

    补救（断链自愈）：每次启动都校验——依赖树内容在所有安装位置都一样，所以
    「能连到真实依赖」就正常；若链接还在但目标已死（用户搬走了安装目录），
    删掉重建指向当前 runtime，下次启动自动修复，不会永久断链。
    """
    link = dsh_home / "node_modules"
    runtime = app_paths.get_runtime_dir()
    target = runtime / "dsh" / "node_modules"

    if not target.exists():
        # 依赖树缺失（runtime 没准备），交给后续拉起自然失败并报「运行时缺失」
        return

    # 已存在且目标可达（junction 或真目录都算）→ 正常，不动
    if link.exists():
        return

    # 链接还在但目标已死（dangling：lexists 真、exists 假）→ 删掉重建自愈
    if os.path.lexists(link):
        _remove_junction(link)

    # 建 junction 前先确保 link 的父目录（dsh_home）存在——首启时 dsh home 还没建，
    # mklink /J 会因父目录缺失报「找不到路径」（测试机 8/30 首启 dsh 起不来就是它）。
    link.parent.mkdir(parents=True, exist_ok=True)

    # 建 junction；失败记日志（dsh 仍会拉起，只是可能 plugin tree failed，靠 dsh.log 兜底）
    if not _create_junction(link, target):
        log(f"dsh 依赖软链失败：无法建 junction {link} -> {target}", "warning")


def ensure_dsh_home():
    """首次把门禁插件 + profile 模板复制到 dsh home（幂等，已就绪则跳过）。
    同时确保依赖树软链（node_modules Junction）就绪——两件事各自幂等。"""
    dsh_home = app_paths.get_dsh_home()
    profile_dir = dsh_home / "profiles" / "web"

    # 依赖树软链：独立于 profile 复制，每次启动都幂等检查 + 断链自愈。
    # 放最前，即使 profile 已初始化（如测试机之前失败过复制了文件但没建软链），也能补建。
    _ensure_dsh_node_modules(dsh_home)

    # 门禁插件已在即认为初始化完成
    if (profile_dir / "yy-approval-gate.mjs").exists():
        return dsh_home

    template = app_paths.get_dsh_profile_template() / "profiles" / "web"
    if not template.exists():
        # 模板缺失（开发环境没准备 runtime）就退回，让后续拉起自然失败
        return dsh_home

    profile_dir.mkdir(parents=True, exist_ok=True)
    for name in _PROFILE_FILES:
        src = template / name
        if src.exists():
            shutil.copy2(src, profile_dir / name)
    return dsh_home


def _sync_cordis_patch(dsh_home, settings) -> bool:
    """每次启动把 cordis.patch.yml 同步成「最新模板 + 当前人设」，返回 patch 是否变化。

    背景（用户 2026-09-10 报「专业模式不知道栗栗人设」）：旧逻辑只在「首次初始化」时
    从模板拷贝 patch、且只在「拉起新 dsh 进程」时才注入人设——已初始化 + dsh 一直复用
    的机器，patch 永远停在旧版（没有 system-prompt/persona 段），人设（连带后来的联网
    搜索限流，todo 61）都不生效。改成每次启动都从模板重建 patch 静态内容 + 注入当前
    persona，模板升级 / 换人设 / 切语言都能自动同步。返回 True 表示 patch 变了，调用方
    据此决定要不要重启已在跑的 dsh 让新配置生效（patch 是 dsh 启动时加载的静态配置）。

    patch 里的 persona 是带引号的占位符 __YY_PERSONA__，这里用 json.dumps 生成的双引号
    字符串替换它——json 的转义恰好是合法 YAML 双引号标量，中文/换行/引号全对。模板里
    没有占位符（老模板）时追加一条 override，保证有人设段。
    """
    template = app_paths.get_dsh_profile_template() / "profiles" / "web" / "cordis.patch.yml"
    patch = dsh_home / "profiles" / "web" / "cordis.patch.yml"
    try:
        text = template.read_text(encoding="utf-8")
    except OSError:
        return False  # 模板缺失（开发环境没准备 runtime），不阻塞启动

    # 注入当前人设（pet.work_persona 开关：开 → 当前皮+语言，关 → 空串回 dsh 原生腔）
    if getattr(settings, "work_persona", True):
        try:
            from tamias.persona import Persona
            persona_text = Persona(settings.persona).build_system_prompt(settings.language)
        except Exception:
            persona_text = ""  # 人设读失败不阻塞启动，退回原生腔
    else:
        persona_text = ""
    value = json.dumps(persona_text, ensure_ascii=False)
    if '"__YY_PERSONA__"' in text:
        text = text.replace('"__YY_PERSONA__"', value)
    else:
        # 模板里没有占位符（老模板）→ 追加一条，保证有人设段
        text = text.rstrip() + (
            "\n\n# 干活人设（pet.work_persona 开关，占位符缺失自动补上）\n"
            f"- id: system-prompt\n  config:\n    persona: {value}\n"
        )

    # 默认 preset 指向（work_persona 开 → tamias 人设 preset，关 → standard 原生腔）。
    # dsh 的 per-agent 人设由 preset 里 persona row 决定（会 shadow 上面的全局 persona），
    # 所以只改 persona 没用，还得靠 tamias preset（_sync_preset_persona 负责生成）
    # + 这里把 default 指过去。
    preset_name = "tamias" if getattr(settings, "work_persona", True) else "standard"
    preset_value = json.dumps(preset_name, ensure_ascii=False)
    if '"__YY_PRESET__"' in text:
        text = text.replace('"__YY_PRESET__"', preset_value)
    else:
        # 模板里没有占位符（老模板）→ 追加一条，保证有 preset 指向
        text = text.rstrip() + (
            "\n\n# 干活人设 preset 指向（pet.work_persona 开关，占位符缺失自动补上）\n"
            f"- id: agent-presets\n  config:\n    default: {preset_value}\n"
        )

    # 对比写前内容：没变就不写盘、也不触发重启（正常重启栗栗不会白等冷启动）
    try:
        old = patch.read_text(encoding="utf-8")
    except OSError:
        old = None
    if old == text:
        return False

    patch.parent.mkdir(parents=True, exist_ok=True)
    try:
        patch.write_text(text, encoding="utf-8")
    except OSError:
        log(f"写入 cordis.patch.yml 失败：{patch}", "warning")
        return False
    return True


def _inject_preset_persona(source: str, persona_text: str) -> str:
    """把 standard preset 的 agent.cordis.yml 里 persona row 的人设文本换成栗栗人设。

    standard 的 persona row 固定形如：
        - id: persona
          name: '@deepseek-ai/dsh-persona'
          config:
            text: >-
              You are a coding agent powered by the {{model}} model. Your working directory is {{cwd}}.
    这里锚定「- id: persona」起点、只替换其 text 折叠标量，其余行原样保留（standard
    升级时其余内容自动跟随）。找不到锚点就原样返回（调用方据此判断没变化）。"""
    idx = source.find("- id: persona")
    if idx == -1:
        return source
    m = re.search(r"text: >-[^\n]*\n\s*[^\n]+", source[idx:])
    if not m:
        return source
    value = json.dumps(persona_text, ensure_ascii=False)
    return source[:idx] + source[idx:].replace(m.group(0), f"text: {value}", 1)


def _sync_preset_persona(dsh_home, settings) -> bool:
    """每次启动同步「栗栗人设 preset」：把 standard 复制成 tamias 并注入栗栗人设
    （work_persona 开）；或删掉 tamias 回落 standard（关）。返回是否变化。

    背景（用户 2026-09-10 二次排查「专业模式人设没变」）：dsh 的 per-agent 人设由
    preset 里 persona row（@deepseek-ai/dsh-persona）决定，会 shadow 全局
    system-prompt 的 persona —— 之前只改全局 persona，注定被 standard preset 盖掉。
    官方自定义人设入口 = 用户 preset（<dshHome>/.agent-presets/，includeUserRoot
    默认开），所以这里复制 standard → tamias、注入栗栗人设；default 指向 tamias 由
    _sync_cordis_patch 里的 __YY_PRESET__ 占位符负责。standard 只有 agent.cordis.yml
    + preset.yml 两个文件，复制很轻。
    """
    runtime = app_paths.get_runtime_dir()
    standard_dir = runtime / "dsh" / "config" / "agent-presets" / "standard"
    tamias_dir = dsh_home / ".agent-presets" / "tamias"

    if not getattr(settings, "work_persona", True):
        # 关：删 tamias preset，default 回落 standard（纯 dsh 原生腔省 token）
        if not tamias_dir.exists():
            return False
        shutil.rmtree(tamias_dir, ignore_errors=True)
        log("已删除栗栗人设 preset（pet.work_persona 关，回落 standard 原生腔）")
        return True

    # 开：从 standard 复制，persona 注入栗栗人设
    agent_src = standard_dir / "agent.cordis.yml"
    if not agent_src.exists():
        # runtime 没准备（开发环境没配 preset 目录），不阻塞启动
        return False

    try:
        source = agent_src.read_text(encoding="utf-8")
    except OSError:
        return False

    # 人设文本（当前皮 + 语言），失败退回空串（preset 仍建立，只是 persona 空）
    try:
        from tamias.persona import Persona
        persona_text = Persona(settings.persona).build_system_prompt(settings.language)
    except Exception:
        persona_text = ""
    # 保留工作目录感知：standard 原文有 {{cwd}}，栗栗人设里补一句（变量由 agent loop 注册）
    if persona_text:
        persona_text += "\n\n当前工作目录：{{cwd}}"

    new_source = _inject_preset_persona(source, persona_text)
    if new_source == source:
        # 锚点没匹配（standard 升级改了 persona 行），别静默失败，日志点名
        log("standard preset 的 persona 锚点未匹配，人设注入失败（请检查 _inject_preset_persona）", "warning")

    changed = False
    agent_target = tamias_dir / "agent.cordis.yml"
    try:
        old = agent_target.read_text(encoding="utf-8")
    except OSError:
        old = None
    if old != new_source:
        try:
            tamias_dir.mkdir(parents=True, exist_ok=True)
            agent_target.write_text(new_source, encoding="utf-8")
            changed = True
        except OSError:
            log(f"写入 tamias preset 失败：{agent_target}", "warning")
            return False

    # preset.yml（显示元数据，可选）原样复制；源缺失或写失败不阻塞
    meta_src = standard_dir / "preset.yml"
    meta_target = tamias_dir / "preset.yml"
    if meta_src.exists():
        try:
            meta = meta_src.read_text(encoding="utf-8")
            if not meta_target.exists() or meta_target.read_text(encoding="utf-8") != meta:
                meta_target.write_text(meta, encoding="utf-8")
                changed = True
        except OSError:
            log(f"同步 tamias preset.yml 失败：{meta_target}", "warning")

    return changed


def _probe(base_url: str, timeout: int = 2) -> bool:
    """探测某个 base_url 是否是「自己人」dsh（session_list 能通即视为在线）"""
    try:
        DshClient(base_url=base_url, timeout=timeout).session_list()
        return True
    except Exception:
        return False


def find_available_port(start: int = 3080, tries: int = 20) -> Optional[int]:
    """从 start 起找第一个空闲端口，找不到返回 None"""
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return None


def _port_occupied(port: int) -> bool:
    """探测端口是否被占用（bind 成功 = 空闲返回 False，失败 = 被占返回 True）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return False
        except OSError:
            return True


def _kill_port_owner(port: int) -> bool:
    """杀掉占用指定端口的进程树（清理僵死残留 dsh 用）。返回是否执行了清理。

    只在「端口被占但引擎 session_list 无响应」这条异常路径调用，正常启动不触发。
    用 PowerShell 按端口反查 PID（Windows 10/11 自带），再 taskkill /T /F 连子进程
    一起端，避免残留进程一直占着端口导致下次启动撞 EADDRINUSE。"""
    if os.name != "nt":
        return False
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             f"(Get-NetTCPConnection -LocalPort {port} -State Listen "
             f"-ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        pid = r.stdout.strip()
        if not pid.isdigit():
            return False
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", pid],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=15,
        )
        return True
    except Exception:
        return False


def _wait_ready(base_url: str, timeout: int = 180) -> bool:
    """轮询 dsh 就绪（session_list 能通），超时返回 False。
    超时给到 180 秒：dsh 冷启动要加载 3 万+ 文件，测试机的机械盘 + 杀软实时扫描
    能把首次启动拖到 60 秒以上——run.log 实测开发机（SSD）都出现过 60 秒超时，
    机械盘 + 杀软首次扫描更慢，60 秒不够，调到 180 秒兜住绝大多数冷启动。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _probe(base_url):
            return True
        time.sleep(0.5)
    return False


def start_dsh(settings) -> Optional[str]:
    """启动（或复用）dsh 引擎，返回 base_url；失败返回 None。

    Args:
        settings: Settings 实例（读写 dsh.port 记录 + 拿配置）
    """
    global _dsh_process

    # 0. 确保 dsh home 就绪 + 每次同步 cordis.patch.yml + 人设 preset（模板升级/换人设/切语言都在这同步）
    dsh_home = ensure_dsh_home()
    patch_changed = _sync_cordis_patch(dsh_home, settings)
    preset_changed = _sync_preset_persona(dsh_home, settings)
    config_changed = patch_changed or preset_changed

    # 1. 先探测上次记录的端口（自己残留的 dsh 还在跑 → 复用，不重复拉起）
    recorded_port = settings.get("dsh.port", 3080)
    recorded_url = f"http://127.0.0.1:{recorded_port}"
    if _probe(recorded_url):
        if config_changed:
            # patch / preset 变了但 dsh 还在用旧配置跑 → 重启才生效（冷启动重新加载新配置）。
            # 复用别人的 dsh 时 _dsh_process 是 None，改按端口清掉占用的旧进程。
            log("dsh 配置已更新（patch 或人设 preset 变化），重启 dsh 让新配置生效")
            _kill_port_owner(recorded_port)
            time.sleep(0.5)  # 等端口释放，让下面 find_available_port 能回到原端口
        else:
            print(f"[栗栗] 复用已在跑的 dsh 引擎（{recorded_url}）")
            log(f"复用已在跑的 dsh 引擎（{recorded_url}）")
            return recorded_url

    # 1.5 清理僵死残留：记录端口被占但 session_list 无响应，说明是上次退出没杀干净
    # 的 dsh 残留（占着端口但引擎已死）。不清理的话 find_available_port 会跳过 3080
    # 换新端口，残留进程还一直占着资源；主动清掉，下次就能干净地回到 3080。
    if _port_occupied(recorded_port):
        log(f"检测到 {recorded_port} 端口被占但引擎无响应（疑似残留 dsh），尝试清理")
        if _kill_port_owner(recorded_port):
            log(f"已清理 {recorded_port} 端口的残留进程")
            time.sleep(0.5)  # 等端口完全释放，让下面的 find_available_port 能探测到

    # 2. 找空闲端口
    port = find_available_port(start=3080)
    if port is None:
        print("[栗栗] 找不到空闲端口，dsh 无法启动")
        log("dsh 自启失败：找不到空闲端口（3080-3099 全被占用）", "error")
        return None

    # 3. dsh home 与 patch 已在步骤 0 同步过（ensure_dsh_home + _sync_cordis_patch），
    # 这里不再重复；直接定位运行时拉起。

    # 4. 定位运行时
    node_exe, bin_js = _resolve_runtime()
    if node_exe is None or bin_js is None:
        _rt = app_paths.get_runtime_dir()
        _node = _rt / "node" / "node.exe"
        _bin = _rt / "dsh" / "lib" / "bin.js"
        print("[栗栗] dsh 运行时缺失（runtime/node/node.exe 或 runtime/dsh/lib/bin.js 不存在）")
        log(
            f"dsh 自启失败：运行时缺失 —— runtime 目录={_rt}（存在={_rt.exists()}），"
            f"node.exe 存在={_node.exists()}，bin.js 存在={_bin.exists()}",
            "error",
        )
        return None

    # 5. 拉起（设 DSH_HOME；Windows 下 CREATE_NO_WINDOW 防止黑框）。
    # 引擎的 stdout/stderr 落盘到 dsh home 的 dsh.log —— 干活失败时应用侧只有
    # 「结束原因：error」一个词，看不到引擎真正报什么错，日志兜底就靠这个文件。
    # 清掉上一次超时残留的进程（可能还在后台启动、还没监听端口），
    # 否则新旧两个 dsh 抢同一端口：旧的一旦起来会撞新进程 EADDRINUSE。
    if _dsh_process is not None:
        stop_dsh()

    env = {**os.environ, "DSH_HOME": str(dsh_home)}
    # 不再用「启动环境变量」喂 DeepSeek Key（DEEPSEEK_API_KEY）——dsh 的
    # credentials-local 插件把环境变量提供的凭据视为「只读」：一旦启动时环境变量
    # 带了 key，之后 main.py / settings_dialog 的 credentials_set 会被拒
    # （credential-rejected），运行中改 Key 就永远失效。所以 Key 只走 credentials_set
    # 这一条路（main.py 引擎就绪后同步，含重试 3 次兜底）。
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        dsh_log = open(dsh_home / "dsh.log", "ab")  # 追加写，保留历史；后续可加轮转
    except Exception:
        dsh_log = subprocess.DEVNULL  # dsh home 打不开就退回吞掉，不影响拉起
    try:
        _dsh_process = subprocess.Popen(
            # --no-open：dsh web 模式默认会自动打开默认浏览器（弹 127.0.0.1:3080 网页，
            # 见 dsh.log 的 "opening the default browser; pass --no-open to disable"）。
            # 栗栗是内嵌桌宠，不需要浏览器页面，加 --no-open 关掉自动弹窗。
            [str(node_exe), str(bin_js), "web", "--port", str(port), "--no-open"],
            env=env,
            creationflags=creationflags,
            stdout=dsh_log,
            stderr=subprocess.STDOUT,   # stderr 并入 stdout，一起进 dsh.log
        )
    except Exception as e:
        print(f"[栗栗] 拉起 dsh 失败：{e}")
        log(f"dsh 自启失败：拉起进程异常 {e}", "error")
        _dsh_process = None
        if dsh_log is not subprocess.DEVNULL:
            dsh_log.close()
        return None
    if dsh_log is not subprocess.DEVNULL:
        dsh_log.close()  # 父进程侧关掉句柄，子进程仍持有 fd 继续写

    # 补记 dsh 引擎进程 PID，便于诊断时对照。
    log(f"dsh 引擎进程已拉起：node.exe PID={_dsh_process.pid}")

    # 6. 轮询就绪，成功则记录端口供下次复用
    base_url = f"http://127.0.0.1:{port}"
    if _wait_ready(base_url):
        settings.set("dsh.port", port)
        print(f"[栗栗] dsh 引擎已自启（{base_url}）")
        log(f"dsh 引擎已自启（{base_url}）")
        return base_url

    # 7. 超时未就绪：不急着杀进程。冷启动（首次安装 3 万文件 + 杀软实时扫描）
    # 可能 >180 秒，杀掉反而让它白启动、下次还得从头再来。保留进程让它继续起，
    # 把端口写回 config 供下次复用——下次 start_dsh 先 _probe 这个端口，
    # 起来了就直接复用（热启动快，不会再有 180 秒空等）。
    # 应用退出时 stop_dsh 仍会杀它，不会永久残留。
    settings.set("dsh.port", port)
    print(f"[栗栗] dsh 首次启动超时（{base_url}），保留进程后台继续启动")
    log(f"dsh 启动超时（{base_url}，180 秒未就绪），保留进程后台继续启动，下次干活自动复用", "warning")
    return None


def stop_dsh():
    """应用退出时停掉栗栗自己拉起的 dsh 进程（复用别人的不杀）。

    Windows 下用 taskkill /T /F 连子进程树一起端——terminate() 只杀父进程
    （node.exe），dsh 可能 spawn 的 worker/webserver 子进程会残留占着端口，
    下次启动撞 EADDRINUSE 恶性循环。测试机 8/22 就是这么挂的。"""
    global _dsh_process
    if _dsh_process is None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(_dsh_process.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=10,
            )
        else:
            _dsh_process.terminate()
    except Exception:
        # taskkill 失败（进程已退出 / 权限不足）退回 terminate 兜底
        try:
            _dsh_process.terminate()
        except Exception:
            pass
    finally:
        _dsh_process = None
