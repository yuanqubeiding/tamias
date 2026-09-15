# 栗栗（Tamias）开发日志

> [English](CHANGELOG.en.md)

> **2026-08-18 改名**：项目「元元（YuanYuan）」→「栗栗（Tamias）」（撞名竞品「仓鼠元元」），英文名 Tamias、日文名 くりくり；版本号重置为 0.1.0。以下为栗栗时代日志，旧「元元」时代日志见下方 v1.0.13 及更早。

## 技术栈（当前，栗栗 v0.1.0）

| 层 | 技术 |
|------|------|
| 语言 | Python 3.14 |
| GUI | PySide6（LGPL，Qt 官方绑定）+ QtWebEngine |
| 立绘渲染 | Live2D（Cubism Core + pixi-live2d-display，QWebEngine 加载） |
| 闲聊 | DeepSeek API（deepseek-chat） |
| 干活引擎 | dsh（DeepSeek Harness，Node.js 运行时随包自启） |
| 配置 | YAML（config.yaml） |
| 打包 | PyInstaller（onedir）→ Inno Setup |
| 角色模型 | Live2D Cubism（.moc3） |

### 技术栈演进（元元 → 栗栗，新旧对照）

| 维度 | 元元 v1.0.x（旧） | 栗栗 v0.1.0（新） | 变更 |
|------|------|------|------|
| GUI | PyQt6（GPL-3.0） | PySide6（LGPL） | 08-24 换库，合规 |
| 立绘 | QPainter 白发少女 → VRM 3D | Live2D（.moc3） | 08-16 定稿 |
| 干活引擎 | Claude Code CLI | dsh（DeepSeek Harness） | 08-15 彻底移除 Claude Code |
| 角色模型 | VRoid Studio → .vrm | Live2D Cubism → .moc3 | 08-16 |
| 闲聊 / 语言 / 打包 | DeepSeek / Python 3.14 / PyInstaller+Inno Setup | 同左（不变） | — |

## 栗栗 v0.1.0 开发期 — 2026-08-16 ~ 09-13

### 形象定稿：Live2D 立绘从无到有 + 改名 + 字体（08-16 ~ 08-20）

- **Live2D 立绘从无到有**：See-through（SIGGRAPH 2026 开源）拆 35 层 PSD → 用户手动二次拆四肢/外套/衬衫/领带 → 用 Cubism 5.4 alpha 官方「外部集成 API」程序化搭骨架（5 个变形器 + 眨眼/眼珠跟随/尾巴/嘴型 9 参数 + 正确嵌套绑定，`_live2d_api/` 客户端库）→ 导出 zhende5.0tamias.moc3 接入桌宠（`pet_widget_live2d.py` 用 QWebEngine 加载，替代旧 VRM 3D 方案）
- **改名「元元→栗栗」**：撞名「仓鼠元元」触发；逐个排查商标/撞名（穆穆/缪缪/榛榛/松松…全崩），最终定「栗栗」（贴松鼠侦探人设 + 好写 + 不撞名）；英文名 Tamias（花栗鼠学名 + 希腊语「管家」，双重咬合）、日文名 くりくり
- **界面字体换开源可商用**：中英 HarmonyOS Sans SC + 日文 Noto Sans JP + 等宽 JetBrains Mono（~26MB），`fonts.py` 统一替换 80+ 处硬编码；坑 = 鸿蒙含假名字形导致字符级 fallback 失效，必须按语言切全局字体；NOTICE.txt 三字体授权声明随包
- **人设资源化（皮骨分离）**：人设五锚 + 来源故事 + 口头禅 + 门禁话术从代码硬编码抽到 `resources/persona/`（persona.yaml + phrases.yaml + 加载器），换角色 = 换目录 + 改 config，代码不动；「拦不拦」（骨）锁死，只换「怎么说」（皮）
- **四语言 i18n 全套**：简/繁/英/日界面文案 + 聊天回复语言跟随界面语言（211+ key）
- **应用图标 + 三界面统一暖棕侦探风**：托盘/任务栏/应用级三处统一

### 门禁方案 B 逐操作审批 + 干活回滚（08-20）

- **方案 B 逐操作审批**：门禁插件 `yy-approval-gate.mjs`（基于 dsh 的 `tools/pre-execute` 返回 `{kind:'ask'}` 即走审批 seam），实现「每个操作逐个问」，弥补方案 A 只拦「整个任务」的粒度缺口
- **干活回滚（改坏能还原）**：复刻 Claude Code「动手前拍照 + 撤销」，不用 git（普通用户不装 git）——门禁插件在 `fs/write-intent` + `fs/edit-intent` 落盘前把原文抄进 `<cwd>/.yuan_yuan/snapshots/`，Python 侧 `snapshot_store.py` 撤销 + 左右对比 UI（`rollback_dialog.py`）+ 聊天流「改了 N 个文件」可点击入口；**真机验收 5 题全过**（改已有精确还原 / 新建撤销=删 / 多文件一键全撤 / 只留最近一次 / 专业模式入口）

### 日志体系 + 内存看门狗 + 合规三件套 + 发布工程（08-21）

