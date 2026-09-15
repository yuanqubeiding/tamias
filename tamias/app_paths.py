# ============================================================
# 栗栗（Tamias）— 应用路径管理模块
# ============================================================
# 集中管理「文件该放哪」，统一处理「开发 vs 打包」两种环境：
#   - 开发阶段：config.yaml / data/ / runtime/ 都在项目根
#   - 打包后：config.yaml / data/ / dsh home 移到 %APPDATA%\Tamias\
#             runtime（node.exe + dsh 依赖）在 PyInstaller 的 _internal 里
#
# 之前这些路径散在 settings.py / conversation_store.py / project_store.py
# 各处用 Path(__file__) 相对定位，打包后都指到只读的安装目录（Program Files），
# 用户数据会写进需要管理员权限的地方、卸载还会连数据一起丢。统一收到这里。
# ============================================================

import os
import sys
from pathlib import Path


# 产品数据目录名（%APPDATA% 下，用户可见；用对外英文名 Tamias，避开中文路径坑）
APP_DIR_NAME = "Tamias"


def is_frozen() -> bool:
    """是否 PyInstaller 打包后运行（frozen = 在 exe 里跑，非源码 python）"""
    return bool(getattr(sys, "frozen", False))


def _project_root() -> Path:
    """项目根目录（本文件在 tamias/ 下，上两级就是项目根）"""
    return Path(__file__).resolve().parent.parent


def get_appdata_dir() -> Path:
    """用户数据根目录：%APPDATA%/Tamias/（config.yaml + data/ + dsh home 都放这）"""
    base = os.environ.get("APPDATA")
    if not base:
        # 极端情况（无 APPDATA 的精简系统）退回用户主目录下的 Roaming
        base = str(Path.home() / "AppData" / "Roaming")
    return Path(base) / APP_DIR_NAME


def get_config_dir() -> Path:
    """config.yaml 所在目录：打包后用 AppData，开发阶段用项目根"""
    if is_frozen():
        return get_appdata_dir()
    return _project_root()


def get_data_dir() -> Path:
    """用户数据目录（对话历史 conversations/、项目缓存 projects/）"""
    if is_frozen():
        return get_appdata_dir() / "data"
    return _project_root() / "data"


def get_mods_dir() -> Path:
    """社区 mod 目录（动作包等）：固定放 AppData 用户数据区（可写、卸载/升级不丢）。
    和 config/data 不同，mod 永远属于用户数据（不分开发/打包），社区直接往这丢文件即可。"""
    return get_appdata_dir() / "mods"


