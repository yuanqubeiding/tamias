// ============================================================
// 栗栗「方案 B」逐操作审批门禁插件 + 干活回滚「改前拍照」
// ------------------------------------------------------------
// 一、门禁（tools/pre-execute 瀑布）：
//   - 只读/查询类工具（白名单）→ next() 直接放行，不打扰主人
//   - 写文件/执行命令/联网抓取/委派子代理/编排等「真正动手」的 → 返回 ask
//   返回 ask 后 dsh 走审批 seam（serviceAsk），发 approval/requested 给栗栗，
//   栗栗弹窗问主人，主人点允许/拒绝再决定要不要执行。
//
// 二、回滚拍照（fs/write-intent + fs/edit-intent 瀑布，prepend 到最前）：
//   文件真正落盘前，把「改前原文」全文抄一份存进快照目录，参照 Claude Code
//   的 file-history：sha256(绝对路径) 前 16 位当文件名，manifest.json 记路径。
//   主人点「撤销」时，栗栗把快照覆盖回文件，确定性还原、不靠模型重写。
//   只拍 write/edit/str_replace_editor 这些「显式文件工具」；pwsh 命令改的
//   文件拿不到路径、拍不到，属已知盲区（跟 Claude Code 一样，如实告知）。
//
// 部署：本文件放在 dsh profile 目录（<DSH_HOME>/profiles/web/），
// 由 cordis.patch.yml 用相对路径 './yy-approval-gate.mjs' 加载。
// ============================================================

import { Service } from "@deepseek-ai/cordis";
import z from "@deepseek-ai/schemastery";
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { join, isAbsolute } from "node:path";

// 只读 / 纯查询 / 无副作用工具：直接放行，不让主人反复点确认。
const SAFE_TOOLS = [
  "read",              // 读文件
  "read_image",        // 读图片
  "glob",              // 按文件名找文件
  "grep",              // 按内容搜文件
  "todo_write",        // 任务清单（内部状态，无副作用）
  "get_goal",          // 查目标
  "job_list",          // 查后台任务
  "job_output",        // 看后台任务输出
  "ask_user_question", // 问主人问题（本来就是等人回答）
  "report",            // 子代理汇报结果
  "web_search",        // 联网查资料（只读，属于「随便查」）
];

// 只读 pwsh 命令白名单：主人钦点，只放行这 3 个「只看不改、无副作用」的。
// 列目录 Get-ChildItem / 读全文 Get-Content 仍要问（能泄文件清单/内容），别擅加。
const READ_ONLY_PWSH = new Set(["test-path", "select-string", "get-location"]);

// 快照目录：<cwd>/.tamias/snapshots/，与 project_store 的 .tamias 同层。
const SNAPSHOT_DIR = ".tamias";
const SNAPSHOT_SUBDIR = "snapshots";

// 文件指纹 = sha256(绝对路径) 前 16 个十六进制字符（参照 Claude Code file-history）。
function fingerprint(absPath) {
  return createHash("sha256").update(absPath).digest("hex").slice(0, 16);
}

// 把一条 pwsh 命令归类成中文人话标签（审批理由用），让主人一眼看懂这条命令是干嘛的。
// 优先看命令名（最可靠），再看模型自带 description 里的中英文关键词兜底；
// 匹配顺序从「具体」到「泛化」，避免「启动/运行程序」把「语法检查」吞掉。
function classifyPwsh(command, description) {
  const cmd = String(command || "");
  const desc = String(description || "");
  const low = cmd.toLowerCase();

  // 语法检查（py_compile / 描述含「语法检查」）
  if (low.includes("py_compile") || /语法检查|syntax[- ]?check|语法校验/i.test(desc)) return "语法检查";
  // 删除文件（Remove-Item / del / rd / 描述含「删除」）
  if (/remove-item/i.test(low) || /(^|[;|&\s])(del|rd|rm)\s/i.test(cmd) || /删除|delete|卸载/i.test(desc)) return "删除文件";
  // 查询进程（Get-Process / Get-CimInstance / 描述含「进程」）
  if (/get-process|get-ciminstance|win32_process/i.test(low) || /进程|process/i.test(desc)) return "查询进程";
  // 联网获取（Invoke-WebRequest / curl / wget / 描述含「联网/天气/抓取」）
  if (/invoke-webrequest|invoke-restmethod|\bcurl\b|\bwget\b/i.test(low) || /联网|天气|weather|fetch|抓取|wttr|api/i.test(desc)) return "联网获取";
  // 测试窗口（mainloop / 描述含「窗口」）
  if (/mainloop/i.test(low) || /创建.*窗口|显示窗口|验证.*(tkinter|窗口)|窗口/i.test(desc)) return "测试窗口";
  // 打开网页（浏览器 + 具体网址）
  if (/bilibili|哔哩|打开.*(网页|网站)/i.test(desc)) return "打开网页";
  // 启动/运行程序（跑脚本 .py/.js / Start-Process / 描述含「运行/启动/launch」）
  if (/\b(py|python|python3)\b[^\n]*\.py\b/i.test(cmd) || /\bnode\b[^\n]*\.(js|mjs)\b/i.test(cmd)
      || /start-process/i.test(low) || /运行|后台运行|\blaunch\b/i.test(desc)) return "启动/运行程序";
  // 检查环境（--version / Get-Command / import / 描述含「版本/是否可用/检查」）
  if (/--version|get-command|py\s+-0\b|\bimport\b/i.test(low) || /版本|version|是否可用|availability|检查|verify|check/i.test(desc)) return "检查环境";
  // 查找程序/路径（描述含「查找/定位/路径/安装位置」）
  if (/locate|find|查找|定位|路径|executable|解释器|安装位置/i.test(desc)) return "查找程序";
  // 获取时间（Get-Date / 描述含「时间」）
  if (/get-date/i.test(low) || /本机时间|时间/i.test(desc)) return "获取时间";
  // 兜底
  return "执行命令";
}

