# 栗栗 (Tamias) Development Log

> English translation for reference; the Chinese original (CHANGELOG.md) prevails.

> **Renamed on 2026-08-18**: the project "元元 (YuanYuan)" → "栗栗 (Tamias)" (the old name collided with a competitor "Hamster Yuanyuan"). English name Tamias, Japanese name くりくり; version reset to 0.1.0. Below is the Tamias-era log; the older "Yuanyuan"-era log is at v1.0.13 and earlier.

## Tech stack (current, Tamias v0.1.0)

| Layer | Technology |
|------|------|
| Language | Python 3.14 |
| GUI | PySide6 (LGPL, official Qt bindings) + QtWebEngine |
| Illustration rendering | Live2D (Cubism Core + pixi-live2d-display, loaded via QWebEngine) |
| Chat | DeepSeek API (deepseek-chat) |
| Work engine | dsh (DeepSeek Harness, Node.js runtime self-started with the app) |
| Config | YAML (config.yaml) |
| Packaging | PyInstaller (onedir) → Inno Setup |
| Character model | Live2D Cubism (.moc3) |

### Tech stack evolution (Yuanyuan → Tamias, old vs new)

| Dimension | Yuanyuan v1.0.x (old) | Tamias v0.1.0 (new) | Change |
|------|------|------|------|
| GUI | PyQt6 (GPL-3.0) | PySide6 (LGPL) | 08-24 library swap, compliance |
| Illustration | QPainter white-haired girl → VRM 3D | Live2D (.moc3) | 08-16 finalized |
| Work engine | Claude Code CLI | dsh (DeepSeek Harness) | 08-15 removed Claude Code entirely |
| Character model | VRoid Studio → .vrm | Live2D Cubism → .moc3 | 08-16 |
| Chat / language / packaging | DeepSeek / Python 3.14 / PyInstaller+Inno Setup | same as left (unchanged) | — |

## Tamias v0.1.0 development period — 2026-08-16 ~ 09-13

### Character finalization: Live2D illustration from scratch + rename + fonts (08-16 ~ 08-20)