- **日志体系四文件**：crash/run/gate/chat 全齐；`log_exporter.py` 一键导出（刻意不含对话原文/API Key，隐私脱敏），反馈走 GitHub Issues
- **内存看门狗**：ctypes 量进程树内存，超 1.5GB 自动 reload Live2D 立绘 + 清 dsh session（`memory_watchdog.py`，不引 psutil）
- **合规三件套**：用户协议 20 节 + 隐私政策 10 节（PIPL 全覆盖）+ AI 标识角标（《暂行办法》第 12 条）+ 首次启动「勾选同意」弹窗 + 右键查看协议/隐私入口
- **新手使用说明**：删旧「教程」系统（环境搭建，跟向导重复），换成「使用说明」七节 + 阅读器
- **安装脚本改名 + 升级机制**：setup.iss 对齐 tamias（8 处）+ AppId 换真实 UUID + [InstallDelete] 升级清理
- **匿名化内容泄露层清零**：API Key / 本机用户名 / 硬编码本地路径 / 测试.vrm 全清，重打包 grep 验证干净
- **dsh 打包自启 + 数据外移 AppData**：Node+dsh 245MB 打进安装包，启动自动拉起（`dsh_launcher.py`），key 共用，数据外移 `%APPDATA%\Tamias\`；dev/frozen/真实 exe 三层验证全过，zip 绿色版 340MB + Inno Setup 安装包产出

### 首次测试 + 修复（08-22）

- 首次外人测试，`docs/测试日志.md` 记 13 条 bug，修 11 条：向导改暖棕侦探风、应用图标漏打包（白发光少女假图标）、persona+i18n 漏打包、版本号统一 0.1.0、日志外移 AppData、dsh.log 落盘、安装目录继承中文路径、启动慢加 Splash、诊断日志强化
- 定位「dsh 自启间歇失败」方向：排除 runtime 缺失 → 指向残留 dsh 进程占端口/锁冲突

### PyQt6 → PySide6 换库（GPL 合规，08-24）

- PyQt6 是 GPL-3.0 copyleft（用 GPL 版分发 = 整包必须开源，与闭源商业冲突），换 PySide6（LGPL，闭源商用友好，Qt 官方绑定）；21 个 `.py` 机械替换 + Live2D(QWebEngine) 真机加载通过；NOTICE 补 PySide6/Qt 授权声明

### 干活体验：步骤可视化 + 审批内联 + 功能库（08-23 ~ 08-24）

- **干活「罗列步骤」可视化**：学 VSCode 接 Claude Code，聊天流逐步显示「读文件/搜索/思考/改文件」，不再只给最终结果（`_StepList` 过程气泡）
- **审批改内联卡片 + 工具名翻译**：常驻右侧审批栏（占 300px）改成聊天流内联卡片（答完即删），工具名 bash/write 翻译成人话，原始命令/JSON 默认折叠
- **干活产出默认落点**：修复「乱放到隐藏 AppData」——默认 `文档\栗栗工作区`，普通用户找得到
- **功能库扩容**：天气（改手动城市 + wttr.in 换掉 ip-api 的非商用限制）/ 随机决定 / 番茄钟 / 单位换算，全本地零 API

### 查看器面板 + 文件预览 + 关窗修复（08-27）

- **右侧查看器一分为二**：原来 240px 项目面板改造成「文件树 / 日志 / 文档」三页可拖拽查看器，吃掉审批删除后的 ~580px 空白；文件页升级成多格式预览（代码/Markdown/.docx 零依赖提取/HTML/图片）
- **dsh 首启「plugin tree failed」修复**：干净装机干活起不来——`mklink /J` junction 软链 node_modules + 断链自愈（方案 A）
- **关窗不退进程修复**：点 X 隐藏≠退出导致删不干净——改「首次关窗二选一（留在托盘/彻底退出）+ 记住」

### Token/余额显示 + 日志脱敏 + 记忆升级（08-30 ~ 08-31）

- **Token 用量 + DeepSeek 余额实时显示**：干活界面每步累计 Token，底部状态条显示账户余额
- **日志隐私脱敏**：写盘 + 导出双打码用户名 + 抹 `sk-` key 串，dsh.log 也过 scrub
- **卸载「选择删除数据」页超大修复**：根因 ShowCaptionBar=False（非 Parent），改官方 CreateCustomForm + 显式钉尺寸；连带加 UninstallSilent 守卫（修 runtime error）
- **记忆升级收尾**：对齐 Claude Code 记忆原理，项目级记忆根 + 索引自动加载 + 正文内联注入 + 「记住 XXX」命令 + [[name]] 交叉引用

### 打包合规 GPL 清理 + 干活并发三连修（09-01 ~ 09-04）

- **GPL QML 插件残留清理**：PySide6 打包误带 GPL-only Qt 模块的 QML 子目录（QtCharts/DataVisualization/Graphs/Quick3D/SerialBus/Lottie 等），扩充 `_strip_gpl_qt_modules` 清理清单；⚠️ 别误删 Qt3D（LGPL 合法）
- **干活「并发叠加 + 假终止 + 排队」三连修**：测试员真机日志坐实——并发 run() 互踩导致 600 秒超时 / 终止键只设标志不真打断 / 忙时回车误当终止；加 busy 互斥 + 真取消 + 排队（忙时入队、干完自动接着做）

### 语音输入 + 测试员反馈（09-05）

- **语音输入（按住说话转文字）**：测试员反馈「不想打字」——对话框旁「麦克风」按钮 + 按住 Alt 键两种触发，松手出字；`speech_input.py` 用 PyWinRT 封装 Windows 本地离线语音识别（**零 token、音频不上传**）；NOTICE + 许可全文 + 隐私政策「不收集语音」合规三件落地。⚠️ 待真机验证中文识别质量 + 打包带上 winrt 包
- **测试员反馈 7 条功能需求**：链接/文件超链接（URL 可点跳转、文件路径可点打开）+ 专业模式隐藏预览页（眼睛图标折叠开关）已做；对话时间分组/字号调整/拖拽开项目等后续分批

### 桌宠精灵动画 + 卡死看门狗 + run.log 事件时间线（09-06）

- **桌宠精灵动画系统（含出场/退场）**：Live2D 之外新增「PNG 序列帧动画」层——`sprite_player.py` 通用播放器（预载 QPixmap + QTimer 逐帧 + 播完发 finished），`pet_window.py` 抽 `_get_sprite`/`_play_sprite_anim`（懒加载 + 冲突停旧播新 + `display_scale` 微调），播完恢复 Live2D。接入一批动作：**出场**（`show_with_animation`，隐藏后重现时播）/ **退场鞠躬告别**（`hide_with_animation` + 退出，播完渐隐）/ **被戳**（左键点击）/ **打哈欠**（空闲触发）/ **看书**（空闲更稀）/ 捏左右 / 按住手害羞 / 连点生气 / 搜索。素材走 Wan2.2 图生视频 → 抠 alpha → `process_*.py` 解帧（appear 308×560 / disappear 315×560，ProRes 4444 带 alpha）。⚠️ 坑：处理脚本 `glob("~\Desktop\*.mov")[0]` 桌面 3 个 .mov 取错、被戳动画实为打哈欠内容，改明确指定「被戳一下.mov」重生成 30 帧；打哈欠间隔 3~5 分钟→30s~1min
- **卡死看门狗**：dsh 真卡死（LLM 挂住/工具死循环）时别让测试员干等满 600 秒——`STALL_TIMEOUT = 180`（依据 dsh 工具超时 120 秒留余量），盯「距上一条事件多久没动静」而非「任务总时长」（长任务不误杀）；等主人审批/反问期间（`_waiting_user`）跳过判定；触发单独报「引擎疑似卡住」，跟「任务超时」区分
- **run.log 事件时间线**：让 run.log 自己就是一份「dsh 在干嘛」的完整流水——`turn/end` 补记 `reason.error.message` + `code`（能看到为什么失败）、关键事件记 `seq`（重连漏事件可发现）、每条附「距上条 Xs」、补 `turn/start` 日志（区分「没开始」vs「开始了又卡住」）
- ⚠️ 均为源码级、未真机验证；run.log 的「任务防串台」（后台线程回报校验序号）仍待做

### 排队可见化 + 体验四连修 + 打包（09-07）

- **排队队列可见化**：忙时接话是「排队不是抢占」，但之前队列不可见、无上限、不能删单条——加排队面板（消息区与输入框之间），上限 3 条（满了提示、不吞消息），每条带 ✕ 删除，当前任务原文（正在处理）与排队原文（排队中）分开显示
- **刷新按钮防手贱**：刷新会取消在跑任务 + 停网关 + 冷重启 dsh（最长 180s），已连接时连续点 = 自毁——改「只在未连接/刷新中显示」，已连接隐藏
- **实时秒表 + token 显示**：标题栏加每秒跳的计时 + token 数（干活累加真实值、闲聊中途估算 ≈N→结束用真实值校准），让用户看见栗栗「还在动」而不是干等
- **会话串线修复**：切会话时清 DeepSeek 闲聊多轮历史——修「答非所问」（问「为什么超时」却答「任务完成啦 + 以后用日语 + Get-Date 被拒」这类跨会话串台）
- **换行丢失修复**：专业模式隐藏预览页后回复丢分行——`_linkify` 转义后 `\n`→`<br/>` 保留段落（RichText 会把换行折叠成空格）
- **打包编译**：`python build.py`（988.7MB 文件夹，GPL-only Qt 清 30 项）+ ISCC（`tamias_setup_v0.1.0.exe`，282MB），发测试员用
- ⚠️ 以上除打包外均为**源码级实现、未真机验证**，随本轮安装包进测试员真机

### 搜索限流 + 一批 bug 修复 + 模式隔离 + 计划卡（09-08 ~ 09-10）

- **联网搜索限流**：dsh 默认 web 搜索 60s 超时 / 5 次，搜个信息要等很久、烧 token——折中 30s / 3 次（`cordis.patch.yml` 两个 id-targeted override；⚠️ patch 是整段替换、保留 `fetch:false` 防 SSRF 与 `apiKeyEnv`）
- **一批 bug 修复**：①对话历史持久化（切对话 AI 回复被清空只剩提问——同步保存 + 固定捕获 conv 对象）②pwsh 只读命令白名单（Test-Path / Select-String / Get-Location 三个「只看不改」放行，引号感知拆子命令 + 逐动词校验）③盘符根路径兜底（选中整个盘 work_dir 被设成盘符根 EPERM，退回默认工作区）
- **模式隔离四修 + chat_dialog 瘦身**：①「最近」列表按模式过滤（专业只看文件夹项目、普通只看日常闲聊）双向封堵跨模式串门 ②对话页加切模式按钮（不必退回启动器）③切模式清空对话状态（回初始界面、不接续旧对话防卡）④抽 ReplyWorker / AnimatedButton / SlideStack 三个辅助类到 `chat_widgets.py`（chat_dialog 3154→2958 行）
- **去「白发少女」兜底**：QPainter 手绘的「二次元白发少女」兜底太丑但又是资源缺失保险丝删不得——三处兜底统一改成「画栗子」（共享 `draw_chestnut()` 暖棕渐变栗子，不画五官保生命感）；顺带修了「i18n key 与 setup_wizard 原文不匹配 → 非中文翻译失效」的隐藏 bug
- **专业模式干活没人设修复**：`ensure_dsh_home()` 用「门禁插件已存在」判「已初始化」后**不再同步模板** → 后来加的 persona 段（连带搜索限流）对已初始化机器不生效；改 `_sync_cordis_patch` 每次启动从模板重建 patch + 变了就重启 dsh
- **干活「计划卡」可视化**：像 Claude Code 那样把 AI 的步骤计划列成 ☐待做 / ⏳进行中 / ✅完成 清单、逐条打勾——dsh 的 `todo/write` 事件经 `on_todo` 回调链（6 文件：dsh_backend → gate → main → ReplyWorker → chat_dialog `todo_event`）落到新增 `PlanCard` 控件（「📋 计划」+「已完成 N/M」计数 + 三态配色深/浅双主题），补上「罗列步骤」当时留的计划那块（过程已做、计划未做）
- ⚠️ 以上均为**源码级实现、未真机验证**，随下一轮打包进测试真机

### 开源准备：协议拍板 + 干净历史 + 同源自证 + 补署名（09-13）

- **开源协议拍板**：代码走 Apache-2.0（宽松 + 专利条款 + 不传染，跟 VPet 一致）、立绘/动画/图标/人设**素材单独保留版权**不随 Apache-2.0 授权（护城河在形象/IP 不在代码）；走过 PolyForm 非商用、GPL 传染两条弯路后定的
- **待办冲突理顺**：原「防抄/私有」旧线对齐开源——Nuitka 目的从「防抄」改「防篡改 + 防反编译出素材」、「仓库必须私有」作废（素材版权 + 时间戳 + 署名兜底防抄）
- **公开版干净历史**：公开版从证据版派生后**全丢重开**为全新 git 历史（脱敏掉本地绝对路径 / 用户名 / 密钥占位），提交作者统一匿名 `yuanqubeiding` + GitHub noreply 邮箱
- **同源自证 PROVENANCE.md**：证据 bundle 的 SHA-256 + 可信时间戳（tsa.cn 脱敏认证）锚定「公开版发布时作者已持有完整底稿」；SHA-256 单向不可逆，公开哈希不泄露隐私
- **补署名**：README + `tamias/__init__.py` 的 `__author__` 加 GitHub 链接（github.com/yuanqubeiding）
- **对手调研**：扫了一遍干活桌宠对手（Miku / AgentPet / Clawd / DSH 鲸鱼娘等），定位收敛「只学壳不碰核、现状够用不再靠拢」

### 决定开源（09-14）

- **闭源？算了**：作者原本想闭源藏着，后来一想，天天防这防那累不累——才不是怕被抄才开源的，纯粹懒得藏了。至于你们用不用……随缘吧，反正东西就在这。
- **才不是随便丢的**：代码 Apache-2.0、素材单独保留版权，版权声明一条不落。嘴上说随缘，其实每行代码、每张立绘都认真磨过，有人拿去用、点个 star，才算没白忙——哼，才没有天天盯着 star 数呢。

### 打包合规 + MVP 版本 0.1.5（09-15）

- **版本号定 0.1.5（MVP 版）**：`__version__` 0.1.2 → 0.1.5，安装包 `tamias_setup_v0.1.5.exe`
- **GPL 合规从「事后删」升级「源头堵」**：PyInstaller 的 PySide6 hook 会过度收集 GPL-only Qt 模块（QtCharts/QtPdf/Quick3D 等）的 DLL；这些 DLL 不是靠 `import` 收集、而是被 QtQml/QtQuick 的 QML 插件收集机制连带塞进来，所以 `--exclude-module` 排除不了（PyInstaller 维护者 rokm 在 Discussion #8673 确认）
- **build.py 改 spec 驱动**：在 spec 里、COLLECT 落盘前过滤 `a.binaries`/`a.datas`，从源头剔除 GPL 模块；`_strip_gpl_qt_modules` 保留作事后兜底（双保险）
- **补漏 QtPdf/QtPdfWidgets/QtPdfQuick**：之前清理列表漏了 GPL-only 的 Qt PDF 模块（绑定 PDFium），已补进清单 + 新增 .pyd 模块名匹配
- ⚠️ 源码级验证通过（spec 生成 + 过滤函数 34 用例全过），**尚未重新打包验证**（打包中途停，改天重跑）

## v1.0.13 — 2026-08-15

### Claude Code 彻底移除：干活链路只走 dsh

- 背景：dsh 未成熟时，干活链路是「dsh 优先 + Claude Code 回退」，单点依赖三个环节（dsh / Claude Code CLI / DeepSeek Key），断一个就退化。现在 dsh 已端到端验证通过，回退路径反而变成隐患（之前还出过 ENOTFOUND stale 报错），于是彻底摘掉 Claude Code
- 改动范围（改 9 文件 + 删 1 文件 + 配置迁移）：
  - `settings.py`：删 `claude_code` 配置块 + `claude_executable` 属性，加顶层 `work_dir`、`always_work`
  - `main.py`：删 `claude_runner` 初始化 + `claude_handler` + claude 回退，`work_handler` 只走 dsh
  - `gate.py`：`claude_handler` → `work_handler`，清 Claude 文案
  - `pet_window.py`：信号/复选框/属性改名，`working_dir` → `work_dir`
  - `chat_dialog.py`：教程 5→3 项，删 Claude Code/DeepSeek 检测分支 + `_start_pro_mode_flow` 死代码
  - `setup_wizard.py`：删 Claude Code CLI 检测页
  - `confirm_dialog.py` / `api/__init__.py`：注释 de-Claude
  - 删 `api/claude_code.py`
- 配置键迁移：`claude_code.working_dir` → 顶层 `work_dir`；`pet.always_claude` → `pet.always_work`
- ⚠️ 本机安装的 Claude Code CLI **保留未动**——只摘元元代码里的引用，不卸载本机 CLI
- 验证：`compileall` 全语法 OK + grep 无残留 `claude_code` 引用 + 重启实测（桌宠显示 / 闲聊 / 干活+门禁）三路全通
- 影响：干活链路现在单点依赖 dsh——dsh 挂了元元会老实说「干活引擎没连上」，不再静默回退（诚实，但少了一层保险）

## v1.0.12 — 2026-08-15

### 门禁（方案 A）落地：干活前先问主人，杜绝「先上车后补票」

- 根因：之前门禁想靠 dsh 的 `approval/requested` 事件拦，但 dsh 审批是**被动**的——只在碰文件沙箱时才发，启动进程（如打开 Edge）根本不触发，所以「先执行了才问」
- 修法：把「干活前确认」接到 `work_handler` 这个**干活总闸**上，任何干活请求（智能路由 + always_claude 两条路）在发给引擎之前，先在主线程弹二次元确认窗，主人批准才动手
- 「是否要审核」不靠枚举危险动作（枚举不完），只判断「闲聊 vs 干活」，是干活就先问：
  - `gate.py` 的 `_classify`：关键词快筛 → DeepSeek 语义兜底 → 失败默认闲聊（fail-safe，宁可漏干活不可漏审批）
  - 确认 UI：优先聊天框右侧**审批栏**（`request_gate_approval` + `_gate_event` 阻塞等待，融入界面不弹独立窗口），非专业模式/聊天框未就绪回退 `confirm_dialog.py` 的 `show_confirm`；跨线程用 `_MainThreadInvoker`（BlockingQueuedConnection）
  - `_MainThreadInvoker` 从 dsh 初始化 try 块**提到外层**，dsh 不可用时门禁仍可用（回退 Claude 也拦得住）
- 边界（方案 B 待补）：粒度是「整个任务」——「打开 Edge」能精确拦，但「帮我跑项目」这种模糊任务，批准后 dsh 内部拆出的中途操作仍不逐个问

## v1.0.11 — 2026-08-15

### 设置界面：API Key 的「填 / 显 / 删」落地

- 新增 `yuan_yuan/settings_dialog.py`：托盘「设置...」打开的真实设置对话框
  - 填：Key 输入框（密码模式 + 👁 显示/隐藏切换）
  - 显：打开时自动回填已保存的 Key，状态栏打码预览（`sk-...后4位`）
  - 删：二次确认后清空，明确提示「不会崩溃，聊天退回复/干活提示没 Key」
- 「一套 Key 两张嘴」双写：
  - 闲聊 → `config.yaml` 的 `deepseek.api_key`（元元自己的 DeepSeek 客户端）
  - 干活 → dsh 引擎凭据 `credentials.set` / `credentials.unset`（新增这 3 个 RPC：set/unset/describe）
  - 引擎没开时优雅降级：只写 config.yaml，并弹提示「等引擎启动后再设/删一次」
- 接线：`tray_icon.py` 的「设置...」从 TODO 改成真回调，`main.py` 传入 `open_settings`
- 诚实说明：改动/删除 Key 需**重启元元**才完全生效（运行中的闲聊客户端 / 门禁是启动时初始化的）

### 承重墙现状

- 桥通了、接线了、设置界面也齐了。剩下最后一环：**填 Key 真跑一遍**，验「记忆（会话恢复）+ 门禁（审批弹窗）」端到端

## v1.0.10 — 2026-08-15

### 桥通了：dsh_client.py 写完并验证

- 把 dsh 的线上协议彻底摸透了（源码级逆向，不是猜）：
  - 事件流是**标准 WebSocket**（不是之前以为的 SSE），连 `ws://127.0.0.1:3080/api/events.mux`
  - HTTP RPC 是 `POST /api/<method>` + `client-request`/`server-response` 信封
  - 审批闭环 = 收 `approval/requested` 帧 → `POST /api/respond` 回允许/拒绝 → 引擎继续跑
