# 部署与排错（AI 版）

> **这份文档写给谁**：写给「要在这台机器上把它装起来、跑通」的你——尤其是执行命令的 AI 助手。
> 目标很具体：**照着做，不需要反复试错**。每一步都有「验证命令」和「期望结果」，
> 对不上就直接跳到第 5 节的故障字典，那里按「现象」查，每条都给了根因和处理办法。
>
> 维护约定：这份文档里的**所有命令都实际跑过**，产物路径、字段名、报错原文都来自真实运行。
> 如果你照做踩到了新坑，请把「现象 + 完整报错 + 第 5 节该补哪条」写进 `docs/`，别只改代码。

---

## 0. 先用一分钟判断：这条链路到底通不通

有三个判据，**全部满足才算装好**。它们分别验证「进程起来了」「数据源有着落」「能产出报告」：

| 判据 | 命令 | 期望 |
| --- | --- | --- |
| ① 服务活着 | 浏览器打开 `http://127.0.0.1:5710/health` | `{"status": "ok", "version": "...", "uptime_seconds": ...}` |
| ② 数据源有着落 | 同上控制台右上角状态点 | 绿色：`数据源已就绪` 或 `内置样例数据（未配置真实数据源）` |
| ③ 能出报告 | `python main.py --group "XX项目工作群" --date 2026-10-27 -f both` | `runs/` 下出现同名的 `.md` 和 `.html` |

状态点是**红色**（`数据源未启动`）才算没装好；黄色/样例态是正常的首次体验状态，不是故障。

一键体检（推荐先跑这个，它会按上面的判据自己查，并给出下一步该敲什么）：

```bash
python tools/doctor.py          # 人看
python tools/doctor.py --json   # 给 AI 看（含每项 id / level / fix）
```

退出码 `0` = 没有阻塞项；`1` = 有 ❌ 必须先处理。**别用退出码判断「能不能用」**，要看 `ok` 字段和 ❌ 项。

---

## 1. 环境要求

| 项 | 硬要求 | 没有会怎样 |
| --- | --- | --- |
| 操作系统 | Windows 10 / 11 | Linux/mac 能用采集以外的全部功能，但**悬浮窗**和**微信解密**是 Windows 专属 |
| Python | 3.10+，推荐 **3.11** | 低于 3.10 直接跑不了；3.13 有依赖还没发轮子，容易装不上 |
| 网络 | 能访问 PyPI（国内建议换源） | `pip install` 卡住/超时 |
| 微信 PC 版 | **选配**，4.x，需登录 | 没有就用内置样例数据，链路照样全通 |
| 解密工具（SIWX 一类） | **选配** | 同上，样例数据可替代 |
| 大模型 Key | **选配** | 总结降级成「离线草稿」，报告照出，只是不是润色稿 |
| ffmpeg / faster-whisper | **选配** | 语音降级为 `[语音]` 占位 |

**这里有个认知差**：README 第 2 节写「能做什么」时列了微信，容易让人以为必须先有微信才能装。
**不是。** 只做完 `pip install -e .` 这一步，用仓库自带的 `data/samples/*.json`（虚构数据）就能跑完
「采集 → 加工 → 合并 → 总结 → 报告」整条链路。先跑通骨架，再接真数据。

---

## 2. 标准安装（5 步，逐步验证）

> 全程在一台**全新机器**上验证过（干净克隆 + 全新 venv + 非默认端口），总耗时约 1~3 分钟（pip 有缓存时十几秒）。
>
> **最快路径（推荐给第一次装的人）**：拿到代码后直接双击 `一键启动.bat`。它会自己找 Python、
> 建 `.venv`、装依赖、起服务、开浏览器。2026-11-23 实测：干净克隆 + 没有任何环境，**30 秒**到
> 「启动成功：http://127.0.0.1:××××」。
>
> 下面 5 步是「想知道每一步在干什么 / 双击失败要定位」时用的，两条路结果一样。

### 步骤 1：拿到代码

```bash
git clone https://github.com/Hello18362/wechat-work-hub.git
cd wechat-work-hub
```

没有 git 就下 zip 解压（GitHub 页面 Code → Download ZIP），效果一样。

**验证**：`ls` 能看到 `main.py`、`tools/`、`config/`、`data/samples/`。
**失败**：`git` 不存在 → 用 zip；`clone` 超时 → 见 5.28。

