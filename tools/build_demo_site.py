# -*- coding: utf-8 -*-
"""构建「沙盘演示站」：纯静态、假数据、可自由点击。

产物目录：demo-site/
    index.html      控制台界面（资源改为相对路径，注入 mock-api.js）
    app.js          原样复制的前端逻辑
    style.css       原样复制
    mock-api.js     假后端（拦截所有 /api/*）
    demo.css        演示提示条样式
    reports/        三份示例报告（用项目自己的渲染器生成，外观完全一致）
    预览.bat        本地起静态服务并打开浏览器
    README.md       部署说明
"""

import os
import shutil
import sys
from datetime import datetime

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(PROJ, "web", "assets")
OUT = os.path.join(PROJ, "demo-site")

sys.path.insert(0, PROJ)

DEMO_CSS = """/* 演示模式提示条 */
#demoBanner{
  position:fixed;top:0;left:0;right:0;z-index:99999;
  display:flex;align-items:center;gap:8px;
  padding:8px 14px;
  background:#1b1b1b;color:#f5f5f5;
  font-size:12.5px;line-height:1.4;
  font-family:inherit;
  box-shadow:0 1px 0 rgba(0,0,0,.2);
}
#demoBanner .demo-dot{
  width:7px;height:7px;border-radius:50%;flex:none;
  background:#FF5C28;
  box-shadow:0 0 0 3px rgba(255,92,40,.22);
}
#demoBanner strong{font-weight:600;flex:none}
#demoBanner .demo-text{color:rgba(255,255,255,.72)}
@media (max-width:640px){
  #demoBanner{font-size:11px;padding:6px 10px}
  #demoBanner .demo-text{display:none}
}

/* 报告页内预览：盖满全屏，顶部一条操作栏 */
#demoReportOverlay{
  position:fixed;inset:0;z-index:100000;
  display:flex;flex-direction:column;
  background:#1b1b1b;
}
#demoReportOverlay .demo-ov-bar{
  display:flex;align-items:center;gap:14px;flex:none;
  height:42px;padding:0 14px;
  background:#1b1b1b;color:#f5f5f5;
  font-size:12.5px;
  border-bottom:1px solid rgba(255,255,255,.12);
}
#demoReportOverlay .demo-ov-title{font-weight:600}
#demoReportOverlay .demo-ov-link{
  margin-left:auto;color:#FF8A5C;text-decoration:none;
  border-bottom:1px dashed rgba(255,138,92,.55);
}
#demoReportOverlay .demo-ov-link:hover{color:#FF5C28}
#demoReportOverlay .demo-ov-close{
  flex:none;cursor:pointer;
  padding:5px 14px;border-radius:999px;
  border:1px solid rgba(255,255,255,.28);
  background:transparent;color:#f5f5f5;
  font-size:12px;font-family:inherit;
  transition:background .22s cubic-bezier(.22,1.35,.36,1),border-color .22s cubic-bezier(.22,1.35,.36,1);
}
#demoReportOverlay .demo-ov-close:hover{
  background:rgba(255,255,255,.12);border-color:rgba(255,255,255,.5);
}
#demoReportOverlay .demo-ov-frame{
  flex:1;width:100%;border:0;background:#fafafa;
}
"""


def build_index():
    src = open(os.path.join(SRC, "index.html"), encoding="utf-8").read()
    html = src
    # 资源改相对路径（去掉服务端注入的版本号占位符）
    html = html.replace('<link rel="stylesheet" href="/assets/style.css?v={{ASSET_V}}">',
                        '<link rel="stylesheet" href="style.css">\n'
                        '<link rel="stylesheet" href="demo.css">')
    html = html.replace('<script src="/assets/app.js?v={{ASSET_V}}"></script>',
                        '<script src="mock-api.js"></script>\n'
                        '<script src="app.js"></script>')
    # 标题标注演示版
    html = html.replace("<title>WeChat Work Hub · 控制台</title>",
                        "<title>WeChat Work Hub · 控制台（演示版）</title>")

    if 'href="style.css"' not in html or 'src="mock-api.js"' not in html:
        raise SystemExit("index.html 替换失败：资源引用没找到，请检查模板是否改过")

    open(os.path.join(OUT, "index.html"), "w", encoding="utf-8", newline="\n").write(html)
    print("  ✓ index.html")