- **Live2D illustration from scratch**: See-through (open-sourced at SIGGRAPH 2026) split into 35 PSD layers → the user manually re-split limbs/coat/shirt/tie → programmatically built the skeleton with Cubism 5.4 alpha's official "external integration API" (5 deformers + blink/eye-tracking/tail/mouth 9 parameters + correct nested binding, `_live2d_api/` client library) → exported zhende5.0tamias.moc3 into the pet (`pet_widget_live2d.py` loads it via QWebEngine, replacing the old VRM 3D approach)
- **Renamed "Yuanyuan → Tamias"**: triggered by the "Hamster Yuanyuan" name collision; checked trademarks/name collisions one by one (Mumu/Miumiu/Zhenzhen/Songsong… all taken), finally settled on "栗栗" (fits the squirrel-detective persona + easy to write + no collision); English name Tamias (chipmunk's scientific name + Greek for "butler", a double pun), Japanese name くりくり
- **Interface fonts switched to open-source commercial-use**: Chinese/English HarmonyOS Sans SC + Japanese Noto Sans JP + monospace JetBrains Mono (~26MB), `fonts.py` replaced 80+ hardcoded spots; pitfall = HarmonyOS includes kana glyphs causing character-level fallback failure, must switch global font by language; NOTICE.txt three-font license notice bundled
- **Persona externalized (skin/bone separation)**: persona five anchors + origin story + catchphrases + gate phrases extracted from hardcoded code into `resources/persona/` (persona.yaml + phrases.yaml + loader); changing character = swapping directory + editing config, code untouched; "whether to block" (bone) is locked down, only "how to say it" (skin) changes
- **Four-language i18n full set**: Simplified/Traditional/English/Japanese UI copy + chat reply language follows UI language (211+ keys)
- **App icon + three UIs unified warm-brown detective style**: tray / taskbar / app-level all unified

### Approval gate plan B (per-operation approval) + work rollback (08-20)

- **Plan B per-operation approval**: the gate plugin `yy-approval-gate.mjs` (based on dsh's `tools/pre-execute` returning `{kind:'ask'}` to enter the approval seam) implements "ask for every single operation", filling the granularity gap where Plan A only blocked "the whole task"
- **Work rollback (undo mistakes)**: replicated Claude Code's "snapshot before action + undo", without git (ordinary users don't have git) — the gate plugin copies the original text into `<cwd>/.yuan_yuan/snapshots/` before `fs/write-intent` + `fs/edit-intent` writes; Python side `snapshot_store.py` undo + side-by-side diff UI (`rollback_dialog.py`) + clickable "changed N files" entry in the chat stream; **real-machine acceptance: 5/5 passed** (exact restore of edits / undo new-file = delete / one-click multi-file revert / keep only the latest / pro-mode entry)

### Logging system + memory watchdog + compliance trio + release engineering (08-21)

- **Four-file logging system**: crash/run/gate/chat all in place; `log_exporter.py` one-click export (deliberately excludes raw conversation text / API key, privacy-desensitized), feedback via GitHub Issues
- **Memory watchdog**: ctypes measures process-tree memory, auto-reloads the Live2D model + clears dsh session past 1.5GB (`memory_watchdog.py`, no psutil dependency)
- **Compliance trio**: 20-section user agreement + 10-section privacy policy (full PIPL coverage) + AI-label badge (Interim Measures Article 12) + first-launch "check to agree" dialog + right-click to view agreement/privacy
- **Beginner usage guide**: removed the old "tutorial" system (environment setup, redundant with the wizard), replaced with a seven-section "usage guide" + reader
- **Install script renamed + upgrade mechanism**: setup.iss aligned to tamias (8 spots) + AppId changed to a real UUID + [InstallDelete] upgrade cleanup
- **Anonymous content-leak layer zeroed out**: API key / local username / hardcoded local paths / test.vrm all cleared, re-packaged and grep-verified clean
- **dsh packaged self-start + data moved to AppData**: Node+dsh 245MB bundled, auto-launched on start (`dsh_launcher.py`), key shared, data moved to `%APPDATA%\Tamias\`; dev/frozen/real-exe three-layer verification passed, 340MB portable zip + Inno Setup installer produced

### First test + fixes (08-22)

- First external test, `docs/测试日志.md` recorded 13 bugs, fixed 11: wizard restyled warm-brown detective, app icon missing from bundle (white-haired-girl fake icon), persona+i18n missing from bundle, version unified to 0.1.0, logs moved to AppData, dsh.log written to disk, install dir inherited Chinese path, slow startup added Splash, diagnostic logging strengthened
- Located the "dsh self-start intermittent failure" direction: ruled out missing runtime → pointed to residual dsh process occupying port/lock conflict

### PyQt6 → PySide6 library swap (GPL compliance, 08-24)

- PyQt6 is GPL-3.0 copyleft (distributing under GPL = the whole package must be open source, conflicting with closed-source commercial use), swapped to PySide6 (LGPL, closed-source-friendly, official Qt bindings); 21 `.py` files mechanically replaced + Live2D (QWebEngine) real-machine load passed; NOTICE added PySide6/Qt license notice

### Work experience: step visualization + inline approval + feature library (08-23 ~ 08-24)

- **Work "step listing" visualization**: modeled on VSCode's Claude Code integration, the chat stream progressively shows "read file / search / think / edit file" instead of only the final result (`_StepList` process bubble)
- **Approval changed to inline card + tool-name translation**: the always-on right approval bar (300px) became an inline chat-stream card (deleted after answering), tool names bash/write translated to plain language, raw command/JSON collapsed by default
- **Work output default location**: fixed "randomly placed in hidden AppData" — default `Documents\栗栗工作区`, findable by ordinary users
- **Feature library expanded**: weather (manual city + wttr.in replacing ip-api's non-commercial limit) / random decision / Pomodoro / unit conversion, all local, zero API

### Viewer panel + file preview + close-window fix (08-27)

- **Right viewer split in two**: the original 240px project panel rebuilt into a three-page (file tree / log / docs) draggable viewer, filling the ~580px blank left by removing approval; the file page upgraded to multi-format preview (code/Markdown/.docx zero-dependency extraction/HTML/images)
- **dsh first-start "plugin tree failed" fix**: clean install couldn't start work — `mklink /J` junction symlink node_modules + broken-link self-heal (Plan A)
- **Close-window-not-exiting fix**: clicking X hid instead of exiting, so it couldn't be fully removed — changed to "first close gives a choice (stay in tray / fully exit) + remember"

### Token/balance display + log desensitization + memory upgrade (08-30 ~ 08-31)

- **Token usage + DeepSeek balance real-time display**: work UI accumulates tokens per step, bottom status bar shows account balance
- **Log privacy desensitization**: write-to-disk + export double-masks username + strips `sk-` key strings, dsh.log also scrubbed
- **Uninstall "choose to delete data" page oversized fix**: root cause ShowCaptionBar=False (non-Parent), changed to official CreateCustomForm + explicit pin size; also added UninstallSilent guard (fix runtime error)
- **Memory upgrade wrap-up**: aligned with Claude Code's memory principle — project-level memory root + auto-loaded index + inline body injection + "remember XXX" command + [[name]] cross-references

### Packaging GPL cleanup + work concurrency triple fix (09-01 ~ 09-04)

- **GPL QML plugin residue cleanup**: PySide6 packaging accidentally bundles GPL-only Qt module QML subdirs (QtCharts/DataVisualization/Graphs/Quick3D/SerialBus/Lottie etc.), expanded the `_strip_gpl_qt_modules` cleanup list; WARNING: don't mistakenly delete Qt3D (LGPL, legitimate)
- **Work "concurrency overlap + fake termination + queueing" triple fix**: confirmed by tester's real-machine logs — concurrent run() collisions cause 600s timeout / the stop key only sets a flag without truly interrupting / Enter when busy is mistaken for stop; added busy mutex + true cancel + queueing (queue when busy, auto-continue when done)

### Voice input + tester feedback (09-05)

- **Voice input (hold-to-talk speech-to-text)**: tester feedback "don't want to type" — a "mic" button next to the input box + hold Alt key, both trigger, release to get text; `speech_input.py` wraps Windows local offline speech recognition with PyWinRT (**zero tokens, audio never uploaded**); NOTICE + full license text + privacy policy "does not collect voice" compliance trio done. WARNING: pending real-machine verification of Chinese recognition quality + bundling the winrt packages
- **Tester feedback — 7 feature requests**: link/file hyperlinks (URL clickable, file path clickable to open) + pro-mode hide preview page (eye-icon collapse toggle) done; conversation time grouping / font-size adjustment / drag-to-open-project etc. deferred

### Desktop-pet sprite animation + stall watchdog + run.log event timeline (09-06)

- **Desktop-pet sprite animation system (incl. appear/exit)**: added a "PNG frame-sequence animation" layer on top of Live2D — `sprite_player.py` generic player (preload QPixmap + QTimer frame-by-frame + finished signal), `pet_window.py` extracted `_get_sprite`/`_play_sprite_anim` (lazy load + stop-old-play-new on conflict + `display_scale` tweak), resumes Live2D after playing. Wired a batch of actions: **appear** (`show_with_animation`, plays when re-shown after hiding) / **exit bow goodbye** (`hide_with_animation` + exit, fades after playing) / **poke** (left click) / **yawn** (idle trigger) / **reading** (idle, rarer) / pinch left-right / hold-hand shy / rapid-click angry / search. Assets via Wan2.2 image-to-video → alpha keying → `process_*.py` frame extraction (appear 308×560 / disappear 315×560, ProRes 4444 with alpha). WARNING pitfalls: the processing script `glob("~\Desktop\*.mov")[0]` grabbed the wrong .mov out of 3 on the desktop, and the poke animation was actually yawn content — fixed by explicitly naming "被戳一下.mov" and regenerating 30 frames; yawn interval 3~5 min → 30s~1min
- **Stall watchdog**: when dsh truly hangs (LLM stuck / tool dead loop), don't make the tester wait the full 600s — `STALL_TIMEOUT = 180` (based on dsh's 120s tool timeout with margin), watches "how long since the last event" instead of "total task duration" (long tasks not falsely killed); skips judgment while waiting for the owner's approval / counter-question (`_waiting_user`); triggers a separate "engine appears stalled" report, distinct from "task timeout"
- **run.log event timeline**: make run.log itself a complete "what dsh is doing" flow — `turn/end` records `reason.error.message` + `code` (to see why it failed), key events record `seq` (reconnect missed events detectable), each line tagged "Xs since last", added `turn/start` logs (distinguish "not started" vs "started then stalled")
- WARNING: all source-level, not real-machine verified; run.log's "task anti-cross-talk" (background thread reports with sequence check) still pending

### Queue visualization + experience quadruple fix + packaging (09-07)

- **Queue visibility**: taking messages while busy is "queueing, not preempting", but previously the queue was invisible, uncapped, and couldn't delete individual items — added a queue panel (between message area and input box), cap 3 (prompt when full, doesn't swallow messages), each with ✕ delete, current task text (processing) and queued text (waiting) shown separately
- **Refresh button anti-fumble**: refresh would cancel the running task + stop the gateway + cold-restart dsh (up to 180s); clicking repeatedly when connected = self-destruct — changed to "only shown when disconnected / refreshing", hidden when connected
- **Real-time stopwatch + token display**: title bar adds per-second ticking timer + token count (work accumulates real values, chat mid-stream estimates ≈N → calibrated with real value at end), so users see Tamias "still moving" instead of waiting blindly
- **Session cross-talk fix**: switching sessions clears the DeepSeek chat multi-turn history — fixed "answering the wrong question" (asking "why the timeout" but getting "task done + use Japanese from now on + Get-Date rejected" cross-session bleed)
- **Newline-loss fix**: pro-mode hiding the preview page dropped line breaks in replies — `_linkify` escaping then `\n`→`<br/>` preserves paragraphs (RichText collapses newlines to spaces)
- **Packaging**: `python build.py` (988.7MB folder, 30 GPL-only Qt items cleaned) + ISCC (`tamias_setup_v0.1.0.exe`, 282MB), sent to testers
- WARNING: everything above except packaging is **source-level, not real-machine verified**, going into tester real machines with this installer round

### Search rate-limiting + a batch of bug fixes + mode isolation + plan card (09-08 ~ 09-10)

- **Web search rate-limiting**: dsh's default web search 60s timeout / 5 tries, searching took forever and burned tokens — compromise 30s / 3 tries (`cordis.patch.yml` two id-targeted overrides; WARNING: the patch is whole-block replacement, keep `fetch:false` to prevent SSRF and `apiKeyEnv`)
- **A batch of bug fixes**: (1) conversation history persistence (switching conversations cleared AI replies leaving only questions — sync save + fixed capture of the conv object) (2) pwsh read-only command whitelist (Test-Path / Select-String / Get-Location three "view-only" allowed, quote-aware subcommand splitting + per-verb validation) (3) drive-root path fallback (selecting a whole drive set work_dir to drive root EPERM, fall back to default workspace)
- **Mode isolation quadruple fix + chat_dialog slimming**: (1) "recent" list filtered by mode (pro only folder projects, normal only daily chat) blocking cross-mode crossover in both directions (2) conversation page adds mode-switch button (no need to go back to launcher) (3) switching mode clears conversation state (back to initial screen, no resuming old conversation to avoid stuck) (4) extracted ReplyWorker / AnimatedButton / SlideStack three helper classes to `chat_widgets.py` (chat_dialog 3154→2958 lines)
- **Removed the "white-haired girl" fallback**: the QPainter hand-drawn "anime white-haired girl" fallback was ugly but was the safety fuse for missing assets, couldn't delete — unified the three fallback spots to "draw a chestnut" (shared `draw_chestnut()` warm-brown gradient chestnut, no facial features to keep it alive); also fixed the hidden bug "i18n key mismatched setup_wizard original text → non-Chinese translation broken"
- **Pro-mode work no-persona fix**: `ensure_dsh_home()` judged "initialized" by "gate plugin already exists" and then **stopped syncing the template** → the later-added persona section (and the search rate-limit) didn't apply to already-initialized machines; changed `_sync_cordis_patch` to rebuild the patch from the template every startup + restart dsh if changed
- **Work "plan card" visualization**: like Claude Code, list the AI's step plan as ☐todo / ⏳in-progress / ✅done checklist, ticking off one by one — dsh's `todo/write` event flows through the `on_todo` callback chain (6 files: dsh_backend → gate → main → ReplyWorker → chat_dialog `todo_event`) to a new `PlanCard` widget ("📋 plan" + "N/M done" count + three-state coloring for light/dark themes), filling the plan gap left by "step listing" (process done, plan not done)
- WARNING: everything above is **source-level, not real-machine verified**, going into tester real machines next round

### Open-source preparation: license decision + clean history + provenance + attribution (09-13)

- **Open-source license decided**: code under Apache-2.0 (permissive + patent clause + non-infectious, consistent with VPet), illustration/animation/icon/persona **assets keep separate copyright** not under Apache-2.0 (the moat is in the image/IP, not the code); settled after two detours (PolyForm non-commercial, GPL infectious)
- **Todo conflict sorted**: the old "anti-copy / private" line aligned with open source — Nuitka's purpose changed from "anti-copy" to "anti-tamper + anti-decompiling assets", "repo must be private" voided (asset copyright + timestamp + attribution as anti-copy fallback)
- **Public-version clean history**: the public version derived from the evidence version then **fully dropped and re-opened** as a fresh git history (desensitized local absolute paths / usernames / key placeholders), commit author uniformly anonymous `yuanqubeiding` + GitHub noreply email
- **Provenance (PROVENANCE.md)**: evidence bundle SHA-256 + trusted timestamp (tsa.cn desensitized attestation) anchors "the author already held the complete manuscript when the public version was published"; SHA-256 one-way and irreversible, publishing the hash leaks no privacy
- **Attribution added**: README + `tamias/__init__.py` `__author__` added GitHub link (github.com/yuanqubeiding)
- **Competitor survey**: swept the working-pet competitor landscape (Miku / AgentPet / Clawd / DSH whale girl, etc.), positioning converged to "learn the shell, don't touch the core; current state is good enough, no more converging"

### Deciding to open-source (09-14)

- **Closed-source? Nah**: The author originally wanted to keep it closed and hidden, then thought — isn't it tiring guarding against this and that every day? It's not that I'm afraid of being copied; I just got too lazy to hide it. As for whether you use it... whatever, it's right here anyway.
- **Not just tossed out carelessly**: code is Apache-2.0, assets keep their own copyright, every single notice is in place. I say "whatever", but honestly every line of code and every illustration was polished with care. Only when someone actually uses it and drops a star does it feel worth the effort — hmph, it's not like I check the star count every day.

### Packaging compliance + MVP version 0.1.5 (09-15)

- **Version set to 0.1.5 (MVP)**: `__version__` 0.1.2 → 0.1.5, installer `tamias_setup_v0.1.5.exe`
- **GPL compliance upgraded from "delete after" to "block at source"**: PyInstaller's PySide6 hook over-collects GPL-only Qt modules (QtCharts/QtPdf/Quick3D etc.)'s DLLs; these DLLs aren't collected via `import` but are dragged in by the QtQml/QtQuick QML plugin collection mechanism, so `--exclude-module` can't exclude them (confirmed by PyInstaller maintainer rokm in Discussion #8673)
- **build.py changed to spec-driven**: filter `a.binaries`/`a.datas` in the spec, before COLLECT writes to disk, removing GPL modules at the source; `_strip_gpl_qt_modules` retained as a post-hoc fallback (double insurance)
- **Patched the QtPdf/QtPdfWidgets/QtPdfQuick gap**: the previous cleanup list missed the GPL-only Qt PDF modules (binding PDFium), added to the list + new .pyd module-name matching
- WARNING: source-level verification passed (spec generation + filter function 34 test cases all passed), **not yet re-packaged to verify** (packaging interrupted midway, will rerun another day)

## v1.0.13 — 2026-08-15

### Claude Code fully removed: the work path only uses dsh

- Background: when dsh was immature, the work path was "dsh first + Claude Code fallback", a single point of failure across three links (dsh / Claude Code CLI / DeepSeek Key), breaking one degraded it. Now dsh is verified end-to-end, the fallback path became a liability instead (it previously produced ENOTFOUND stale errors), so Claude Code was fully removed
- Change scope (9 files changed + 1 file deleted + config migration):
  - `settings.py`: deleted the `claude_code` config block + `claude_executable` property, added top-level `work_dir`, `always_work`
  - `main.py`: deleted `claude_runner` init + `claude_handler` + claude fallback, `work_handler` only uses dsh
  - `gate.py`: `claude_handler` → `work_handler`, cleaned Claude copy
  - `pet_window.py`: signal/checkbox/property renamed, `working_dir` → `work_dir`
  - `chat_dialog.py`: tutorial 5→3 items, removed Claude Code/DeepSeek detection branches + `_start_pro_mode_flow` dead code
  - `setup_wizard.py`: removed the Claude Code CLI detection page
  - `confirm_dialog.py` / `api/__init__.py`: comments de-Claude'd
  - deleted `api/claude_code.py`
- Config key migration: `claude_code.working_dir` → top-level `work_dir`; `pet.always_claude` → `pet.always_work`
- WARNING: the locally installed Claude Code CLI **is kept untouched** — only the references in Yuanyuan's code were removed, the local CLI is not uninstalled
- Verification: `compileall` full syntax OK + grep no residual `claude_code` references + restart real test (pet display / chat / work+gate) all three paths passed
- Impact: the work path now has a single dependency on dsh — if dsh goes down, Yuanyuan will honestly say "work engine not connected" instead of silently falling back (honest, but one less safety net)

## v1.0.12 — 2026-08-15

### Approval gate (Plan A) landed: ask the owner before working, no "board first, ask later"

- Root cause: the gate previously relied on dsh's `approval/requested` event, but dsh approval is **passive** — it only fires when touching the file sandbox, launching processes (like opening Edge) doesn't trigger it at all, hence "executed before asking"
- Fix: connected "confirm before working" to `work_handler`, the **master switch** of work — any work request (smart routing + always_claude two paths), before being sent to the engine, first pops a confirmation dialog on the main thread, only acts after the owner approves
- "Whether to review" doesn't enumerate dangerous actions (can't enumerate them all), only judges "chat vs work", if work then ask first:
  - `gate.py`'s `_classify`: keyword quick-filter → DeepSeek semantic fallback → failure defaults to chat (fail-safe, rather miss work than miss approval)
  - Confirmation UI: prefer the chat box's right **approval bar** (`request_gate_approval` + `_gate_event` blocking wait, integrated into UI not a popup), non-pro mode / chat box not ready falls back to `confirm_dialog.py`'s `show_confirm`; cross-thread via `_MainThreadInvoker` (BlockingQueuedConnection)
  - `_MainThreadInvoker` moved from the dsh init try block **to the outer scope**, so the gate still works when dsh is unavailable (Claude fallback also gated)
- Boundary (Plan B pending): granularity is "the whole task" — "open Edge" blocks precisely, but a vague task like "help me run the project" — after approval, dsh's internally-split mid-task operations are still not asked one by one

## v1.0.11 — 2026-08-15

### Settings UI: API Key "fill / show / delete" landed

- Added `yuan_yuan/settings_dialog.py`: the real settings dialog opened from tray "Settings..."
  - Fill: key input (password mode + 👁 show/hide toggle)
  - Show: auto-fills the saved key on open, status bar masked preview (`sk-...last 4`)
  - Delete: clear after second confirmation, explicit note "won't crash, chat falls back to reply / work prompts no key"
- "One key, two mouths" dual-write:
  - Chat → `config.yaml`'s `deepseek.api_key` (Yuanyuan's own DeepSeek client)
  - Work → dsh engine credentials `credentials.set` / `credentials.unset` (3 new RPCs: set/unset/describe)
  - Graceful degradation when the engine is off: only write config.yaml, prompt "set/delete again after the engine starts"
- Wiring: `tray_icon.py`'s "Settings..." changed from TODO to a real callback, `main.py` passes in `open_settings`
- Honest note: changing/deleting the Key requires **restarting Yuanyuan** to fully take effect (the running chat client / gate is initialized at startup)

### Load-bearing wall status

- The bridge works, wiring done, settings UI in place. One last link remains: **fill in the Key and actually run it**, verifying "memory (session restore) + gate (approval dialog)" end-to-end

## v1.0.10 — 2026-08-15

### The bridge works: dsh_client.py written and verified

- Fully reverse-engineered dsh's wire protocol (source-level, not guessing):
  - The event stream is **standard WebSocket** (not SSE as previously thought), connects to `ws://127.0.0.1:3080/api/events.mux`
  - HTTP RPC is `POST /api/<method>` + `client-request`/`server-response` envelope
  - Approval loop = receive `approval/requested` frame → `POST /api/respond` reply allow/deny → engine continues
- Wrote `yuan_yuan/api/dsh_client.py` (three-piece, all-Chinese comments):
  - `DshClient`: HTTP RPC (session/workspace/approval reply), synchronous
  - `DshEventStream`: WebSocket event stream, background thread runs asyncio, auto-reconnect on disconnect
  - `DshGateway`: composite facade, `on_approval(rpc_id, payload)` callback + `answer()` reply
- Real-test passed:
  - `session.list` read 2 test sessions ✓
  - `session.create` pre-allocated ID idempotent (same ID returns same session) ✓ — **memory's foundation confirmed usable**
  - WebSocket connects and immediately receives `session/subscribed` frame ✓

### Load-bearing wall status

- The wall's foundation (bridge) is laid. Two segments remain: configure the DeepSeek API Key, and replace main.py's claude_handler with DshGateway
- End-to-end (actually running a task + approval dialog) needs a Key to verify

### Honest summary

> Protocol reverse-engineered, bridge written, even "memory can be restored" is half-verified. But still at "laying the foundation" — without a Key I can't prove the gate truly connects to Yuanyuan's dialog. The next step isn't writing code, it's filling in the Key.

## v1.0.9 — 2026-08-15

### Major turn: DeepSeek Harness appeared, the memory chasm now has a path

- DeepSeek open-sourced **DeepSeek Harness (DSH) v0.1** on Aug 13, MIT license, positioned as "benchmarking Claude Code"
- Core concept "Model + Harness = Agent" + "everything is a plugin" — model, tool, gate, session, sandbox, storage are all replaceable components
- Precisely hits the two things we were stuck on:
  - **Memory**: session is a first-class component, with the ACP protocol for cross-process session restore (exactly the pit where `--session-id` repeatedly said "already in use")
  - **Gate**: gate/approval is a pluggable plugin, Yuanyuan can write its own gate into the Agent loop, no longer relying on plan/bypassPermissions to "work around"
- And it runs native DeepSeek models, no VPN, no Anthropic login — the ugly "set ANTHROPIC_BASE_URL" trick in the tutorial can be deleted

### Mindset upgrade: Yuanyuan from "remote control" to "the body itself"

- Old architecture: Yuanyuan = Claude Code's remote control (subprocess commands, the gate in someone else's hands)
- New direction: Yuanyuan = the Agent runtime itself (face = desktop pet, gate = its own plugin, session = standard protocol, model = DeepSeek)
- Key constraint: Harness is Node/TS, Yuanyuan is Python, can't import, needs ACP/stdio bridging; gate.py can't be rewritten in TS

