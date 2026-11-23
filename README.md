# WeChat Work Hub

**把微信群聊变成一份能直接看的工作报告。**

本地优先（local-first）的微信群聊多模态整理工具：从你本机的微信数据库读取指定群的消息，语音转文字、图片生成描述、公众号抓正文，再用大模型提炼成任务清单与日报，输出 Markdown 与可交互的 HTML 报告。

聊天数据默认只在你的电脑上处理；只有你主动配置在线模型时，用于总结的文本才会发送到你所选的服务商。

`本地优先` `微信群聊` `多模态` `大模型` `DeepSeek` `OpenAI 兼容` `Windows`

> 不想装环境也能先看效果：双击 `demo-site/预览.bat`，打开一个纯静态演示站（示例数据，不需要微信、不需要 API Key）。
>
> 要发微信 / 用手机看：双击 `demo-site/打包单文件.bat`，生成 `demo-site/dist/WeChatWorkHub-演示-单文件.html`（约 250 KB，CSS/JS/示例报告全内联，微信发过去点开就能用）。

---

## 一、它解决什么问题

| 场景 | 这个项目怎么做 |
| --- | --- |
| 领导在群里发语音布置任务，事后翻不到 | 语音自动转文字，并入文本流 |
| 一天刷了 300 条，分不清哪条有料 | 按「重点关注名单」打 `[领导]` 标记，可切换只看重点 |
| 截图、报表里的信息抓不住 | 图片生成一句话描述，和文字一起进上下文 |
| 转发的公众号文章懒得点开 | 自动抓正文，失败降级为「标题 + 链接」 |
| 总结还得手动复制粘贴 | 直接调 API 出总结，或一键生成待处理文件 |
| 报告是一坨纯文本 | 输出带交互的 HTML：目录联动、卡片详情、深色模式 |

---

## 二、它不能做什么（先看限制，避免白装）

- **只能读 Windows 微信 PC 版**（4.x），且需要微信保持登录、电脑保持开机。微信客户端不会补采离线消息，关机期间的消息抓不到——这是微信的机制，不是本项目的 bug。
- **不内置解密能力**。数据源需要你自己准备一个能把微信本地数据库解出来的工具（见「前置依赖」）。本项目只读取解密后的 SQLite。
- **不提供云端服务**。没有账号体系、没有云端同步，换台电脑要重新配置。
- **图片理解能力有限**。目前只有两种 provider：占位符（`dummy`）与豆包视觉模型（`doubao`）。DeepSeek 没有视觉能力，即使用了 DeepSeek 做总结，识图仍需另配。
- **摘要由大模型生成，可能出错**。涉及金额、合同、人事的内容请人工复核原始聊天记录。

---

## 三、数据流向

```
微信本地数据库 (SQLite, 加密)
        │  ① 外部解密工具（自备，仅本机）
        ▼
解密后的 SQLite（本机目录，只在 .env 中配置路径）
        │  ② 本项目只读访问
        ▼
语音转写 / 图片描述 / 公众号正文抓取（全部本机执行）
        │  ③ 组装成提示词
        ├──► 离线模式：写成 runs/pending/*.md，你自己贴到任意 AI 对话框
        └──► 在线模式：POST 到你配置的模型 API（仅这一步出网）
        ▼
Markdown + HTML 报告（runs/，本机）
```

- 使用 Ollama / LM Studio 等本地模型时，**全程不出网**。
- 作者不运营任何服务器，不收集任何数据。项目内没有遥测、没有埋点、没有统计上报。

---

## 四、前置依赖

| 依赖 | 要求 | 说明 |
| --- | --- | --- |
| 操作系统 | Windows 10 / 11 | 微信 PC 版仅 Windows 可解密读取 |
| 微信 | PC 版 4.x，保持登录 | 建议固定版本，微信升级可能影响数据库结构 |
| Python | 3.10+（推荐 3.11） | |
| 数据库解密工具 | 选配 | 本项目使用 [stories-in-wx] 风格的工具，能输出解密后的 SQLite 目录即可；不配也能先用内置样例数据演示完整链路 |
| 大模型 API Key | 可选 | 不配也能跑，自动降级为离线模式 |
| ffmpeg | 可选 | 语音为 SILK 格式时用于转码 |
| faster-whisper | 可选 | 不装则语音降级为 `[语音]` 占位 |