### 步骤 2：建虚拟环境（双击 bat 的用户可跳过）

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -U pip
```

> 双击 `一键启动.bat` 时这一步是**自动完成**的（没有 `.venv` 就当场建一个）。
> 下面手动敲的两行，是给命令行用户、或者想确认环境干净的人用的。

**为什么必须用 `.venv`**：这台机器上可能有好几个 Python（商店版 / conda / WorkBuddy 自带的 3.13）。
依赖装进 A，运行时用了 B，报错永远是 `ModuleNotFoundError`，而且看起来莫名其妙。
本项目所有 `.bat` 入口**已优先使用项目根目录的 `.venv`**，所以你把依赖装进 `.venv` 就是对的。

**验证**：`.venv\Scripts\python.exe -V` 打印 3.11.x。
**失败**：`python` 找不到 → 见 5.3；`venv` 创建失败 → 见 5.24。

### 步骤 3：装依赖（这一步会装 5 个包）

```bash
.venv\Scripts\python.exe -m pip install -e .
```

会装 `requests`、`PyYAML`、`beautifulsoup4`、`Pillow`、`zstandard`，并把本项目装成可编辑包（这样 `wgh` 命令可用）。

**验证**：

```bash
.venv\Scripts\python.exe -c "import requests,yaml,bs4,PIL,zstandard;print('deps ok')"
```

期望输出 `deps ok`。**失败**：见 5.1 / 5.2 / 5.28 / 5.29。

> 国内网络慢就换源：
> `.venv\Scripts\python.exe -m pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple`

### 步骤 4：起服务

两种方式，选一个：

```bash
# A. 双击（最省事；首次会自动建 .venv 并装依赖）
一键启动.bat

# B. 命令行（能看见日志，排错时用这个）
.venv\Scripts\python.exe tools\launch.py
```

`launch.py` 会做这些事：找配置端口 → 查依赖（缺了会问你要不要现在装，回车＝装）→
结束上一个占着端口的自己 → 后台起服务 → 轮询直到端口通 → 打印「启动成功」并开浏览器。

**验证**：

```bash
curl http://127.0.0.1:5710/health
```

期望 `{"status": "ok", ...}`。

**注意端口不是写死的**：实际端口取 `config/settings.yaml` 的 `web.port`（默认 5710），
也可以用环境变量 `WEB_PORT=5720` 覆盖。**所以永远以 `launch.py` 打印的地址为准**，
不要假设 5710。**失败**：见 5.2（「启动超时」是历史上最容易误判的一条）。

### 步骤 5：跑一份报告

```bash
.venv\Scripts\python.exe main.py --list-groups
.venv\Scripts\python.exe main.py --group "XX项目工作群" --date 2026-10-27 -f both
```

第一条列出有哪些群（没接真数据时就是两个样例群）。第二条出报告。

**验证**：`runs/` 目录里多出一份 `.md` 和一份 `.html`，打开 html 能看到任务卡、总结、聊天记录三个区块。

---

## 3. 四种「看起来坏了，其实正常」的状态

排错前先对照这张表，能省掉一半的无效折腾：

| 现象 | 为什么正常 |
| --- | --- |
| 状态点写「内置样例数据（未配置真实数据源）」 | 没接微信时的**设计行为**，不是错误。样例数据是虚构的，专门用来验证链路 |
| 报告总结部分像「待处理清单」而不是润色稿 | 没配大模型 Key，走的是**离线降级**。`runs/pending/` 里会存一份原文，可以手动交给任意 AI |
| `--list-groups` 只有 2~3 个群 | 样例模式就是这几个；接了真数据才会有你微信里的群 |
| 语音消息显示 `[语音]`、图片显示 `[图片]` | 没装 faster-whisper / 没开 vision，属于**降级占位**，不是失败 |
| 控制台里中文是方块/问号 | 终端编码不是 UTF-8，数据本身没问题。`chcp 65001` 或 `set PYTHONUTF8=1` |

---

## 4. 数据源：三态与怎么接真数据

程序按下面的顺序找数据源，**找到哪个用哪个**（`/api/status` 的 `source_mode` 会告诉你当前是哪个）：

| 顺序 | 条件 | `source_mode` | 说明 |
| --- | --- | --- | --- |
| 1 | `WX_DECRYPTED_DIR` 指向的目录里有 `message/message_0.db` | `sqlite` | 直读解密后的 SQLite，最完整（含语音/图片文件） |
| 2 | 本机 `127.0.0.1:5030` 有 chatlog 服务 | `chatlog` | 通过 HTTP 拉，需要外部工具在跑 |
| 3 | 以上都没有，且 `chatlog.fallback_sample` 不是 `false` | `sample` | 用仓库自带虚构样例 |

**接真实微信数据（Windows only）**：

1. 用你信任的解密工具，把本机微信数据库解出成一个目录（目录里应有 `message/message_0.db`）。
   **本仓库不内置、也不提供解密能力**，这是刻意的：解密属于使用者自己的操作，风险与合规责任在使用者。
2. 在项目根目录把 `.env.example` 复制成 `.env`，写一行：
   ```
   WX_DECRYPTED_DIR=D:\path\to\decrypted
   ```
3. `python tools/doctor.py` → 「数据源」应变成 ✅「解密库可用」，并显示最新消息时间。
4. `python main.py --list-groups` 应该列出你真实的群。

**注意**：配了 `decrypted_dir` 但目录无效时，程序**不会**偷偷回退到样例（会明确报错），
这是故意的——否则你会以为自己在看真实数据，其实在看虚构样例。

---

## 5. 故障字典

> 用法：`Ctrl+F` 搜你的**报错原文**或**现象关键词**。每条都给了「怎么确认是这个原因」，
> 别猜，先用判定命令证实，再动手。
>
> 目前 **32 条**。新加的 5.31（SIWX 缺 psutil 导致消息不更新）、5.32（卡片不更新的两种原因）来自
> 2026-11-23 的真实反馈。

### 5.1 `ModuleNotFoundError: No module named 'yaml'`（或 requests / bs4 / PIL）

**现象**：双击 bat 后窗口一闪而过，或 `启动超时`；`logs/console.out` 里是这行报错。
**根因**：跑起来的解释器不是装依赖的那个。最常见是「依赖装进了 `.venv`，但用的是系统 Python」，
或者根本没装依赖。
**判定**：

```bash
python tools/doctor.py --json
```

看 `dep_yaml` / `dep_requests` 是不是 ❌，以及 `venv` 那一项的 detail。

**处理**：

```bash
# 用项目 venv 装（推荐）
.venv\Scripts\python.exe -m pip install -e .

