# 一键部署：给 AI 的操作手册

> **这份文件的读者是 AI（或照做的命令行老手），不是人。**
> 人类只需要做三件事：① 建一个 DeepSeek API Key；② 把 Key 交给你；③ （可选）授权你读自己的微信记录。
> 其余——建虚拟环境、装依赖、写配置文件、起服务、跑验收——全部由你完成，并且每一步都要**看到期望输出**才算这一步过了。
>
> 本文所有命令、输出、耗时都在 Windows 11 + Python 3.11 上实测过（2026-11-23）。
> 遇到本文没写的问题：查 `docs/部署与排错-AI版.md` 第 5 节（32 条故障字典）。**不要靠猜。**
>
> 整套项目的前提：这是**本地工具**，不需要服务器、不需要域名、不需要数据库。它读本机数据，在本机出报告。

---

## 0. 一分钟判断这份文档能不能用

| 机器情况 | 能不能按本文装 | 走哪节 |
|---|---|---|
| Windows 10/11，能装 Python | ✅ 标准路径 | 第 3 节 |
| Windows，装不了/不想装 Python | ⚠️ 只能跑打包版（暂未发布） | 第 9.1 节 |
| macOS / Linux | ⚠️ 核心链路能跑，悬浮窗和 .bat 不能 | 第 9.2 节 |
| 公司电脑、有杀软/无管理员 | ⚠️ 多半会被拦 | 第 9.3 节 |
| 想接自己真实微信记录 | ✅ 但多两步 | 第 6 节 |

---

## 1. 你的角色与硬约束

**你可以做**：创建/修改项目里的文件、建 `.venv`、装依赖、写 `.env`、起停本项目的进程、跑测试、截屏验证。

**你必须做**：
- 每条命令都要看输出，按本文的「通过标准」核对，不看输出不算完成。
- 失败先查第 5 节的症状表，再查 `docs/部署与排错-AI版.md` 第 5 节；**不要靠改代码绕过**。
- 每个阶段结束贴一次真实输出（用户在看着）。

**你绝对不能做**：
- `taskkill /IM python.exe /F`、`taskkill /IM pythonw.exe /F` —— 会杀掉用户其他 Python 程序（也可能是本项目的服务，但你看不出是哪个）。要停服务用 `tools\launch.py` 或按 5.4 精确定位 PID。
- `git push --force`、`git reset --hard`、删除 `.git`。
- 把 `.env`、`runs/`、`logs/`、`data/uploads/` 提交进 git（`.gitignore` 已覆盖，别去改它）。
- 用 `pip install` 往**全局** Python 里装本项目依赖；也不要用 `sudo`/管理员。
- 改 `config/settings.yaml` 里的 `chatlog.decrypted_dir` 写死路径——路径属于隐私，只能放 `.env` 的 `WX_DECRYPTED_DIR`。
- 让用户「自己去看文档第 X 节」。他要的是你装好。

---

## 2. 开工前只问三个问题（别多问）

1. **「你这台是 Windows 吗？」** 不是 → 第 9.2 节。
2. **「装了 Python 3.10 或更高版本吗？在命令行敲 `python -V` 会显示什么？」**
   - 显示 `Python 3.10/3.11/3.12.x` → 继续。
   - 显示 `Python 3.13.x` → 能装，但个别包可能没轮子，见 5.2。
   - 打不开、跳微软商店、提示不是内部命令 → 第 9.1 节。
3. **「要不要接你自己的微信聊天记录？」**
   - 不要 → 用**内置样例数据**，链路一样能跑通（推荐先这样验证）。
   - 要 → 装完主体后再按第 6 节补，别一上来就搞解密。

以及（唯一必须由人完成的动作）：**请用户去 https://platform.deepseek.com 建一个 API Key**，把 Key 给你。
用户问「不填行不行」→ 行，报告照样出，只是总结会降级成本地草稿（第 5.6 节）。但你要明确告诉他这个差别。

---

## 3. 五步装完（每步都有「通过标准」）

先把项目放到**纯英文、无空格**的路径下，例如 `D:\wwh`。
（路径里有中文/空格也能跑，但 ffmpeg、部分 Python 包会出玄学报错，见 5.10。能避就避。）

### 第 1 步：拿到代码