---

## 五、快速开始

> **只想最快跑起来？** 一条命令：
> `python tools\setup.py --yes`（Windows 上直接双击 `一键启动.bat` 也可以）。
> 它会自动建 `.venv`、装依赖、生成 `.env`、跑 22 项自检。
>
> **想把这件事交给 AI 做？** 让 AI 读 **[docs/一键部署-给AI的操作手册.md](docs/一键部署-给AI的操作手册.md)**，
> 里面是逐步命令 + 每步的期望输出 + 五条硬验收 + 故障决策树，AI 照做即可，你只需要建一个 API Key。
>
> 中途任何一步报错，别往下猜：先 `python tools\doctor.py`，再查
> **[docs/部署与排错-AI版.md](docs/部署与排错-AI版.md)** 第 5 节的故障字典（按报错原文搜）。

```bash
git clone https://github.com/Hello18362/wechat-work-hub.git
cd wechat-work-hub

# 1) 安装依赖（核心包：requests / PyYAML / beautifulsoup4 / Pillow / zstandard）
pip install -e .

# 2) 配置群与负责人
copy config\groups.example.yaml config\groups.yaml
copy .env.example .env
#    然后编辑 .env，把 WX_DECRYPTED_DIR 指向你的解密目录

# 3) 看看有哪些群（需解密数据已就绪）
python main.py --list-groups

# 4) 跑一次
python main.py --group "XX项目工作群" -f both --open
```

Windows 用户也可以直接双击 `一键启动.bat` 拉起本地控制台——**第一次运行时它会自动创建
`.venv` 并安装依赖**，不需要你先手动 `pip install`。

### 让别人（或者 AI）一句话装好

上面那四条命令，实际上**一条都不用自己敲**。分两种情况：

**情况一：你自己装。** Windows 上双击 `一键启动.bat` 就完了。它会自己找 Python、
没有 `.venv` 就当场建一个、缺依赖会问你要不要现在装（回车＝装，直连失败自动换国内镜像），
装完在后台起服务、自动打开浏览器。
唯一的门槛是机器上得有 Python 3.10+（没装的话它会给出下载地址，并提醒勾选
「Add Python to PATH」）。

**情况二：让 AI 帮你装。** 把下面这段原话发给任意能执行命令的 AI 助手
（Claude Code / Cursor / Codex / 本项目的 DSH 都行），把仓库地址换成你自己的：

> 帮我把 `https://github.com/Hello18362/wechat-work-hub` 装到本地并跑起来。
> **严格按仓库里的 `docs/一键部署-给AI的操作手册.md` 执行，不要自己发明步骤。**
> 那份手册里有五个步骤、每步的期望输出、五条硬验收和故障决策树。
> 装完把「硬验收清单」五条的真实输出贴给我。任何一步失败，先按手册第 5 节用报错原文查，
> 查不到再把完整报错贴给我，别自己猜着跳过。

AI 装完，你在浏览器里应该看到控制台。**怎么判断它真的装对了**，看三件事：

1. `http://127.0.0.1:5710/health` 返回 `{"status": "ok", ...}`（这个地址不碰数据源，纯探活）。
2. 控制台右上角有个状态点：绿色写着「数据源已就绪」或「内置样例数据（未配置真实数据源）」，都算正常；
   红色「数据源未启动」才是没装好。
3. 跑一次 `python main.py --group "XX项目工作群" --date 2026-10-27 -f both`，
   `runs/` 目录里应该出现一份 `.md` 和一份 `.html`。

不需要 API Key 也能走完这三步——没配 Key 时总结会自动降级成离线草稿（报告照出，
但内容是「待处理清单」形态，不是润色后的成稿）。想看成稿效果，再按第七节配一个 Key。