# 或者让启动器帮你装（它会先问一句，回车即装）
python tools\launch.py
```

**复验**：`python tools/doctor.py` 里 5 个 `依赖 *` 全绿。

---

### 5.2 「启动超时。请查看 logs/console.out 里的报错。」

**这是历史上最容易误判的一条**：服务其实已经起来了，是启动器探错了端口。

**判定**（先看日志，别急着重装）：

```bash
type logs\console.out
```

如果里面有 `本地控制台已就绪：http://127.0.0.1:57xx`，那就是端口不一致：

- 服务按 `config/settings.yaml` 的 `web.port` 监听（比如 5763）；
- 而启动器在**没装 PyYAML 时**读不到配置，退回默认 5710 去探 → 永远探不到。

**处理**：

1. 先把依赖装好（5.1），端口就能正确读出来；
2. 代码侧已修：`tools/launch.py` 在缺 yaml 时会**退回文本解析** `settings.yaml`，
   并且在超时前会读日志里的就绪地址，直接判定成功。所以**先 `git pull` 到最新**。
3. 还是不行就打开日志里那个真实端口，手动确认 `/health`。

**复验**：`python tools\launch.py --no-browser` 打印「启动成功：http://127.0.0.1:<你的端口>」。

---

### 5.3 双击 bat，窗口闪一下就没了 / 提示找不到 Python

**根因**：`python` 不在 PATH，且常见安装目录里没有。
**判定**：`where python` 与 `py -3 -V` 都没输出。
**处理**：

1. 装 Python 3.11，安装时**必须勾选** `Add Python to PATH`；
2. 或直接用完整路径跑：`C:\Users\<你>\AppData\Local\Programs\Python\Python311\python.exe tools\launch.py`；
3. 想看清闪退原因：`cmd` 里 `cd` 到项目目录再执行 bat，窗口就不会关。

---

### 5.4 控制台中文乱码 / `UnicodeEncodeError: 'gbk' codec can't encode character`

**根因**：中文 Windows 控制台默认 GBK，打印 `✓ ✗ →` 这类符号会炸。
**处理**：

- 代码侧已修：`main.py` 会检测编码，GBK 下自动降级成 `[OK]` / `[X]`，并给 stdout 加 `errors="replace"`；
- 临时手段：`set PYTHONUTF8=1` 再跑，或 `chcp 65001`。

**复验**：`python main.py --list-groups` 不再抛编码异常（乱码可能还在，那是终端显示问题，不影响数据）。

---

