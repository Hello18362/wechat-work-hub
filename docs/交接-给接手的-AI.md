# 交接：给接手的 AI

> 写给**下一个接手这个项目的 AI**。读完这份 + 仓库里的 README，你应该能在 30 分钟内接手，并且**不改坏任何东西**。
> 人类读者只需要看第 1 节和第 11 节。

---

## 1. 三十秒现状

| 项 | 值 |
|---|---|
| 仓库 | https://github.com/Hello18362/wechat-work-hub （公开，PolyForm Noncommercial 1.0.0，**非商业**） |
| 分支 / HEAD | `main` / `ed8cbda`（工作树干净） |
| 回流点 | tag `stable-2026-11-24`（改坏了可以整机回退到这里） |
| 版本 | 0.2.0（`pyproject.toml` 与 `/health` 一致），另有历史 tag `v0.1.0`、`v0.2` |
| 规模 | 125 个受版本控制文件，67 个 `.py`（约 1.48 万行），10 个测试文件 |
| 单测 | **123 项全绿**（9 个纯 unittest 文件；`tests/test_server.py` 是需要先起服务的手动集成脚本，不进 CI） |
| CI | GitHub Actions，windows + ubuntu × Python 3.10/3.11 四路，最近一次全 success |
| 本机运行状态 | 控制台 `http://127.0.0.1:5710` 在跑；数据源 `sqlite`（真实解密库）；悬浮窗 + 守护进程在跑 |

**它能干什么**：选群 + 选日期 → 读当天消息（含语音/图片/文章）→ 调大模型抽任务 → 出 Markdown + HTML 日报（任务卡带负责人、截止时间、来源回链）→ 桌面悬浮窗勾选。
**它不干什么**：不做微信解密（依赖外部工具产出的库）、不做群机器人、不是 SaaS。

---

## 2. 三条硬纪律（先记这个，比读代码重要）

1. **一个改动必须配一条能复现的测试。** 没测试不许改行为。
2. **一次只做一件事。** 别顺手重构。这个项目的坑有一半来自「顺手改」。
3. **不许动这些**：`config/settings.yaml` 的默认值、`.env.example` 的键名、`data/samples/` 里的样例数据、`.env`（本地私密配置，永不入库）。

> 历史背景：2026-11-24 有过一次「另一个 AI 改了三处、没加测试」的返工，为此立了 ADR-027（见 `docs/` 里交接记录）。上面的纪律就是那次事故的产物。

---

## 3. 目录地图（只列你会碰的）

```
main.py                    CLI 总入口（--group/--date/--leaders-only/--serve/--list-groups…）
core/config.py             配置读取。所有 .env / yaml 都走 _read_text_friendly()，支持 GBK 与 BOM
core/pipeline.py           主流水线：读取 → 逐条加工 → 合并 → 总结 → 输出；单条失败降级
core/auto_refresh.py       调外部解密工具刷新数据；会自动挑一个「装了 psutil/Crypto」的 Python
collector/models.py        统一 Message 模型（时间/发言人/类型/附件/是否领导）
collector/sqlite_client.py 直读解密后的 SQLite（主路径）
collector/chatlog_client.py HTTP 采集接口（备用路径）+ 工厂 build_client_from_config()
collector/sample_client.py 内置样例数据客户端（没有真实数据源时的兜底，source_mode="sample"）
processor/                 语音转写、图片理解、文章正文抓取；每个都有 dummy 降级实现
summarizer/                大模型总结（deepseek 等）；无 Key 时降级为「待处理清单」并写 runs/pending/
output/markdown.py|html.py 报告渲染（HTML 带任务卡、来源回链、深浅色）
web/server.py              标准库 http.server；/health /api/status /api/run /api/groups /api/upload …
web/assets/                控制台前端（原生 JS，无构建步骤）
tools/setup.py             一条命令装完：建 .venv → 装依赖（失败换清华源）→ 生成 .env → advice 自检
tools/doctor.py            24 项体检，--json 给 AI 读；「没数据源/没 Key」只算提醒不算失败
tools/launch.py            启动器：查依赖（缺了问一次就自动装）→ 杀旧进程 → 起后台服务 → 探活
tools/smoke_chain.py       端到端链路自检（健康检查 → 群列表 → 取消息 → 出报告）
tools/desktop_widget.py    桌面悬浮窗（Win32 分层窗口 + PIL 绘制）
tools/widget/              悬浮窗内部：app.py 状态机 / render.py 绘制 / geom.py 纯几何 / win32.py 封装 / watchdog.py 自愈判定
tools/auto_daemon.py       守护：每 60s 看窗口是否活着；有新消息才调 AI（最小间隔 3600s）
tests/                     9 个纯 unittest + 1 个手动集成脚本
docs/                      部署手册、排错字典、施工记录（见第 10 节）
```