### 全新安装、还没配数据源？先用内置样例数据

只做完第 1 步（`pip install -e .`）也可以完整跑通「采集 → 多模态加工 → 合并 →
总结 → 报告」全链路：没配置解密目录、本地也没有 chatlog 服务时，程序会自动兜底到
仓库自带的**虚构样例数据**（`data/samples/*.json`），控制台状态栏会明确显示
「内置样例数据（未配置真实数据源）」。

```bash
# 看看内置样例群
python main.py --list-groups

# 用样例数据出一份演示报告（无需任何 Key，总结自动离线降级）
python main.py --group "XX项目工作群" --date 2026-10-27 -f both --open
```

样例数据里有两个群：`XX项目工作群`（2026-10-26 / 10-27）和 `部门周会群`
（2026-10-27），全部是虚构的演示内容。配置好真实数据源（`.env` 里的
`WX_DECRYPTED_DIR`）后会自动切回，无需手动开关；想关闭这个兜底，把
`config/settings.yaml` 里 `chatlog.fallback_sample` 改为 `false`。

### 刷新解密数据

解密工具不在本项目内。以 stories-in-wx 为例（路径请替换成你自己的）：

```bash
python <你的解密工具目录>/run.py auto
```

输出目录形如 `.../output/wxid_xxxxx/`，把它填进 `.env`：

```ini
WX_DECRYPTED_DIR=C:/你的路径/output/wxid_xxxxx
```

控制台启动后也会在后台按需触发一次刷新（可选，可用 `WX_SIWX_RUN` 指定脚本路径）。

### 产物

```
runs/
├── 2026-11-14_XX项目工作群.md      # Markdown 报告
├── 2026-11-14_XX项目工作群.html    # HTML 报告（双击即可看）
└── pending/
    └── 20261114_143000_content.md  # 离线模式的待处理文件
```

### 语音转写要占多少资源

默认用 `small` 模型（约 490MB，首次运行自动下载），CPU 就能跑。想更准可以自己往上调，但代价很明显：

| 模型 | 体积 | CPU 速度（1 分钟语音） | 适用 |
| --- | --- | --- | --- |
| `tiny` | ~75MB | 约 5–10 秒 | 只求听个大概 |
| `base` | ~145MB | 约 10–20 秒 | 老机器 / 快速试跑 |
| **`small`（默认）** | **~490MB** | **约 20–40 秒** | **中文识别够用，推荐** |
| `medium` | ~1.5GB | 约 1 分钟 | 口音重、术语多 |
| `large-v3` | ~3GB | 2 分钟以上 | 有 GPU 或极看重准确率 |

改 `config/settings.yaml` 里的 `asr.model` 即可。不开语音转写的话（`asr.enabled: false`），整个项目非常轻：三个纯 Python 包，内存 300MB 以内。

---

## 六、桌面悬浮窗（可选，仅 Windows）

把「今日待办」做成桌面上的一块玻璃小窗：贴边吸附、可收起成球、卡片可以点掉。
**这是 Windows 独占功能**——macOS / Linux 上采集、报告、控制台都能用，只有这块不行。

### 启动

```bash
python tools/desktop_widget.py            # 有控制台，能看到日志
python tools/desktop_widget.py --demo     # 还没生成过卡片时，用示例数据看效果
```

Windows 也可以直接双击项目根目录的 `启动悬浮窗.bat`（会同时拉起数据守护进程）。
窗口卡住/不见了双击 `重启悬浮窗.bat`（先关旧的再拉新的）。

#### 这个窗口不会自己消失

- **不会因为鼠标移开而自动收起**（以前会，害得人天天找卡片）。想收起请点面板右上角的「∨」。
- **崩溃或被结束会自动回来**：数据守护进程每 60 秒看一眼窗口在不在，不在就拉起来。
  崩溃栈会写到 `%LOCALAPPDATA%\WeChatWorkHub\crash.log`。