- 写了 `yuan_yuan/api/dsh_client.py`（三件套，全中文注释）：
  - `DshClient`：HTTP RPC（会话/工作区/审批应答），同步
  - `DshEventStream`：WebSocket 事件流，后台线程跑 asyncio，断线自动重连
  - `DshGateway`：组合门面，`on_approval(rpc_id, payload)` 回调 + `answer()` 应答
- 实测通过：
  - `session.list` 读到 2 个测试会话 ✓
  - `session.create` 预分配 ID 幂等（同 ID 返回同会话）✓ —— **记忆的地基确认可用**
  - WebSocket 连上即收 `session/subscribed` 帧 ✓

### 承重墙现状

- 墙的地基（桥）已经打好。还差两段：配 DeepSeek API Key、把 main.py 的 claude_handler 换成 DshGateway
- 端到端（真跑任务 + 审批弹窗）需要 Key 才能验

### 诚实总结

> 协议摸透了，桥写好了，连"记忆能恢复"都验了一半。但还停在"打地基"——没 Key 就没法证明门禁真能接上元元的弹窗。下一步不是写代码，是填 Key。

## v1.0.9 — 2026-08-15

### 重大转机：DeepSeek Harness 出现，记忆这道山沟有路可走了

- DeepSeek 8 月 13 号开源 **DeepSeek Harness（DSH）v0.1**，MIT 协议，定位「对标 Claude Code」
- 核心理念「Model + Harness = Agent」+「一切皆插件」——模型、工具、门禁、会话、沙箱、存储全是可替换组件
- 精准命中我们卡死的两件事：
  - **记忆**：会话（session）是一等公民组件，配套 ACP 协议做跨进程会话恢复（正是 `--session-id` 反复 "already in use" 的那个坑）
  - **门禁**：门禁/审批是可插拔插件，元元可以写自己的门禁装进 Agent 循环，不再靠 plan/bypassPermissions 去「绕」
