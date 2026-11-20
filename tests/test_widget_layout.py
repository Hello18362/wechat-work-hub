"""widget 渲染与布局回归：归档行/完成条目/命中区/小球与细条冒烟。

不依赖 win32：只测 render 与 theme（draw_* 用纯 PIL 绘制，字体有 system fallback）。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.widget import render, theme as T


def _card(title, group="XX项目工作群", pri="中", due="", **_kw):
    base = {"group": group, "title": title, "source": "张总", "owner": "小陈",
            "priority": pri, "due": due, "seq": 0}
    base.update(_kw)
    return base


class LayoutCardsTest(unittest.TestCase):
    def _rows(self, cards, expanded):
        rows, content_h = render.layout_cards(cards, done_expanded=expanded)
        return rows, content_h

    def test_no_done_no_archive(self):
        cards = [_card("任务%d" % i, due="明天") for i in range(5)]
        rows, content_h = self._rows(cards, False)
        self.assertEqual(len(rows), 5)
        self.assertFalse(any(r[0].get("__archive__") for r in rows))
        self.assertGreater(content_h, 0)

    def test_done_appends_collapsed_archive(self):
        cards = [_card("任务%d" % i) for i in range(3)]
        cards.append(_card("已完成的", done=True))
        rows, content_h = self._rows(cards, False)
        self.assertEqual(len(rows), 4)
        self.assertTrue(rows[-1][0].get("__archive__"))
        h = rows[-1][1][3] - rows[-1][1][1]
        self.assertEqual(h, T.ARCH_H)

    def test_done_expanded_rows(self):
        cards = [_card("任务%d" % i) for i in range(2)]
        cards += [_card("完%d" % i, done=True) for i in range(3)]
        rows, content_h = self._rows(cards, True)
        self.assertEqual(len(rows), 2 + 1 + 3)
        self.assertTrue(rows[2][0].get("__archive__"))
        ah = rows[2][1][3] - rows[2][1][1]
        self.assertEqual(ah, T.ARCH_HEAD_H)
        for r in rows[3:]:
            h = r[1][3] - r[1][1]
            self.assertEqual(h, T.DONE_ROW_H)

    def test_archive_visible_without_scroll(self):
        # 6 张未完成 + 归档（折叠）：归档行应该正好贴住可视区底边，无需滚动即可看到
        cards = [_card("任务%d" % i) for i in range(6)]
        cards.append(_card("已完成的", done=True))
        rows, content_h = self._rows(cards, False)
        region_h = T.CARDS_BOTTOM - T.CARDS_TOP
        self.assertLessEqual(content_h, region_h + 0.01)
        self.assertGreaterEqual(content_h, region_h - 2.0)

    def test_empty_archive_when_only_pending(self):
        rows, _ = self._rows([_card("任务")], True)
        self.assertFalse(any(r[0].get("__archive__") for r in rows))


class DrawPanelHitsTest(unittest.TestCase):
    def _draw(self, cards, done_expanded=False, **st):
        state = {"cards": cards, "done_expanded": done_expanded,
                 "scroll": 0.0, "hover": -1, "hover_key": ""}
        state.update(st)
        return render.draw_panel(state, 2.0, None, ss=1, fast=True, bkey=0)

    def test_hits_kinds_with_cards(self):
        cards = [_card("任务A", pri="紧急", due="今天"),
                 _card("完", done=True)]
        img, hits = self._draw(cards, done_expanded=False)
        kinds = {h["kind"] for h in hits}
        self.assertIn("collapse", kinds)
        self.assertIn("check", kinds)
        self.assertNotIn("thumb", kinds)  # thumbs 条已移除
        # 折叠态有归档行命中区，无完成条目 hit
        self.assertIn("archive", kinds)
        self.assertFalse(any(h["kind"] == "card" and h["card"].get("done")
                              for h in hits))

    def test_done_rows_hit_kinds(self):
        cards = [_card("任务A"), _card("完", done=True)]
        img, hits = self._draw(cards, done_expanded=True)
        done_hits = [h for h in hits
                     if h["kind"] == "card" and h["card"].get("done")]
        self.assertEqual(len(done_hits), 1)

    def test_empty_panel_smoke(self):
        try:
            img, hits = self._draw([])
        except Exception as e:
            self.fail("draw_panel raised: %s" % e)
        kinds = {h["kind"] for h in hits}
        self.assertIn("collapse", kinds)


class BallSliverSmokeTest(unittest.TestCase):
    def test_ball_and_sliver(self):
        for painter in (render.draw_ball, render.draw_sliver):
            for state in ({}, {"cards": [_card("任务", pri="紧急")]}):
                try:
                    img, hits = painter(state, 2.0, None, ss=1, fast=True)
                except Exception as e:
                    self.fail("%s raised: %s" % (painter.__name__, e))
                self.assertGreaterEqual(len(hits), 1)


class SliverHoverTest(unittest.TestCase):
    """细条悬停判定：用户报告「收成细条后点不动」，这里锁住判定边界。"""

    RECT = (1900, 400, 68, 384)   # 贴在 1920 宽的屏幕右侧

    def _hit(self, cx, cy, pad=24):
        from tools.widget.geom import hover_pad_hit
        return hover_pad_hit(self.RECT, cx, cy, pad)

    def test_inside_bar(self):
        self.assertTrue(self._hit(1934, 600))

    def test_within_pad_left(self):
        self.assertTrue(self._hit(1900 - 20, 600))   # 24px 缓冲内
        self.assertTrue(self._hit(1876, 600))        # 正好边界

    def test_outside_pad(self):
        self.assertFalse(self._hit(1800, 600))       # 离太远，不该弹
        self.assertFalse(self._hit(1934, 100))       # 纵向不沾边


class DragGeometryTest(unittest.TestCase):
    """回归：小球拖到边缘后被推出屏幕（缩成小球再拖动就再也叫不出来）。"""

    WORK = (0, 0, 1920, 1040)

    def _ball_visible(self, panel_x, panel_y, k=1.0):
        """模拟 _rect_for("ball")：由 panel 坐标算出小球在屏幕上的可见矩形。"""
        from tools.widget.geom import visible_box
        bx = panel_x + T.PANEL_W * k - T.BALL * k
        rect = (bx - T.BALL_MARGIN * k, panel_y - T.BALL_MARGIN * k,
                (T.BALL + 2 * T.BALL_MARGIN) * k, (T.BALL + 2 * T.BALL_MARGIN) * k)
        return visible_box("ball", rect, k)

    def test_ball_box_strips_shadow_margin(self):
        from tools.widget.geom import visible_box
        box = visible_box("ball", (100, 200, 96, 96), 1.0)
        self.assertEqual(box, (100 + T.BALL_MARGIN, 200 + T.BALL_MARGIN,
                               T.BALL, T.BALL))

    def test_expanded_box_strips_shadow_margin(self):
        from tools.widget.geom import visible_box
        box = visible_box("expanded", (10, 20, 522, 820), 1.0)
        self.assertEqual(box, (10 + T.PANEL_MARGIN, 20 + T.PANEL_MARGIN,
                               T.PANEL_W, T.PANEL_H))

    def test_ball_panel_pos_round_trip(self):
        from tools.widget.geom import panel_pos_from_box
        box = (1852, 155, T.BALL, T.BALL)
        px, py = panel_pos_from_box("ball", box, 1.0)
        self.assertEqual(px, 1852 - (T.PANEL_W - T.BALL))
        self.assertEqual(py, 155)
        self.assertEqual(self._ball_visible(px, py), box)

    def test_dragged_ball_to_right_edge_stays_visible(self):
        from tools.widget.geom import clamp_to_work, panel_pos_from_box, snap_x, visible_box
        # 用户把小球拖到屏幕右下角
        box = visible_box("ball", (1880, 900, 96, 96), 1.0)
        x, side = snap_x(box, self.WORK, T.SNAP_DIST)
        self.assertEqual(side, "right")
        x, y, w, h = clamp_to_work((x, box[1], box[2], box[3]), self.WORK)
        px, py = panel_pos_from_box("ball", (x, y, w, h), 1.0)
        # 关键：换算回 panel 坐标后，小球必须仍然整块落在屏幕里
        vx, vy, vw, vh = self._ball_visible(px, py)
        self.assertGreaterEqual(vx, 0)
        self.assertLessEqual(vx + vw, self.WORK[2])
        self.assertGreaterEqual(vy, 0)
        self.assertLessEqual(vy + vh, self.WORK[3])

    def test_ball_dragged_far_offscreen_is_pulled_back(self):
        from tools.widget.geom import clamp_to_work, panel_pos_from_box, visible_box
        # 旧版本存下来的坏位置：panel_x=1852 时小球被推到 2266
        bad = visible_box("ball", (2252, 155, 96, 96), 1.0)
        self.assertGreater(bad[0], self.WORK[2])          # 确实在屏幕外
        x, y, w, h = clamp_to_work(bad, self.WORK)
        px, py = panel_pos_from_box("ball", (x, y, w, h), 1.0)
        vx, _vy, vw, _vh = self._ball_visible(px, py)
        self.assertLessEqual(vx + vw, self.WORK[2])

    def test_clamp_keeps_top_left_when_box_larger_than_work(self):
        from tools.widget.geom import clamp_to_work
        self.assertEqual(clamp_to_work((10, 10, 3000, 3000), self.WORK),
                         (0, 0, 3000, 3000))


if __name__ == "__main__":
    unittest.main()