- **开机自启**：注册表 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 下有两项
  `WeChatWorkHubDaemon` / `WeChatWorkHubWidget`，登录即起。
- **bat 只认装了依赖的 Python**：`tools\找Python.bat` 会逐个候选执行
  `import PIL,requests,yaml,bs4`，不合格就换下一个。以前只看 `python -V`，
  抓到 WorkBuddy 自带的 3.13（没有 Pillow）就会「窗口一闪就没了」。

### 三个形态

| 形态 | 尺寸 | 怎么进入 |
| --- | --- | --- |
| 展开 | 482 × 780 | 启动默认形态；点玻璃球也能回来 |
| 玻璃球 | 68 × 68 | 点面板右上角的「∨」 |
| 贴边细条 | 10 × 168 | 仅 `--mode sliver` 快照用，日常不再自动进入 |

### 先有数据才好看

卡片来自 `%LOCALAPPDATA%\WeChatWorkHub\cards.json`，它由下面任一步生成：

```bash
python tools/make_daily_cards.py     # 只重算卡片（免费，不调模型）
python tools/daily_job.py            # 刷新数据 + 出报告 + 写卡片（会调模型）
```

没有这个文件时会自动回落到示例数据，但**建议先跑一次真实数据**，否则看到的不是你的任务。

### 依赖与限制（重要）

| 项 | 说明 |
| --- | --- |
| **Pillow** | 必需，`pip install -e .` 已经包含 |
| **仅 Windows 10 / 11** | 依赖 Win32 分层窗口 + GDI 抓屏 + DWM，其他系统会直接提示不支持 |
| **DPI 缩放** | 100% 已验证；**125% / 150% 未做真机验证**，若出现错位请反馈 |
| **Win11** | 代码保留了 Acrylic 分支，但**未在 Win11 实测** |
| **背景是快照** | 玻璃背后是抓屏后模糊的图，不是实时渲染。盖在正在播放的视频上会露馅，这时把它收成球即可 |
| **对壁纸敏感** | 深色壁纸效果最好；纯白背景下面板会自动压深，否则白字看不清 |

### 开机自启（可选）

把下面内容的 `.bat` 放进启动文件夹：
`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\`

```bat
@echo off
cd /d "你的项目路径"
start "" pythonw.exe "tools\auto_daemon.py"
start "" pythonw.exe "tools\desktop_widget.py"
```

`auto_daemon.py` 是数据守护：每 10 分钟查一次微信有没有新消息，有就自动出报告、更新卡片。
**查询本身不花钱**，只有真的生成报告才调模型。

### 遇到问题先自检

```bash
python tools/doctor.py
```

会逐项检查依赖、配置、数据源、字体、平台支持，并告诉你缺什么。

---

## 七、模型配置（重点）

### 6.1 你的 Key 不会跟着仓库走

- 密钥只从 `.env` 读取，`.env` 已在 `.gitignore` 中；
- 代码中没有硬编码密钥，仓库里只有空模板 `.env.example`；
- 每个人的 Key 只存在他自己的机器上。

### 6.2 两种模式，不配 Key 也能用

| 模式 | 触发条件 | 行为 | 费用 |
| --- | --- | --- | --- |
| `file_output`（默认兜底） | 不填任何 Key | 生成结构化提示词文件，你复制到任意 AI 对话框即可 | 0 |
| `deepseek` / `openai` / `doubao` | 填 Key + Base URL + Model | 直接调用 API，自动写入报告 | 按 token 计费 |

配置了在线模式但**没填 Key** 时，程序打印一行警告后自动回落到 `file_output`，**不会报错中断**。

### 6.3 图形界面配置（推荐，不用手改文件）

打开控制台，点右上角的「模型」按钮：选服务商 → 粘贴 Key → 点「测试连接」→ 通了点「保存」。全程不需要打开 `.env`，也不用手工核对地址和模型名。

这个面板实际做了三件事：

- **自动填地址**：选了 DeepSeek，Base URL 和模型名自动填好，你只需要粘一个 Key；
- **真的测一次**：测试连接会发一个真实请求（`max_tokens=8`，成本可忽略），当场告诉你 Key 有没有效、地址通不通、模型名存不存在；
- **保存即生效**：不需要重启服务，下次生成报告就用新配置。

右上角「模型」旁边的小圆点表示当前状态：**绿点 = 在线模型已就绪，灰点 = 离线模式**。

测试失败时面板直接给中文原因，比如「Key 无效或已失效」「地址或模型不存在，检查是否需要带 /v1」「连接超时」，不用去翻日志。

### 6.4 支持的模型服务

请求走 OpenAI 兼容协议（`POST {base_url}/chat/completions`），所以下列服务都能直接接：

| 服务 | `BASE_URL` | `MODEL` 示例 |
| --- | --- | --- |
| DeepSeek（默认） | `https://api.deepseek.com` | `deepseek-chat` |
| 火山方舟 / 豆包 | `https://ark.cn-beijing.volces.com/api/v3` | 推理接入点 ID `ep-xxxxxx` |
| 月之暗面 Kimi | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` |
| 阿里通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-plus` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| Ollama（本地） | `http://127.0.0.1:11434/v1` | `qwen2.5:7b` |
| LM Studio（本地） | `http://127.0.0.1:1234/v1` | 你加载的模型名 |
| one-api / new-api 中转 | 你的中转地址 `/v1` | 中转内配置的模型名 |