- 且跑 DeepSeek 原生模型，不翻墙、不登录 Anthropic —— 教程里「设 ANTHROPIC_BASE_URL」那套丑办法可以删

### 思路升级：元元从「遥控器」变「本体」

- 旧架构：元元 = Claude Code 的遥控器（subprocess 喊话，门禁在别人手里）
- 新方向：元元 = Agent 运行时本身（脸=桌宠、门禁=自己的插件、会话=标准协议、模型=DeepSeek）
- 关键约束：Harness 是 Node/TS，元元是 Python，不能 import，要 ACP/stdio 桥接；gate.py 不能被 TS 重写

### 记忆拆解（诚实的边界）

- 短记忆（一次对话里记得前面）→ Harness 原生会话恢复，能解决
- 长记忆（关掉重开还记得）→ 仍靠 `.yuan_yuan/` 存储 + 上下文注入，但短记忆一通它才第一次真正有用

### 进度

- dsh 已全局安装成功（528 packages）
- 待办：摸清接口（headless / 能否外部审批 / 会话恢复）→ 画承重墙施工图 → 动 gate.py

### 诚实总结

> 等了两个月，DeepSeek 的「DeepCode」以 Harness 的形式来了。但 v0.1 不稳、接口未验证、还有 Python↔Node 语言边界要跨。不是终点，是终于有了一条看起来能走通的路。