### Memory breakdown (honest boundary)

- Short memory (remembers earlier in one conversation) → Harness native session restore, solvable
- Long memory (remembers after closing and reopening) → still relies on `.yuan_yuan/` storage + context injection, but it only truly becomes useful once short memory works

### Progress

- dsh globally installed (528 packages)
- Todos: figure out the interface (headless / external approval possible / session restore) → draw the load-bearing-wall construction plan → touch gate.py

### Honest summary

> Waited two months, DeepSeek's "DeepCode" came in the form of Harness. But v0.1 is unstable, interfaces unverified, and there's the Python↔Node language boundary to cross. Not the finish line, but finally a path that looks walkable.

## v1.0.8 — 2026-07-24

### Shelved: the memory problem

- Session passthrough tried 4 times, all failed. `--session-id` reuse always reports "already in use"
- Pipe mode (persistent subprocess) — Claude Code CLI's `--print` is one-shot, interactive mode is a TUI that can't be parsed
- Anthropic API direct — needs VPN + Anthropic Key, unrealistic at this stage
- Trae Agent CLI considered — usable in China, but not yet tested

**Conclusion**: Claude Code CLI's subprocess model doesn't support the session persistence Yuanyuan needs. Waiting for DeepSeek to release its own CLI coding assistant ("DeepCode"), then just replace the backend. Frontend UI, gate layer, project panel need no changes.