### 6.5 配置示例

**DeepSeek**

```ini
DEEPSEEK_API_KEY=sk-xxxxxxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_TEXT_MODEL=deepseek-chat
```

**Kimi**

```ini
DEEPSEEK_API_KEY=sk-xxxxxxxx
DEEPSEEK_BASE_URL=https://api.moonshot.cn/v1
DEEPSEEK_TEXT_MODEL=moonshot-v1-8k
```

变量名统一用 `DEEPSEEK_*` 是历史原因，实际含义是「文本模型」，填别家的 Key 也一样生效。也支持 `OPENAI_API_KEY` / `DOUBAO_API_KEY` 同义写法。

**Ollama（本地，注意这个坑）**

```ini
DEEPSEEK_API_KEY=ollama
DEEPSEEK_BASE_URL=http://127.0.0.1:11434/v1
DEEPSEEK_TEXT_MODEL=qwen2.5:7b
```

Ollama 本身不校验 Key，但程序以「Key 是否为空」判断在线模式是否可用，所以这里必须填一个非空占位值（内容随意），否则会被判定为不可用而回落离线模式。

### 6.6 图片理解

```yaml
# config/settings.yaml
vision:
  provider: "dummy"        # dummy = 占位符「图片」；doubao = 火山方舟视觉模型
  model: "doubao-vision-pro"
  max_images: 20           # 单次最多处理多少张，防止额度被打爆
```

用 `doubao` 时需额外配置 `DOUBAO_API_KEY`（与文本模型可以是同一把，取决于你在方舟开通的模型）。

---

## 八、使用方式

### 本地控制台

```bash
python main.py --serve        # http://127.0.0.1:5710
```

可以选群、选日期、点按钮跑任务、查看历史报告、设置关注名单、置顶常用群。控制台用 Python 标准库 `http.server` 实现，**零额外 Web 依赖**，且只监听 `127.0.0.1`。

### 桌面窗口

```bash
python app.py        # 用 PyWebView 打开原生窗口，缺依赖时降级为浏览器
```

打包成 exe：双击 `build_exe.bat`（需 `pip install -e ".[desktop,build]"`）。

### 命令行

| 参数 | 说明 |
| --- | --- |
| `--group / -g` | 目标群名，需与微信中显示的一致 |
| `--date / -d` | `2026-11-14` / `today` / `yesterday`，默认今天 |
| `--leaders-only` | 只让重点关注的人进入总结 |
| `--model` | `file_output`（离线）/ `deepseek` / `doubao` |
| `--template` | 模板名，对应 `config/prompts/*.md` |
| `--format / -f` | `markdown` / `html` / `both` / `none` |
| `--no-chat` | 报告里不附聊天全文 |
| `--dry-run` | 跑通链路但不落盘 |
| `--open` | 生成后自动打开 HTML |
| `--list-groups` | 列出可读的全部群 |
| `--serve` | 启动控制台 |
| `--verbose` | 输出 DEBUG 日志 |

