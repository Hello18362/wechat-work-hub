# WeChat Work Hub

本地优先的微信群聊多模态 AI 工作助手：从指定微信群采集消息，做语音转写 / 图片理解 / 公众号正文抓取，最后输出可直接用的工作任务清单。

**所有数据处理默认在本机完成，聊天记录不出本地。**

---

## 一、它解决什么

| 痛点 | 这个项目怎么做 |
| --- | --- |
| 领导在群里发语音布置任务，事后找不到 | 语音自动转文字，进文本流 |
| 群里刷了 300 条，分不清哪条有料 | 按「领导名单」打 `[领导]` 标记，可切换「只看重点」 |
| 截图 / 报表里的信息抓不住 | 图片生成一句话描述，和文字一起进上下文 |
| 转发的公众号文章懒得点开 | 自动抓正文，失败自动降级为链接＋标题 |
| 总结时还要手动复制粘贴 | 一键生成带完整提示词的待处理文件，或直接接在线模型 |

---

## 二、快速开始

> 本机已配置好环境，Windows 下**双击 `启动.bat`** 即可一键拉起控制台。
> 数据源走 SIWX 解密 + SQLite 直读（微信 4.x 唯一可用方案），无需提权、无需手动取密钥。

### 前置：刷新解密数据

数据源由 SIWX（stories-in-wx）完成「密钥提取 + 数据库解密」，本项目直读解密后的 SQLite 库。

```bash
# 刷新解密数据（密钥已缓存，几秒钟；启动.bat 会自动执行这一步）
python "C:/your-path/.workbuddy/binaries/siwx/run.py" auto

# 或直接双击「刷新数据.bat」
```

解密输出目录在 `config/settings.yaml` 的 `chatlog.decrypted_dir` 中配置，目录有效时自动走 SQLite 直读，无需手动切换。

### 跑一次

```bash
# 1) 依赖（本机已装好 requests + pyyaml）
pip install -e .          # 可选：语音转写 pip install -e ".[asr]"

# 2) 看看有哪些群，把群名填进 config/groups.yaml
python main.py --list-groups

# 3) 跑一次
python main.py --group "XX项目工作群"
```

产物落在 `runs/`：

```
runs/
├── 2026-10-22_XX项目工作群.md      # Markdown 报告
├── 2026-10-22_XX项目工作群.html    # HTML 报告（双击就能看）
└── pending/
    └── 20261022_143000_content.md  # 待处理内容（给 Codex / Claude Code 用）
```

### 本地可视化控制台

```bash
python main.py --serve        # 或双击 启动.bat
```

浏览器会自动打开 `http://127.0.0.1:5710`，可以选群、选日期、点按钮跑任务、翻阅历史报告。

> 控制台用 Python 标准库 `http.server` 实现，**不引入任何额外 Web 依赖**，且只监听 `127.0.0.1`。

---

## 三、命令行参数

| 参数 | 说明 |
| --- | --- |
| `--group / -g` | 目标群名（必须与 chatlog 里的群名一致） |
| `--date / -d` | `2026-10-22` / `today` / `yesterday`，默认今天 |
| `--leaders-only` | 只让领导发言进入总结 |
| `--model` | `file_output`（默认，离线）/ `doubao`（在线直连） |
| `--template` | prompt 模板名，对应 `config/prompts/*.md` |
| `--format / -f` | `markdown`（默认）/ `html` / `both` / `none` |
| `--no-chat` | 报告里不附带聊天记录全文 |
| `--dry-run` | 跑完链路但不落盘 |
| `--open` | 生成后自动打开 HTML 报告 |
| `--list-groups` | 列出 chatlog 里的全部群聊 |
| `--serve` | 启动本地控制台 |
| `--no-progress` / `--verbose` | 关闭进度条 / DEBUG 日志 |

---

## 四、目录结构

