# -*- coding: utf-8 -*-
"""把报告里的任务卡片渲染成一张桌面壁纸（1920×1080）。

用法（后续接入每日定时任务时由调度器调用）：
    from desktop_cards import render_wallpaper
    render_wallpaper(cards, out_path, subtitle="2026-11-15 周六")

cards 每个元素：
    {
        "group": "示例 · 项目协作群",   # 群名
        "source": "张经理 14:32",       # 源 = 发起人 + 时间
        "owner": "李四",                # 人 = 指定对象
        "due": "今天 18:00",            # 时 = 截止
        "title": "提交季度报表",         # 任务内容
        "priority": "紧急",             # 紧急 / 重要 / 常规
        "done": False,
    }
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------- 视觉参数

W, H = 1920, 1080
BG_TOP = (18, 18, 18)
BG_BOTTOM = (28, 27, 26)
CARD_BG = (31, 31, 31)
CARD_BORDER = (52, 52, 52)
CARD_BG_DONE = (26, 26, 26)

INK = (245, 244, 242)
INK_2 = (168, 166, 163)
INK_3 = (118, 116, 113)
ACCENT = (255, 92, 40)
ACCENT_SOFT = (255, 138, 92)

PRI_COLORS = {
    "紧急": (255, 92, 40),
    "重要": (255, 176, 76),
    "高": (255, 176, 76),
    "中": (140, 170, 255),
    "常规": (120, 120, 120),
}

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyhbd.ttc",   # 微软雅黑 Bold
    r"C:\Windows\Fonts\msyh.ttc",     # 微软雅黑
    r"C:\Windows\Fonts\simhei.ttf",   # 黑体
    "/System/Library/Fonts/PingFang.ttc",                              # macOS
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",             # Linux
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
]
FONT_REG_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
]


def _font(size: int, bold: bool = False):
    pool = FONT_CANDIDATES if bold else FONT_REG_CANDIDATES
    for path in pool:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _text_w(draw, text: str, font) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def _ellipsis(draw, text: str, font, max_w: int) -> str:
    """按像素宽度截断，超出部分用省略号。"""
    if not text or _text_w(draw, text, font) <= max_w:
        return text
    ell = "…"
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _text_w(draw, text[:mid] + ell, font) <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + ell


def _vertical_gradient(size, top, bottom):
    img = Image.new("RGB", size, top)
    draw = ImageDraw.Draw(img)
    for y in range(size[1]):
        t = y / max(1, size[1] - 1)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        draw.line([(0, y), (size[0], y)], fill=color)
    return img


def _draw_card(base: Image.Image, box, card: Dict[str, str]) -> None:
    """在 base 上画一张任务卡片。"""
    x0, y0, x1, y1 = box
    w = x1 - x0
    radius = 20
    done = bool(card.get("done"))

    layer = Image.new("RGBA", (w, y1 - y0), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle(
        (0, 0, w - 1, y1 - y0 - 1),
        radius=radius,
        fill=CARD_BG_DONE if done else CARD_BG,
        outline=CARD_BORDER,
        width=1,
    )
    base.paste(layer, (x0, y0), layer)

    d = ImageDraw.Draw(base)

    f_group = _font(17)
    f_pri = _font(16, bold=True)
    f_title = _font(27, bold=True)
    f_meta = _font(19)
    f_tag = _font(16, bold=True)

    pad_x = 26
    pad_y = 22
    cur_y = y0 + pad_y

    # 顶部：群名 + 优先级
    pri = card.get("priority") or "常规"
    pri_color = PRI_COLORS.get(pri, PRI_COLORS["常规"])

    pri_label = pri
    pri_w = _text_w(d, pri_label, f_pri) + 20
    chip_h = 26
    chip_x1 = x1 - pad_x
    chip_x0 = chip_x1 - pri_w
    d.rounded_rectangle(
        (chip_x0, cur_y, chip_x1, cur_y + chip_h),
        radius=chip_h // 2,
        fill=pri_color + (46,) if False else None,
        outline=pri_color,
        width=1,
    )
    d.text((chip_x0 + 10, cur_y + 4), pri_label, font=f_pri, fill=pri_color)

    group_text = _ellipsis(d, card.get("group") or "未知群", f_group, w - pad_x * 2 - pri_w - 16)
    d.text((x0 + pad_x, cur_y + 3), group_text, font=f_group, fill=INK_3)
    cur_y += chip_h + 16

    # 任务标题（最多两行）
    title = card.get("title") or ""
    max_w = w - pad_x * 2
    line1 = _ellipsis(d, title, f_title, max_w)
    d.text((x0 + pad_x, cur_y), line1, font=f_title, fill=INK_3 if done else INK)
    used = _text_w(d, line1, f_title)
    cur_y += 40
    if used >= max_w - 8 and len(line1) < len(title):
        rest = title[len(line1.rstrip("…")):]
        line2 = _ellipsis(d, rest, f_title, max_w)
        d.text((x0 + pad_x, cur_y), line2, font=f_title, fill=INK_3 if done else INK)
        cur_y += 40

    cur_y += 6

    # 三行元信息：源（发起人）/ 人（对象）/ 时（截止）
    rows = []
    if card.get("source"):
        rows.append(("源", card["source"]))
    if card.get("owner"):
        rows.append(("人", card["owner"]))
    if card.get("due"):
        rows.append(("时", card["due"]))

    tag_size = 24
    for tag, value in rows:
        d.rounded_rectangle(
            (x0 + pad_x, cur_y + 2, x0 + pad_x + tag_size, cur_y + 2 + tag_size),
            radius=6,
            fill=(42, 41, 40),
        )
        tw = _text_w(d, tag, f_tag)
        d.text(
            (x0 + pad_x + (tag_size - tw) / 2, cur_y + 5),
            tag, font=f_tag, fill=INK_2,
        )
        val = _ellipsis(d, value, f_meta, max_w - tag_size - 14)
        d.text((x0 + pad_x + tag_size + 12, cur_y + 2), val, font=f_meta, fill=INK_2)
        cur_y += tag_size + 12


def render_wallpaper(
    cards: List[Dict[str, str]],
    out_path: str,
    subtitle: str = "",
    title: str = "今日群聊摘要",
    max_cards: int = 6,
) -> str:
    """渲染一张桌面壁纸并保存为 PNG，返回路径。"""
    img = _vertical_gradient((W, H), BG_TOP, BG_BOTTOM)

    # 左上角一抹极淡的暖色，避免纯黑太死
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((-380, -520, 900, 420), fill=(255, 92, 40, 14))
    img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")

    draw = ImageDraw.Draw(img)

    f_h1 = _font(44, bold=True)
    f_sub = _font(21)
    f_stat = _font(19)

    pad = 96
    draw.text((pad, 76), title, font=f_h1, fill=INK)

    if subtitle:
        draw.text((pad, 138), subtitle, font=f_sub, fill=INK_3)

    # 右上角统计
    total = len(cards)
    urgent = sum(1 for c in cards if (c.get("priority") in ("紧急", "高")))
    stat_text = "%d 项待办 · %d 项紧急" % (total, urgent)
    sw = _text_w(draw, stat_text, f_stat)
    draw.text((W - pad - sw, 96), stat_text, font=f_stat, fill=INK_3)

    # 顶部细分隔线
    draw.line([(pad, 190), (W - pad, 190)], fill=(46, 45, 44), width=1)

    shown = cards[:max_cards]
    if shown:
        cols = 3 if len(shown) > 2 else len(shown)
        rows = (len(shown) + cols - 1) // cols
        gap = 26
        grid_top = 232
        grid_w = W - pad * 2
        card_w = (grid_w - gap * (cols - 1)) // cols
        avail_h = H - grid_top - 96
        card_h = min(250, (avail_h - gap * (rows - 1)) // max(1, rows))

        for i, card in enumerate(shown):
            r, c = divmod(i, cols)
            x0 = pad + c * (card_w + gap)
            y0 = grid_top + r * (card_h + gap)
            _draw_card(img, (x0, y0, x0 + card_w, y0 + card_h), card)
    else:
        f_empty = _font(24)
        msg = "今天没有需要跟进的待办，可以安心开始新的一天。"
        mw = _text_w(draw, msg, f_empty)
        draw.text(((W - mw) / 2, 480), msg, font=f_empty, fill=INK_3)

    # 底部脚注
    f_foot = _font(16)
    foot = "WeChat Work Hub · 每天早上 8:00 自动生成"
    draw.text((pad, H - 62), foot, font=f_foot, fill=(92, 90, 88))

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path, "PNG")
    return out_path


if __name__ == "__main__":
    demo_cards = [
        {"group": "示例 · 项目协作群", "source": "张经理 09:13", "owner": "李主管",
         "due": "周四 18:00", "title": "完成 v0.9 回归测试并输出报告", "priority": "紧急"},
        {"group": "示例 · 班级通知群", "source": "辅导员 08:31", "owner": "班长",
         "due": "下周三", "title": "收齐奖学金申请表纸质版", "priority": "重要"},
        {"group": "示例 · 学生干部群", "source": "王老师 10:20", "owner": "生活委员",
         "due": "周四", "title": "完成迎新晚会物资清单核对", "priority": "常规"},
        {"group": "示例 · 部门周会群", "source": "陈总监 14:02", "owner": "刘工",
         "due": "明天上午", "title": "输出接口联调纪要并发群里", "priority": "重要"},
        {"group": "示例 · 项目协作群", "source": "李主管 09:35", "owner": "未指定",
         "due": "无明确截止", "title": "确认分享版脱敏规则是否符合评审要求", "priority": "常规"},
        {"group": "示例 · 实验讨论群", "source": "赵老师 16:40", "owner": "小周",
         "due": "周五 12:00", "title": "补做第三组对照实验并整理数据", "priority": "常规",
         "done": True},
    ]
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "preview_wallpaper.png")
    out = os.path.abspath(out)
    print(render_wallpaper(demo_cards, out, subtitle="2026-11-15 周六 · 6 个置顶群 · 共 86 条消息"))
    print("尺寸 1920×1080")
