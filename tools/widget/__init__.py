# -*- coding: utf-8 -*-
"""桌面悬浮窗：液态玻璃卡片。

模块划分：
    win32  —— ctypes 封装的 Win32 能力（分层窗口、取景、DPI）
    theme  —— 颜色、尺寸、手感参数
    render —— 用 Pillow 把状态画成整图
    store  —— cards.json / widget.json 读写
    app    —— 窗口、状态机、拖拽、吸边、动画
"""

__all__ = ["app", "render", "store", "theme", "win32"]