```
wechat-work-hub/
├── main.py                  # CLI 入口
├── pyproject.toml
├── config/
│   ├── groups.yaml          # 目标群 + 领导名单
│   ├── settings.yaml        # 所有可变参数
│   └── prompts/             # leader_brief / daily_digest / todo_list
├── collector/
│   ├── models.py            # 统一消息数据结构 Message
│   └── chatlog_client.py    # chatlog HTTP API 客户端
├── processor/
│   ├── voice_asr.py         # faster-whisper 语音转写
│   ├── image_vision.py      # 图片理解（VisionProvider 抽象 + 豆包 + dummy）
│   ├── article_fetch.py     # 公众号正文抓取
│   └── merge.py             # 消息合并成文本流
├── summarizer/
│   ├── base.py              # Summarizer 抽象基类
│   ├── file_output.py       # 离线模式：生成待处理文件（MVP 默认）
│   └── doubao_api.py        # 在线模式：直连火山方舟
├── output/
│   ├── markdown.py          # Markdown 报告
│   ├── html.py              # HTML 报告（重点打磨的视觉产物）
│   └── md_lite.py           # 极简 Markdown 渲染器
├── web/
│   ├── server.py            # 本地控制台后端（标准库实现）
│   └── assets/              # index.html / style.css / app.js
├── core/                    # 基础设施（见下方说明）
│   ├── config.py            # 配置 + .env 加载
│   ├── log.py               # 日志（控制台色带 + 文件滚动）
│   ├── stats.py             # 统计指标
│   └── pipeline.py          # 流水线编排（CLI 与控制台共用）
├── runs/                    # 产物
├── logs/                    # 日志
├── tests/                   # 回归测试（见「八、测试」）
│   ├── test_regression.py   # 纯 unittest，不需要 pytest
│   └── test_server.py       # 控制台集成校验（需先 --serve）
└── tools/
    └── demo_seed.py         # 生成演示用的合成数据报告
```

### 关于目录结构的两处增补

施工提示词给了标准骨架，本项目在上面对齐的前提下**新增了两个包**，原因如下：

- **`core/`** —— `main.py` 和 `web/server.py` 都需要加载配置、初始化日志、跑流水线。如果不抽出来，就会出现「把业务流程复制两份」或「从 `main.py` 里 import 业务函数」这两种都不理想的结果。
- **`web/`** —— 控制台不做则已，要做就不能是难看的。放在这里与 `core.pipeline` 解耦，随时可以删掉而不影响 CLI。

其余路径（`collector / processor / summarizer / output / config / runs / logs`）与施工提示词**逐条一致**。

---

## 五、配置说明

### `config/groups.yaml`

```yaml
target_groups:
  - name: "XX项目工作群"
    enabled: true
    leaders:
      - name: "张总"
        id: "wxid_xxxx"
global_leaders:              # 跨群都要关注的老板放这里
  - name: "陈总"
    id: ""
```

命中规则：`id` 与 `name` 任一匹配即算命中，`id` 优先。

### `config/settings.yaml`

全部参数都有默认值，缺任何一个 key 都不会崩：

| 区块 | 关键项 |
| --- | --- |
| `chatlog` | `api_base` / `timeout` / `page_size` / `max_pages` |
| `asr` | `enabled` / `model` / `device` / `compute_type` / `language` |
| `vision` | `provider`（`dummy` / `doubao`）/ `model` / `max_images` |
| `article` | `enabled` / `timeout` / `max_chars` / `retry` |
| `summarizer` | `provider`（`file_output` / `doubao`）/ `prompt_template` / `pending_dir` |
| `output` | `dir` / `format` / `html_theme` |
| `web` | `enabled` / `host` / `port` / `open_browser` |

密钥走 `.env`（复制 `.env.example` 改名即可）：

```
DOUBAO_API_KEY=...
DOUBAO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
```

**没配密钥也不会报错** —— `doubao` 模式会检测到缺密钥后自动回落到离线模式。

---

## 六、UI 是怎么做的

这部分参考了抖音博主「西瓜同学」「叨叨」系列的 UI 交互提示词（共 104 条），选了真正有用的落在两个产物上。

### HTML 报告（`output/html.py`）

| 提示词 | 落地 |
| --- | --- |
| 07 补充 · 大标题收缩吸顶 | 顶部导航随滚动收缩，背景毛玻璃渐显 |
| 07-4 · 大色块网格 | Hero 主数字块 + 四宫格副指标 |
| 04-15 · 动态弥散光晕 | 主卡缓慢旋转的渐变描边 |
| 04-7 · 数字缓停 | 统计数字 Odometer 式缓停计数 |
| 07-18 · 分类联动滚动 | 左侧目录随滚动高亮，点击滚动定位 |
| 03-11 · 物理弹簧交错弹入 | 聊天流逐条错峰入场（22ms 递增） |
| 05-9 · 未读分割线不位移 | 「领导发言」浮标吸顶但不推挤内容 |
| 01-8 · 卡片弹出详情 | 点击条目由原位放大为居中面板，原路收回 |
| 04-2 · 弹性开关 | 深色模式开关（滑块拉伸再回压） |
| 05-2 · Toast 柔和进场 | 复制操作反馈 |

### 本地控制台（`web/assets/`）

在报告的基础上额外实现了：按钮变进度条 `02-3`、点击位置扩散 `02-1`、滑动确认危险操作 `02-4`、删除二次确认 `02-6`、弹出菜单 `01-7`、日期日历 `01-14`、下拉展开面板 `01-13`、骨架屏流光 `03-12`、Toast 堆叠让位 `05-3` 与撤销进度条 `05-4`。