// 从工具参数里摘出最「像人话」的一小段，塞进审批理由给主人看。
// pwsh/bash 命令特殊处理：优先用模型自带的 description（人话），中文直接展示、
// 英文前缀中文类型标签，让主人一眼看懂这条命令是「语法检查/删除文件/运行程序」还是别的，
// 而不是被 `py -m py_compile ...` 这种天书命令搞懵。
function summarize(args) {
  if (args === null || typeof args !== "object") return "";
  // 命令类工具（pwsh/bash）：description + 中文类型标签
  if (typeof args.command === "string" && args.command.trim() !== "") {
    const command = args.command.trim();
    const desc = (typeof args.description === "string" && args.description.trim() !== "")
      ? args.description.trim() : "";
    if (desc) {
      // description 已是中文（含汉字）就直接用；否则前缀中文类型标签兜底
      if (/[一-鿿]/.test(desc)) return desc;
      return classifyPwsh(command, desc) + "：" + desc;
    }
    // 没有 description：中文标签 + 命令摘要（截断）
    const label = classifyPwsh(command, "");
    return label + "：" + (command.length > 120 ? command.slice(0, 120) + "…" : command);
  }
  // 文件/查询/技能等其他工具：按字段优先级取最像人话的一个
  const picks = [
    "file_path", "query", "url", "description",
    "skill", "prompt", "name",
  ];
  for (const key of picks) {
    const value = args[key];
    if (typeof value === "string" && value.trim() !== "") return value.trim();
  }
  try {
    const json = JSON.stringify(args);
    return json.length > 200 ? json.slice(0, 200) + "…" : json;
  } catch {
    return "";
  }
}

// 判断一条 pwsh 命令是否「纯只读」：按 ; | && || 换行 引号感知地拆成子命令，
// 每个子命令的「首动词」都得在 READ_ONLY_PWSH 里才放行。保守 fail-closed：
// 带反引号（转义/续行）或 $() 子表达式的命令一律不放行（容易藏命令），交审批。
function isReadOnlyPwsh(command) {
  if (typeof command !== "string" || command.trim() === "") return false;
  const cmd = command.trim();
  if (cmd.includes("`") || cmd.includes("$(")) return false;
  const subs = splitPwshCommands(cmd);
  if (subs.length === 0) return false;
  for (const sub of subs) {
    const verb = firstVerb(sub);
    if (!verb || !READ_ONLY_PWSH.has(verb.toLowerCase())) return false;
  }
  return true;
}

// 引号感知地把 pwsh 命令切成子命令：只在引号外识别分隔符。
// 单引号里 '' 是转义引号，这里简化成「再遇单引号就出栈」——分隔符误判只会
// 拆出多余子命令 → 更可能走到 ask，方向是安全的（宁多问不误放行）。
function splitPwshCommands(cmd) {
  const parts = [];
  let cur = "";
  let inSingle = false;
  let inDouble = false;
  for (let i = 0; i < cmd.length; i++) {
    const ch = cmd[i];
    if (inDouble && ch === "`") {  // 双引号内反引号转义：连下一字一起吞，不算分隔符
      cur += ch + (cmd[i + 1] ?? "");
      i++;
      continue;
    }
    if (ch === "'" && !inDouble) { inSingle = !inSingle; cur += ch; continue; }
    if (ch === '"' && !inSingle) { inDouble = !inDouble; cur += ch; continue; }
    if (!inSingle && !inDouble) {
      if (ch === ";" || ch === "\n" || ch === "\r") { parts.push(cur); cur = ""; continue; }
      if (ch === "|") { if (cmd[i + 1] === "|") i++; parts.push(cur); cur = ""; continue; }
      if (ch === "&" && cmd[i + 1] === "&") { i++; parts.push(cur); cur = ""; continue; }
    }
    cur += ch;
  }
  parts.push(cur);
  return parts.map((p) => p.trim()).filter((p) => p !== "");
}