## v1.0.8 — 2026-07-24

### 搁置：记忆问题

- 会话透传尝试 4 次，全部失败。`--session-id` 复用始终报 "already in use"
- 管道模式（常驻子进程）——Claude Code CLI 的 `--print` 是一次性的，交互模式是 TUI 无法解析
- Anthropic API 直连——需要翻墙 + Anthropic Key，现阶段不现实
- Trae Agent CLI 考察过——国内可用，但尚未测试

**结论**：Claude Code CLI 的子进程模型不支持元元需要的会话持久化。等待 DeepSeek 推出自研 CLI 编程助手（"DeepCode"），届时直接替换后端即可。前端 UI、门禁层、项目面板无需改动。

### 维持状态
- 聊天：上下文注入方式（`chat_text` 带最近对话），勉强可用
- 干活：plan → 审批 → exec，门禁正常，但不带记忆
- 路由：两条路（干活关键词 → 审批流 / 其余 → 聊天直回），简单干净

## v1.0.7 — 2026-07-22

### 大扫除（删代码比写代码多的一天）

- 删掉 `PersistentClaudeSession`（常驻进程从来没跑通过）
- 删掉 `_call_deepseek_directly`（纯对话 DeepSeek 直连）
- 删掉 `claude_handler` 里所有分支（exec/chat/plan 三条路全砍）
- 删掉 `main.py` 里所有路由（gate、TASK_KEYWORDS、_always_claude）
- 删掉上下文拼装（`full_text`、`chat_text`、`recent`）
- 删掉残留死代码（孤立的 `claude_runner.run()` 调用、重复的 plan 段）