### 5.5 `wgh` 命令找不到 / `ModuleNotFoundError: No module named 'main'`

**根因**：`pyproject.toml` 的入口配置与打包发现不一致（历史 bug，已修：`py-modules = ["main"]`）。
**处理**：

```bash
.venv\Scripts\python.exe -m pip install -e .   # 重新装一次，生成 .venv\Scripts\wgh.exe
.venv\Scripts\wgh.exe --help
```

不想折腾就用等价命令：`python main.py ...`。**复验**：`wgh --help` 打印帮助。

---

### 5.6 端口被占用 / 启动器把我的 python 杀了

**必须知道的行为**：`tools/launch.py` 为了「重复双击不出两个服务」，会**结束正在监听该端口的 python 进程**。
如果你有别的 Python 服务恰好用同一个端口，它会被误杀。

**处理**：

- 换端口：改 `config/settings.yaml` 的 `web.port`，或临时 `set WEB_PORT=5720`；
- 查是谁占着：`netstat -ano | findstr :5710` 然后 `tasklist /FI "PID eq <pid>"`。

**别做**：不要用 `taskkill /IM python.exe /F` 这种一刀切，会杀掉你自己别的程序。

---

### 5.7 状态点是红色「数据源未启动」

**按顺序查**（这也是程序自己的查找顺序）：

1. `.env` 里 `WX_DECRYPTED_DIR` 有没有？指向的目录在不在？里面有没有 `message/message_0.db`？
2. 本机 5030 端口有没有 chatlog 服务在跑？
3. `data/samples/*.json` 在不在（`git checkout -- data/samples` 可恢复）？
4. `config/settings.yaml` 里 `chatlog.fallback_sample` 是不是被改成了 `false`？

`python tools/doctor.py` 的「数据源」一项会把结论直接写出来。

---

### 5.8 配了解密目录，但报「目录不存在 / 缺 message_0.db」

**根因**：解密没跑完，或者路径带了引号/空格/中文导致解析错。
**处理**：

- `.env` 里的路径**不要加引号**，用正斜杠或双反斜杠都行：`WX_DECRYPTED_DIR=D:/wx/decrypted`；
- 确认目录结构是 `<decrypted>/message/message_0.db`（少一层都不行）；
- 微信正在运行会锁库，先退出微信再解密。

---

### 5.9 微信升级后突然读不到消息

**根因**：微信 4.x 的数据库结构/加密方式随版本变，解密工具需要跟进。
**处理**：固定微信版本，或更新解密工具后重新解密。程序这边不需要改。
**判定**：`python tools/doctor.py` 的「消息数据库」显示「能打开但没读到消息」= 库是空的。

---

### 5.10 消息条数明显偏少 / 有些消息内容是空的

**根因**：微信新版本对消息体做了 zstd 压缩；**没有 `zstandard` 时解压失败会被静默跳过**，
表现就是「消息丢了」。
**处理**：`pip install -e .`（现在 `zstandard` 已经是必装依赖），然后 `python tools/doctor.py` 确认
`依赖 zstandard` 是 ✅。
**判定**：`python -c "import zstandard"` 成功；`logs/` 里有 `未安装 zstandard` 警告。

---

### 5.11 语音全是 `[语音]`

**原因链**：需要 `faster-whisper`（转写）+ `ffmpeg`（SILK 转码），缺一个就降级。
**处理**：

```bash
.venv\Scripts\python.exe -m pip install -e ".[asr]"
winget install Gyan.FFmpeg      # 或去 ffmpeg.org 下 Windows 版解压后加 PATH
```

首次转写会下载模型（几百 MB），**第一次慢是正常的**。

---

### 5.12 语音转写慢到没法用

**根因**：`config/settings.yaml` 的 `asr.model` 被设成了 `large-v3`。CPU 上跑 large 系列，
一段 30 秒语音要几十秒。
**处理**：改回 `small`（默认就是 small）或 `base`。没有 GPU 不要用 large。
**判定**：`python tools/doctor.py` 的「语音模型」一项会标 ⚠️。

---

### 5.13 图片不识别，只有「[图片]」

**根因**：`vision.provider` 是 `dummy`（默认），即「不调用视觉模型」。
**处理**：在 `config/settings.yaml` 里配 `vision.provider` 与对应 Key；或在控制台「模型设置」里配。
不配也能用，只是图片不参与总结。

---

### 5.14 总结像是「待处理清单」，不像 AI 写的