### Maintained state
- Chat: context injection approach (`chat_text` carries recent conversation), barely usable
- Work: plan → approval → exec, gate works, but no memory
- Routing: two paths (work keywords → approval flow / rest → chat direct), simple and clean

## v1.0.7 — 2026-07-22

### Spring cleaning (a day of deleting more code than writing)

- Deleted `PersistentClaudeSession` (the persistent process never worked)
- Deleted `_call_deepseek_directly` (pure-conversation DeepSeek direct)
- Deleted all branches in `claude_handler` (exec/chat/plan three paths all cut)
- Deleted all routing in `main.py` (gate, TASK_KEYWORDS, _always_claude)
- Deleted context assembly (`full_text`, `chat_text`, `recent`)
- Deleted residual dead code (orphaned `claude_runner.run()` call, duplicate plan block)

### Fix: the gate finally works

- **Root cause**: `_start_pro_mode_flow` went through `_on_message_callback` → `claude_handler` → `bypassPermissions`. The plan was treated as chat and executed directly, the approval bar was decorative.
- **Fix**: `_start_pro_mode_flow` directly calls Claude Code with `ClaudeCodeRunner(permission_mode="plan")`, not via `claude_handler`. Approval bar lights → click approve → `__EXEC__` → `bypassPermissions` truly executes.
- Verification: say "open Edge" → plan returns "needs approval" → Edge **not opened** → click approve → Edge opens. The door is tightly shut.