### 修复：门禁终于管用了

- **根因**：`_start_pro_mode_flow` 走的是 `_on_message_callback` → `claude_handler` → `bypassPermissions`。plan 被当成聊天直接执行了，审批栏形同虚设。
- **修复**：`_start_pro_mode_flow` 直接用 `ClaudeCodeRunner(permission_mode="plan")` 调 Claude Code，不经过 `claude_handler`。审批栏亮 → 点批准 → `__EXEC__` → `bypassPermissions` 真正执行。
- 验证：说"打开Edge" → plan 返回"需要审批" → Edge **没打开** → 点批准 → Edge 才打开。门关紧了。

### 当前架构（简单干净）

```
chat_dialog.py:
  干活关键词 → _start_pro_mode_flow → plan（只看不执行）→ 审批 → exec
  其余消息 → _ReplyWorker → claude_handler → bypassPermissions

main.py claude_handler:
  __EXEC__ → bypassPermissions 执行
  普通消息 → bypassPermissions 直回
```

### 诚实总结
> 删了 200+ 行烂代码，加回 20 行。门禁从纸糊的变成了真门。
> 代价：审批流每次新建 ClaudeCodeRunner（~2秒开销），但正确性优先。

## v1.0.6 — 2026-07-22

### 退展（今天主要修 bug，路由逻辑越改越乱）

- 路由从四条分支简化为两条（干活 → 审批 / 其余 → 聊天）
  - 简化是对的，但过程中产生了残留代码和缩进错误
- 聊天记忆反复丢：full_text → text → 又加回上下文 → 格式不对 → 再改格式
  - 结论：上下文传递方式不稳定，需要统一成结构化格式
- 项目存储从集中式改为跟随文件夹（`.yuan_yuan/`）
  - 注册表模式工作正常，但旧数据需要手动迁移
- Claude Code session 复用彻底关闭（每次都 `--no-session-persistence`）
  - 避免了"session already in use"错误，但失去了 plan→exec 会话连贯性
- 审批栏激活逻辑三次打补丁仍不稳定
  - `_on_plan_done` 直接操作按钮属性，绕过 `_activate_approval`
- "命名为元元"等模糊消息仍偶尔漏到审批流
  - 关键词匹配的天然缺陷暴露
- 聊天回复时 Claude Code 看到项目文件就乱回复
  - chat 路径改走 DeepSeek，但记忆又丢了

### 诚实总结
> 今天修了 10+ 个 bug，修出一个新的。代码从清楚的四分支变成了复杂的补丁堆。
> chat_dialog.py 的路由逻辑需要一次彻底的重构——集中管理、远离 `_on_send`。

### 下一步
- 重构：把路由抽成独立函数，去掉所有内联分支
- 统一上下文传递格式（结构化 JSON，不是字符串拼接）
- 不再往 chat_dialog.py 里加新功能，直到清理完毕

## v1.0.5 — 2026-07-21

### 修复
- 审批栏不激活：项目模式下模糊消息（非聊天非干活）走到普通回复路径，不会触发 `_on_plan_done`，审批栏永远不亮。
  - 修复路由：项目模式只有明确聊天关键词才直回，其余全部走审批流
- 打开项目时旧对话不保存、不清空，新项目显示旧项目对话
  - `_pick_project`：先 `_sync_conv()` 保存 → `_messages.clear()` 清空 → 再加载
- 新建项目后聊天窗保留旧上下文，Claude Code 误以为继续旧任务
  - `_launch("new")`：新建后清空聊天窗 + 欢迎消息
- "你是谁"在项目内被误判为干活：历史上下文含"文件/代码"等关键词导致 `is_chat_only` 误判
- Claude Code 文件上传报 `Session token required`：`--file` 参数用于远程资源，本地文件改用路径拼入 prompt
- 教程第四步（配置 DeepSeek）无检测逻辑：单独加环境变量 + settings.json 检查分支
- 教程点击第一单元跳回菜单：`_start_unit(0)` 调错方法，改为 `_show_tutorial_loading_for_step()`

### 新增
- 纯对话模式走 DeepSeek API 黑盒直连（`_call_deepseek_directly`），不审批、秒回
- Claude Code 登录绕过方案：教程教用户设 `ANTHROPIC_BASE_URL` 走 DeepSeek，不翻墙不登录 Anthropic

### 架构记录
- 消息路由三层：纯对话（DeepSeek 直连）/ 项目聊天（直回）/ 项目干活（审批流）
- 审批栏激活强制直设按钮属性，跳过中间函数，避免信号丢失

## v1.0.4 — 2026-07-09