**根因**：没有可用的大模型 Key，走了**离线降级**：程序把提示词和原文写到 `runs/pending/`，
等你手动交给任意 AI。这不是 bug。
**处理**：`.env` 里配 `DEEPSEEK_API_KEY`（或豆包/OpenAI 兼容的 key），重启服务。

---

### 5.15 配了 Key 但报 401 / 超时 / 连不上

**判定顺序**：

1. Key 是不是复制少了字符（前后空格、换行）；
2. `DEEPSEEK_BASE_URL` 是否与 Key 匹配的服务商（换服务商要一起换 base_url）；
3. 公司网络/代理是否拦了 `api.deepseek.com`；浏览器能打开不代表 Python 能（代理变量 `HTTP_PROXY`）；
4. 用 `python tools/test_model_api.py` 单独测，不要从整条链路倒推。

---

### 5.16 报告里出现本机绝对路径（`D:/.../runs/pending/...`）

**根因**：离线降级时，提示词里带上了待处理文件的绝对路径，被原样写进报告。
**处理**：这是**已知问题**，已记录在案；如果你看到，说明你用的是离线降级模式。
想要干净的报告就配 Key，或在 `runs/` 里手工替换该行。
（维护者注：`summarizer/file_output.py` 的 note 字段需要改成相对路径，属于待办。）

---

### 5.17 悬浮窗（桌面卡片）根本不出现

**按顺序查**：

1. **是不是已经有一个在跑**：悬浮窗有单实例互斥锁（`WeChatWorkHubWidget_SingleInstance`），
   第二个进程会**静默退出**。任务管理器里找 `pythonw.exe`，看命令行有没有 `desktop_widget.py`。
2. **崩溃日志**：`%LOCALAPPDATA%\WeChatWorkHub\crash.log`（没有这个文件＝没崩过）。
   运行日志：同目录 `widget.log`。
3. **手动前台启动看报错**（最关键的一步）：

```bash
.venv\Scripts\python.exe tools\desktop_widget.py
```

前台跑会把异常直接打出来。**别用 pythonw**，它把 stdout 丢了，你什么都看不见。

4. 缺 Pillow 会直接失败：`pip install -e .`。

**一键修**：

```bash
python tools\start_widget.py --restart
```

它会先杀掉旧窗口再拉起，并等窗口真的出现才返回（会打印「启动成功，窗口稳定」）。

---

### 5.18 悬浮窗跑到屏幕外面，看不见也点不到

**根因**：历史 bug——小球形态把「面板坐标」当成了「小球坐标」存盘，右吸边时被推到屏幕外。
（已修：可见区域换算后再夹取，并且启动时会做一次「不出屏」矫正。）

**处理**：

```bash
python tools\start_widget.py --restart
```

重启会按当前屏幕重新摆放。**如果重启后仍然不在屏内**，删掉状态文件再启：
`%LOCALAPPDATA%\WeChatWorkHub\widget.json`。

---

### 5.19 悬浮窗卡住：不展开、不收起、点不动

**根因（两层，都已修）**：
1. 帧定时器（`SetTimer`）在某些情况下**整条失效**，但没有任何异常日志。动画停在第一帧，
   `self.anim` 一直是「真」，于是后续所有交互都被「正在动画」挡回去。
2. 小球单击是「等 0.28 秒看有没有第二击」，这一步以前靠空闲定时器，定时器死了就永不执行。

**现在的做法**（不用定时器也能动）：
- 动画改成**内联帧循环**：`_animate()` 里同步跑完帧，中间 `win32.pump()` 把鼠标/窗口消息放出去；
- 小球单击改成**后台线程睡 0.30 秒后 `PostMessage(WM_APP_SELF)`**，由消息循环接手；
- 双保险：内置看门狗仍会在 1 秒内把没收尾的动画强制落到终态，并写一行 `[自愈]` 到 `widget.log`。

**判定**：`%LOCALAPPDATA%\WeChatWorkHub\widget.log` 里有 `[自愈]` 行（说明兜底生效过）。
**处理**：升级到最新代码即可；临时手段是 `python tools\start_widget.py --restart`。

---

### 5.20 开机自启没生效

**根因**：历史 bug——写进启动项的 bat 调用了一个不存在的文件，所以从来没成功过（已修）。
**处理**：

```bash
python tools\make_startup_entry.py           # 重新生成启动项
python tools\make_startup_entry.py --remove  # 想撤掉
```

生成的文件在 `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\WeChatWorkHub.bat`。
想验证：双击这个 bat，应该能起服务。

---

### 5.21 项目放在中文/带空格路径里，报「找不到文件」