### Current architecture (simple and clean)

```
chat_dialog.py:
  work keywords → _start_pro_mode_flow → plan (view only, no execute) → approval → exec
  other messages → _ReplyWorker → claude_handler → bypassPermissions

main.py claude_handler:
  __EXEC__ → bypassPermissions execute
  normal message → bypassPermissions direct reply
```

### Honest summary
> Deleted 200+ lines of bad code, added back 20. The gate went from paper to a real door.
> Cost: the approval flow creates a new ClaudeCodeRunner each time (~2s overhead), but correctness first.

## v1.0.6 — 2026-07-22

### Retreat (today mostly bug-fixing, routing logic getting messier)

- Routing simplified from four branches to two (work → approval / rest → chat)
  - The simplification was right, but the process left residual code and indentation errors
- Chat memory repeatedly lost: full_text → text → added context back → format wrong → reformatted
  - Conclusion: the context-passing approach is unstable, needs a unified structured format
- Project storage changed from centralized to follow-the-folder (`.yuan_yuan/`)
  - Registry mode works, but old data needs manual migration
- Claude Code session reuse fully disabled (always `--no-session-persistence`)
  - Avoids the "session already in use" error, but loses plan→exec session continuity
- Approval bar activation logic patched three times, still unstable
  - `_on_plan_done` directly manipulates button properties, bypassing `_activate_approval`