```bat
git clone https://github.com/Hello18362/wechat-work-hub.git D:\wwh
cd /d D:\wwh
```

**通过标准**：`dir` 里能看到 `main.py`、`tools\`、`config\`、`web\`、`README.md`。
**没有 git** → 让用户下载 ZIP 解压，效果一样。

### 第 2 步：一条命令装完（建 venv + 装依赖 + 生成 .env + 自检）

```bat
python tools\setup.py --yes
```

这一条命令做的事（幂等，重复跑不会坏）：

1. 检查 Python 版本（低于 3.10 直接报错停下）。
2. 没有 `.venv` 就建一个 `.venv`。
3. 在 `.venv` 里 `pip install -e .`（直连 PyPI 失败会自动换清华镜像）。
4. 没有 `.env` 就从 `.env.example` 复制一份。
5. 调 `tools/doctor.py --json` 做 23 项自检，把 FAIL 项连同修法打印出来。

**通过标准（原文照抄，一字不差）**：

```
[OK]  Python 3.11.x（...python.exe）
[OK]  虚拟环境已创建：D:\wwh\.venv\Scripts\python.exe
[OK]  依赖已装好
      已从 .env.example 生成 .env —— 这是**唯一需要人动手**的地方：
      自检结果：22 项，失败 0，提醒 3
[OK]  自检通过：没有硬问题
```

> 项数会变：全新机器 22 项；接了真实数据源会多出 `message_db` 等，最多 23 项。
> **唯一要盯的是「失败 0」**，项数不用对。

实测耗时：**25 秒**（首次，含建 venv 与下载依赖；第二次跑 2 秒内完成）。

- 看到「失败 1 或更多」→ 别往下走，按打印的「下一步」修，再重跑同一条命令。
- 之后**所有命令都用 `.venv\Scripts\python.exe`**，不要再用裸 `python`（裸 python 里没装依赖）。
  或者直接双击 `一键启动.bat`——它会自动优先用 `.venv`。

### 第 3 步：填 API Key（唯一的人工动作）

让用户把 Key 发给你，然后写进 `.env`：

```
DEEPSEEK_API_KEY=sk-xxxxxxxx
```

改完跑一次确认：

```bat
.venv\Scripts\python.exe tools\doctor.py --json
```

**通过标准**：`checks` 里 `id` 为 `model` 的那项 `"level": "OK"`，`counts.fail` 为 `0`。

> 没有 Key 就跳过这步。链路照样通，只是报告里的「总结」是本地草稿而不是模型写的。

### 第 4 步：起服务

```bat
.venv\Scripts\python.exe tools\launch.py --no-browser
```

**通过标准（原文）**：

```
项目目录：D:\wwh
使用的解释器：D:\wwh\.venv\Scripts\pythonw.exe
正在启动后台服务…
启动成功：http://127.0.0.1:5710
```

实测耗时 **2.7 秒**。它会：
- 杀掉监听这个端口的旧本项目进程（只杀监听者，不滥杀）；
- 起一个不带黑窗口的后台服务，日志写到 `logs\console.out`；
- 打印最终地址（如果你设了 `WEB_PORT`，地址会跟着变）。

**端口说明**：默认 5710。要换端口：

```bat
set WEB_PORT=5777
.venv\Scripts\python.exe tools\launch.py --no-browser
```
启动器、服务、`doctor` 三处都以 `WEB_PORT` 为准（优先级：`WEB_PORT` > `config\settings.yaml` > 5710）。

### 第 5 步：验收（这一步不过 = 没装好，不许说成功）

按顺序跑四条，每条都要贴真实输出。

**5.1 健康检查**

```bat
curl http://127.0.0.1:5710/health
```
期望：`{"status": "ok", "version": "0.2.0", "uptime_seconds": 5, "root": "D:\\wwh"}`
关键点：`status` 必须是 `ok`；`root` 必须**就是你现在这个目录**（不是别的副本）。

**5.2 数据源状态**

```bat
curl http://127.0.0.1:5710/api/status
```
期望含 `"source_mode": "sample"`（没接真实微信时）或 `"sqlite"`（接了），且 `"chatlog_online": true`。
`source_mode` 是 `"sample"` **不是错误**——它表示「没配真实数据源，用内置虚样例在跑」，见第 5.5 节。

**5.3 全链路自检（前端资源 + 每个接口 + 数据规模）**

```bat
.venv\Scripts\python.exe tools\smoke_chain.py --url http://127.0.0.1:5710
```
期望结尾：

```
  总计 28 项，通过 25，失败 0，跳过 3
  跳过项（不算失败）：
    - 好友总数 > 0 当前数据源没有联系人（样例数据，或没配 WX_DECRYPTED_DIR）