def make_messages(group, date_str, rows):
    """rows: (时:分, 发送人, 类型, 内容, 是否领导)"""
    from collector.models import Message

    base = datetime.strptime(date_str, "%Y-%m-%d")
    msgs = []
    for i, (hm, sender, mtype, content, leader) in enumerate(rows):
        hh, mm = [int(x) for x in hm.split(":")]
        ts = base.replace(hour=hh, minute=mm, second=0)
        msgs.append(
            Message(
                msg_id=f"{group}-{i}",
                group_name=group,
                sender_name=sender,
                sender_id=f"wxid_demo_{i}",
                timestamp=ts,
                msg_type=mtype,
                content=content,
                raw_content="",
                is_leader=leader,
                seq=i,
                note="",
            )
        )
    return msgs


REPORTS = [
    {
        "file": "demo-report-1",
        "group": "示例 · 项目协作群",
        "date": "2026-11-13",
        "summary": """## 今日要点

- 版本 v0.9 已提测，张经理要求**周四前完成回归**，重点覆盖数据同步与导出。
- 数据接口联调延后到明天上午，李主管负责对接对方技术同学。
- 新增的「报告分享版」已完成评审，确认去掉原始聊天记录、对手机号与身份证打码。

## 风险与关注

- 回归时间只有两天，测试人力只有一个，建议优先保证主流程。
- 联调依赖外部团队，若明天上午未就绪，需要同步调整提测时间。

## 任务安排

- ☐ 完成 v0.9 回归测试 · 负责人：张经理 · 截止：周四
- ☐ 输出接口联调记录 · 负责人：李主管 · 截止：明天上午
- ☐ 补充分享版脱敏规则说明 · 负责人：刘工 · 截止：周五
- ☑ 评审会议纪要已归档
""",
        "rows": [
            ("09:12", "张经理", "text", "早上好，v0.9 昨晚提测了，今天开始回归。", True),
            ("09:13", "张经理", "text", "重点看数据同步和导出这两块，周四前必须完成。", True),
            ("09:20", "刘工", "text", "收到，我这边先把导出用例跑一遍。", False),
            ("09:34", "李主管", "text", "接口联调对方今天请假，改到明天上午了。", True),
            ("09:35", "李主管", "text", "我明天上午十点拉会，一起过一遍字段。", True),
            ("10:02", "刘工", "file", "[文件] 回归测试用例_v0.9.xlsx", False),
            ("10:05", "张经理", "text", "用例我看了，缺一个批量导出的场景，补一下。", True),
            ("10:40", "小周", "image", "[图片 1280×720]", False),
            ("10:41", "小周", "text", "这是导出后 Excel 的样子，格式没问题。", False),
            ("11:15", "阿May", "voice", "[语音 8″]", False),
            ("14:20", "张经理", "article", "https://example.com/blog/report-share", True),
            ("14:21", "张经理", "text", "这篇讲报告脱敏的思路，可以借鉴一下。", True),
            ("15:30", "刘工", "emoji", "[表情]", False),
            ("16:10", "李主管", "text", "分享版评审通过了，按去掉聊天原文的方案做。", True),
            ("16:12", "小周", "text", "那我把脱敏规则整理成一页说明。", False),
            ("17:05", "张经理", "system", "系统消息：张经理 邀请 陈总监 加入了群聊", True),
            ("17:30", "陈总监", "text", "刚进群，麻烦把当前进度同步我一份。", True),
            ("17:32", "刘工", "text", "好的，我把用例和进度表一起发您。", False),
        ],
    },
    {
        "file": "demo-report-2",
        "group": "示例 · 班级通知群",
        "date": "2026-11-12",
        "summary": """## 通知汇总

- **本周五下午 3 点**在教学楼 302 开班会，主题是期末安排与安全注意事项，全体同学务必参加。
- 奖学金材料提交截止到**下周三**，纸质版交到辅导员办公室，电子版发班级邮箱。
- 四六级报名本周日 24:00 截止，还没报的同学抓紧。

## 需要确认

- 班会有 3 位同学在外实习，是否线上同步，需要辅导员确认。

## 任务安排

- ☐ 收齐奖学金申请表 · 负责人：班长 · 截止：下周三
- ☐ 统计班会到场人数 · 负责人：学习委员 · 截止：周四
- ☐ 转发四六级报名通知到各宿舍 · 负责人：生活委员 · 截止：今天
""",
        "rows": [
            ("08:30", "辅导员", "text", "各位同学早上好，本周五下午三点在教学楼 302 开班会。", True),
            ("08:31", "辅导员", "text", "主题是期末安排和安全注意事项，全体都要到。", True),
            ("08:45", "班长", "text", "收到，我在群里接龙统计一下到场人数。", True),
            ("09:10", "学习委员", "text", "奖学金材料截止下周三，纸质交办公室，电子发班级邮箱。", False),
            ("09:12", "陈同学", "text", "请问成绩单需要原件吗？", False),
            ("09:15", "学习委员", "text", "要原件，复印件不行。", False),
            ("10:20", "生活委员", "text", "四六级报名本周日 24 点截止，还没报的抓紧。", False),
            ("10:22", "沈同学", "text", "已经报了，谢谢提醒。", False),
            ("11:05", "辅导员", "file", "[文件] 期末安排通知.pdf", True),
            ("14:30", "杨同学", "text", "老师，我在外实习，班会有线上同步吗？", False),
            ("14:35", "辅导员", "text", "这个我再确认一下，晚点回复你。", True),
            ("16:00", "班长", "image", "[图片 1080×1440]", True),
            ("16:01", "班长", "text", "接龙二维码放这儿了，方便没看到的同学。", True),
            ("18:20", "生活委员", "voice", "[语音 4″]", False),
        ],
    },
    {
        "file": "demo-report-3",
        "group": "示例 · 学生干部群",
        "date": "2026-11-11",
        "summary": """## 讨论结论

- 迎新晚会节目单初稿已确定，共 12 个节目，总时长约 95 分钟。
- 物资采购统一走王老师这边的流程，本周内下单，逾期要等下个月。
- 彩排定在下周二、周四晚 7 点，地点改到体育馆（原教室有课）。

## 待办分配

- 节目单终稿需要各节目负责人确认伴奏与道具，未确认的按弃权处理。
- 主持人串词由宣传部负责，本周日前出第一版。

## 任务安排

- ☐ 提交节目单终稿 · 负责人：王老师 · 截止：周五
- ☐ 完成物资清单核对 · 负责人：生活委员 · 截止：周四
- ☐ 主持人串词第一版 · 负责人：宣传委员 · 截止：周日
- ☑ 体育馆场地申请已通过
""",
        "rows": [
            ("09:05", "王老师", "text", "迎新晚会节目单初稿出来了，一共 12 个节目。", True),
            ("09:06", "王老师", "text", "总时长 95 分钟，大家看一下有没有要调整的。", True),
            ("09:18", "宣传委员", "file", "[文件] 节目单初稿_v2.docx", False),
            ("09:40", "生活委员", "text", "物资这块走老师那边统一采购对吧？", False),
            ("09:42", "王老师", "text", "对，本周内下单，逾期要等下个月。", True),
            ("10:15", "文艺委员", "text", "彩排地点定哪？原来那个教室周四有课。", False),
            ("10:20", "王老师", "text", "改到体育馆，我已经申请通过了。", True),
            ("10:22", "文艺委员", "emoji", "[表情]", False),
            ("11:00", "王老师", "text", "彩排定周二、周四晚七点，各节目负责人必须到。", True),
            ("11:30", "宣传委员", "text", "主持人串词我这周日出第一版。", False),
            ("14:10", "生活委员", "image", "[图片 720×1280]", False),
            ("14:11", "生活委员", "text", "这是物资清单截图，大家核对一下有没有漏。", False),
            ("15:40", "文艺委员", "text", "第三个节目的伴奏要换，原来的版本太长。", False),
            ("16:00", "王老师", "text", "那周五前把终稿发我，没确认的按弃权处理。", True),
            ("17:20", "宣传委员", "article", "https://example.com/stage-design", False),
            ("17:21", "宣传委员", "text", "舞台设计的参考，可以看看。", False),
        ],
    },
]