- Vague messages like "name it Yuanyuan" still occasionally leak into the approval flow
  - The natural flaw of keyword matching exposed
- Claude Code sees project files during chat replies and answers randomly
  - Chat path changed to DeepSeek, but memory lost again

### Honest summary
> Fixed 10+ bugs today, introduced a new one. The code went from a clear four-branch into a complex patch pile.
> chat_dialog.py's routing logic needs a thorough refactor — centralized management, away from `_on_send`.

### Next steps
- Refactor: extract routing into standalone functions, remove all inline branches
- Unify the context-passing format (structured JSON, not string concatenation)
- Stop adding features to chat_dialog.py until cleaned up

## v1.0.5 — 2026-07-21

### Fixes
- Approval bar not activating: in project mode, vague messages (non-chat non-work) go to the normal reply path, don't trigger `_on_plan_done`, approval bar never lights.
  - Fixed routing: in project mode only explicit chat keywords reply directly, the rest all go to the approval flow
- Opening a project doesn't save or clear the old conversation, new project shows old project's conversation
  - `_pick_project`: first `_sync_conv()` save → `_messages.clear()` clear → then load
- After creating a new project the chat window keeps old context, Claude Code mistakenly thinks it's continuing the old task
  - `_launch("new")`: clear chat window + welcome message after creation
- "Who are you" misjudged as work in project: history context containing "file/code" keywords causes `is_chat_only` misjudgment
- Claude Code file upload reports `Session token required`: `--file` is for remote resources, local files changed to path-in-prompt
- Tutorial step 4 (configure DeepSeek) has no detection logic: added separate env var + settings.json check branch
- Tutorial clicking first unit jumps back to menu: `_start_unit(0)` called the wrong method, changed to `_show_tutorial_loading_for_step()`

### Added
- Pure conversation mode via DeepSeek API black-box direct (`_call_deepseek_directly`), no approval, instant reply
- Claude Code login workaround: tutorial teaches setting `ANTHROPIC_BASE_URL` to use DeepSeek, no VPN no Anthropic login