统一遵守两条硬约束：**动效 200–420ms、一律用 spring 曲线，不用 `linear`**；并完整支持 `prefers-reduced-motion`。

---

## 七、容错设计

施工提示词里「任何单条消息失败都不应中断整个流程」这条被严格执行：

| 情况 | 行为 |
| --- | --- |
| 单条消息加工异常 | 该条标记 `[处理失败]` 并写 note，整批继续 |
| 未装 faster-whisper | 语音降级为 `[语音]`，只警告一次 |
| 未装 beautifulsoup4 | 公众号正文改用内置正则抽取 |
| SILK 原始流 | 尝试 `asr.silk_decoder` → `ffmpeg` 转码，都失败则跳过该条 |
| 公众号反爬 / 超时 | 降级为「链接 + 标题」 |
| chatlog 服务不可达 | 明确提示并要求先启动服务 |
| 缺 `DOUBAO_API_KEY` | 自动回落到离线模式 |
| 磁盘不可写 | 日志降级到仅控制台输出 |
| chatlog 字段命名差异 | 多别名兼容读取（驼峰 / 下划线 / 中文类型名） |
| 控制台路径穿越请求 | 校验后返回 404 |
| 总结正文自带标题 | 渲染前剥离，避免出现两个「总结」标题 |
| 媒体下载中途断流 | 先写 `.part` 再原子改名，失败即清理，不留坏缓存 |
| 重复点击「生成报告」 | 返回 409，前端改为接入已在运行的任务进度 |
| 控制台任务挂死 | 15 分钟软超时，前端标记超时而非无限转圈 |
| 无法解析的日期 | 明确报错并列出可用格式，不静默 fallback 成今天 |
| chatlog v4 媒体 key 在 contents 里 | 从 `contents.md5` / `contents.voice` / `contents.url` 提取，不漏媒体 |

---

## 八、测试

两套测试都用标准库写成，不需要额外安装 pytest：

```bash
# 回归测试：25 个用例，覆盖曾经真实啃到人的边界
python tests/test_regression.py

# 控制台集成校验：需先在另一个终端起服务
python main.py --serve
python tests/test_server.py
```

`test_regression.py` 里每个用例都对应一个具体故障场景，防止回退：

| 用例 | 曾经的故障 |
| --- | --- |
| `test_yesterday_on_new_year_day` | 元旦跑 `--date yesterday` 直接 `ValueError` 崩溃 |
| `test_yesterday_on_first_day_of_month` | 每月 1 号跑 `yesterday` 返回的是当天本身 |
| `test_yesterday_after_leap_day` | 闰年 2 月末日期算错 |
| `test_markdown_has_single_summary_heading` | 报告里出现两个 `## 总结` 标题 |
| `test_html_has_single_summary_heading` | HTML 版同样重复渲染了一层标题 |
| `test_does_not_mutate_shared_config` | 控制台里换模板把共享配置写脏，之后所有运行串味 |
| `test_interrupted_download_leaves_no_corrupt_cache` | 下载中断留下残缺文件，之后一直命中这份坏缓存 |
| `test_evicts_oldest_finished_tasks` | 任务注册表回收算法写错，长期运行持续膨胀 |
| `test_soft_timeout_status` | 任务挂住时前端进度条永远停在 99% |

`test_server.py` 则校验运行中的服务：接口可用性、路径穿越拦截、畸形请求不打挂、
重复点击时的并发保护，以及**长连接是否真的复用**（一条 TCP 承载 25 次请求，
TIME_WAIT 不随请求量增长）。

---

## 九、MVP 验收对照

| # | 验收标准 | 状态 |
| --- | --- | --- |
| 1 | `python main.py --group "测试群"` 能跑 | ✅ |
| 2 | 能通过 chatlog API 拉到指定群消息 | ✅（含分页、字段兼容） |
| 3 | 文字消息原样保留 | ✅ |
| 4 | 语音能转写，没有语音文件时不报错 | ✅（缺失依赖时降级） |
| 5 | 图片标记 `[图片]`（dummy provider） | ✅ |
| 6 | 公众号能抓正文，抓不到降级为链接+标题 | ✅ |
| 7 | 输出写入 `runs/`，格式 Markdown | ✅（额外支持 HTML） |
| 8 | 领导发言标注 `[领导]` | ✅ |
| 9 | 所有异常有 try-catch，单条失败不崩整体 | ✅ |
| 10 | 日志清晰，能看到每一步在做什么 | ✅（控制台色带 + 文件滚动 + 进度条） |

---

## 十、免责声明

本项目仅供处理**你自己合法拥有的聊天数据**。请遵守当地法律法规，勿用于采集或分析他人隐私数据。