def build_reports():
    from output.html import render_report

    rep_dir = os.path.join(OUT, "reports")
    os.makedirs(rep_dir, exist_ok=True)

    for spec in REPORTS:
        msgs = make_messages(spec["group"], spec["date"], spec["rows"])
        counts = {}
        for m in msgs:
            counts[m.msg_type] = counts.get(m.msg_type, 0) + 1
        stats = {
            "total": len(msgs),
            "leader_count": sum(1 for m in msgs if m.is_leader),
            "counts": counts,
            "first_time": msgs[0].timestamp,
            "last_time": msgs[-1].timestamp,
        }
        html = render_report(
            spec["summary"], msgs, spec["group"], spec["date"], stats, "light", None, False
        )
        path = os.path.join(rep_dir, spec["file"] + ".html")
        open(path, "w", encoding="utf-8", newline="\n").write(html)
        print("  ✓ reports/%s.html  (%.0f KB, %d 条消息)"
              % (spec["file"], len(html.encode()) / 1024, len(msgs)))


PREVIEW_BAT = """@echo off
chcp 936 >nul
cd /d "%~dp0"
title 演示站 - 本地预览

echo ==========================================
echo    沙盘演示站 - 本地预览
echo ==========================================
echo.

set "PY=python"
where "%PY%" >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 python，请先安装 Python 并加入 PATH
    pause
    exit /b 1
)

echo 正在启动本地服务：http://127.0.0.1:5730
start "" http://127.0.0.1:5730/
"%PY%" -m http.server 5730

echo.
echo 服务已停止。
pause
"""