// 取子命令的首动词：剥掉前导调用运算符 &，再取第一个「词」（到空白或左括号为止）。
function firstVerb(sub) {
  let s = sub.trim();
  while (s.startsWith("&")) s = s.slice(1).trim();
  const m = s.match(/^[^\s(]+/);
  return m ? m[0] : "";
}

// 判断一个文件路径是否落在「记忆目录」里。
// 记忆目录两条：全局 <DSH_HOME>/skills（= %APPDATA%\Tamias\dsh\skills）和
// 项目 <工作目录>/.dsh/skills。模型干完活「记个事」写 SKILL.md 属于可信操作，
// 门禁放行、不弹「修改文件」卡（沙箱升级那层由栗栗 main.py 另行豁免）。
function isMemoryPath(filePath) {
  if (typeof filePath !== "string" || filePath.trim() === "") return false;
  const p = filePath.replace(/\\/g, "/").toLowerCase();
  return p.includes("/dsh/skills/") || p.includes("/.dsh/skills/");
}

class YuanYuanApprovalGate extends Service {
  // 白名单可配置；默认只放行上面的只读工具，其余一律 ask（fail-closed）。
  static Config = z.object({
    safe: z.array(z.string()).default(SAFE_TOOLS),
  });

  constructor(ctx, config) {
    super(ctx, "yuanYuanApprovalGate");
    this.config = config;
    this.safe = new Set(this.config.safe);

    // 门禁：tools/pre-execute 瀑布监听器（next() 放行，返回 ask 即触发审批）。
    ctx.on("tools/pre-execute", (exec, next) => {
      if (this.safe.has(exec.name)) return next();
      // pwsh 只读命令白名单：Test-Path / Select-String / Get-Location 直接放行，
      // 其余 pwsh（写/删/跑程序）照旧 ask。解析不到 / 结构可疑 → fallback 到 ask。
      if (exec.name === "pwsh" && isReadOnlyPwsh(exec.arguments?.command)) return next();
      // 写记忆文件：放行。模型干完活「记个事」写 SKILL.md（全局/项目记忆目录），
      // 这是可信操作，别为它弹「修改文件」卡。只豁免记忆目录，其它写文件照旧问。
      if ((exec.name === "write" || exec.name === "edit" || exec.name === "str_replace_editor")
          && isMemoryPath(exec.arguments?.file_path || exec.arguments?.path)) return next();
      return { kind: "ask", reason: summarize(exec.arguments) };
    });

    // 回滚拍照：fs/write-intent + fs/edit-intent（single-slot 瀑布）。
    // prepend 到最前 → 先拍照、再 next() 委托给 fs-observation-policy 决定
    // 版本守卫；只做快照副作用，绝不自己 return intent 抢占。
    ctx.on("fs/write-intent", (target, actor, next) => {
      this._snapshot(target, actor);
      return next();
    }, { prepend: true });
    ctx.on("fs/edit-intent", (target, actor, next) => {
      this._snapshot(target, actor);
      return next();
    }, { prepend: true });
  }

  // 改前拍照：把文件原文抄进快照目录，更新 manifest.json。
  // 只做尽力而为的副作用，任何失败都静默吞掉，绝不影响干活本身。
  _snapshot(target, actor) {
    try {
      const absPath = target?.displayPath;
      if (!absPath || !isAbsolute(absPath)) return;  // 没绝对路径（remote URI 等）就不拍
      const cwd = actor?.agent?.session?.header?.cwd;
      if (!cwd) return;  // 拿不到工作目录就不拍（agentless 调用）
      const snapRoot = join(cwd, SNAPSHOT_DIR, SNAPSHOT_SUBDIR);
      const existedBefore = existsSync(absPath);  // 改前是否存在（决定撤销是写回还是删）
      const fp = fingerprint(absPath);
      mkdirSync(snapRoot, { recursive: true });
      // 快照文件：改前原文（原样二进制拷贝）；新建文件则写空标记，撤销=删文件
      writeFileSync(join(snapRoot, fp), existedBefore ? readFileSync(absPath) : Buffer.alloc(0));
      // manifest：hash → { path, saved_at, existed_before }，供栗栗撤销时定位+还原
      const manifestFile = join(snapRoot, "manifest.json");
      let manifest = {};
      if (existsSync(manifestFile)) {
        try {
          manifest = JSON.parse(readFileSync(manifestFile, "utf8"));
        } catch {
          manifest = {};  // 坏掉的 manifest 重建
        }
      }
      // 若这个文件是本任务里新建的（manifest 已记 existed_before=false），
      // 就算之后又被改过也要保持 false——撤销时应整文件删除，而不是还原成中间态。
      const createdThisTask = manifest[fp]?.existed_before === false;
      manifest[fp] = {
        path: absPath,
        saved_at: new Date().toISOString(),
        existed_before: createdThisTask ? false : existedBefore,
      };
      writeFileSync(manifestFile, JSON.stringify(manifest, null, 2));
    } catch {
      // 拍照失败（读不到原文 / 磁盘满 / 权限）不影响干活，静默忽略。
    }
  }
}

export { YuanYuanApprovalGate, YuanYuanApprovalGate as default };