### Architecture notes
- Three-layer message routing: pure conversation (DeepSeek direct) / project chat (direct reply) / project work (approval flow)
- Approval bar activation force-sets button properties directly, skipping intermediate functions to avoid signal loss

## v1.0.4 — 2026-07-09

### Added
- Pure conversation mode via DeepSeek API black-box direct (`_call_deepseek_directly`)
  - Doesn't go through Claude Code, no approval, instant reply
  - Friendly prompt when DeepSeek Key not configured
- Tutorial adds step 4 "configure DeepSeek"
  - Teaches setting `ANTHROPIC_BASE_URL` env var to bypass Anthropic login
  - Checks whether `~/.claude/settings.json` is configured
  - 5 steps, the tutorial route has no VPN, no Anthropic login, compliant
- Tutorial directory structure: four units, clickable
- Tutorial progress bar 1/5 + skip button unified

### Improvements
- Pure conversation vs project mode routing clarified:
  - Pure conversation → DeepSeek direct
  - Project + work keywords → plan→approval
  - Project + chat keywords → direct reply
- Chat degradation path: when the persistent session hangs, auto-fallback to `bypassPermissions` direct, no longer leaking to plan

### Fixes
- "Who are you" misjudged as work (persistent session startup failure broke the degradation chain)
- Tutorial clicking first unit jumps back to menu (`_start_unit` called wrong method)
- Tutorial "configure DeepSeek" step has no detection logic (added separate detection branch)

## v1.0.3 — 2026-07-02

### Added
- Tutorial mode (launcher 📚 button):
  - Course catalog: four units (environment setup / first project / understanding the gate / team collaboration)
  - Unit one: 4-step wizard (Node.js / Git / Claude Code / DeepSeek Key)
  - Each step "check" self-verify + "skip" continue, progress 1/4 → 4/4
  - Explains why each item is needed, where to download, how to install
  - Tutorial embedded in the launcher's right side, no popup
  - ← back button returns to welcome page
  - Loading page + green progress bar animation

### Improvements
- Launcher button hover animation: `QPropertyAnimation` + `QEasingCurve`, smooth right-shift on hover
- Claude Code detection compatible with multiple Windows methods: `claude` / `claude.cmd` / `bash` / `cmd /c`
- Gear management menu reverted from embedded panel to QDialog (stability first)
- Gear management dialog enlarged: 480×520

### Fixes
- Gear menu crash (ProjectStore method-call compatibility)
- Star pin crash (`_toggle_pin` / `_delete_history` compatible with old/new store)
- File upload then Claude Code error (session token issue, changed to path-in-prompt)
- Launcher right-side tutorial content reference lost (stored `_launcher_right_layout`)
- Duplicate method made tutorial ineffective (deleted old `_show_tutorial_loading` duplicate definition)

### Architecture notes
- Page-switch animation: 5 attempts, 5 failures. Position sliding and opacity fade both conflict with QStackedWidget. Conclusion: **page-level animation is infeasible**. Button-level hover animation works and is deployed.
- QWebEngineView vs animation conflict root cause: Chromium doesn't go through Qt's paint pipeline, GPU draws directly to screen.
- Chat page doesn't include WebEngine (VRM is in PetWindow), but QStackedWidget's own limits still blocked animation.
- Tutorial right-column injection mode (`self._launcher_right_layout` reference storage) can serve as a template for later embedded panels.

## v1.0.2 — 2026-06-30

### Added
- Persistent Claude Code process (pipe mode): chat second-level replies, no cold start
- Conversation memory: each request carries the recent 6 turns of history, no more amnesia
- Launcher (pro mode): left-right split, left option area + right welcome area
  - 💬 pure conversation / 📂 open project / ＋ new project
  - Recent list (recent conversations + recent projects)
  - ← back button to launcher
- Project storage `project_store.py`: project > conversation, movable/copyable
- Left panel rebuilt: pure conversation area + project area, ＋ new project button
- Agent communication bus `agent_bus.py`: multi-instance JSON communication via shared folder
- Send-review button: project panel bottom 📤, push tasks to other instances
- Attachment upload (＋ button): file copied to work dir, path passed to Claude Code

### Improvements
- Gate precision: simple chat (who are you / hello / what did I just say) replies directly, no approval
- Plan prompt optimized: require future tense, no full code, no complaining about permissions
- Approval bar: buttons labeled with shortcuts (1 approve / 2 reject), keyboard support
- Approval summary scrollable, 300px wide
- Bubble incremental update + conversation save async: UI no longer freezes
- Claude Code timeout raised from 120s to 300s
- Settings checkboxes: checked turns green `#00FF66`, easy to distinguish
- Right-click menu + settings dialog black-bg white-text

### Fixes
- Chat box multi-click duplicate popups
- QMenu vs WebEngine conflict crash (gear, summon changed to QDialog)
- Confirmation dialog blocks chat-window dragging
- New project doesn't switch Claude Code working directory
- Single-instance protection, EXE packaging, VRM resource packaging

### Architecture changes
- `conversation_store.py` → upgraded to `project_store.py`
- Added `agent_bus.py`, `CHANGELOG.md`
- Code size: 5,445 → 6,031 lines (+586), 19 Python files

## v1.0.1 — 2026-06-30

### Added
- Developer log `CHANGELOG.md`
- Approval bar keyboard shortcuts: press **1** approve, press **2** reject
- Button labels: approve (press 1 to approve), reject (press 2 to reject)
- Message prompt optimization: "generating plan, just a moment...", "executing, wait a moment..."
- Attachment upload (＋ button): images and files, copied to work dir and passed to Claude Code
- Approval summary scrollable (QScrollArea), long text no longer stretches the UI
- Pro mode widened: 1020 → 1360, approval bar 200 → 300px, project panel 200 → 240px
- History management panel changed to embedded (no popup), below the sidebar
- Batch delete mode in the management panel (checkboxes + one-click delete selected)
- Star favorite button in the management panel, real-time toggle without rebuilding the panel

