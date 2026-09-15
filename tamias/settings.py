# ============================================================
# 栗栗（Tamias）— 配置管理模块
# ============================================================
# 负责 config.yaml 的读写、首次运行自动生成配置、
# 敏感信息从环境变量读取等功能。
# ============================================================

# 配置构建 11C861Q105

import os
import yaml
from pathlib import Path
from typing import Any, Optional

from tamias import app_paths


# ---------- 常量 ----------

# 配置文件名
CONFIG_FILENAME = "config.yaml"

# 配置文件模板（首次运行时生成）
DEFAULT_CONFIG = {
    "deepseek": {
        "api_key": "",                          # DeepSeek API Key
        "api_base": "https://api.deepseek.com/v1",  # API 地址
        "model": "deepseek-chat",               # 默认模型
    },
    "work_dir": "",                             # 干活工作目录（空=项目根目录）
    "dsh": {
        "port": 3080,                           # dsh 引擎端口（自启时记录实际端口，下次复用）
    },
    "pet": {
        "name": "栗栗",                         # 角色名称
        "position_x": -1,                       # 初始 X（-1=自动右下角）
        "position_y": -1,                       # 初始 Y（-1=自动右下角）
        "scale": 1.0,                           # 角色缩放
        "always_work": False,                   # 是否始终干活（绕过闲聊路由）
        "pro_mode": False,                      # 专业模式：显示计划+深色主题
        "work_persona": True,                   # 干活时是否用栗栗人设（开=像栗栗办事，关=纯 dsh 工具腔省 token）
        "chat_font_size": 13,                   # 聊天气泡正文字号（普通=该值，专业=该值-3；范围 10~20）
    },
    "language": "zh-CN",                        # 界面语言（zh-CN/zh-TW/en/ja）
    "persona": "tamias",                     # 人设资源包名（resources/persona/<名字>）
    "weather": {
        "city": "",                            # 手动天气城市（空=按 IP 自动定位）
    },
    "first_run": True,                          # 是否首次运行
    "agreed_terms": False,                      # 是否已勾选同意《用户协议》+《隐私政策》（首次启动弹窗）
    "close_behavior": "",                       # 关窗行为：""=首次问 / "tray"=留在托盘 / "quit"=彻底退出
}

# 环境变量映射：配置路径 → 环境变量名
# 用于敏感信息（如 API Key）可以从环境变量覆盖
ENV_OVERRIDES = {
    "deepseek.api_key": "TAMIAS_DEEPSEEK_API_KEY",
}