---

## 4. 怎么跑起来（本机已装过，别人从零装）

```powershell
# 从零（干净机器，实测 24.9 秒）
python tools\setup.py --yes

# 起服务（会自己开浏览器）
.venv\Scripts\python.exe tools\launch.py

# 或者 Windows 上直接双击  一键启动.bat （首次会自动建 .venv 并装依赖，实测 30 秒）
```

只体检不安装：`python tools\doctor.py`（人读）或 `--json`（机器读）。
想看报告但不接真实数据：`python main.py --group "XX项目工作群" --date 2026-10-27 -f both --open`（走内置样例数据）。

---

## 5. 「我改完没改坏」的验证清单（改任何代码后都跑）

```powershell
$py = ".venv\Scripts\python.exe"

# 1) 单测：必须 123 项全绿
foreach ($t in 'test_regression','test_sample_client','test_launch','test_widget_layout',
                'test_widget_watchdog','test_doctor','test_auto_refresh','test_setup','test_config_robust') {
  & $py "tests\$t.py"
}

# 2) 语法自检（改过的文件逐个过一遍）
& $py -m py_compile <改过的文件>

# 3) 服务活着
Invoke-WebRequest http://127.0.0.1:5710/health -UseBasicParsing | % Content
# 期望 {"status": "ok", "version": "0.2.0", ...}

# 4) 链路自检（真实数据源时 34 项全过；样例态会有 3 个 SKIP，那是正常的）
& $py tools\smoke_chain.py --url http://127.0.0.1:5710
```

**判定标准**：单测绿 + `/health` ok + `smoke_chain` 失败 0。三条缺一条就不算改完。

---

## 6. 平台陷阱（Windows 专属，踩过就流血）

| 陷阱 | 表现 | 正确做法 |
|---|---|---|
| **`.bat` 必须 CRLF** | 用 LF 写回去，cmd 解析多行块直接崩，满屏 `'安装依赖' is not recognized` | 读出后 `replace('\r\n','\n').replace('\n','\r\n')` 再写；单测抓不到，只能真跑 |
| **`.bat` 是 GBK** | 用 UTF-8 写中文会变乱码或解析失败 | `path.read_bytes().decode('gbk')` → 改 → `.encode('gbk')` |
| **控制台 GBK 打不出 ✓ ✗** | `UnicodeEncodeError: 'gbk' codec can't encode character '\u2717'` | 用 `main.py` 里现成的 `MARK_OK` / `MARK_BAD`（非 UTF-8 控制台自动降成 `[OK]`/`[X]`） |
| **记事本存 .env 成 ANSI/GBK** | 启动崩：`UnicodeDecodeError ... byte 0xca` | 已修：`_read_text_friendly()` 会自动转；`setup.py` 检测到就就地转 UTF-8 |
| **记事本存成 UTF-8 with BOM** | 配置静默失效（首键变 `\ufeffWX_SIWX_RUN`） | 同上；`doctor.py` 会 WARN 提示 |
| **路径含中文/空格** | 少数第三方库路径处理出错 | 项目能跑（本机就是 `D:\我的空间\...`），但 `doctor.py` 会提醒 |
| **PowerShell 没有 heredoc** | `python - <<'PY'` 报 ParserError | 写临时 `.py` 文件再跑 |
| **`Add-Type` 里的 C# 源码** | 用双引号会被 PowerShell 吃转义 | 必须单引号 here-string，且别在 `powershell -Command` 里拼 |

---

## 7. 悬浮窗：这个项目最容易「看起来好了其实没好」的地方

窗口类名 `WeChatWorkHubWidget`，窗口实现类 `widget.win32.LayeredWindow`（**不是** `WinWindow`，写错过一次）。三种形态：`expanded`(522×820) / `ball`(96×96) / `sliver`(34×192)，缩放系数 `k` 随 DPI。