```
关键点：**失败必须是 0**。SKIP 是正常的（样例数据没有联系人）。

**5.4 真跑一次出报告**

```bat
.venv\Scripts\python.exe main.py --group "XX项目工作群" --date 2026-10-27 -f both --no-progress
```
期望结尾：

```
  Markdown  D:\wwh\runs\2026-10-27_XX项目工作群.md
  HTML      D:\wwh\runs\2026-10-27_XX项目工作群.html
```
实测 2.6 秒，产出 `.md`（约 1.1 KB）+ `.html`（约 37 KB）。
`runs\` 里出现这两个文件 = **链路真的通了**（这是最硬的一条证据）。

四条全过 → 才算部署成功，才能向用户说「好了」。

---

## 4. 硬验收清单（复制进你的汇报里，逐条打勾）

| # | 命令 | 通过标准 | 不过跳转 |
|---|---|---|---|
| 1 | `tools\setup.py --yes` | 末行「自检通过：没有硬问题」 | 5.2 / 5.10 |
| 2 | `curl /health` | `status":"ok"` 且 `root` 是本目录 | 5.3 / 5.4 |
| 3 | `smoke_chain.py` | `失败 0` | 5.5 / 5.8 |
| 4 | `main.py --group ... -f both` | `runs\` 里出现 .md + .html | 5.6 / 5.7 |
| 5 | 打开 `http://127.0.0.1:5710` | 页面正常、右上角状态点是绿的 | 5.4 / 5.5 |

---

## 5. 故障决策树（按症状查，别按猜查）

### 5.1 `python` 不是内部或外部命令 / 打开微软商店

没装 Python，或装的是微软商店的「假 python」。
- 装官方 Python 3.11 或 3.12：https://www.python.org/downloads/windows/ ，安装时**勾选「Add python.exe to PATH」**。
- 装完**必须新开一个命令行窗口**（旧窗口不会刷新 PATH）。
- 验证：`python -V` 显示 `Python 3.11.x`。

### 5.2 `pip install` 失败

| 报错片段 | 原因 | 修法 |
|---|---|---|
| `Could not find a version that satisfies` | 网络到 PyPI 不通 | `python tools\setup.py --yes` 会自动换清华源；还不行用 `-i https://pypi.tuna.tsinghua.edu.cn/simple` |
| `error: Microsoft Visual C++ 14.0 is required` | 没有编译环境 | 换 3.11/3.12（有预编译轮子），别用 3.13 |
| `No matching distribution found for zstandard` | 同上 / 平台不匹配 | 同上 |
| `Read timed out` | 慢 | 重跑一次（pip 有缓存），或换镜像 |

装完必须复验：`.venv\Scripts\python.exe -c "import requests, yaml, bs4, PIL, zstandard"` 无输出 = 成功。

### 5.3 「启动超时」

**先看 `logs\console.out` 最后 20 行**，九成情况服务其实起来了，只是启动器探错了端口。
- 日志里有「本地控制台已就绪：http://127.0.0.1:XXXX」→ 直接访问那个地址。启动器新版会自己识别并打印「服务已就绪（按服务日志判断）」。
- 端口对不上：`echo %WEB_PORT%` 看看有没有残留的旧环境变量；或显式 `set WEB_PORT=5710`。
- 真的没起来：看 `logs\console.out` 里的 `Traceback`，按报错去 5.2 或 5.10。

### 5.4 页面能开但是旧界面 / 某个接口 404

**服务进程还是旧的**（改了 `.py` 没重启）。这是本项目历史上最高频的假 bug。
```bat
.venv\Scripts\python.exe tools\launch.py --no-browser
```
它会先停掉旧进程再起新的。之后刷新浏览器（`Ctrl+F5`）。
如果 `/health` 返回的 `root` 不是当前目录 → 5710 上跑的是**另一个副本**，按 5.3 换端口。

