# ============================================================
# 栗栗（Tamias）— 天气模块（免费接口，零 key 零 token）
# ============================================================
# 拉当前天气，用于功能库里的「查天气」。
# 天气 + 位置名都用 wttr.in（Apache-2.0，明确允许商用）一家搞定：
#   - 填了城市 → wttr.in/{城市}，位置名原样回显用户填的（中文城市中文回显）
#   - 留空 → wttr.in 按请求 IP 自动定位，返回英文位置名 + 天气
#
# 之前还用过 ip-api.com 反查中文地名，但它免费版限「非商业用途」，
# 栗栗是商业软件（皮肤库收费），合规审查后已移除。
#
# 为什么免费：天气 API 是「查一条天气数据」（照表返回），不是 AI 生成，
# 跟 DeepSeek 按 token 计费是两码事。wttr.in 是公共服务，限制的是请求频率
# （一天一两次完全在免费额度内）。
#
# 全部用标准库 urllib（不引第三方依赖），失败静默降级——没网就跳过，
# 不影响其他功能。
# ============================================================

import urllib.request
from urllib.parse import quote

# 天气接口：不带城市参数时 wttr.in 按请求 IP 自动定位（返回「位置名: 天气」）
_WEATHER_URL = "https://wttr.in/?format=3"

# 装成 curl 的 UA：wttr.in 对默认 urllib UA 可能返回 403
_UA = {"User-Agent": "curl/8.0"}


def _http_get(url: str, timeout: int = 8) -> str:
    """带 UA 的 GET，任何异常（无网/超时/非 200）都静默返回空串。"""
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore").strip()
    except Exception:
        return ""


def fetch_weather(city: str = "") -> str:
    """完整天气串：位置名 + 天气，如「深圳 · 🌤️ 31°C」。

    填了 city（手动城市）就查那座城市、位置名原样回显用户填的（中文友好）；
    留空由 wttr.in 按公网 IP 自动定位，位置名是英文（如「Shenzhen, Guangdong, CN」），
    取第一段当城市名展示（「Shenzhen」）。天气拿不到就返回空串。
    """
    if city.strip():
        url = f"https://wttr.in/{quote(city.strip())}?format=3"
        loc = city.strip()  # 用户填的城市，原样当位置名
    else:
        url = _WEATHER_URL
        loc = ""  # 待会儿从返回值里取位置名

    raw = _http_get(url)
    if not raw or ":" not in raw:
        return ""

    # format=3 返回一行如「Shenzhen, Guangdong, CN: 🌤️  +31°C」
    # 或「深圳: 🌤️  +31°C」。按冒号拆成「位置名」和「天气」。
    raw_loc, _, cond = raw.partition(":")
    cond = cond.replace("+", "").replace("  ", " ").strip()
    if not cond:
        return ""

    # 留空自动定位时，位置名从返回值里取第一段（Shenzhen, Guangdong, CN → Shenzhen）
    if not loc:
        loc = raw_loc.split(",")[0].strip()

    if loc:
        return f"{loc} · {cond}"
    return cond


# ============================================================
# 模块级测试（直接跑，打印当前 IP 对应的天气）
# ============================================================
if __name__ == "__main__":
    print("自动定位：", fetch_weather())
    print("手动城市：", fetch_weather("深圳"))