**必须知道的三个教训：**

1. **不要依赖 `SetTimer`。** 曾出现过「TID_FRAME 和 TID_IDLE 两个定时器同时失效、只剩鼠标消息还在走」的偶发故障，表现是点了没反应、状态文件说已展开但窗口还是细条。现在动画改成 `_run_anim_inline()` 内联帧循环（不依赖 WM_TIMER），另有 `_watchdog()` 兜底强制落到终态。**改动画代码时别把这条退回去。**
2. **小球点击靠线程投递，不靠定时器。** `_arm_ball_click()` 起一个 0.30s 的线程，睡醒后 `self.win.post()` 发 `WM_APP_SELF`，`_flush_ball_click()` 再展开。
3. **几何必须用「可见矩形」算。** 窗口矩形包含投影留白（expanded 20px / ball 14px / sliver 12px），直接拿窗口矩形吸边会把小球推到屏幕外（`panel_x=1852` 而屏宽 1920，球在 right+346 处）。所有吸边/夹取走 `tools/widget/geom.py` 的 `visible_box` / `panel_pos_from_box` / `clamp_to_work` / `snap_x`，它们不 import win32，Linux CI 也能测。

**怎么验证悬浮窗**（不靠肉眼）：
```powershell
# 静态出图
& $py tools\desktop_widget.py --snapshot "$env:TEMP\w.png" --mode expanded --demo
# 全形态自检（把定时器打成 no-op 后仍应正确切形态、点球能展开）
& $py "$env:TEMP\anim_no_timer.py"
```
发 Win32 消息模拟点击时注意：`WM_LBUTTONDOWN/UP` 的 lparam 是**客户区坐标**，不是屏幕坐标 —— 传屏幕坐标会命中不到任何控件，看起来像「点击无效」，其实是脚本自己的错。

---

## 8. 当前状态清单

**能用（已验证）**：一条命令安装、GBK/BOM 配置容错、24 项体检、端到端链路自检、后台启动与探活、端口被占时自动避开、报告 Markdown/HTML、控制台（选群/日期/历史/上传）、悬浮窗三形态与自愈、自动刷新（自动挑能跑 SIWX 的 Python）、无 Key 时的降级。

**仍是占位（不影响跑通，影响「功能全面」）**：
- 语音：没装 `faster-whisper` → 语音消息只显示 `[语音]`。补法：`.venv` 里 `pip install -e ".[asr]"`（几百 MB 模型；CPU 已在配置里设成 `small`）。
- 图片理解：`config/settings.yaml` 里 `vision.provider: dummy` → 只从文件名猜描述。改成 `doubao` 并配 `DOUBAO_API_KEY` 才会真的看图（要花钱）。

**已知未修（有意暂缓，别再自己加戏）**：
- 同一台机器起两份实例时，第二份会静默跑到 5711（`web/server.py` 里端口 `range(port, port+12)` 自动重试），而 `launch.py` 报的仍是 5710 → 用户以为连的是自己那份。判定办法：`/health` 里带 `root` 字段，比对路径即可。
- 报告（`runs/pending/*` 与部分 HTML）里可能残留本机绝对路径。

**发布契约**：`/api/status` 里 `chatlog_online` 是历史字段（语义歧义，样例态恒为 true，**别拿它当通过标准**）；判断数据源是否可用请看 `data_source_ready`，判断是否样例态看 `source_mode`。这三个字段名已写进文档当契约，**不要改名**。

---

## 9. 过去两周踩过的坑（照着看，能省你两天）