**现象**：`FileNotFoundError` 指向一个明明存在的路径；或 ffmpeg 子进程失败。
**根因**：`subprocess` 传参没加引号，或第三方库对非 ASCII 路径处理不当。
**处理**：把项目挪到纯英文短路径（如 `D:\wwh`）再试。**这是最快的验证手段**，不是妥协。
`python tools/doctor.py` 会对「项目路径」出一行提醒。

---

### 5.22 桌面在 OneDrive 里，`runs/` 写不进去 / 文件被同步锁住

**根因**：OneDrive 会锁正在写的文件，导致原子改名失败。
**处理**：把项目放到**非 OneDrive 同步目录**（如 `D:\wwh`）。数据量不大，没必要同步。

---

### 5.23 系统是 Windows 但没管理员权限

**事实**：本项目**不需要管理员**。所有写入都在项目目录和 `%LOCALAPPDATA%\WeChatWorkHub\`。
装 Python 时选「仅为当前用户安装」即可；`pip install -e .` 装在 venv 里，不碰系统。

---

### 5.24 `python -m venv .venv` 失败（`ensurepip` 报错）

**根因**：Python 安装时没装 pip，或被杀软拦了。
**处理**：

```bash
python -m ensurepip --upgrade
# 或直接建裸 venv 再补 pip
python -m venv --without-pip .venv
.venv\Scripts\python.exe -m ensurepip
```

---

### 5.25 浏览器打不开 127.0.0.1:5710，但 `curl` 能通

**根因**：浏览器/系统代理把 localhost 也代理走了。
**处理**：代理设置里把 `127.0.0.1; localhost` 加进「不使用代理」，或临时关代理。

---

### 5.26 杀软报毒 / 删掉 `pythonw.exe`

**根因**：`pythonw` + 自启 + 常驻窗口的组合容易被启发式误判。
**处理**：把项目目录与 Python 目录加入白名单；或用前台 `python tools\desktop_widget.py` 验证是行为问题还是误报。

---

### 5.27 `git clone` 后中文文件名显示成 `\346\226\207...`

**根因**：git 的 `core.quotepath` 默认把非 ASCII 转义显示，**只是显示问题**，文件是好的。
**处理**：`git config --global core.quotepath false`。

---

### 5.28 `pip install` 卡住 / 超时 / SSL 错误

**处理**：

```bash
.venv\Scripts\python.exe -m pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 60
```

公司网络要证书就 `--trusted-host pypi.tuna.tsinghua.edu.cn`。**别用 `--no-deps`**，会缺包。

---

### 5.29 `pip install -e .` 报 building wheel 失败（要 VC++ build tools）

**根因**：用的 Python 版本没有预编译 wheel（例如 3.13 上的某些包）。
**处理**：换 Python 3.11 建 venv：`py -3.11 -m venv .venv`。**不要**去装几个 G 的 VS Build Tools，
没必要。

---

### 5.30 我只想验证「整条链路通不通」，不想接微信

```bash
.venv\Scripts\python.exe main.py --list-groups
.venv\Scripts\python.exe main.py --group "XX项目工作群" --date 2026-10-27 -f both --open
```

样例数据是虚构的（人名、群名、时间都是编的），可以随便截图、随便演示。

---

### 5.31 `自动刷新失败（连续第 N 次）` / `No module named 'psutil'`

**现象**：控制台日志或 `logs\console.out` 里反复出现

```
File "...\siwx\discover.py", line 6, in <module>
  import psutil
ModuleNotFoundError: No module named 'psutil'
自动刷新失败（连续第 4 次），下次冷却 3600 秒
```

新消息一直进不来，卡片停在老日期。

**根因**：解密工具 SIWX 有自己的一套依赖（`psutil`、`pycryptodome`、`flask`、`openpyxl`、`rich`）。
项目一旦用 `.venv` 运行（双击 `一键启动.bat` 现在优先 `.venv`），`sys.executable` 只装了本项目依赖，
跑 SIWX 就缺包。**这不是没装 Python，是两个 Python 各装了一半。**

**现在的做法**：`core/auto_refresh.py` 会**自己挑一个真能跑 SIWX 的解释器**
（`WX_PYTHON` > 当前 > 系统 > PATH，逐个试 `import psutil, Crypto`），挑不到才报错，并给出能直接粘的命令。
`python tools\doctor.py` 也会检查这一项（id `siwx`）。

**处理**（任选其一）：

```bash
# A. 给当前解释器补上 SIWX 的依赖（doctor 会把完整命令打出来）
<doctor 给出的 python.exe> -m pip install -r "C:\...\siwx\requirements.txt"