---

## 九、配置说明

### `config/groups.yaml`

完整字段见 `config/groups.example.yaml`。真实配置文件已被 git 忽略，请勿提交。

```yaml
target_groups:
  - name: "XX项目工作群"
    enabled: true
    pinned: true          # 控制台置顶
    leaders:              # 命中后打 [领导] 标记
      - name: "张总"
        id: "wxid_xxxxxxxx"
global_leaders:           # 跨群统一关注的人
  - name: "陈总"
```

命中规则：`id` 与 `name` 任一匹配即算命中，`id` 优先。

### `config/settings.yaml`

所有参数都有默认值，缺 key 不会崩。

| 区块 | 关键项 |
| --- | --- |
| `chatlog` | `decrypted_dir`（也可用 `.env` 的 `WX_DECRYPTED_DIR`）/ `timeout` / `page_size` |
| `asr` | `enabled` / `model`（`tiny`~`large-v3`）/ `device` / `compute_type` / `language` |
| `vision` | `provider`（`dummy`/`doubao`）/ `model` / `max_images` |
| `article` | `enabled` / `timeout` / `max_chars` |
| `summarizer` | `provider` / `prompt_template` / `model` / `max_input_chars` |
| `output` | `dir` / `format` / `html_theme` |
| `web` | `host` / `port` / `open_browser` |

---

## 十、目录结构

```
wechat-work-hub/
├── main.py                 # CLI 入口
├── app.py                  # 桌面窗口入口
├── collector/              # 数据源：SQLite 直读 + 统一消息模型
│   ├── sqlite_client.py
│   └── models.py
├── processor/              # 语音转写 / 图片描述 / 公众号正文 / 消息合并
├── summarizer/             # 总结后端：file_output（离线）/ OpenAI 兼容（在线）
├── output/                 # Markdown 报告 / HTML 报告 / 轻量 Markdown 渲染器
├── core/                   # 配置、日志、流水线编排、自动刷新
├── web/                    # 本地控制台（标准库实现，零框架前端）
├── config/                 # groups.yaml / settings.yaml / prompts/
├── tools/                  # 冒烟测试、演示站构建、分享版生成
├── demo-site/              # 纯静态演示站（mock 数据，可直接打开）
├── tests/                  # 回归测试（纯 unittest）
└── runs/  logs/            # 产物与日志（已 git 忽略）
```

`core/` 与 `web/` 是在基础骨架上额外抽出的两个包：前者避免 CLI 与控制台重复实现业务流程，后者保证控制台可以随时删除而不影响命令行。

---

## 十一、容错设计

「任何单条消息处理失败都不应中断整批任务」是硬约束：

| 情况 | 行为 |
| --- | --- |
| 单条消息加工异常 | 标记 `[处理失败]` 并记录原因，整批继续 |
| 未装 faster-whisper | 语音降级为占位，只警告一次 |
| 未装 beautifulsoup4 | 公众号正文改用正则抽取 |
| 公众号反爬 / 超时 | 降级为「标题 + 链接」 |
| 缺模型 Key | 自动回落离线模式 |
| 数据库不可读 | 明确提示检查解密目录 |
| 磁盘不可写 | 日志降级为仅控制台 |
| 媒体下载中断 | 先写 `.part` 再原子改名，不留坏缓存 |
| 重复点击生成 | 返回 409 并接入正在运行的任务进度 |
| 任务挂死 | 15 分钟软超时，前端标记超时 |
| 无法解析的日期 | 明确报错并列出可用格式，不静默当作今天 |

---

## 十二、测试