### 新增
- 纯对话模式走 DeepSeek API 黑盒直连（`_call_deepseek_directly`）
  - 不经过 Claude Code，不审批，秒回
  - DeepSeek Key 未配时给友好提示
- 教程新增第 4 步"配置 DeepSeek"
  - 教用户设 `ANTHROPIC_BASE_URL` 环境变量，绕过 Anthropic 登录
  - 检查 `~/.claude/settings.json` 是否已配
  - 5 步完成，教程路线全程不翻墙、不登录 Anthropic、合规
- 教程目录结构：四单元可点击进入
- 教程进度条 1/5 + 跳过按钮统一

### 改进
- 纯对话 vs 项目模式路由清晰：
  - 纯对话 → DeepSeek 直连
  - 项目 + 干活关键词 → plan→审批
  - 项目 + 聊天关键词 → 直接回复
- 聊天降级路径：常驻会话挂时自动走 `bypassPermissions` 直连，不再漏到 plan

### 修复
- "你是谁"被误判为干活（常驻会话启动失败导致降级链断裂）
- 教程点击第一单元跳回菜单（`_start_unit` 调错方法）
- 教程"配置 DeepSeek"步骤无检测逻辑（单独加检测分支）

## v1.0.3 — 2026-07-02

### 新增
- 教程模式（启动页 📚 按钮）：
  - 课程目录：四个单元（环境搭建 / 第一个项目 / 理解门禁 / 团队协作）
  - 第一单元：4 步向导（Node.js / Git / Claude Code / DeepSeek Key）
  - 每步可"检查"自查 + "跳过"继续，进度条 1/4 → 4/4
  - 讲解为什么需要每一项、去哪下载、怎么安装
  - 教程嵌入启动页右边，不弹窗
  - ← 返回按钮回到欢迎页
  - 加载页 + 绿色进度条动画

### 改进
- 启动页按钮 hover 动画：`QPropertyAnimation` + `QEasingCurve`，鼠标悬停平滑右移
- Claude Code 检测兼容 Windows 多种方式：`claude` / `claude.cmd` / `bash` / `cmd /c`
- 齿轮管理菜单从内嵌面板回退为 QDialog（稳定优先）
- 齿轮管理对话框放大：480×520

### 修复
- 齿轮菜单闪退（ProjectStore 方法调用兼容）
- 星星置顶闪退（`_toggle_pin` / `_delete_history` 兼容新旧 store）
- 文件上传后 Claude Code 错误（session token 问题，改为路径拼接 prompt）
- 启动页右侧教程内容引用丢失（存储 `_launcher_right_layout`）
- 重复方法导致教程不生效（删除旧 `_show_tutorial_loading` 重复定义）

### 架构记录
- 页面切换动画：5 次尝试，5 次失败。位置滑动、透明度渐变均与 QStackedWidget 冲突。结论：**页面级动画不可行**。按钮级 hover 动画可行且已部署。
- QWebEngineView 与动画冲突根因：Chromium 不走 Qt 绘制管线，GPU 直绘屏幕。
- 聊天页不含 WebEngine（VRM 在 PetWindow），但 QStackedWidget 自身限制仍阻断了动画。
- 教程右栏注入模式（`self._launcher_right_layout` 引用存储）可作为后续内嵌面板的模板。

## v1.0.2 — 2026-06-30

### 新增
- 常驻 Claude Code 进程（管道模式）：聊天秒级回复，不再冷启动
- 对话记忆：每次请求带最近 6 轮历史，不再健忘
- 启动页（专业模式）：左右分栏，左边选项区 + 右边欢迎区
  - 💬 纯对话 / 📂 打开项目 / ＋ 新建项目
  - 最近列表（最近对话 + 最近项目）
  - ← 返回按钮回到启动页
- 项目存储 `project_store.py`：项目 > 对话，可移动/复制
- 左侧面板重构：纯对话区 + 项目区，＋新建项目按钮
- Agent 通信总线 `agent_bus.py`：多实例通过共享文件夹 JSON 通信
- 发送审查按钮：项目面板底部 📤，推送任务给其他实例
- 附件上传（＋按钮）：文件复制到工作目录，路径传给 Claude Code

### 改进
- 门禁精准化：简单聊天（你是谁/你好/刚刚说了什么）直接回复，不走审批
- Plan 提示词优化：要求用将来时态，不写完整代码，不抱怨权限
- 审批栏：按钮标注快捷键（1 批准/2 拒绝），支持键盘操作
- 审批摘要可滚动，宽 300px
- 气泡增量更新 + 对话保存异步化：UI 不再卡死
- Claude Code 超时从 120 秒提到 300 秒
- 设置复选框：已选变绿色 `#00FF66`，一眼分辨
- 右键菜单 + 设置弹窗黑底白字

### 修复
- 聊天框多点击重复弹窗
- QMenu 与 WebEngine 冲突闪退（齿轮、摇人改用 QDialog）
- 确认弹窗阻塞聊天窗口拖拽
- 新建项目不切换 Claude Code 工作目录
- 单实例保护、EXE 打包、VRM 资源打包

### 架构变动
- `conversation_store.py` → 升级为 `project_store.py`
- 新增 `agent_bus.py`、`CHANGELOG.md`
- 代码量：5,445 → 6,031 行（+586），19 个 Python 文件

## v1.0.1 — 2026-06-30

### 新增
- 开发者日志 `CHANGELOG.md`
- 审批栏键盘快捷键：按 **1** 批准，按 **2** 拒绝
- 按钮标注：批准（按1批准）、拒绝（按2拒绝）
- 消息提示优化："正在生成计划，马上就好..."、"正在执行，稍等一下..."
- 附件上传（＋按钮）：支持图片和文件，复制到工作目录传给 Claude Code
- 审批摘要可滚动（QScrollArea），长文本不再拉伸界面
- 专业模式整体加宽：1020 → 1360，审批栏 200 → 300px，项目面板 200 → 240px
- 历史管理面板改为内嵌（不弹窗），位于侧边栏下方
- 管理面板内批量删除模式（复选框 + 一键删除选中）
- 管理面板内的星星收藏按钮，实时切换不重建面板