# B. 直接在 .env 里指定一个装好这些包的解释器
WX_PYTHON=C:\Users\你\AppData\Local\Programs\Python\Python311\python.exe
```

验证：`python tools\refresh_data.py` 应打印「完成：解密数据已刷新。」

---

### 5.32 卡片不更新 / 「有新消息但就是不出新卡片」

**先分清两件事**：

| 你点的东西 | 它做什么 | 会不会调 AI |
| --- | --- | --- |
| 悬浮窗右键 →「立即更新消息」 | 立刻跑一次完整链路（拉消息 → AI → 出卡片） | 会，花钱 |
| 悬浮窗右键 →「重新读取数据」 | 只重读磁盘上的 `cards.json`，不拉消息 | 不会 |
| `刷新数据.bat` | 只做解密/刷新微信快照，不出卡片 | 不会 |

**根因**：自动守护默认**最多 60 分钟才跑一次 AI**（`MIN_GAP_SEC`，省钱），
所以「有新消息但距上次执行只有 N 分钟」时它是有意不跑的，日志里会这么写。
以前写的是 2 小时，现在降到 1 小时，并且日志会告诉你「还要等 N 分钟」。

**处理**：
- 想马上要：右键悬浮窗 →「立即更新消息」（后台跑，几十秒后卡片自己变）；
- 改间隔：`tools/auto_daemon.py` 顶部 `MIN_GAP_SEC`（秒）；
- 想看它到底怎么判断的：`python tools\auto_daemon.py --once`。

---

---

## 6. 模型配置与降级

| 状态 | 表现 | 怎么切 |
| --- | --- | --- |
| 没 Key | 总结 = 离线草稿，`runs/pending/` 有原文 | 配 `DEEPSEEK_API_KEY` |
| 有 Key | 总结 = 模型输出，带任务卡 | 同上 |
| Key 失效 | 报错后**自动降级**为离线草稿，不会中断整次运行 | `tools/test_model_api.py` |

支持的三种服务（DeepSeek / 豆包 / OpenAI 兼容）见 README 第七节。
**Key 只写在你自己的 `.env` 里，`.env` 已被 `.gitignore`，永远不会进仓库。**

---

## 7. 悬浮窗（Windows 可选）

| 动作 | 命令 |
| --- | --- |
| 启动（含守护进程） | `python tools\start_widget.py` |
| 重启（卡住/找不到就用这个） | `python tools\start_widget.py --restart` |
| 只看效果，不真跑 | `python tools\desktop_widget.py --demo`（前台运行，报错看得见） |
| 停止 | 窗口上右键 → 退出；或 `python tools\start_widget.py --restart` 直接换新的 |

形态：面板（522×820）↔ 玻璃球（96×96）↔ 右侧细条（34×192）。
**点面板以外的地方约 5 秒会自动收成细条，鼠标移到细条上会重新展开**（细条在屏外时靠 `--restart` 找回）。

右键菜单：

| 菜单项 | 作用 | 是否调 AI |
| --- | --- | --- |
| 打开最新报告 | 浏览器打开最近一份 HTML 报告 | 否 |
| 立即更新消息 | 后台跑一次完整链路（拉消息 → AI → 出卡片） | **是，花钱** |
| 重新读取数据 | 只重读磁盘上的 `cards.json` | 否 |
| 展开面板 / 收起成球 | 换形态 | 否 |
| 退出 | 关掉悬浮窗（守护进程 60 秒内会把它拉回来，要彻底停见第 8 节） | 否 |

状态文件全在 `%LOCALAPPDATA%\WeChatWorkHub\`：

| 文件 | 作用 | 坏了怎么办 |
| --- | --- | --- |
| `cards.json` | 卡片数据 | 删掉，`python tools/make_daily_cards.py` 重生成 |
| `done.json` | 已完成的卡片 | 删掉即全部恢复未完成 |
| `widget.json` | 窗口位置/形态 | 删掉即回到默认位置 |
| `widget.log` | 运行日志（含 `[自愈]` 记录） | 排错第一现场 |
| `crash.log` | 崩溃栈 | 只有真崩过才存在 |

---

## 8. 进程与端口（动手前先看这一节）

| 进程 | 干什么 | 能不能随便杀 |
| --- | --- | --- |
| `python tools/serve_hidden.py`（或 venv 的 pythonw） | 本地控制台服务，持有端口 | 可以，`launch.py` 会重起 |
| `python tools/desktop_widget.py` | 悬浮窗窗口 | 可以，守护进程 60 秒内会拉回来 |
| `python tools/auto_daemon.py` | 看护：窗口掉了拉起来、有新消息出卡 | 可以，但拉回能力就没了 |
| `python tools/launch.py` | 启动器，起完就退出 | 它自己会退 |

**危险操作黑名单**（我踩过，别重复）：

- ❌ `taskkill /IM python.exe /F` —— 会杀掉这台机器上所有 Python 程序（包括你自己的别的项目）。
- ❌ `taskkill /IM pythonw.exe /F` —— 同上，还会连带杀掉无关的后台程序。
- ✅ 正确做法：`netstat -ano | findstr :5710` 拿到 PID，只杀那一个；
  或者干脆用 `python tools\launch.py`，它只处理监听该端口的 python。
- ❌ 直接改远端 git 历史（`push --force`）——本项目协作时踩过，会把别人的提交冲掉。

---

## 9. 给 AI 的完整提示词（复制即用）

```text
帮我把 https://github.com/Hello18362/wechat-work-hub 装到本地并跑通。