```bash
# 回归测试，纯标准库，不需要 pytest
python tests/test_regression.py

# 链路冒烟（会跑通采集→处理→输出）
python tools/smoke_chain.py

# 控制台集成校验（需先 python main.py --serve）
python tests/test_server.py
```

回归用例覆盖了真实踩过的边界：跨年/月末/闰日的 `yesterday` 计算、报告标题重复、共享配置被写脏、下载中断留下坏缓存、任务注册表无限膨胀等。

---

## 十三、常见问题

> 装不上、跑不通、报错看不懂，先看 **[docs/部署与排错-AI版.md](docs/部署与排错-AI版.md)**：
> 30 条「现象 → 根因 → 处理 → 复验」的故障字典，写给人和 AI 都能直接照着做。
> 想快速判断这台机器行不行：`python tools\doctor.py`（加 `--json` 给 AI 解析）。

**Q：跑出来是空的 / 提示找不到数据库？**
先确认三件事：微信 PC 版已登录、解密工具已成功执行、`.env` 的 `WX_DECRYPTED_DIR` 指向的目录里确实有 `*.db` 文件。

**Q：昨天的消息缺失？**
微信不补采离线消息。电脑关机或未登录期间的消息，微信服务器上的副本不会自动同步到本地库。需要先在手机/电脑端把聊天窗口翻一遍触发同步。

**Q：语音全是 `[语音]`？**
没装 `faster-whisper`（`pip install -e ".[asr]"`），或 SILK 转码失败（需要 ffmpeg）。

**Q：图片只显示「图片」两个字？**
默认 `vision.provider=dummy`。要识图请配豆包视觉模型，或接受占位符。

**Q：能不能在 Mac / 手机上跑？**
不能。数据源依赖 Windows 微信本地库。手机端无法读取其他 App 的数据库。

**Q：能不能部署到服务器上共享给多人用？**
不建议。控制台没有鉴权设计，且解密数据属于个人隐私。如需多人使用，请自行加反向代理与认证，并确保符合当地法规。

---

## 十四、许可与免责

**使用前请阅读 [DISCLAIMER.md](DISCLAIMER.md)。** 简要说明：

- 本工具只能用于处理**你自己合法持有并有权处理**的聊天数据；
- 采集、分析、传播他人聊天内容可能违反《个人信息保护法》等法律法规及微信服务协议，责任由使用者承担；
- 大模型输出可能包含错误，不构成任何专业建议；
- 使用在线模型产生的 API 费用由使用者自行承担；
- 软件按「现状」提供，作者不对数据丢失、决策损失、账号风险等后果负责。

### 许可协议：[PolyForm Noncommercial 1.0.0](LICENSE)

一句话：**免费用，随便改，就是不能卖。**

| 你可以 | 你不可以 |
| --- | --- |
| 下载、安装、使用，个人 / 学习 / 课程 / 竞赛 / 社团都行 | **商业使用**（出售、打包进收费产品、做付费服务） |
| **修改代码**，二次开发、加功能、改界面都可以 | **去掉或篡改作者署名** |
| **把改过的版本再分发**（必须连同本协议与署名一起） | 用作者名义做背书或承诺 |
| 在论文、作业、汇报中引用，注明来源 | |

几件需要说明的事：

1. **这不是 OSI 开源协议**，因为它限制了商业用途，所以 GitHub 不会给它打 Open Source 标签。但对个人使用者来说，上面的自由度和 MIT 几乎没差别。
2. **署名靠协议里的 `Required Notice` 行保住**：`LICENSE` 开头写了 `Required Notice: Copyright 2026 Hello18362`。协议要求任何分发者都必须把这行和协议原文一起带上——别人可以改你的代码，但改完发出去，作者仍然是你。
3. **想商用怎么办**：需要单独获得作者书面授权。没有授权就商用，属于违反许可协议。
4. 这个项目**接受 Pull Request**（因为协议允许修改），但请先看 [CONTRIBUTING.md](CONTRIBUTING.md) 里关于「不要提交真实聊天数据」的那条。

安全相关问题请按 [SECURITY.md](SECURITY.md) 私下报告。