README = """# 沙盘演示站（示例数据）

这是「微信群工作报告」控制台的**演示版本**：界面、交互与真实版完全一致，
但所有数据都是编好的示例，**不含任何真实群聊内容**。

## 为什么有这个版本

真实版的界面背后是 Python 服务，数据源是你电脑上登录的微信 —— 别人电脑上跑不起来。
演示版把「假后端」写在 `mock-api.js` 里拦截 `/api/*`，于是变成**纯静态站**：
不需要 Python、不需要微信、不需要服务器，任何人打开就能点。

## 能演示哪些功能

- 群列表、置顶（图钉可点，置顶群会跳到最上面）
- 「关注的人」设置面板（增删成员、保存）
- 好友 / 公众号标签页、搜索、无有效昵称筛选
- 报告卡片、点卡片上的按钮直接打开报告
- 点「生成报告」→ 进度条走完 → 列表顶部多出一份报告
- 报告详情弹窗、复制 Markdown、删除报告

## 三种打开方式

**① 本地预览（最快）**

双击 `预览.bat`，浏览器自动打开 `http://127.0.0.1:5730`。
关掉黑窗口即停止。

> 不能直接双击 `index.html` —— 页面里打开报告用的是 `/reports/xxx.html` 绝对路径，
> 走 `file://` 会找不到文件。必须用 http 打开。

**② 传到公网（给老师一个链接）**

整个 `demo-site` 文件夹就是一个静态网站，任选其一：

- **Vercel**：<https://vercel.com/new> → 把文件夹拖进去 → 得到 `https://xxx.vercel.app`
- **Netlify**：<https://app.netlify.com/drop> → 把文件夹拖进去 → 立刻得到网址
- **GitHub Pages**：推到仓库，Settings → Pages → 选分支根目录

三个都不需要命令行，也不用备案。

**③ 拷给别人本地跑**

整个文件夹发给对方，让他双击 `预览.bat`（需要装 Python）。
如果对方没有 Python，就用方式 ② 给链接。

## 文件说明

```
index.html     控制台页面（资源引用改成了相对路径）
app.js         前端逻辑（与真实版完全相同，未改动）
style.css      样式（与真实版完全相同）
mock-api.js    假后端：拦截 /api/*，返回示例数据
demo.css       顶部「演示模式」提示条样式
reports/       三份示例报告（由项目自己的渲染器生成，外观与真实报告一致）
预览.bat       本地起静态服务
```

## 要说清楚的一点

这是**沙盘**：点「生成报告」不会真的调用大模型，进度条走完后弹出的是预置结果。
给人演示时建议主动说明「界面是同一套，数据是示例」，比让人误以为在跑真实数据更稳妥。
真实效果可以配合一段录屏或现场演示补充。
"""


def main():
    os.makedirs(OUT, exist_ok=True)

    print("复制前端资源…")
    shutil.copy2(os.path.join(SRC, "app.js"), os.path.join(OUT, "app.js"))
    shutil.copy2(os.path.join(SRC, "style.css"), os.path.join(OUT, "style.css"))
    print("  ✓ app.js / style.css")

    print("生成 index.html / demo.css …")
    build_index()
    open(os.path.join(OUT, "demo.css"), "w", encoding="utf-8", newline="\n").write(DEMO_CSS)
    print("  ✓ demo.css")

    print("生成示例报告…")
    build_reports()

    print("写入 预览.bat / README.md …")
    open(os.path.join(OUT, "预览.bat"), "w", encoding="gbk", newline="\r\n").write(PREVIEW_BAT)
    open(os.path.join(OUT, "README.md"), "w", encoding="utf-8", newline="\n").write(README)
    print("  ✓ 预览.bat / README.md")

    total = 0
    for dp, dn, fn in os.walk(OUT):
        for f in fn:
            total += 1
    print("\n完成：%s（%d 个文件）" % (OUT, total))


if __name__ == "__main__":
    main()