### 5.5 状态点红 / 群列表空 / 报告空了

先看 `/api/status` 的 `source_mode`：

| source_mode | 含义 | 是否正常 |
|---|---|---|
| `sample` | 没配真实数据源，用内置虚样例 | **正常**（首次就该是这个） |
| `sqlite` | 读本机解密后的微信库 | 正常 |
| `chatlog` | 读 chatlog HTTP 服务 | 正常 |

- `sample` 但你想接真实数据 → 第 6 节。
- 配了解密目录却显示 `sample` → 目录不存在或库文件不对，见 5.7。
- 群列表空但 `health` ok → 解密库里那天没消息，换个日期（CLI 加 `--date 2026-10-27` 试样例群）。

### 5.6 报告里的「总结」像待处理清单 / 全是占位符

没配 Key，走了本地降级。这不是 bug。
- 要真总结：第 3 步填 `DEEPSEEK_API_KEY`，重启服务，重跑报告。
- 配了 Key 还是降级：`.env` 里 Key 有空格/引号；或 `settings.yaml` 的 `summarizer.provider` 不是 `deepseek`。跑 `tools\test_model_api.py` 单独验 Key。

### 5.7 配了解密目录但读不到消息

1. 目录里应该有 `message\message_0.db` 这类文件：`dir "你的目录\message"`。
2. `.env` 里路径用**正斜杠**或双反斜杠：`WX_DECRYPTED_DIR=C:/siwx/output/wxid_abc`。
3. 微信客户端升级过 → 老的解密库失效，需要重新解密（见第 6 节）。
4. 跑 `tools\doctor.py` 看 `datasource` 那项的具体说明。

### 5.8 语音全是 `[语音]` / 图片不识别

- 语音：需要 `ffmpeg` 在 PATH 里，且 `settings.yaml` 的 `asr.model` 是 `small`（`large-v3` 在普通 CPU 上慢到不可用）。
- 图片：`settings.yaml` 的 `vision.provider` 是 `dummy` 时不识图（这是默认，为了不烧钱）。要识图改成 `doubao` 并配 `DOUBAO_API_KEY`。
- 两者都**不影响主链路**：媒体处理失败会降级成占位文本，其余消息照常出报告。

### 5.9 悬浮窗相关

| 症状 | 原因 | 修法 |
|---|---|---|
| 双击没反应/闪退 | 缺依赖或另一个实例在跑 | `python tools\desktop_widget.py --demo` 前台跑，看报错 |
| 窗口在屏幕外找不回来 | 位置存坏了 | `python tools\start_widget.py --restart`（会自动夹回屏内） |
| 点了没反应 | 动画卡死（已修，若复现） | 看 `%LOCALAPPDATA%\WeChatWorkHub\widget.log` 有无 `[自愈]` 行 |
| 卡片不更新 | 守护最小间隔 60 分钟 | 右键菜单 →「立即更新消息」 |

### 5.10 路径含中文/空格、OneDrive、无管理员

- OneDrive 同步目录会让文件被锁、venv 被反复重写 → 换到 `D:\wwh`。
- 路径带空格时，所有命令里的路径都要加引号。
- 无管理员权限：不要试图装到 `C:\Program Files`；装用户目录（默认就是这样）。

---

## 6. 想接自己的微信记录（可选，且需要用户知情同意）

这一步**必须由用户自己决定**，你只能按他给的路径配置，不能自己去找他的微信数据。

1. 用户在自己电脑上用解密工具（例如 SIWX）导出**已解密**的 SQLite 目录，形如 `...\output\wxid_xxx\`。
2. 写进 `.env`（不要写进 `settings.yaml`）：
   ```
   WX_DECRYPTED_DIR=C:/siwx/output/wxid_xxx
   WX_SIWX_RUN=C:/siwx/run.py            # 可选：想自动刷新时填
   WX_PYTHON=C:/.../Python311/python.exe # 可选：跑解密工具用的解释器
   ```
3. 验证：
   ```bat
   .venv\Scripts\python.exe tools\doctor.py
   .venv\Scripts\python.exe main.py --list-groups
   ```
   能列出真实群名 = 通了。
4. 自动刷新（可选）：`python tools\refresh_data.py`。它需要解密工具自己的依赖（`psutil`、`pycryptodome`），
   缺了会打印一条明确的修法；按那条命令装到**系统 Python**（不是 `.venv`），或直接设 `WX_PYTHON`。

**注意**：解密工具不在本项目里，也不随本项目分发。这一步的合规责任在使用者。

---

## 7. 汇报模板（装完照这个说，别自由发挥）

```
部署完成，实测结果：