class Settings:
    """
    配置管理器
    --------
    负责 config.yaml 的加载、保存和访问。
    自动处理首次运行时的默认配置生成，
    以及从环境变量读取敏感信息。
    """

    def __init__(self, config_dir: Optional[str] = None):
        """
        初始化配置管理器

        Args:
            config_dir: 配置文件所在目录。默认：可执行文件所在目录。
                       开发阶段为项目根目录。
        """
        # 确定配置文件目录
        if config_dir is None:
            # 开发阶段：项目根目录；打包后：%APPDATA%\Tamias\（用户可写，卸载不丢数据）
            config_dir = str(app_paths.get_config_dir())

        self.config_dir = Path(config_dir)
        self.config_path = self.config_dir / CONFIG_FILENAME
        self._data: dict = {}  # 内存中的配置数据

        # 加载配置（如果文件不存在则创建）
        self.load()

    # ---------- 配置加载与保存 ----------

    def load(self) -> None:
        """
        从 config.yaml 加载配置。
        如果文件不存在，自动创建默认配置文件。
        然后从环境变量覆盖敏感配置项。
        """
        if self.config_path.exists():
            # 文件存在：读取
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self._data = yaml.safe_load(f) or {}
            except Exception as e:
                print(f"[栗栗] 读取配置文件失败：{e}，使用默认配置")
                self._data = DEFAULT_CONFIG.copy()
        else:
            # 文件不存在：使用默认配置并保存
            self._data = DEFAULT_CONFIG.copy()
            self.save()

        # 从环境变量覆盖敏感配置
        self._apply_env_overrides()

    def save(self) -> None:
        """
        将当前配置保存到 config.yaml。
        保持 YAML 格式，支持中文注释。
        """
        try:
            # 确保目录存在
            self.config_dir.mkdir(parents=True, exist_ok=True)

            with open(self.config_path, "w", encoding="utf-8") as f:
                # 写入文件头注释
                f.write("# ============================================================\n")
                f.write("# 栗栗（Tamias）桌面智能助手 — 用户配置文件\n")
                f.write("# ============================================================\n")
                f.write("# 敏感信息（如 API Key）优先从环境变量读取。\n")
                f.write(f"# 环境变量：{ENV_OVERRIDES.get('deepseek.api_key', 'N/A')}\n")
                f.write("# ============================================================\n\n")

                yaml.dump(
                    self._data,
                    f,
                    default_flow_style=False,
                    allow_unicode=True,        # 允许中文
                    sort_keys=False,            # 保持字段顺序
                    indent=2,
                )
        except Exception as e:
            print(f"[栗栗] 保存配置文件失败：{e}")

    def _apply_env_overrides(self) -> None:
        """
        从环境变量覆盖配置中的敏感项。
        使用点号分隔的路径表示嵌套配置，例如 "deepseek.api_key"。
        """
        for config_path, env_var in ENV_OVERRIDES.items():
            env_value = os.environ.get(env_var, "")
            if env_value:
                self._set_nested(config_path, env_value)

    # ---------- 通用取值/设值 ----------

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        获取配置值。

        Args:
            key_path: 点号分隔的配置路径，如 "deepseek.api_key"
            default: 如果路径不存在时的默认值

        Returns:
            配置值，或 default
        """
        keys = key_path.split(".")
        value = self._data
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default

    def set(self, key_path: str, value: Any) -> None:
        """
        设置配置值（同时保存到文件）。

        Args:
            key_path: 点号分隔的配置路径，如 "deepseek.api_key"
            value: 要设置的值
        """
        self._set_nested(key_path, value)
        self.save()

    def _set_nested(self, key_path: str, value: Any) -> None:
        """
        设置嵌套配置值（仅内存，不存盘）。

        Args:
            key_path: 点号分隔路径，如 "pet.name"
            value: 要设置的值
        """
        keys = key_path.split(".")
        target = self._data
        for k in keys[:-1]:
            if k not in target or not isinstance(target[k], dict):
                target[k] = {}
            target = target[k]
        target[keys[-1]] = value

    # ---------- 便捷属性 ----------

    @property
    def is_first_run(self) -> bool:
        """是否首次运行"""
        return bool(self.get("first_run", True))

    @is_first_run.setter
    def is_first_run(self, value: bool) -> None:
        """设置首次运行标记"""
        self.set("first_run", value)

    @property
    def agreed_terms(self) -> bool:
        """是否已勾选同意《用户协议》+《隐私政策》"""
        return bool(self.get("agreed_terms", False))

    @agreed_terms.setter
    def agreed_terms(self, value: bool) -> None:
        """设置是否已同意协议"""
        self.set("agreed_terms", value)

    @property
    def language(self) -> str:
        """界面语言"""
        return self.get("language", "zh-CN")

    @language.setter
    def language(self, value: str) -> None:
        """设置界面语言"""
        self.set("language", value)

    @property
    def deepseek_api_key(self) -> str:
        """DeepSeek API Key"""
        return self.get("deepseek.api_key", "")

    @deepseek_api_key.setter
    def deepseek_api_key(self, value: str) -> None:
        """设置 DeepSeek API Key"""
        self.set("deepseek.api_key", value)

    @property
    def deepseek_api_base(self) -> str:
        """DeepSeek API 地址"""
        return self.get("deepseek.api_base", "https://api.deepseek.com/v1")

    @property
    def deepseek_model(self) -> str:
        """DeepSeek 模型名"""
        return self.get("deepseek.model", "deepseek-chat")

    def resolve_work_dir(self) -> str:
        """干活真正的工作目录（写文件 + 会话记忆 + 回滚快照统一用它）。
        只有用户「打开文件夹」开了真文件夹才用那个；空值、或还停在「日常闲聊」
        （项目文件夹藏在 data 目录下，打包后 = 隐藏 AppData）都退回可见的默认工作区，
        否则栗栗产出的文件用户翻不到（"乱放"）。"""
        wd = self.get("work_dir", "") or ""
        if wd:
            try:
                p = Path(wd).resolve()
                # 日常闲聊项目文件夹在 data 目录下（打包后是隐藏 AppData），不算真工作区
                if p.is_relative_to(app_paths.get_data_dir().resolve()):
                    return str(app_paths.get_default_work_dir())
                # 盘符根（"C:\\"/"C:/" 等，resolve 后 parent==自身）：dsh 建会话时会
                # mkdir(cwd) 确保目录存在，而盘符根本来就不能被「创建」、会 EPERM
                # （"failed to ensure project directory"）。退回默认工作区，别把根目录交给引擎。
                if p.parent == p:
                    return str(app_paths.get_default_work_dir())
            except Exception:
                pass
            return wd
        return str(app_paths.get_default_work_dir())

    @property
    def pet_name(self) -> str:
        """角色名称"""
        return self.get("pet.name", "栗栗")

    @property
    def chat_font_size(self) -> int:
        """聊天气泡正文字号（普通模式实际值，专业模式 = 该值 - 3；范围 10~20）"""
        return int(self.get("pet.chat_font_size", 13))

    @chat_font_size.setter
    def chat_font_size(self, value: int) -> None:
        """设置聊天气泡正文字号（同时存盘）"""
        self.set("pet.chat_font_size", int(value))

    @property
    def persona(self) -> str:
        """人设资源包名（换角色 = 改这个字段 + 提供对应资源目录）"""
        return self.get("persona", "tamias")

    @property
    def work_persona(self) -> bool:
        """干活时是否用栗栗人设（开=专业模式像栗栗办事，关=纯 dsh 工具腔省 token）"""
        return bool(self.get("pet.work_persona", True))

    @work_persona.setter
    def work_persona(self, value: bool) -> None:
        """设置干活人设开关（存盘）"""
        self.set("pet.work_persona", bool(value))

    @property
    def weather_city(self) -> str:
        """手动天气城市（空=按 IP 自动定位）"""
        return self.get("weather.city", "")

    @weather_city.setter
    def weather_city(self, value: str) -> None:
        """设置手动天气城市（同时存盘）"""
        self.set("weather.city", value)

    @property
    def pet_position(self) -> tuple:
        """角色初始位置 (x, y)，-1 表示自动"""
        return (
            self.get("pet.position_x", -1),
            self.get("pet.position_y", -1),
        )

    @pet_position.setter
    def pet_position(self, pos: tuple) -> None:
        """设置角色位置"""
        self._set_nested("pet.position_x", pos[0])
        self._set_nested("pet.position_y", pos[1])
        self.save()


# ============================================================
# 模块级测试（直接运行此文件时执行）
# ============================================================
if __name__ == "__main__":
    print("=" * 50)
    print("测试：settings.py 配置管理模块")
    print("=" * 50)

    # 1. 创建配置管理器（会自动生成 config.yaml）
    settings = Settings(config_dir=str(Path(__file__).resolve().parent.parent))
    print(f"\n[测试1] 配置文件路径: {settings.config_path}")
    print(f"         文件存在: {settings.config_path.exists()}")

    # 2. 读取默认配置
    print(f"\n[测试2] 读取默认配置:")
    print(f"         首次运行: {settings.is_first_run}")
    print(f"         角色名称: {settings.pet_name}")
    print(f"         DeepSeek 模型: {settings.deepseek_model}")

    # 3. 修改并保存配置
    print(f"\n[测试3] 修改配置...")
    settings.set("pet.name", "小栗")
    print(f"         角色名称已改为: {settings.pet_name}")
    settings.set("pet.name", "栗栗")  # 改回去
    print(f"         角色名称已恢复: {settings.pet_name}")

    # 4. 测试环境变量覆盖
    print(f"\n[测试4] 环境变量测试:")
    print(f"         API Key 长度: {len(settings.deepseek_api_key)}")
    print(f"         (如果设置了 TAMIAS_DEEPSEEK_API_KEY 则有值)")

    print(f"\n[全部测试通过] OK")
