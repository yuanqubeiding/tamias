# 栗栗（Tamias）— 松鼠侦探管家桌宠

> [English](README.md)

> ⚠️ **当前为 MVP（早期）版本，尚未到 1.0**：因时间与资源等各种因素，本产品**未经充分测试**，
> 可能存在功能缺陷、稳定性或兼容性问题，请勿用于关键/生产场景。
> 如有重大问题，欢迎通过 [GitHub Issues](https://github.com/yuanqubeiding/tamias/issues) 指正反馈。

> Windows 桌面宠物形态的「AI 管家」：能陪你聊天、帮你干活，办事先过门禁、改坏了能一键回滚。
> 栗栗是只穿格纹风衣、戴猎鹿帽的松鼠侦探，气质「清澈大学生」。

## 栗栗能做什么

- **日常闲聊**：调用 DeepSeek API，和栗栗聊天（流式回复、记忆、四语言）
- **专业干活**：让栗栗读文件、搜索、写代码、改文件（走 dsh 引擎，过程逐步可视化）
- **门禁保护**：每个系统操作都要经你审批，工具名翻译成人话、具体命令可折叠查看
- **干活回滚**：动手前自动拍照，改坏了点一下就能精确还原（左右对比 + 一键撤销）
- **顺手小工具**：查天气、番茄钟、随机决定、单位换算、定时提醒
- **语音输入**：按住说话转文字，走 Windows 本地离线识别，音频不上传
- **精灵动画**：栗栗会打哈欠、被戳、看书、思考等 19 组动态小动作，还有随互动起伏的「精神值」

## 技术栈

- **Python 3.14** / **PySide6**（LGPL，闭源商用友好）
- **DeepSeek API**：闲聊链（deepseek-chat）
- **dsh（DeepSeek Harness）**：干活引擎（Node.js 运行时，随包自启）
- **Live2D**：桌宠立绘渲染（Cubism Core + PixiJS）
- 打包：PyInstaller（onedir）→ Inno Setup

## 快速开始（开发）

```bash
pip install -r requirements.txt
python tamias/main.py
```

## 许可与版权

本仓库**代码**遵循 [Apache License 2.0](LICENSE)（开源）。
**立绘、动画、图标、人设等素材**保留版权、不随 Apache-2.0 授权，详见 [素材版权声明](ASSETS_LICENSE.md)。

集成的第三方组件按其各自许可使用，详见 [NOTICE.txt](NOTICE.txt)：

字体（HarmonyOS Sans SC / Noto Sans JP / JetBrains Mono）、Node.js、dsh、
PySide6 / Qt（LGPL-3.0）、Live2D Cubism Core（专有许可）、pixi-live2d-display 与
PixiJS（MIT）、Lucide 图标（ISC）等。

## 致谢

栗栗的一些交互设计，参考了优秀开发工具的现成范式：

- **Claude Code**：忙时排队、审批内联、干活回滚（file-history）、记忆索引
- **Visual Studio Code**：干活过程列表（读文件 / 搜索 / 思考 / 改文件）的呈现

感谢这些工具背后的团队，让我们少踩很多设计上的坑。

## 作者

© 2026 栗栗（Tamias）作者

- GitHub：github.com/yuanqubeiding
- 反馈：GitHub Issues