# 首次启动写进 mods/README.md 的制作说明（面向社区 mod 作者）
_MODS_README = r"""# 栗栗 动作 Mod 制作说明

欢迎给栗栗做动作 Mod！把动作包丢进本目录的 `animations\` 子文件夹，重启栗栗即生效，不用改代码。

## 一、动作包放哪

丢进（Windows 下即 `%APPDATA%\Tamias\mods\animations\`）：

    animations\<动作名>\

例：`animations\watch_tv\`。

## 二、动作包里有什么

```
animations\<动作名>\
├── frame_000.png
├── frame_001.png
├── ...
└── manifest.json    ← 描述这个动作怎么触发、怎么播
```

- `frame_NNN.png`：透明底 PNG 序列，从 000 连续编号。
- `manifest.json`：动作配置（见下）。

## 三、manifest.json 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| fps | 数字 | 播放帧率，一般 15 |
| logical_scale | 数字 | 素材缩放，一般 2 |
| loop | 布尔 | 是否循环播（缺省 false） |
| ping_pong | 布尔 | 是否正反往复播（缺省 false） |
| offset | 对象 | 位置微调 `{"dx":0,"dy":0}`，dx 正=往右、dy 正=往下 |
| replace | 字符串 | 点名替换某个内置动作（见下方清单） |
| triggers | 数组 | 新增触发（见下） |

### triggers 两种触发

1. 按状态文字触发（栗栗出现这句状态就播）：
   `{"type":"status","status":"正在读取文件…"}`

2. 按空闲时间触发（静置 min_sec~max_sec 随机播一次）：
   `{"type":"idle","min_sec":1800,"max_sec":3600}`

## 四、内置动作名清单（可用 replace 替换）

yawn / reading / poke / nod / angry / hand_touch / pinch_left / pinch_right / appear / disappear / search / folder / think / hand_over / hand_wait / exec_cmd / exec_cmd_loop

## 五、内置已占用的状态文字（status 触发别用，会被内置抢走）

正在上网搜集资料… / 正在上网浏览网页… / 正在搜索文件… / 正在执行命令…

## 六、三个完整示例

（1）换掉内置「搜索」动作 —— `animations\my_search\manifest.json`：
```json
{"fps": 15, "logical_scale": 2, "replace": "search"}
```

（2）加一个「看文件」动作，栗栗出现「正在读取文件…」时播 —— `animations\read\manifest.json`：
```json
{"fps": 15, "logical_scale": 2, "triggers": [{"type": "status", "status": "正在读取文件…"}]}
```

（3）加一个「看电视」动作，静置 30~60 分钟随机播 —— `animations\watch_tv\manifest.json`：
```json
{"fps": 15, "logical_scale": 2, "offset": {"dx": 0, "dy": 0}, "triggers": [{"type": "idle", "min_sec": 1800, "max_sec": 3600}]}
```

## 七、素材要求

- 透明底 PNG 序列，任意工具生成（Aseprite / AE / 视频抠图转帧 等）。
- 建议 15fps、角色高约 560 像素（和内置动作一致；不同大小也能播，只是显示大小略不同）。
- 帧名从 `frame_000.png` 连续编号。

改完丢进去，重启栗栗即可看到效果。
"""


def ensure_mods_dir() -> Path:
    """确保社区 mod 目录存在，并首次生成 README.md 制作说明。
    社区把动作包丢进 mods/animations/ 即生效；README 让他们知道怎么操作。"""
    mods = get_mods_dir()
    (mods / "animations").mkdir(parents=True, exist_ok=True)
    readme = mods / "README.md"
    if not readme.exists():
        try:
            readme.write_text(_MODS_README, encoding="utf-8")
        except Exception:
            pass
    return mods


def get_default_work_dir() -> Path:
    """干活默认工作目录（用户没「打开文件夹」时的产出落点）。
    放在用户看得见的「文档\\栗栗工作区」，不退回隐藏的 AppData——
    否则栗栗产出的文件用户翻不到（"乱放"）。首次调用时自动创建。"""
    d = Path.home() / "Documents" / "栗栗工作区"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_runtime_dir() -> Path:
    """dsh 运行时目录（node.exe + dsh 包）：打包后在 _internal/runtime，开发在项目根/runtime"""
    if is_frozen():
        return Path(sys._MEIPASS) / "runtime"
    return _project_root() / "runtime"


def get_dsh_home() -> Path:
    """dsh 的 DSH_HOME（dsh 用户数据：profiles/ + 凭据 + storages/），固定放 AppData"""
    return get_appdata_dir() / "dsh"


def get_dsh_profile_template() -> Path:
    """门禁插件 + profile 配置模板（首次运行时复制到 dsh home）"""
    if is_frozen():
        return Path(sys._MEIPASS) / "tamias" / "resources" / "dsh-profile"
    return _project_root() / "tamias" / "resources" / "dsh-profile"


def get_logs_dir() -> Path:
    """日志目录（logs/）：打包后 AppData/Tamias/logs（可写，普通权限也能写），
    开发阶段项目根/logs。不能写安装目录——Program Files 只读，普通用户写不进去。"""
    if is_frozen():
        return get_appdata_dir() / "logs"
    return _project_root() / "logs"