### 修复
- UI 卡死问题：API 调用移到后台线程（`threading.Thread`）
- 对话保存卡顿：JSON 写入异步化（后台线程）
- 气泡更新慢：改为增量替换单个 widget，不全量重建
- 右键 QMenu 闪退：用 QDialog 替代（齿轮管理、摇人菜单）
- 管理面板星星取消收藏后左侧星星残留
- 侧边栏 + 管理面板宽度和字体加大（200 → 220px）

### 已知问题
- 图片上传后 Claude Code 无法识别（DeepSeek V4 不支持多模态）
- 摇人上限检测不准（wmic 计数误差）
- EXE 启动短暂黑框（PyInstaller 通病）
- 两个实例约 800MB 内存占用

## v1.0.0 — 2026-06-27

### 项目初始化
- 搭建 Python 3.14 + PyQt6 项目骨架
- `requirements.txt`：PyQt6、PyYAML、requests
- `config.yaml` 配置管理系统（支持环境变量覆盖）
- 透明无边框桌宠窗口，右下角定位，支持拖拽移动
- QPainter 手绘 2D 白发少女角色 + 眨眼/晃动动画
- 系统托盘图标（显示/隐藏/退出）

### AI 接入
- DeepSeek API 客户端（聊天补全、多轮对话、流式响应）
- Claude Code CLI 调用封装（`--print` 非交互模式、`--output-format json`）
- 门禁层 `gate.py`：意图分类（闲聊/干活）、路由分发
- Claude Code 权限模式：`plan` → 确认 → `bypassPermissions`

### 聊天系统
- 粉色二次元对话气泡（用户蓝色/AI粉色）
- Enter 发送、Shift+Enter 换行
- 事件过滤器拦截按键（避免 WebEngine 冲突）
- 终止按钮（等待中可取消 AI 请求）

### 专业模式（Pro Mode）
- VS Code 终端风格：黑底 `#0D0D0D`、绿字 `#00FF66`、Consolas 字体
- 左侧历史面板（200px）：
  - 对话自动保存为 JSON（`data/conversations/`）
  - 首次发消息创建对话，关闭元元结束对话
  - 按项目目录分组
  - 置顶（金色标记）、删除
  - 齿轮管理对话框（QMenu 与 WebEngine 冲突，改用 QDialog）
- 话题切换：＋ 新对话按钮
- 审批栏（300px）：内嵌右侧，替代弹窗
  - 灰色禁用/青色激活
  - 按 **1** 批准，按 **2** 拒绝
  - 审批摘要可滚动
- 项目面板（240px）：计划/进度/问题自动提取
  - 可手动编辑、Ctrl+C 复制传递给其他实例
- 工作目录切换：📂 按钮 + 文件选择器
- 摇人功能（📞）：多实例协作，弹窗选人数（1/2/3人）
- 附件上传（＋按钮）：文件复制到工作目录，路径传给 Claude Code
- 宽度：1360×620

### VRM 3D 角色
- PyQt6-WebEngine 嵌入 Three.js 渲染
- 本地化加载：`three.module.js` + GLTFLoader + BufferGeometryUtils
- CDN 全部绕过（unpkg/jsdelivr 在国内不可用 → 全部本地化）
- 模型自动缩放适配、呼吸动画、右键拖拽旋转
- VRoid Studio 导出的 `.vrm` 模型直接使用

### 交互优化
- 左键点击开聊天（任务栏可见，支持最大化）
- 左/右键拖拽移动窗口（透明覆盖层捕获事件）
- 右键菜单：设置/退出
- 设置对话框：版本号、始终使用 Claude Code、专业模式开关
- 单实例保护（PID 锁文件 + wmic 进程名校验）

### 性能优化
- API 调用移到后台线程（`threading.Thread`），UI 不再冻结
- 对话保存异步写入文件
- 气泡增量更新（替换单个 widget，不重建全部）
- 提示语优化："正在生成计划，马上就好..."

### 打包
- PyInstaller `--onedir`：`dist/yuan_yuan/yuan_yuan.exe`（~540MB 含 WebEngine）
- Inno Setup 安装脚本：`installer/setup.iss`
- VRM 资源文件随包打包

### 进度摘要
- 2026-06-17 ~ 06-30，约两周，14 个开发会话
- 第一阶段（06-17 ~ 06-21）：项目骨架、桌宠窗口、QPainter 角色、动画、托盘
- 第二阶段（06-22 ~ 06-24）：聊天对话框、DeepSeek/Claude Code 接入、门禁层、打包
- 第三阶段（06-25 ~ 06-27）：专业模式、VRM 3D、历史面板、审批栏、项目面板
- 第四阶段（06-28 ~ 06-30）：多实例协作、附件上传、性能优化、bug 修复

### 已知问题
- EXE 启动有短暂黑框闪烁（PyInstaller 通病）
- 单实例保护偶尔失效（wmic 检测竞争条件）
- 图片上传无法识别（Claude Code 走 DeepSeek V4，不支持多模态）
- 右键 QMenu 与 WebEngine 冲突（已用 QDialog 替代）
- 两个实例约 800MB 内存占用

### 技术栈（元元 v1.0.0 旧快照，2026-06-27）

> ⚠️ 此表是元元 v1.0.0 时代的旧技术栈，现已演进——当前技术栈见顶部「技术栈（当前）」。

| 层 | 技术 |
|------|------|
| 语言 | Python 3.14 |
| GUI | PyQt6 + PyQt6-WebEngine |
| 3D 渲染 | Three.js (ESM) |
| 闲聊 | DeepSeek API (deepseek-chat) |
| 干活 | Claude Code CLI (claude-opus-4-8) |
| 配置 | YAML + 环境变量 |
| 打包 | PyInstaller 6.21 + Inno Setup |
| 角色模型 | VRoid Studio → .vrm |