| 症状 | 根因 | 修法 / 提交 |
|---|---|---|
| 全新机器「启动超时」，但日志里写着已就绪 | `launch.py` 在装依赖**之前**读端口，`import yaml` 失败 → 退回默认 5710；改过端口的人 100% 中招 | 端口改「先 yaml，失败走文本解析」，并加「按服务日志判断已就绪」兜底 · `61a0c14` |
| 装了依赖却 `ModuleNotFoundError: yaml` | `.bat` 自己找系统 Python，不看项目 `.venv`；且探测块里有无守卫的 `set "PY=python"` 覆盖了值 | `.bat` 优先 `.venv`、解析成 `sys.executable` 完整路径、首次自动建 venv · `0b884a3` |
| `wgh --help` 报 `No module named 'main'` | `pyproject.toml` 里 `py-modules = []` 与 entry point 冲突 | 改成 `["main"]` · `24a8292` |
| 双击 bat 一闪而过 / 控制台 `UnicodeEncodeError` | 脚本打 `✗`，GBK 控制台编不出来 | `MARK_OK/MARK_BAD` 自动降级 · `0e41d88` |
| 没有任何数据源时整条链路全盲 | 只认真实库，health 失败直接抛 | 新增 `SampleClient` + `fallback_sample` 开关 · `e27b48f` |
| 重启后「有新消息但不更新」 | 守护最小间隔 2 小时；且 `.venv` 缺 `psutil`，SIWX 跑不起来（**我自己改 bat 引入的回归**） | `_pick_siwx_python()` 自动挑能跑的解释器；间隔改 1 小时；右键菜单加「立即更新消息」 · `4600a8d` |
| 悬浮窗点了没反应 | `self.anim` 永真 + 帧定时器失效（见第 7 节） | 内联帧循环 + 看门狗 · `38fca43` |
| 小球拖到边缘后消失 | 面板坐标与可见坐标混用 | `geom.py` 四函数 + `_ensure_on_screen` · `0c9ad7b` |
| 卡片背景糊成一片 | 磨砂模糊半径写死 1px（等于没模糊） | `FROST_BLUR=26` · `53da584` |
| 配置存成 GBK/BOM 就崩或静默失效 | 全文按 UTF-8 硬读 | `_read_text_friendly()` + doctor 编码项 · `ed8cbda` |

**另一个雷**：`git push` 到 `github.com:443` 经常失败（`Empty reply` / `Failed to connect`）。可靠路径是 GitHub Git Data API（blob → tree → commit → ref）；注意本地 blob sha 远端不认，必须 `POST /git/blobs` 用 base64 重建，`base_tree` 用**父提交的树**。另外提交作者邮箱必须是 `<ID>+<name>@users.noreply.github.com`，否则会被拒（`push declined due to email privacy restrictions`）。

---

## 10. 文档在哪、看哪份

| 文档 | 给谁 |
|---|---|
| `README.md` | 所有人，先看这个 |
| `docs/一键部署-给AI的操作手册.md` | **接手/部署的 AI**：五步安装、硬验收、11 组故障决策树、汇报模板 |
| `docs/部署与排错-AI版.md` | 同上，32 条症状字典（症状 → 原因 → 修法），装不下去按症状查 |
| `docs/三版本对照.md` `docs/开源发布方案.md` | 了解这个仓库和另外两个衍生版本的关系 |
| `docs/施工记录-桌面悬浮窗.md` `docs/施工报告-桌面悬浮窗.md` | 悬浮窗的设计与逐次修复记录 |
| `docs/交接-下一个我.md` | 更早一版交接（2026-11-22），**已被本文件取代**，仅作历史 |

---

## 11. 人类怎么完成这次交接（三步）

1. 把**仓库地址**给对方 AI：`https://github.com/Hello18362/wechat-work-hub`
2. 把**本文件**（`docs/交接-给接手的-AI.md`）正文发给它，或者直接说「读仓库里 `docs/交接-给接手的-AI.md`，按它接手」
3. 明确三件只有你能给的东西：
   - 它能改代码吗（只读 / 提 PR / 直接推 main）
   - `.env` 里的模型 Key 谁来配（别把 Key 抄进对话里）
   - 遇到不确定的产品决策，先问你，还是它自己拍

**给它的一句话开场白**（可直接复制）：

> 这个仓库是 https://github.com/Hello18362/wechat-work-hub 。
> 先读 `docs/交接-给接手的-AI.md` 和 `README.md`，再动手。
> 纪律：一个改动配一条测试、一次只做一件事、不动 `config/settings.yaml` 默认值 / `.env.example` 键名 / `data/samples/`。
> 每次改完按第 5 节验证（123 项单测 + `/health` + `smoke_chain` 失败 0）再提交。
> 不确定的产品决策先问我，不要自己改需求。

---

## 12. 接手后建议的第一件事

先别改代码。跑一遍第 5 节的验证清单，把真实输出记下来当基线；再打开悬浮窗、控制台各用两分钟。**你在能复现「当前是好的」之后，才有资格判断「你改坏了什么」。**