### Fixes
- UI freeze: API calls moved to a background thread (`threading.Thread`)
- Conversation save lag: JSON write async (background thread)
- Bubble update slow: incremental replacement of single widgets, not full rebuild
- Right-click QMenu crash: replaced with QDialog (gear management, summon menu)
- Management panel star unfavorite leaves residual star on the left sidebar
- Sidebar + management panel width and font enlarged (200 → 220px)

### Known issues
- Image upload not recognized by Claude Code (DeepSeek V4 doesn't support multimodal)
- Summon limit detection inaccurate (wmic count error)
- EXE startup brief black window (PyInstaller common issue)
- Two instances ~800MB memory usage

## v1.0.0 — 2026-06-27

### Project initialization
- Built the Python 3.14 + PyQt6 project skeleton
- `requirements.txt`: PyQt6, PyYAML, requests
- `config.yaml` config management (supports env var override)
- Transparent frameless desktop-pet window, bottom-right positioned, draggable
- QPainter hand-drawn 2D white-haired girl character + blink/sway animation
- System tray icon (show/hide/exit)

### AI integration
- DeepSeek API client (chat completion, multi-turn, streaming)
- Claude Code CLI call wrapper (`--print` non-interactive, `--output-format json`)
- Gate layer `gate.py`: intent classification (chat/work), routing dispatch
- Claude Code permission mode: `plan` → confirm → `bypassPermissions`

### Chat system
- Pink anime conversation bubbles (user blue / AI pink)
- Enter send, Shift+Enter newline
- Event filter intercepts keys (avoids WebEngine conflict)
- Stop button (cancel AI request while waiting)

### Pro Mode
- VS Code terminal style: black bg `#0D0D0D`, green text `#00FF66`, Consolas font
- Left history panel (200px):
  - Conversations auto-saved as JSON (`data/conversations/`)
  - First message creates a conversation, closing Yuanyuan ends it
  - Grouped by project directory
  - Pin (gold mark), delete
  - Gear management dialog (QMenu vs WebEngine conflict, changed to QDialog)
- Topic switch: ＋ new conversation button
- Approval bar (300px): embedded right, replacing popup
  - Gray disabled / cyan active
  - Press **1** approve, press **2** reject
  - Approval summary scrollable
- Project panel (240px): plan/progress/questions auto-extracted
  - Manually editable, Ctrl+C copy to pass to other instances
- Working directory switch: 📂 button + file picker
- Summon feature (📞): multi-instance collaboration, dialog to pick count (1/2/3 people)
- Attachment upload (＋ button): file copied to work dir, path passed to Claude Code
- Size: 1360×620

### VRM 3D character
- PyQt6-WebEngine embedded Three.js rendering
- Localized loading: `three.module.js` + GLTFLoader + BufferGeometryUtils
- All CDN bypassed (unpkg/jsdelivr unusable in China → all localized)
- Model auto-scale-fit, breathing animation, right-click drag rotate
- `.vrm` models exported from VRoid Studio used directly

### Interaction polish
- Left-click opens chat (taskbar visible, supports maximize)
- Left/right-drag moves the window (transparent overlay captures events)
- Right-click menu: settings/exit
- Settings dialog: version number, always use Claude Code, pro mode toggle
- Single-instance protection (PID lock file + wmic process-name check)

### Performance optimization
- API calls moved to background thread (`threading.Thread`), UI no longer freezes
- Conversation save written to file async
- Bubble incremental update (replace single widget, not rebuild all)
- Prompt optimization: "generating plan, just a moment..."

### Packaging
- PyInstaller `--onedir`: `dist/yuan_yuan/yuan_yuan.exe` (~540MB incl. WebEngine)
- Inno Setup install script: `installer/setup.iss`
- VRM resource files bundled

### Progress summary
- 2026-06-17 ~ 06-30, about two weeks, 14 development sessions
- Phase 1 (06-17 ~ 06-21): project skeleton, pet window, QPainter character, animation, tray
- Phase 2 (06-22 ~ 06-24): chat dialog, DeepSeek/Claude Code integration, gate layer, packaging
- Phase 3 (06-25 ~ 06-27): pro mode, VRM 3D, history panel, approval bar, project panel
- Phase 4 (06-28 ~ 06-30): multi-instance collaboration, attachment upload, performance optimization, bug fixes

### Known issues
- EXE startup brief black-window flicker (PyInstaller common issue)
- Single-instance protection occasionally fails (wmic detection race condition)
- Image upload not recognized (Claude Code uses DeepSeek V4, no multimodal)
- Right-click QMenu vs WebEngine conflict (already replaced with QDialog)
- Two instances ~800MB memory usage

### Tech stack (Yuanyuan v1.0.0 old snapshot, 2026-06-27)

> WARNING: this table is the old Yuanyuan v1.0.0-era tech stack, now evolved — see the top "Tech stack (current)" for the current stack.

| Layer | Technology |
|------|------|
| Language | Python 3.14 |
| GUI | PyQt6 + PyQt6-WebEngine |
| 3D rendering | Three.js (ESM) |
| Chat | DeepSeek API (deepseek-chat) |
| Work | Claude Code CLI (claude-opus-4-8) |
| Config | YAML + env vars |
| Packaging | PyInstaller 6.21 + Inno Setup |
| Character model | VRoid Studio → .vrm |