1. 环境：Windows 11 / Python 3.11.9 / 项目目录 D:\wwh
2. 安装：python tools\setup.py --yes → 25 秒，「自检通过：没有硬问题」（失败 0，提醒 3）
3. 服务：http://127.0.0.1:5710 已启动，/health 返回 ok，root 指向 D:\wwh
4. 数据源：sample（内置样例数据，2 个虚拟群）—— 还没接你的微信记录
5. 链路自检：28 项，通过 25，失败 0，跳过 3（联系人相关，样例数据没有）
6. 出报告：runs\2026-10-27_XX项目工作群.md（1.1 KB）+ .html（37 KB）
7. 模型总结：未配置 Key，本次为本地草稿降级；填 .env 的 DEEPSEEK_API_KEY 后即为模型总结

你只需要做一件事：把 DeepSeek 的 Key 填进 .env（或发我，我填）。
想接真实微信记录的话告诉我，我按第 6 节配，需要你先解密导出一次。
```

---

## 8. 一页速查（命令卡）

```bat
:: 装（幂等）
python tools\setup.py --yes

:: 只体检
.venv\Scripts\python.exe tools\doctor.py            :: 人读
.venv\Scripts\python.exe tools\doctor.py --json     :: 机器读

:: 起 / 停
.venv\Scripts\python.exe tools\launch.py --no-browser
.venv\Scripts\python.exe tools\launch.py --no-browser --no-install   :: 缺依赖时不自动装，只报错

:: 验收
curl http://127.0.0.1:5710/health
curl http://127.0.0.1:5710/api/status
.venv\Scripts\python.exe tools\smoke_chain.py --url http://127.0.0.1:5710

:: 出报告
.venv\Scripts\python.exe main.py --list-groups
.venv\Scripts\python.exe main.py --group "XX项目工作群" --date 2026-10-27 -f both

:: 悬浮窗
.venv\Scripts\python.exe tools\start_widget.py
.venv\Scripts\python.exe tools\start_widget.py --restart
.venv\Scripts\python.exe tools\desktop_widget.py --demo            :: 前台跑，看报错

:: 数据
.venv\Scripts\python.exe tools\refresh_data.py      :: 重新解密并刷新（需要 WX_* 配置）
```

---

## 9. 特殊机器

### 9.1 没有 Python / 装不了 Python

当前没有发布免安装 exe。要么装 Python（推荐 3.11），要么暂时只用 `demo-site\index.html`
（静态演示页，双击就能看报告长什么样，但不能读真实数据、不能出新报告）。

### 9.2 macOS / Linux

核心链路（采集 adapter → 加工 → 总结 → 报告 + 控制台）可以跑：
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e .
python tools/setup.py --check
python tools/launch.py --no-browser
```
**不能跑**：`一键启动.bat` 等所有 `.bat`、桌面悬浮窗（依赖 Win32 API）、开机自启。
CI 已在 Ubuntu × Python 3.10/3.11 上跑通单元测试，说明核心代码跨平台。

### 9.3 公司电脑 / 杀软 / 无管理员

大概率卡在：pip 被代理拦、`.venv` 被实时防护锁、端口被策略封。
先跑 `tools\doctor.py`，它会把「写不进去」「端口不通」单独标出来。别硬改代码。

---

## 10. 用户直接复制给你（AI）的话

> 这个仓库是 https://github.com/Hello18362/wechat-work-hub 。
> 请严格按仓库里的 `docs/一键部署-给AI的操作手册.md` 把项目装好。
> 要求：第 4 节的五条硬验收全部通过，并把每条的真实输出贴给我。
> 你只负责装和环境；需要我做的事（建 API Key、决定要不要接微信记录）再问我。
> 装的过程中任何一步失败，先查那份手册第 5 节，不要自己改代码。