环境：<Windows 11 / 有 Python 3.11 / 没有微信解密数据>

请严格按仓库里的 docs/部署与排错-AI版.md 执行，不要自己发明步骤：
1. 克隆仓库到 <你选一个纯英文短路径，如 D:\wwh>。
2. python -m venv .venv，然后 .venv\Scripts\python.exe -m pip install -e .（国内可加清华源；
   启动器装依赖失败时会自动换清华源重试一次，不必你手动干预）。
   如果你在 Windows 上能双击文件，直接双击 一键启动.bat 也行：它会自建 .venv 并装依赖。
3. 运行 .venv\Scripts\python.exe tools\doctor.py --json，把 ❌ 项按 fix 字段逐条处理，
   直到没有 ❌（⚠️ 和 ➖ 允许存在）。
4. 运行 .venv\Scripts\python.exe tools\launch.py --no-browser 起服务，
   用返回的地址访问 /health，确认 "status": "ok"。
5. 运行 .venv\Scripts\python.exe main.py --group "XX项目工作群" --date 2026-10-27 -f both，
   确认 runs/ 下生成了 .md 和 .html。

任何一步失败，先去文档第 5 节按报错原文查；查不到再把「完整报错 + 你在做什么」贴给我，
不要跳过、不要用 --no-deps、不要改代码来绕过。
最后向我报告：/health 的返回、doctor 的 fail/warn 数、生成的报告文件名。
```

---

## 10. 维护者备忘：这一轮到底修了什么

写这份文档时顺手修掉的问题（都在代码里，不是只写在文档里）：

| 问题 | 修法 |
| --- | --- |
| 全新机器缺 PyYAML 时读不到端口 → 误报「启动超时」 | `launch.py` 加文本兜底解析 + 读日志就绪地址 |
| 依赖装在 `.venv`，双击 bat 却用系统 Python | 所有 `.bat` 优先 `%~dp0.venv\Scripts\python.exe` |
| `wgh` 入口 ModuleNotFoundError | `py-modules = ["main"]` |
| GBK 控制台打印 `✗` 崩溃 | 编码探测 + `errors="replace"` |
| 缺 `zstandard` 时静默丢消息 | 声明为必装依赖 + ImportError 明确告警 |
| 没有数据源时全盲 | 内置样例数据兜底 + 状态栏明示 |
| 开机自启调用了不存在的 bat | 重写 `make_startup_entry.py` |
| 没有统一的体检入口 | 重写 `tools/doctor.py`（含 `--json`） |
| 悬浮窗跑到屏外 / 卡住不动 | 可见区域夹取 + 看门狗自愈 |
| 磨砂背景糊在壁纸上 | 模糊半径按比例放大（26px @2x） |
| 第一次双击时没有 `.venv`，依赖被装进系统 Python | `一键启动.bat` 首次运行自动创建 `.venv` |
| Python 装在 `C:\Program Files\...` 时 bat 调用被空格截断 | 解释器统一解析成 `sys.executable` 完整路径并加引号 |
| 国内网络直连 PyPI 装不动 | 装依赖失败自动换清华源重试一次 |

**还欠着的**（诚实列出，别在文档里假装没有）：

1. 报告里可能出现本机绝对路径（5.16）；2. 没有鉴权，只适合本机/内网；
3. 语音只支持 SILK/常见格式，没做说话人分离；4. 微信升级可能打破解密链路，需要外部工具跟进。