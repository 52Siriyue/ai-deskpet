# -*- coding: utf-8 -*-
"""
桌面宠物程序 DeskPet
功能：透明无边框置顶、左键拖动、点击互动、滚轮缩放、右键菜单、对话气泡
依赖：PyQt5
"""
import sys
import os
import glob
import json
import base64
import random
import math
import time
import ast
import datetime
import subprocess
import threading
import urllib.parse
import re
import ctypes
from ctypes import wintypes
from PyQt5.QtWidgets import (QApplication, QWidget, QMenu, QAction, QLabel,
                             QVBoxLayout, QHBoxLayout, QInputDialog,
                             QGraphicsDropShadowEffect, QMessageBox, QDialog,
                             QProgressBar, QPushButton, QSpinBox, QLineEdit,
                             QScrollArea)
from PyQt5.QtGui import (QPixmap, QPainter, QColor, QFont, QBrush, QPen, QTransform,
                         QPainterPath, QRadialGradient, QLinearGradient, QBitmap)
from PyQt5.QtCore import (Qt, QTimer, QPoint, QRect, QPropertyAnimation,
                          QEasingCurve, pyqtProperty, QSize, QTime, pyqtSignal)
from PyQt5.QtNetwork import QLocalSocket, QLocalServer

# ============================================================
# 气泡字体：加载 fonts/pet_font.ttf（源码 / 打包 _MEIPASS 路径通用）
# ============================================================
PET_FONT_FAMILY = "fengsanqian_4_2435214"
_FONT_LOADED = False


def load_pet_font():
    """加载内置字体，返回字体族名（加载失败回退默认字体）"""
    global _FONT_LOADED
    if _FONT_LOADED:
        return PET_FONT_FAMILY
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "pet_font.ttf"),
        os.path.join(getattr(sys, '_MEIPASS', ''), "fonts", "pet_font.ttf"),
    ]
    from PyQt5.QtGui import QFontDatabase
    for c in candidates:
        if c and os.path.exists(c):
            fid = QFontDatabase.addApplicationFont(c)
            fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
            if fams:
                _FONT_LOADED = True
                return fams[0]
    return "Microsoft YaHei"  # 兜底

# ============================================================
# 角色图片（base64 嵌入，打包后无需外部文件）
# 运行 build 脚本前会由 insert_image.py 自动填充此处
# ============================================================
IMAGE_B64 = ""  # 已移除内嵌图片（隐私：原为真人照片 base64），素材走 frames/ 目录

# ============================================================
# 多帧动画系统：自动扫描 frames/ 目录，按"动作名_序号.png"加载
# 例如 frames/idle_1.png, idle_2.png, walk_1.png ...
# 目录位置：exe（或 main.py）同目录下的 frames/ 文件夹
# 无帧图的动作自动回退到"数学变形"模式，完全向后兼容
# ============================================================
FRAME_FPS = {"idle": 6, "walk": 10, "sleep": 2, "jump": 12,
             "squash": 12, "shake": 12, "drag": 10}
STATE_FRAME_MAP = {
    "drag": "walk",   # 拖动时复用走路帧
    "follow": "walk", # 跟随鼠标移动时复用走路帧
    "sleep": "idle",  # 睡觉时复用 idle 帧（变暗+躺下效果照常）
    "pet": "idle",    # 摸头时复用 idle 帧（画卡通手抚摸）
    "jump": "idle",   # 互动时复用 idle 帧（数学变形照常叠加，不再回退 base64 原图）
    "squash": "idle",
    "shake": "idle",
    "throw": "idle",  # 甩飞弹回
}

# 设置文件（记忆大小/位置/置顶状态）
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "settings.json")


def _find_frame_dir(subdir=None):
    """查找帧图目录：exe同目录 → PyInstaller解压目录 → 源码目录（可指定子目录）"""
    base_candidates = [
        os.path.dirname(os.path.abspath(sys.argv[0])),
        getattr(sys, '_MEIPASS', ''),
        os.path.dirname(os.path.abspath(__file__)),
    ]
    for base in base_candidates:
        if not base:
            continue
        path = os.path.join(base, "frames", subdir) if subdir else os.path.join(base, "frames")
        if path and os.path.isdir(path):
            return path
    return None


def load_frames(subdir=None, frames_dir=None):
    """扫描 frames/ 目录（或其子目录） → {动作名: [QPixmap, ...]}（按序号升序）
    frames_dir 优先（完整路径），否则按 subdir 走 _find_frame_dir。"""
    frames = {}
    d = frames_dir if frames_dir else _find_frame_dir(subdir)
    if not d:
        return frames
    for path in glob.glob(os.path.join(d, "*.png")) + \
               glob.glob(os.path.join(d, "*.jpg")) + \
               glob.glob(os.path.join(d, "*.jpeg")) + \
               glob.glob(os.path.join(d, "*.webp")) + \
               glob.glob(os.path.join(d, "*.bmp")):
        base = os.path.splitext(os.path.basename(path))[0]
        parts = base.rsplit("_", 1)
        if len(parts) == 2 and parts[1].isdigit():
            action, idx = parts[0], int(parts[1])
        else:
            action, idx = base, 0
        pix = QPixmap(path)
        if pix.isNull():
            continue
        frames.setdefault(action, []).append((idx, pix))
    for action in frames:
        frames[action].sort(key=lambda x: x[0])
        frames[action] = [p for _, p in frames[action]]
    return frames


# ============================================================
# 表情占位符 → 真实 emoji 映射（见 ai/emoji.py）
# ============================================================
from ai.emoji import EMOJI_MAP, fix_emoji  # noqa: E402


# ============================================================
# 对话文案库
# ============================================================
CHAT_LINES = [
    "🤦我去 刚吃完饭 在刷手机",
    "好嘟好嘟！",
    "嘿嘿 你在干嘛呀",
    "是牙是牙 没错",
    "我不行了 今天好累",
    "55 想吃好吃的",
    "宝 陪我打游戏嘛",
    "今天吃了蛋糕 太幸福啦",
    "啊啊啊啊啊 作业好多",
    "😭考试周好痛苦",
    "嗯嗯 知道啦",
    "额啊 怎么说呢",
    "你在干嘛 好无聊哦",
    "噢噢 原来是这样",
    "嘿嘿 我是不是很棒",
    "蒽蒽 在呢",
    "今天天气不错 出去逛逛吧",
    "😳别夸我啦",
    "好困 但是还不想睡",
    "你去哪啦 半天不理我",
    "🤦刚下课 累死了",
    "好嘟 明天一起吃食堂呀",
    "嘿嘿 发现一家好吃的",
    "你人呢 在干嘛呀",
    "😭今天倒霉死了",
    "宝 你吃饭了吗",
    "嘿嘿 偷偷告诉你个事",
    "我不行了 笑死我了",
    "55 我的快递还没到",
    "好嘟 听你的",
    "我去 感觉今天要累死了",
    "感觉你最近好忙哦",
    "好像有点道理",
    "但是……好像不对",
    "啊啊啊 好烦",
    "555 我好惨",
    "好的吧 听你的",
    "感觉今天天气好好",
    "啥呀 你在说啥",
    "然后呢 后来呢",
    "笑死我了 哈哈哈",
    "有点想你了",
    "我：？？？",
    "今天吃西园 嘿嘿",
    "不行了 我要笑死",
    "好的好的 知道了",
    "感觉要完蛋了",
    "呜呜 好委屈",
    "怎么感觉怪怪的",
    "你说啥 我没听懂",
]
PET_LINES = [
    "嘿嘿 舒服～",
    "好嘟 再摸摸嘛",
    "🐷头顶暖暖的",
    "嗯嗯 不要停",
    "嘿嘿 被摸头好开心",
    "噢噢 好舒服",
    "55 头要摸秃啦",
    "再摸一下下嘛",
    "嘿嘿 就喜欢这样",
]
FEED_LINES = [
    "好嘟！好吃！",
    "我去 这个好好吃",
    "嘿嘿 谢谢投喂",
    "555 太好吃了",
    "还要还要！",
    "😭感动 有吃的",
    "吃饱啦 好幸福",
    "嗯嗯 味道不错",
    "嘿嘿 最喜欢你啦",
]
SLEEP_LINES = [
    "我睡啦 白白～",
    "好困 睡觉去了 zzz",
    "晚安 宝",
    "先睡啦 明天找你",
]
WALK_LINES = [
    "出去走走～",
    "好嘟 散步去",
    "嘿嘿 呼吸新鲜空气",
    "走走走 出发！",
]
FOLLOW_LINES = [
    "跟着你走～",
    "好嘟 我在后面",
    "等等我呀 宝",
    "你去哪我去哪",
]

# ============================================================
# 男桌宠台词：稳重、简洁、不卖萌
# ============================================================
MALE_CHAT_LINES = [
    "在干嘛",
    "嗯 知道了",
    "吃饭了吗",
    "周末有什么安排",
    "刚忙完 歇会儿",
    "你刚才说啥",
    "早点休息",
    "我在呢",
    "嗯。",
    "好 就这么定",
    "睡了吗",
    "累了一天 躺会儿",
    "没事 慢慢来",
    "有我在",
    "嗯 继续说",
    "想吃什么 我带你去",
    "好的 收到",
    "干啥呢",
    "我也这么觉得",
    "还有呢",
    "睡觉了 晚安",
    "我去 这么厉害",
    "666",
    "嗯 差不多",
    "刚在忙 才看到",
    "你呢 吃了没",
    "不错 继续",
    "这个可以",
    "行 就这么办",
    "走吧 别磨蹭",
    "哦 原来是这样",
]
MALE_PET_LINES = [
    "嗯 还行",
    "可以",
    "别一直摸",
    "……舒服",
    "行了",
]
MALE_FEED_LINES = [
    "嗯 可以",
    "味道不错",
    "够了",
    "谢了",
    "嗯",
]
MALE_SLEEP_LINES = [
    "睡了 晚安",
    "累 先睡了",
    "晚安",
]
MALE_WALK_LINES = [
    "走了",
    "出去走走",
    "嗯",
]
MALE_FOLLOW_LINES = [
    "跟着你",
    "嗯 走吧",
    "行",
]


class Bubble(QWidget):
    """对话气泡窗口，显示在角色附近，不遮挡角色。用 QLabel 显示文字（最可靠）。"""
    MAX_W = 260
    PAD_X = 12
    PAD_TOP = 8
    PAD_BOTTOM = 16  # 留更多底部给小尾巴

    def __init__(self, name="", accent=(255, 105, 135)):
        super().__init__()
        self.name = name
        self.accent = accent
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        # 字体：延迟到实例创建时加载（QApplication 已存在，避免段错误）
        self.FONT = QFont(load_pet_font(), 10)
        # QLabel 处理文本：Qt 内部自动换行 + sizeHint，气泡不会再截断
        self.label = QLabel(self)
        self.label.setWordWrap(True)
        self.label.setFont(self.FONT)
        self.label.setStyleSheet("color: rgb(60,40,50); background: transparent; padding: 0; margin: 0;")
        self.label.setAlignment(Qt.AlignCenter)
        self._text = ""
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self._fade = QPropertyAnimation(self, b"windowOpacity")
        self._fade.setDuration(200)
        self._fade.setEasingCurve(QEasingCurve.InOutQuad)
        self.resize(200, 60)

    def _resize_label(self):
        self.label.setGeometry(self.PAD_X, self.PAD_TOP,
                               self.width() - 2 * self.PAD_X,
                               self.height() - self.PAD_TOP - self.PAD_BOTTOM)

    def _clear_hide_conn(self):
        try:
            self._fade.finished.disconnect(self.hide)
        except (TypeError, RuntimeError):
            pass

    def _fade_out(self):
        self._fade.stop()
        self._clear_hide_conn()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self.hide)
        self._fade.start()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._resize_label()  # 气泡尺寸变了自动同步 label

    def show_text(self, text, duration=2500):
        self._text = text
        self.label.setText(text)
        self.label.setFixedWidth(self.MAX_W - 2 * self.PAD_X)
        # QLabel.sizeHint 是 Qt 内部计算的最准确尺寸，绝不截断
        hint = self.label.sizeHint()
        w = min(self.MAX_W, hint.width() + 2 * self.PAD_X)
        h = hint.height() + self.PAD_TOP + self.PAD_BOTTOM
        self.resize(max(w, 80), max(h, 44))
        self._fade.stop()
        self._clear_hide_conn()
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._timer.start(duration)

    def set_stream_text(self, text):
        """流式输出：直接更新气泡文本（含首次显示），尺寸随内容自适应，防淡出"""
        self._text = text
        # 首次显示保护：清残留 hide 连接 + 置顶显示（防止气泡被旧连接瞬间隐藏）
        self._fade.stop()
        self._clear_hide_conn()
        self.setWindowOpacity(1.0)
        self.show()
        self.raise_()
        self.label.setText(text)
        self.label.setFixedWidth(self.MAX_W - 2 * self.PAD_X)
        hint = self.label.sizeHint()
        w = min(self.MAX_W, hint.width() + 2 * self.PAD_X)
        h = hint.height() + self.PAD_TOP + self.PAD_BOTTOM
        self.resize(max(w, 80), max(h, 44))
        self._resize_label()
        self._timer.start(6000)  # 持续显示中：不断重置，防中途淡出

    def paintEvent(self, event):
        # 只画背景+小尾巴，文字完全交给 QLabel（绝不截断）
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        p.setBrush(QColor(255, 255, 255, 235))
        p.setPen(QPen(QColor(255, 182, 193, 200), 2))
        p.drawRoundedRect(rect.adjusted(0, 0, 0, -8), 14, 14)
        p.setBrush(QColor(255, 255, 255, 235))
        p.setPen(Qt.NoPen)
        cx = self.width() // 2
        p.drawPolygon(QPoint(cx - 7, self.height() - 9), QPoint(cx + 7, self.height() - 9),
                      QPoint(cx, self.height() + 2))
        p.end()


class ReminderOverlay(QWidget):
    """全屏提醒动画：到点全屏显示大动画 + 文字（喝水/休息/吃饭等），自动淡出消失。
    全局单例：任何桌宠触发提醒都复用同一个全屏层，避免叠加。
    """
    _instance = None

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        super().__init__()
        screen = QApplication.primaryScreen().availableGeometry()
        self.setGeometry(screen)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)  # 不挡鼠标
        self.emoji = "⏰"
        self.action = "bell"   # water/coffee/food/walk/eyes/work/bell
        self.text = ""
        self.phase = 0
        self.particles = []
        self._fading = False
        self.is_active = False  # 提醒动画激活中：桌宠一切活动让路
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

    @staticmethod
    def match_emoji(text):
        """按提醒内容智能归类：返回 (emoji, action)。每类含多组同义词，
        没见过的词也能归到最接近的类别（如"写作业"→ 工作类）。
        """
        # 类别库：关键词越靠前优先级越高（按语义宽度组织）
        CATEGORIES = [
            ("💧", "water", ["水", "喝", "渴", "补水", "水分", "饮水"]),
            ("☕", "coffee", ["休息", "放松", "累", "番茄", "午休", "小憩", "歇", "充电", "摸鱼"]),
            ("🍚", "food", ["吃", "饭", "饿", "餐", "早点", "早饭", "午饭", "晚饭", "夜宵", "零食"]),
            ("🚶", "walk", ["站", "走", "动", "起身", "伸懒腰", "运动", "活动", "散步", "锻炼"]),
            ("👀", "eyes", ["眼", "远眺", "看远", "视力", "护眼", "眼睛", "放松眼"]),
            ("💻", "work", ["工作", "作业", "学习", "上班", "开会", "会议", "代码", "编程",
                            "报告", "ppt", "课件", "复习", "考试", "读书", "项目", "任务",
                            "deadline", "截止", "写", "改", "方案", "论文", "作业本"]),
        ]
        low = text.lower()
        for emoji, action, kws in CATEGORIES:
            if any(k in low for k in kws):
                return emoji, action
        return "⏰", "bell"

    def show_reminder(self, text, duration=4000):
        self.emoji, self.action = self.match_emoji(text)
        self.text = text
        self.phase = 0
        self.particles = []
        self._fading = False
        self.is_active = True  # 提醒期间优先级最高：桌宠所有活动让路
        self.setWindowOpacity(1.0)
        self.show()
        self.raise_()
        self.timer.start(30)
        # 显示 duration 后淡出
        QTimer.singleShot(duration, self._begin_fade)

    def _begin_fade(self):
        self._fading = True

    def _tick(self):
        self.phase += 1
        # 粒子推进
        w = self.width(); h = self.height()
        cx = w // 2
        alive = []
        for pt in self.particles:
            pt["y"] += pt["vy"]
            pt["x"] += pt.get("vx", 0)
            pt["life"] -= 1
            if pt["life"] > 0:
                alive.append(pt)
        # 按动作生成新粒子
        r = random.random
        if self.action == "water" and self.phase % 6 == 0:  # 水滴下落
            alive.append({"x": cx + r() * 220 - 110, "y": 0, "vy": 6 + r() * 4,
                          "life": 40, "e": "💧", "size": 22})
        elif self.action == "coffee" and self.phase % 5 == 0:  # 热气上升
            alive.append({"x": cx + r() * 160 - 80, "y": h * 0.62, "vy": -3 - r() * 2,
                          "life": 35, "e": "♨️", "size": 18})
        elif self.action == "food" and self.phase % 7 == 0:
            alive.append({"x": cx + r() * 300 - 150, "y": h * 0.75, "vy": -2 - r() * 2,
                          "life": 40, "e": random.choice(["🍚", "🥢", "🍽️"]), "size": 20})
        elif self.action == "walk" and self.phase % 6 == 0:
            alive.append({"x": r() * w, "y": h - 20, "vy": -3 - r() * 2,
                          "life": 35, "e": random.choice(["👟", "🦶"]), "size": 18})
        elif self.action == "eyes" and self.phase % 6 == 0:
            alive.append({"x": cx + r() * 300 - 150, "y": h * 0.7, "vy": -2,
                          "life": 40, "e": "👁️", "size": 20})
        elif self.action == "work" and self.phase % 5 == 0:  # 工作/学习：代码符号上飘
            alive.append({"x": cx + r() * 360 - 180, "y": h * 0.85, "vy": -2 - r() * 2,
                          "life": 40, "e": random.choice(["⌨️", "✏️", "📄", "🖊️", "💡"]), "size": 20})
        elif self.phase % 8 == 0:  # 默认星星飘
            alive.append({"x": r() * w, "y": h, "vy": -2 - r() * 2,
                          "life": 45, "e": random.choice(["✨", "⭐", "💫"]), "size": 16})
        self.particles = alive[:60]
        # 淡出
        if self._fading:
            op = self.windowOpacity() - 0.06
            if op <= 0:
                self.timer.stop()
                self.hide()
                self._fading = False
                self.is_active = False  # 提醒结束，桌宠恢复自由
            else:
                self.setWindowOpacity(op)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w // 2, int(h * 0.40)
        # 半透明深色背景（径向渐变，中心亮四周暗）
        grad = QRadialGradient(cx, cy, w * 0.7)
        grad.setColorAt(0, QColor(30, 40, 80, 70))
        grad.setColorAt(1, QColor(10, 15, 40, 150))
        p.fillRect(self.rect(), QBrush(grad))
        # 大 emoji 上下浮动 + 轻微放大
        bounce = math.sin(self.phase * 0.09) * 22
        scale = 1.0 + math.sin(self.phase * 0.05) * 0.06
        size = int(150 * scale)
        p.setFont(QFont("Segoe UI Emoji", size))
        p.drawText(QRect(cx - size, cy - size + int(bounce), size * 2, size * 2),
                   Qt.AlignCenter, self.emoji)
        # 粒子
        for pt in self.particles:
            p.setFont(QFont("Segoe UI Emoji", pt["size"]))
            p.drawText(QRect(int(pt["x"] - 20), int(pt["y"] - 20), 40, 40),
                       Qt.AlignCenter, pt["e"])
        # 标题 + 内容（艺术字体，白字带阴影）
        title = {"water": "该喝水啦！", "coffee": "休息一下吧！", "food": "该吃饭啦！",
                 "walk": "起来动一动！", "eyes": "看看远处！", "work": "该加油啦！",
                 "bell": "提醒时间到！"}.get(self.action, "提醒时间到！")
        p.setFont(QFont(load_pet_font(), 34, QFont.Bold))
        p.setPen(QColor(255, 255, 255, 255))
        p.drawText(QRect(0, int(h * 0.55), w, 60), Qt.AlignCenter, title)
        p.setFont(QFont(load_pet_font(), 22))
        p.setPen(QColor(255, 235, 240, 255))
        p.drawText(QRect(0, int(h * 0.55) + 62, w, 50), Qt.AlignCenter, self.text)
        p.end()


class ChatLogWindow(QWidget):
    """聊天记录窗口：两个桌宠 + 用户共用一个对话框。
    桌宠消息靠左（带头像），用户消息靠右；粉色可爱风与气泡统一。
    只记录真正的对话（聊天/划词/截图问答），日常随机台词不记录。
    """
    _instance = None
    AVATARS = {"user": "👤"}
    AVATAR_PIX = {}  # 桌宠名 → 形象素材图（PetWindow 创建时注册）
    ACTIVE_PET = None  # 对话框发送时回复的桌宠（最近活跃的）
    PET_INSTANCES = {}  # 所有桌宠实例：name → PetWindow（用于消息识别找谁）

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        super().__init__()
        self.setWindowTitle("💬 聊天记录")
        self.setWindowFlags(Qt.Window)
        self.setMinimumSize(400, 520)
        self.resize(440, 580)
        self.setStyleSheet("""
            ChatLogWindow { background: #fff5f7; border: 2px solid #ffc0cb; border-radius: 14px; }
            QLineEdit { background: white; border: 2px solid #ffd6e0; border-radius: 10px;
                        padding: 8px 12px; font-family: Microsoft YaHei; font-size: 13px; color: #3c2832; }
            QLineEdit:focus { border-color: #ff8fab; }
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { background: #ffeef2; width: 8px; border-radius: 4px; }
            QScrollBar::handle:vertical { background: #ffc0cb; border-radius: 4px; }
            QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
        """)
        # 标题栏：标题 + 关闭按钮
        head = QHBoxLayout()
        head.setContentsMargins(16, 12, 12, 4)
        title = QLabel("💬 聊天记录")
        title.setStyleSheet("font-family: Microsoft YaHei; font-size: 16px; font-weight: bold; color: #d4537e;")
        close_btn = QPushButton("✖")
        close_btn.setFixedSize(30, 30)
        close_btn.setStyleSheet("""
            QPushButton { background: #ffd6e0; border: none; border-radius: 15px;
                          font-size: 14px; color: #993556; }
            QPushButton:hover { background: #ff8fab; color: white; }
        """)
        close_btn.clicked.connect(self.hide)
        head.addWidget(title)
        head.addStretch()
        head.addWidget(close_btn)
        # 消息滚动区
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.msg_container = QWidget()
        self.msg_layout = QVBoxLayout(self.msg_container)
        self.msg_layout.setContentsMargins(12, 8, 12, 8)
        self.msg_layout.setSpacing(10)
        self.msg_layout.addStretch()
        self.scroll.setWidget(self.msg_container)
        # 输入区
        bottom = QHBoxLayout()
        bottom.setContentsMargins(12, 6, 12, 12)
        self.input = QLineEdit()
        self.input.setPlaceholderText("和她说点什么～（回车发送）")
        self.input.returnPressed.connect(self._send)
        send_btn = QPushButton("💌 发送")
        send_btn.setStyleSheet("""
            QPushButton { background: #ff8fab; color: white; border: none; border-radius: 10px;
                          padding: 8px 18px; font-family: Microsoft YaHei; font-size: 13px; }
            QPushButton:hover { background: #ff6f91; }
        """)
        send_btn.clicked.connect(self._send)
        bottom.addWidget(self.input, 1)
        bottom.addWidget(send_btn)
        # 组装
        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.addLayout(head)
        main.addWidget(self.scroll, 1)
        main.addLayout(bottom)

    def add_system(self, text):
        """居中灰色小字系统消息（如工具调用提示）"""
        row = QHBoxLayout()
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("color: #b08a96; font-size: 12px; font-family: Microsoft YaHei;")
        row.addWidget(lbl)
        self.msg_layout.insertLayout(self.msg_layout.count() - 1, row)
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()))

    def _bubble_style(self, mine):
        bg = "#ffffff"
        border = "#ff8fab" if mine else "#ffc0cb"
        return (f"QLabel {{ background: {bg}; border: 2px solid {border}; border-radius: 12px;"
                f" padding: 8px 12px; color: #3c2832; font-family: Microsoft YaHei;"
                f" font-size: 13px; }}")

    def _avatar_label(self, sender):
        """桌宠头像用形象素材图（圆形裁剪）；用户用 emoji"""
        pix = self.AVATAR_PIX.get(sender)
        if pix is not None and not pix.isNull():
            size = 36
            scaled = pix.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            mask = QBitmap(scaled.size())
            mask.clear()
            mp = QPainter(mask)
            mp.setBrush(Qt.black)
            mp.setPen(Qt.NoPen)
            mp.drawEllipse(0, 0, scaled.width(), scaled.height())
            mp.end()
            scaled.setMask(mask)
            label = QLabel()
            label.setFixedSize(size, size)
            label.setPixmap(scaled)
            return label
        label = QLabel(self.AVATARS.get(sender, "👤"))
        label.setFixedSize(36, 36)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("font-size: 20px; background: #ffeef2; border-radius: 18px;")
        return label

    def add_message(self, sender, text):
        """添加一条消息：sender = 'user' | 桌宠名"""
        text = text.strip()
        if not text:
            return
        # 桌宠消息显示时转换表情占位符 [捂脸] → 🤦
        if sender != "user":
            text = fix_emoji(text)
        row = QHBoxLayout()
        row.setSpacing(8)
        avatar = self._avatar_label(sender)
        bubble = QLabel(text)
        bubble.setWordWrap(True)
        bubble.setMaximumWidth(280)
        bubble.setStyleSheet(self._bubble_style(sender == "user"))
        name_tag = QLabel("你" if sender == "user" else sender)
        name_tag.setStyleSheet("color: #b08a96; font-size: 11px; font-family: Microsoft YaHei;")
        if sender == "user":
            # 用户消息靠右：名字+气泡+头像
            col = QVBoxLayout()
            col.setSpacing(2)
            col.addWidget(name_tag, alignment=Qt.AlignRight)
            col.addWidget(bubble, alignment=Qt.AlignRight)
            row.addStretch()
            row.addLayout(col)
            row.addWidget(avatar, alignment=Qt.AlignTop)
        else:
            # 桌宠消息靠左：头像+名字+气泡
            col = QVBoxLayout()
            col.setSpacing(2)
            col.addWidget(name_tag, alignment=Qt.AlignLeft)
            col.addWidget(bubble, alignment=Qt.AlignLeft)
            row.addWidget(avatar, alignment=Qt.AlignTop)
            row.addLayout(col)
            row.addStretch()
        self.msg_layout.insertLayout(self.msg_layout.count() - 1, row)
        # 滚动到底部
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()))

    def _send(self):
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        pet = self._pick_pet(text)
        if pet is None:
            self.add_message("user", text)
            self.add_message("欣悦", "先右键桌宠打开聊天，我才能回你哦～")
            return
        # 用户消息记录交给 _chat_with 统一处理（避免重复）
        pet._chat_with(text)

    def _pick_pet(self, text):
        """根据消息内容/历史选择回复桌宠：
        提到"业成"→业成；提到"欣悦"→欣悦；否则用最近活跃的。"""
        all_pets = [p for p in ChatLogWindow.PET_INSTANCES.values() if p]
        if "业成" in text:
            for p in all_pets:
                if p.name == "业成":
                    return p
        if "欣悦" in text:
            for p in all_pets:
                if p.name == "欣悦":
                    return p
        return self.ACTIVE_PET or (all_pets[0] if all_pets else None)


class PetWindow(QWidget):
    # AI 回复信号（object 类型可传 None）：后台线程 emit → 主线程槽安全执行
    ai_reply_signal = pyqtSignal(object)
    # 流式输出信号：增量文本 / 完成标志（True=成功 False=出错）
    ai_delta_signal = pyqtSignal(str)
    ai_done_signal = pyqtSignal(bool)
    # 截图 OCR 结果信号（worker 线程 → 主线程）
    screenshot_signal = pyqtSignal(str)
    # 工具调用可视化信号（worker 线程 → 主线程聊天记录窗口）
    tool_call_signal = pyqtSignal(str)
    # ReAct 推理链信号：思考过程 / 工具结果（worker 线程 → 主线程）
    reason_signal = pyqtSignal(str)
    observe_signal = pyqtSignal(str)
    # 工具提醒信号（分钟数, 内容）：工具 handler 在 worker 线程 → 信号投递主线程启定时器
    reminder_signal = pyqtSignal(int, str)
    # 小游戏触发信号（game 名）：LLM 触发桌宠应用内的小游戏
    minigame_signal = pyqtSignal(str)

    def __init__(self, frames_subdir=None, name="桌宠", theme="pink",
                 frames_dir=None, persona_file=None):
        super().__init__()
        self.name = name  # 桌宠名字（多实例用）
        self.frames_subdir = frames_subdir  # 帧图子目录（兼容：None/A/B）
        self.frames_dir = frames_dir        # 帧图完整路径（配置驱动优先）
        self.persona_file = persona_file    # 人格文件（配置驱动；None 按名字推断）
        self.partner = None  # 互动对象（另一桌宠）
        self.ai_reply_signal.connect(self._on_ai_reply)
        self.ai_delta_signal.connect(self._on_ai_delta)
        self.ai_done_signal.connect(self._on_ai_done)
        self.screenshot_signal.connect(self._on_screenshot_text)
        self.tool_call_signal.connect(self._on_tool_call_msg)
        self.reason_signal.connect(self._on_reason_msg)
        self.observe_signal.connect(self._on_observe_msg)
        # 主题色（pink 可爱 / blue 沉稳）+ 对应台词集
        self.theme = theme
        if theme == "blue":
            self.glow_colors = ((120, 170, 255, 55), (140, 190, 255, 26))
            self.particle_emoji = ["⭐", "💙", "💫", "✨", "🔵"]
            self.particle_color = (90, 140, 255)
            self.chat_lines = MALE_CHAT_LINES
            self.pet_lines = MALE_PET_LINES
            self.feed_lines = MALE_FEED_LINES
            self.sleep_lines = MALE_SLEEP_LINES
            self.walk_lines = MALE_WALK_LINES
            self.follow_lines = MALE_FOLLOW_LINES
        else:
            self.glow_colors = ((255, 190, 220, 55), (190, 220, 255, 28))
            self.particle_emoji = ["❤️", "💕", "✨", "⭐", "💗"]
            self.particle_color = (255, 80, 120)
            self.chat_lines = CHAT_LINES
            self.pet_lines = PET_LINES
            self.feed_lines = FEED_LINES
            self.sleep_lines = SLEEP_LINES
            self.walk_lines = WALK_LINES
            self.follow_lines = FOLLOW_LINES
        # 窗口属性
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        # 加载图片
        self.original_pix = QPixmap()
        if IMAGE_B64:
            self.original_pix.loadFromData(base64.b64decode(IMAGE_B64))
        else:
            #  fallback：同目录 character.png
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "character.png")
            if os.path.exists(path):
                self.original_pix.load(path)

        if self.original_pix.isNull():
            # 占位图
            self.original_pix = QPixmap(200, 300)
            self.original_pix.fill(Qt.transparent)
            p = QPainter(self.original_pix)
            p.setBrush(QColor(255, 192, 203))
            p.drawEllipse(50, 50, 100, 100)
            p.end()

        # 缩放与显示
        self.scale = 0.28  # 默认缩放比例
        self._update_size()

        # 位置
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.width() - self.width() - 60, screen.height() - self.height() - 80)

        # 拖动
        self._drag_pos = None
        self._press_pos = None
        self._moved = False

        # 动画状态
        self._set_state("idle")  # idle/jump/squash/shake/walk/sleep/follow/drag
        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self._anim_tick)
        self.anim_frame = 0
        self.anim_total = 0
        self.base_y = 0
        self.base_x = 0
        self.flip = False  # 是否水平翻转（跑步方向）

        # 互动轮次
        self.interact_index = 0

        # 走路 / 跟随
        self.walk_dir = 1
        self.follow_speed = 3
        self.base_x = 0
        self.base_y = 0
        self._last_global_x = 0
        self._drag_bob = 0

        # 对话气泡
        self.bubble = Bubble(name=self.name,
                             accent=self.particle_color if hasattr(self, 'particle_color') else (255, 105, 135))

        # AI 引擎（美团 LongCat-2.0，Persona 人格注入 + 记忆持久化）
        self.ai = None
        try:
            from ai.engine import AIEngine
            _persona = ""
            # 不同桌宠用各自 persona（配置驱动；默认：欣悦→persona.md，其他→persona_b.md）
            _here = os.path.dirname(os.path.abspath(__file__))
            if self.persona_file:
                _persona_file = self.persona_file
            else:
                _persona_file = "persona.md" if self.name == "欣悦" else "persona_b.md"
            _p = os.path.join(_here, _persona_file)
            if not os.path.exists(_p) and self.name != "欣悦":
                _p = os.path.join(_here, "persona.md")  # persona 缺失兜底
            if os.path.exists(_p):
                with open(_p, "r", encoding="utf-8") as _f:
                    _persona = _f.read()
            _hf = os.path.join(self._data_dir(), f"chat_history_{self.name}.json")
            self.ai = AIEngine(persona=_persona, history_file=_hf,
                               facts_file=os.path.join(self._data_dir(), "facts.json"))
            self._register_ai_tools()  # V2: Function Calling 工具注册
            # RAG：加载知识库（备忘录 + 本宠聊天历史 + persona）
            self.ai.build_knowledge([
                self._memo_path(),
                _hf,
                os.path.join(_here, _persona_file),
            ])
        except Exception:
            self.ai = None  # 无 AI 时聊天自动兜底本地台词
        # 注册到聊天记录窗口（用于识别消息找谁）
        try:
            ChatLogWindow.PET_INSTANCES[self.name] = self
        except Exception:
            pass

        # 右键菜单
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)

        # 置顶状态
        self._always_on_top = True

        # 多帧动画系统（自动加载 frames/ 目录）
        self.frame_sets = load_frames(self.frames_subdir, frames_dir=self.frames_dir)
        # 注册头像素材（聊天记录窗口用桌宠形象 = 帧图首帧 QPixmap）
        try:
            _frames = next(iter(self.frame_sets.values()))
            if _frames:
                ChatLogWindow.AVATAR_PIX[self.name] = _frames[0]  # 已是 QPixmap
            else:
                ChatLogWindow.AVATAR_PIX[self.name] = self.original_pix
        except Exception:
            ChatLogWindow.AVATAR_PIX[self.name] = self.original_pix
        self.frame_idx = 0
        self.frame_timer = QTimer(self)
        self.frame_timer.timeout.connect(self._frame_tick)
        self._sync_frame_timer()

        # 粒子特效（点击互动/喂食时飘爱心）
        self.particles = []
        self.particle_timer = QTimer(self)
        self.particle_timer.timeout.connect(self._particle_tick)

        # 全屏检测定时器：打游戏（全屏）时自动隐藏，游戏优先
        self._hidden_by_fullscreen = False
        self.fullscreen_timer = QTimer(self)
        self.fullscreen_timer.timeout.connect(self._check_fullscreen)
        self.fullscreen_timer.start(1500)

        # 摸头动画（卡通手抚摸）
        self.pet_anim = 0
        self.pet_timer = QTimer(self)
        self.pet_timer.timeout.connect(self._pet_tick)
        # 食物（喂食时随机出现，然后被吃掉）
        self.food = None

        # 心情 & 饱食度系统
        self.mood = 70
        self.full = 70
        self.stat_timer = QTimer(self)
        self.stat_timer.timeout.connect(self._stat_tick)
        self.stat_timer.start(60000)  # 每分钟衰减
        # 定时提醒（每 30 分钟提醒喝水/休息）
        self.remind_timer = QTimer(self)
        self.remind_timer.timeout.connect(self._remind)
        self.remind_timer.start(30 * 60 * 1000)
        # 头顶特效动画相位（乌云雨滴/饥饿标志浮动）
        self._fx_phase = 0

        # 甩飞弹回
        self.throw_vel = [0.0, 0.0]
        self.throw_angle = 0          # 翻滚旋转角度
        self._prev_pos = None
        self._prev_t = 0.0
        self._vx = 0.0
        self._vy = 0.0
        self.throw_timer = QTimer(self)
        self.throw_timer.timeout.connect(self._throw_tick)

        # 待机小动作（歪头）
        self.tilt_offset = 0

        # 载入记忆的设置（大小/位置/置顶）
        self._load_settings()

        # 聊天计时器（随机主动说话）
        self.chat_timer = QTimer(self)
        self.chat_timer.timeout.connect(self._random_chat)
        self.chat_timer.start(random.randint(25000, 50000))
        # 流式打字机：缓冲 + 逐字定时器（服务端 chunk 多大都逐字显示）
        self._type_buf = ""
        self._type_timer = QTimer(self)
        self._type_timer.timeout.connect(self._type_tick)
        # Agent 任务管理：提醒列表（可查询/取消）
        self._reminders = []

        self.show()

    # ---------- 尺寸与绘制 ----------
    def _update_size(self):
        # 基准图用帧图首帧（桌宠真实形象），帧图缺失才退回 original_pix
        src = self.original_pix
        for _frames in getattr(self, 'frame_sets', {}).values():
            if _frames:
                src = _frames[0]
                break
        w = int(src.width() * self.scale)
        h = int(src.height() * self.scale)
        self.setFixedSize(w, h)
        self._scaled_pix = src.scaled(
            w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._pix_cache = None  # 尺寸变化后清空帧缓存

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        # 帧动画优先：当前动作有帧图就用帧图，否则退回数学变形
        key = STATE_FRAME_MAP.get(self.state, self.state)
        fs = self.frame_sets.get(key)
        if fs:
            idx = self.frame_idx % len(fs)
            # 帧缓存：同尺寸+同帧+同翻转时复用，避免每帧重算缩放/翻转
            ckey = (key, idx, self.flip, self.width(), self.height())
            if getattr(self, "_pix_cache", None) and self._pix_cache[0] == ckey:
                pix = self._pix_cache[1]
            else:
                pix = fs[idx].scaled(self.width(), self.height(),
                                     Qt.KeepAspectRatio, Qt.SmoothTransformation)
                if self.flip:
                    pix = pix.transformed(QTransform().scale(-1, 1))
                self._pix_cache = (ckey, pix)
        else:
            pix = self._scaled_pix
        # 睡觉时变暗
        if self.state == "sleep":
            p.setOpacity(0.75)
        # 压扁效果
        sy = 1.0
        sx = 1.0
        if self.state == "squash":
            t = self.anim_frame / max(self.anim_total, 1)
            # 先压扁再回弹
            if t < 0.4:
                k = t / 0.4
                sy = 1.0 - 0.35 * k
                sx = 1.0 + 0.15 * k
            elif t < 0.7:
                k = (t - 0.4) / 0.3
                sy = 0.65 + 0.45 * k
                sx = 1.15 - 0.2 * k
            else:
                k = (t - 0.7) / 0.3
                sy = 1.10 - 0.10 * k
                sx = 0.95 + 0.05 * k
        if self.state == "jump":
            t = self.anim_frame / max(self.anim_total, 1)
            # 起跳时略微拉长
            if t < 0.2:
                sy = 1.0 + 0.1 * (t / 0.2)
            elif t > 0.8:
                sy = 1.0 + 0.1 * ((1 - t) / 0.2)

        xoff = 0
        yoff = 0
        # 计算角色当前显示矩形（阴影/光晕跟随跳动）
        if self.state in ("squash", "jump"):
            rw = int(pix.width() * sx)
            rh = int(pix.height() * sy)
            rx = (self.width() - rw) // 2
            ry = self.height() - rh
        elif self.state == "drag":
            bob = int(4 * math.sin(self._drag_bob * 0.9))
            rx, ry, rw, rh = 0, bob, pix.width(), pix.height()
        elif self.state == "throw":
            # 翻滚：以角色几何中心为轴旋转，光晕跟随实际旋转尺寸
            w, h = pix.width(), pix.height()
            trans = QTransform()
            trans.translate(w / 2.0, h / 2.0)
            trans.rotate(self.throw_angle)
            trans.translate(-w / 2.0, -h / 2.0)
            spinned = pix.transformed(trans)
            spinned = spinned.scaled(int(self.width() * 0.62),
                                     int(self.height() * 0.68),
                                     Qt.KeepAspectRatio, Qt.SmoothTransformation)
            rx = (self.width() - spinned.width()) // 2
            ry = self.height() - spinned.height() - 8
            rw, rh = spinned.width(), spinned.height()
        elif self.state == "sleep":
            lying = pix.transformed(QTransform().rotate(90))
            lying = lying.scaled(int(self.width() * 0.9), self.height() - 20,
                                 Qt.KeepAspectRatio, Qt.SmoothTransformation)
            rx = (self.width() - lying.width()) // 2
            ry = self.height() - lying.height() - 6
            rw, rh = lying.width(), lying.height()
        elif self.tilt_offset and self.state == "idle":
            rx = (self.width() - pix.width()) // 2
            ry = self.height() - pix.height()
            rw, rh = pix.width(), pix.height()
        else:
            rx, ry, rw, rh = 0, 0, pix.width(), pix.height()

        # 脚下阴影（跟随角色脚底；跳跃时缩小变淡，压扁时贴地加深）
        shadow_scale = 1.0
        shadow_alpha = 48
        if self.state == "jump":
            shadow_scale = 0.55
            shadow_alpha = 22
        elif self.state == "squash":
            shadow_scale = 1.2
            shadow_alpha = 62
        shadow_w = int(rw * 0.75 * shadow_scale)
        shadow_h = max(4, int(rw * 0.07 * shadow_scale))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, shadow_alpha))
        p.drawEllipse(rx + (rw - shadow_w) // 2, ry + rh - shadow_h,
                      shadow_w, shadow_h)
        # 角色背后光晕（跟随角色中心，随跳动上下移动；颜色按主题）
        gx = rx + rw // 2
        gy = ry + int(rh * 0.42)
        # 半径限制在窗口内，避免被裁剪成方形
        gr = int(min(self.width(), self.height()) * 0.52)
        g0, g1 = self.glow_colors
        # 靠近伙伴时（光晕相交）自动减淡，避免两个光晕重叠
        alpha_k = 1.0
        if self.partner and self.partner.isVisible():
            pax = self.partner.x() + self.partner.width() / 2
            pay = self.partner.y() + self.partner.height() / 2
            pd = math.hypot(pax - gx, pay - gy)
            if pd < gr * 1.6:
                alpha_k = max(0.15, pd / (gr * 1.6))
        grad = QRadialGradient(gx, gy, gr)
        grad.setColorAt(0, QColor(g0[0], g0[1], g0[2], int(g0[3] * alpha_k)))
        grad.setColorAt(0.6, QColor(g1[0], g1[1], g1[2], int(g1[3] * alpha_k)))
        grad.setColorAt(1, QColor(g1[0], g1[1], g1[2], 0))
        p.setBrush(QBrush(grad))
        p.drawEllipse(gx - gr, gy - gr, gr * 2, gr * 2)

        if self.state in ("squash", "jump"):
            draw_w = int(pix.width() * sx)
            draw_h = int(pix.height() * sy)
            xoff = (self.width() - draw_w) // 2
            yoff = self.height() - draw_h
            p.drawPixmap(xoff, yoff, draw_w, draw_h, pix)
        elif self.state == "drag":
            bob = int(4 * math.sin(self._drag_bob * 0.9))
            p.drawPixmap(0, bob, pix)
        elif self.state == "throw":
            # 翻滚旋转（已按几何中心旋转，光晕随其尺寸贴合）
            p.drawPixmap(rx, ry, spinned)
        elif self.state == "sleep":
            # 睡觉躺下：顺时针旋转 90°（头朝右）贴底部绘制
            p.drawPixmap(rx, ry, lying)
        elif self.tilt_offset and self.state == "idle":
            # 待机歪头小动作
            tilted = pix.transformed(QTransform().rotate(self.tilt_offset))
            p.drawPixmap(rx, ry, tilted)
        else:
            p.drawPixmap(0, 0, pix)

        # 睡觉时画 Zzz（靠近躺下角色头部：头朝右，在角色右上方）
        if self.state == "sleep":
            zx = rx + int(rw * 0.70)
            zy = ry + int(rh * 0.12)
            p.setPen(QColor(150, 150, 200))
            p.setFont(QFont("Arial", 14, QFont.Bold))
            p.drawText(zx, zy, "Z")
            p.setFont(QFont("Arial", 10, QFont.Bold))
            p.drawText(zx + 16, zy - 14, "z")
        # 摸头时画卡通手
        if self.state == "pet":
            self._draw_pet_hand(p)
        # 食物（喂食时随机出现）
        self._draw_food(p)
        # 心情/饥饿头顶特效（乌云雨滴 / 饿标志）
        if self.mood < 30:
            self._draw_mood_cloud(p)
        if self.full < 30:
            self._draw_hunger(p)
        # 粒子特效（爱心/星星，绘制在最上层）
        self._draw_particles(p)
        p.end()

    # ---------- 心情/饥饿头顶特效 ----------
    def _draw_mood_cloud(self, p):
        """心情不好：头顶乌云 + 小雨滴"""
        cx = self.width() // 2
        cloud_y = int(self.height() * 0.13)
        p.setPen(Qt.NoPen)
        # 云朵（三个叠加椭圆 + 底部矩形）
        p.setBrush(QColor(90, 90, 115, 230))
        p.drawEllipse(cx - 36, cloud_y - 16, 50, 34)
        p.drawEllipse(cx - 12, cloud_y - 26, 52, 42)
        p.drawEllipse(cx + 14, cloud_y - 16, 44, 32)
        p.drawRect(cx - 36, cloud_y - 6, 84, 24)
        # 云朵高光
        p.setBrush(QColor(140, 140, 170, 120))
        p.drawEllipse(cx - 18, cloud_y - 20, 30, 18)
        # 雨滴（循环下落）
        for i in range(5):
            x = cx - 26 + i * 13
            drop_y = int(cloud_y + 16 + ((self._fx_phase * 1.2 + i * 14) % 40))
            alpha = max(40, 200 - int(drop_y - cloud_y) * 3)
            p.setBrush(QColor(110, 150, 235, alpha))
            p.drawEllipse(x, drop_y, 6, 9)

    def _draw_hunger(self, p):
        """饥饿：头顶 🍽️ 上下浮动"""
        cx = self.width() // 2
        y = int(self.height() * 0.17) + int(5 * math.sin(self._fx_phase * 0.25))
        f = QFont("Segoe UI Emoji", 22)
        p.setFont(f)
        p.setPen(QColor(255, 150, 80, 230))
        p.drawText(QPoint(cx - 16, y), "🍽️")

    # ---------- 摸头动画（卡通手） ----------
    def _draw_pet_hand(self, p):
        """画一只卡通手从右侧伸出来摸头"""
        t = self.pet_anim / 24.0
        hand_x = int(self.width() * 0.70)
        bob = int(6 * math.sin(t * math.pi * 3))  # 上下抚摸
        hand_y = int(self.height() * 0.16) + bob   # 头顶位置
        # 手臂（肤色线条）
        arm_x0 = self.width() + 10
        arm_y0 = int(self.height() * 0.34)
        p.setPen(QPen(QColor(240, 205, 180, 230), 15))
        p.drawLine(arm_x0, arm_y0, hand_x, hand_y)
        # 手掌（椭圆）
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(240, 205, 180, 255))
        p.drawEllipse(hand_x - 14, hand_y - 12, 28, 24)
        # 三个小手指
        for i, dx in enumerate((-8, 0, 8)):
            p.setBrush(QColor(240, 205, 180, 255))
            p.drawEllipse(hand_x - 6 + dx, hand_y - 20, 12, 14)

    def _pet_tick(self):
        """摸头动画推进"""
        self.pet_anim += 1
        if self.pet_anim >= 24:  # 约 1.7 秒
            self.pet_timer.stop()
            self.pet_anim = 0
            self._set_state("idle")
        self.update()

    # ---------- 食物 ----------
    def _draw_food(self, p):
        if not self.food:
            return
        fd = self.food
        if fd['phase'] == 'move':
            # 从嘴巴右侧同一水平线，水平移到嘴边
            x = fd['sx'] + (fd['tx'] - fd['sx']) * fd['t']
            y = fd['y']
            size = fd['size']
            alpha = 255
        else:
            # 被啃食：每口大小跳减 + 咀嚼上下抖动
            progress = fd['bite'] + fd['bite_t']
            size = max(6, int(fd['size'] * (1 - 0.28 * progress)))
            x = fd['tx']
            y = fd['y'] + int(3 * math.sin(fd['bite_t'] * math.pi * 2))
            alpha = 255
        f = QFont("Segoe UI Emoji", size)
        p.setFont(f)
        p.setPen(QColor(255, 90, 60, alpha))
        p.drawText(QPoint(int(x - size), int(y - size)), fd['emoji'])

    # ---------- 全屏检测（游戏优先，自动隐藏） ----------
    def _check_fullscreen(self):
        """检测前台是否全屏应用（游戏/播放器），是则隐藏桌宠，退出全屏恢复"""
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if hwnd == 0 or hwnd == int(self.winId()):
                return
            rect = wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            sw = ctypes.windll.user32.GetSystemMetrics(0)
            sh = ctypes.windll.user32.GetSystemMetrics(1)
            # 前台窗口覆盖整个屏幕 → 全屏
            is_fullscreen = (rect.left <= 1 and rect.top <= 1 and
                             rect.right >= sw - 1 and rect.bottom >= sh - 1)
            if is_fullscreen and self.isVisible():
                self.hide()                       # 全屏游戏：隐藏桌宠
                self._hidden_by_fullscreen = True
            elif not is_fullscreen and getattr(self, '_hidden_by_fullscreen', False):
                self.show()                       # 退出全屏：恢复显示
                self._hidden_by_fullscreen = False
        except Exception:
            pass

    # ---------- 粒子特效 ----------
    def _spawn_hearts(self, count=4):
        """在角色周围生成飘浮的爱心/星星粒子"""
        cx = self.width() // 2
        cy = self.height() // 2
        for _ in range(count):
            self.particles.append({
                'x': cx + random.randint(-45, 45),
                'y': cy + random.randint(-35, 25),
                'vx': (random.random() - 0.5) * 1.4,
                'vy': -1.6 - random.random() * 1.2,
                'life': 40 + random.randint(0, 25),
                'max_life': 65,
                'size': random.randint(10, 20),
                'emoji': random.choice(self.particle_emoji),
            })
        if not self.particle_timer.isActive():
            self.particle_timer.start(30)

    def _particle_tick(self):
        alive = []
        for pt in self.particles:
            pt['x'] += pt['vx']
            pt['y'] += pt['vy']
            pt['vy'] += 0.03  # 向上渐缓
            pt['life'] -= 1
            if pt['life'] > 0:
                alive.append(pt)
        self.particles = alive
        # 头顶特效动画相位推进（乌云雨滴/饥饿标志/星星闪烁）
        self._fx_phase += 1
        # 粒子/食物/低状态/睡眠（需持续动画）存在时才保持定时器
        need_fx = (self.mood < 30 or self.full < 30)
        if not alive and not self.food and not need_fx:
            self.particle_timer.stop()
        # 食物动画：水平移到嘴边 → 分3口啃食掉
        if self.food:
            fd = self.food
            if fd['phase'] == 'move':
                fd['t'] += 0.05
                if fd['t'] >= 1.0:
                    fd['phase'] = 'bite'
            else:
                fd['bite_t'] += 0.10
                if fd['bite_t'] >= 1.0:
                    fd['bite'] += 1
                    fd['bite_t'] = 0.0
                    if fd['bite'] >= 3:
                        self.food = None
        self.update()

    def _draw_particles(self, p):
        for pt in self.particles:
            # 透明度随生命衰减
            ratio = pt['life'] / pt['max_life']
            alpha = int(220 * min(1.0, ratio * 1.6))
            f = QFont("Segoe UI Emoji", pt['size'])
            p.setFont(f)
            p.setPen(QColor(*self.particle_color, alpha))
            p.drawText(QPoint(int(pt['x'] - pt['size']), int(pt['y'] - pt['size'])),
                       pt['emoji'])

    # ---------- 时间感知问候 ----------
    def _time_greeting(self):
        h = QTime.currentTime().hour()
        if 5 <= h < 9:
            return "早安呀～今天也要元气满满哦！"
        if 9 <= h < 12:
            return "上午好～工作加油，摸摸头～"
        if 12 <= h < 14:
            return "午安～记得吃午饭哦！"
        if 14 <= h < 18:
            return "下午好～喝口水休息一下～"
        if 18 <= h < 22:
            return "晚上好～今天辛苦啦！"
        return "夜深了…早点休息呀～"

    # ---------- 心情 & 饱食度 ----------
    def _stat_tick(self):
        """每分钟：饱食度/心情缓慢衰减，低状态时主动反馈"""
        self.full = max(0, self.full - 2)
        self.mood = max(0, self.mood - 1)
        r = random.random()
        if self.full < 30 and r < 0.35:
            self._say(random.choice(["好饿啊…想吃东西…", "肚子咕咕叫了～",
                                     "喂我吃点嘛～", "饿得没力气了…"]))
        elif self.mood < 30 and r < 0.35:
            self._say(random.choice(["哼！不开心…", "呜呜…心情不好",
                                     "要摸摸头才开心", "不开心，求哄～"]))
        elif self.mood > 80 and r < 0.15:
            self._say(random.choice(["今天好开心呀！", "最喜欢你啦～",
                                     "嘿嘿，心情超棒！", "被你宠得好幸福～"]))
        # 低状态时确保头顶特效动画运行
        if (self.mood < 30 or self.full < 30) and not self.particle_timer.isActive():
            self.particle_timer.start(30)

    def _show_stats(self):
        """可爱风格的状态面板（心情/饱食度进度条）"""
        dlg = QDialog(self)
        dlg.setWindowTitle("📊 状态")
        dlg.setFixedWidth(280)
        dlg.setStyleSheet("""
            QDialog { background: #fff5f7; }
            QLabel { color: #5a4a52; font-family: "Microsoft YaHei"; font-size: 14px; }
            QProgressBar { border: none; border-radius: 10px; background: #ffe4ec;
                           height: 20px; text-align: center; color: #5a4a52;
                           font-family: "Microsoft YaHei"; font-size: 12px; font-weight: bold; }
            QProgressBar::chunk { border-radius: 10px; }
            QPushButton { background: #ffb6c1; color: white; border: none;
                          border-radius: 12px; padding: 6px 20px;
                          font-family: "Microsoft YaHei"; font-size: 13px; font-weight: bold; }
            QPushButton:hover { background: #ff8fa3; }
        """)
        lay = QVBoxLayout(dlg)
        lay.setSpacing(8)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.addWidget(QLabel("❤️ 心情"))
        mb = QProgressBar()
        mb.setRange(0, 100)
        mb.setValue(self.mood)
        mb.setFormat(f"%v / 100")
        mb.setStyleSheet("QProgressBar::chunk { background: #ff7f9f; }")
        lay.addWidget(mb)
        lay.addWidget(QLabel("🍗 饱食度"))
        fb = QProgressBar()
        fb.setRange(0, 100)
        fb.setValue(self.full)
        fb.setFormat(f"%v / 100")
        fb.setStyleSheet("QProgressBar::chunk { background: #ffb347; }")
        lay.addWidget(fb)
        hint = QLabel("💡 喂食 +25 饱食度，摸摸头 +10 心情")
        hint.setStyleSheet("color: #b08a96; font-size: 12px;")
        lay.addWidget(hint)
        ok = QPushButton("知道啦～")
        ok.clicked.connect(dlg.accept)
        lay.addWidget(ok, alignment=Qt.AlignCenter)
        dlg.exec_()

    def _pretty_box(self, title, html_body):
        """粉色可爱风格消息框"""
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setTextFormat(Qt.RichText)
        box.setText(html_body)
        box.setStyleSheet("""
            QMessageBox { background: #fff5f7; }
            QLabel { color: #5a4a52; font-family: "Microsoft YaHei";
                     font-size: 16px; padding: 8px 6px; }
            QPushButton { background: #ffb6c1; color: white; border: none;
                          border-radius: 14px; padding: 8px 26px;
                          font-family: "Microsoft YaHei"; font-size: 14px; font-weight: bold; }
            QPushButton:hover { background: #ff8fa3; }
            QPushButton:pressed { background: #ff7590; }
        """)
        box.exec_()

    # ---------- 设置持久化 ----------
    def _load_settings(self):
        try:
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    s = json.load(f)
                self.scale = float(s.get("scale", self.scale))
                self._update_size()
                self.move(int(s.get("x", self.x())), int(s.get("y", self.y())))
                if not s.get("top", True):
                    self._toggle_top()
                # 心情/饱食度持久化
                if "mood" in s:
                    self.mood = int(s["mood"])
                if "full" in s:
                    self.full = int(s["full"])
        except Exception:
            pass

    def _save_settings(self):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "scale": self.scale,
                    "x": self.x(),
                    "y": self.y(),
                    "top": self._always_on_top,
                    "mood": self.mood,
                    "full": self.full,
                }, f, ensure_ascii=False)
        except Exception:
            pass

    def closeEvent(self, e):
        self._save_settings()
        super().closeEvent(e)

    def _remind(self):
        """定时提醒：喝水/休息（30 分钟一次）"""
        if self.state == "sleep":
            return  # 睡觉不打扰
        if self.theme == "blue":
            lines = ["该喝水了。", "起来活动一下。", "休息一会儿吧。", "注意用眼，看看远处。"]
        else:
            lines = ["该喝水啦～", "起来活动一下嘛！", "休息一会儿吧～", "眼睛累了吧，看看远处～"]
        self._say(random.choice(lines), 3500)

    # ---------- 迷你小游戏 ----------
    def _choose_rock_paper(self):
        """可爱风格的出拳选择界面：三个大 emoji 按钮"""
        dlg = QDialog(self)
        dlg.setWindowTitle("✊✌️✋ 猜拳")
        dlg.setFixedWidth(340)
        dlg.setStyleSheet("""
            QDialog { background: #fff5f7; }
            QLabel { color: #5a4a52; font-family: "Microsoft YaHei"; }
            QPushButton { background: #ffffff; border: 2px solid #ffd0dc;
                          border-radius: 18px; font-family: "Segoe UI Emoji";
                          font-size: 44px; min-width: 84px; min-height: 72px; }
            QPushButton:hover { background: #ffe4ec; border-color: #ffb6c1; }
            QPushButton:pressed { background: #ffd0dc; }
        """)
        lay = QVBoxLayout(dlg)
        lay.setSpacing(10)
        lay.setContentsMargins(20, 18, 20, 16)
        tip = QLabel("<div style='text-align:center;font-size:17px;font-weight:bold'>你出什么？</div>")
        lay.addWidget(tip)
        row = QHBoxLayout()
        row.setSpacing(16)
        result = {"v": None}
        for emoji, name, idx in (("✊", "石头", 0), ("✌️", "剪刀", 1), ("✋", "布", 2)):
            col = QVBoxLayout()
            col.setSpacing(2)
            btn = QPushButton(emoji)
            btn.clicked.connect(
                lambda _, i=idx: (result.__setitem__("v", i), dlg.accept()))
            col.addWidget(btn, alignment=Qt.AlignCenter)
            lbl = QLabel(f"<div style='text-align:center;color:#b08a96;font-size:13px'>{name}</div>")
            col.addWidget(lbl, alignment=Qt.AlignCenter)
            row.addLayout(col)
        lay.addLayout(row)
        dlg.exec_()
        return result["v"]

    def _do_rock_paper(self):
        user_idx = self._choose_rock_paper()
        if user_idx is None:
            return
        # 桌宠出拳策略：60% 出"能赢你"的拳（更聪明），40% 随机（放水）
        if random.random() < 0.6:
            pet_idx = (user_idx + 2) % 3  # 出能赢用户的拳
        else:
            pet_idx = random.randint(0, 2)
        emojis = ["✊", "✌️", "✋"]
        user_emoji, pet_emoji = emojis[user_idx], emojis[pet_idx]
        # 判定：(user - pet) % 3 == 2 用户胜；== 1 用户输；== 0 平局
        diff = (user_idx - pet_idx) % 3
        if diff == 0:
            result, color, mood_delta = "平局～嘿嘿", "#8a8a8a", 0
            self._say("平局～再来一局！")
        elif diff == 2:
            result, color, mood_delta = "你赢啦！", "#ff6b81", -5
            self._say("你赢啦…哼！")
        else:
            result, color, mood_delta = "我赢啦！", "#7c6cf0", 10
            self._say("耶！我赢啦！")
        self.mood = max(0, min(100, self.mood + mood_delta))
        self._game_result_dialog("✊✌️✋ 猜拳",
                                 "你", user_emoji,
                                 "我", pet_emoji,
                                 result, color)
        self._spawn_hearts(2)

    def _do_dice(self):
        n = random.randint(1, 6)
        self._say(f"🎲 {n} 点！")
        self._game_result_dialog("🎲 掷骰子",
                                 "", "🎲",
                                 "点数", f"{n}",
                                 f"我掷出了 <b>{n}</b> 点！", "#ff6b81")
        self._spawn_hearts(2)

    def _guess_input(self, tip_text):
        """可爱风格的猜数字输入界面"""
        dlg = QDialog(self)
        dlg.setWindowTitle("🔢 猜数字")
        dlg.setFixedWidth(300)
        dlg.setStyleSheet("""
            QDialog { background: #fff5f7; }
            QLabel { color: #5a4a52; font-family: "Microsoft YaHei"; }
            QSpinBox { background: #ffffff; border: 2px solid #ffd0dc;
                       border-radius: 12px; font-family: "Microsoft YaHei";
                       font-size: 26px; color: #5a4a52; padding: 6px 10px;
                       min-height: 44px; }
            QSpinBox::up-button, QSpinBox::down-button { width: 0; border: none; }
            QPushButton { background: #ffb6c1; color: white; border: none;
                          border-radius: 14px; padding: 10px 40px;
                          font-family: "Microsoft YaHei"; font-size: 16px; font-weight: bold; }
            QPushButton:hover { background: #ff8fa3; }
            QPushButton:pressed { background: #ff7590; }
        """)
        lay = QVBoxLayout(dlg)
        lay.setSpacing(12)
        lay.setContentsMargins(24, 20, 24, 18)
        tip = QLabel(f"<div style='text-align:center;font-size:16px;font-weight:bold'>{tip_text}</div>")
        lay.addWidget(tip)
        spin = QSpinBox()
        spin.setRange(1, 100)
        spin.setValue(50)
        spin.setAlignment(Qt.AlignCenter)
        lay.addWidget(spin)
        ok = QPushButton("🎯 猜！")
        ok.clicked.connect(dlg.accept)
        lay.addWidget(ok, alignment=Qt.AlignCenter)
        if dlg.exec_():
            return spin.value()
        return None

    def _do_guess_number(self):
        """猜数字：桌宠心里想一个 1~100 的数，你猜"""
        target = random.randint(1, 100)
        attempts = 0
        self._say("我想了一个 1~100 的数，你猜！", 3000)
        tip = "我想到一个数啦（1~100）<br>猜猜看？"
        while True:
            guess = self._guess_input(tip)
            if guess is None:
                self._say("不玩啦？那下次再来～", 2500)
                return
            attempts += 1
            if guess == target:
                self.mood = min(100, self.mood + 10)
                self._spawn_hearts(5)
                self._say(f"猜对啦！就是 {target}！用了 {attempts} 次～", 3500)
                return
            hint = "小了" if guess < target else "大了"
            tip = f"提示：<b>{hint}</b>啦～<br>再猜一次！"
            self._say(f"{hint}哦！再试一次～", 2500)
            if attempts >= 10:
                self._say(f"猜不到吧？答案是 {target}～", 3000)
                return

    def _game_result_dialog(self, title, left_label, left_emoji,
                            right_label, right_emoji, result_text, result_color):
        """可爱对局结果弹窗：两个大 emoji 并排 + 结果"""
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setStyleSheet("""
            QDialog { background: #fff5f7; }
            QLabel { color: #5a4a52; font-family: "Microsoft YaHei"; }
            QPushButton { background: #ffb6c1; color: white; border: none;
                          border-radius: 14px; padding: 8px 26px;
                          font-family: "Microsoft YaHei"; font-size: 14px; font-weight: bold; }
            QPushButton:hover { background: #ff8fa3; }
        """)
        lay = QVBoxLayout(dlg)
        lay.setSpacing(8)
        lay.setContentsMargins(28, 20, 28, 16)
        row = QHBoxLayout()
        u = QLabel(f"<div style='text-align:center;font-size:52px'>{left_emoji}</div>"
                   f"<div style='text-align:center;color:#b08a96;font-size:13px'>{left_label}</div>")
        vs = QLabel("<div style='text-align:center;color:#d0a0b0;font-size:22px;padding:14px 10px'>VS</div>")
        p = QLabel(f"<div style='text-align:center;font-size:52px'>{right_emoji}</div>"
                   f"<div style='text-align:center;color:#b08a96;font-size:13px'>{right_label}</div>")
        row.addStretch()
        row.addWidget(u)
        row.addWidget(vs)
        row.addWidget(p)
        row.addStretch()
        lay.addLayout(row)
        res = QLabel(f"<div style='text-align:center;font-size:20px;font-weight:bold;"
                     f"color:{result_color};margin-top:4px'>{result_text}</div>")
        lay.addWidget(res)
        ok = QPushButton("好耶～")
        ok.clicked.connect(dlg.accept)
        lay.addWidget(ok, alignment=Qt.AlignCenter)
        dlg.exec_()

    # ---------- 待机小动作 ----------
    def _idle_action(self):
        """待机时随机触发小动作（歪头/表情气泡）"""
        if self.state != "idle":
            return
        r = random.random()
        if r < 0.25:
            # 歪头几帧
            self.tilt_offset = random.choice([-7, 7])
            QTimer.singleShot(500, self._untilt)
            self.update()
        elif r < 0.45:
            # 表情气泡
            self._say(random.choice(["❤️", "😊", "✨", "💗", "⭐"]), 1500)

    def _untilt(self):
        self.tilt_offset = 0
        self.update()

    # ---------- 鼠标事件 ----------
    def mouseDoubleClickEvent(self, e):
        # 双击切换跟随鼠标
        if e.button() == Qt.LeftButton:
            self._do_follow()
            e.accept()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            # 用户介入：解除贴贴锁定
            if getattr(self, "manager", None) and self.manager.locked:
                self.manager._unlock()
            self._press_pos = e.globalPos()
            self._drag_pos = e.globalPos() - self.frameGeometry().topLeft()
            self._moved = False
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() & Qt.LeftButton:
            new_pos = e.globalPos() - self._drag_pos
            if (e.globalPos() - self._press_pos).manhattanLength() > 5:
                self._moved = True
                # 拖动时进入跑步状态
                if self.state not in ("jump", "squash", "shake"):
                    self._set_state("drag")
                    self.flip = (e.globalPos().x() < self._last_global_x) if hasattr(self, '_last_global_x') else False
                self.move(new_pos)
                self._last_global_x = e.globalPos().x()
                # 拖动时上下轻微浮动模拟跑步
                self._drag_bob = (self._drag_bob + 1) % 8 if hasattr(self, '_drag_bob') else 0
                # 记录速度（甩飞检测用）
                now = time.monotonic()
                if self._prev_pos is not None and self._prev_t:
                    dt = now - self._prev_t
                    if dt > 0:
                        self._vx = (e.globalPos().x() - self._prev_pos.x()) / dt
                        self._vy = (e.globalPos().y() - self._prev_pos.y()) / dt
                self._prev_pos = e.globalPos()
                self._prev_t = now
                # 实时碰撞检测：拖动时撞到伙伴 → 撞飞或推开（严格不重叠）
                self._collide_with_partner()
            e.accept()

    def _collide_with_partner(self):
        """拖动时与伙伴的实时碰撞：拖拽中为无敌状态，只推开防重叠（不撞飞）"""
        p = self.partner
        if not p or not p.isVisible():
            return
        ax = self.x() + self.width() / 2
        ay = self.y() + self.height() / 2
        bx = p.x() + p.width() / 2
        by = p.y() + p.height() / 2
        dist = math.hypot(bx - ax, by - ay)
        ra = self.width() * 0.40
        rb = p.width() * 0.40
        if dist >= (ra + rb) * 0.85:
            return
        # 只推开：严格不重叠（撞飞只在飞行状态下由 PetManager 触发）
        dx = ax - bx
        dy = ay - by
        if math.hypot(dx, dy) < 1:
            dx, dy = 1, 0
        push = 30
        nx = p.x() - int(dx / math.hypot(dx, dy) * push)
        ny = p.y() - int(dy / math.hypot(dx, dy) * push)
        sw = QApplication.primaryScreen().availableGeometry().width()
        sh = QApplication.primaryScreen().availableGeometry().height()
        nx = max(0, min(nx, sw - p.width()))
        ny = max(0, min(ny, sh - p.height()))
        p.move(nx, ny)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._drag_pos:
            if not self._moved:
                self._on_click()
            else:
                # 甩飞检测：速度够快就甩出去弹回
                speed = math.hypot(self._vx, self._vy)
                if speed > 2500:
                    # 固定飞行初速（与鼠标拖拽速度无关，方向沿拖拽方向）
                    FIXED_SPEED = 200.0
                    if speed > 1:
                        dir_x = self._vx / speed
                        dir_y = self._vy / speed
                    else:
                        dir_x, dir_y = 1, 0
                    self.throw_vel = [dir_x * FIXED_SPEED, dir_y * FIXED_SPEED]
                    self._set_state("throw")
                    self.throw_timer.start(16)
                else:
                    # 结束拖动，恢复 idle
                    if self.state == "drag":
                        self._set_state("idle")
                        self.update()
            self._drag_pos = None
            self._prev_pos = None
            self._prev_t = 0.0
            e.accept()

    def _throw_tick(self):
        """甩飞弹回：翻滚旋转 + 撞边缘反弹（每次碰撞大幅减速）"""
        self.throw_vel[0] *= 0.96
        self.throw_vel[1] *= 0.96
        # 翻滚：速度越快转得越快
        speed = abs(self.throw_vel[0]) + abs(self.throw_vel[1])
        self.throw_angle = (self.throw_angle + speed * 0.07) % 360
        nx = self.x() + int(self.throw_vel[0])
        ny = self.y() + int(self.throw_vel[1])
        sw = QApplication.primaryScreen().availableGeometry().width()
        sh = QApplication.primaryScreen().availableGeometry().height()
        # 边缘反弹（每次碰撞损耗约 68% 速度，更温和）
        if nx < 0:
            nx = 0
            self.throw_vel[0] = abs(self.throw_vel[0]) * 0.32
        elif nx + self.width() > sw:
            nx = sw - self.width()
            self.throw_vel[0] = -abs(self.throw_vel[0]) * 0.32
        if ny < 0:
            ny = 0
            self.throw_vel[1] = abs(self.throw_vel[1]) * 0.32
        elif ny + self.height() > sh:
            ny = sh - self.height()
            self.throw_vel[1] = -abs(self.throw_vel[1]) * 0.32
        self.move(nx, ny)
        self.update()
        if speed < 10:
            self.throw_timer.stop()
            self.throw_angle = 0
            self._anim_squash()  # 落地压扁缓冲（自动回 idle）
            self._say(random.choice(["晕乎乎的…", "转圈圈了～", "呼…站稳了！"]))

    def wheelEvent(self, e):
        # 滚轮缩放
        delta = e.angleDelta().y()
        if delta > 0:
            self.scale = min(self.scale * 1.1, 1.5)
        else:
            self.scale = max(self.scale / 1.1, 0.08)
        # 保持中心位置
        cx = self.x() + self.width() // 2
        cy = self.y() + self.height() // 2
        self._update_size()
        self.move(cx - self.width() // 2, cy - self.height() // 2)
        self.update()
        e.accept()

    # ---------- 点击互动 ----------
    def _on_click(self):
        actions = [self._anim_jump, self._anim_squash, self._anim_shake]
        actions[self.interact_index % len(actions)]()
        self.interact_index += 1
        # 飘爱心粒子
        self._spawn_hearts(3)
        # 随机对话
        self._say(random.choice(self.chat_lines))

    def _anim_jump(self):
        self._start_anim("jump", 24)

    def _anim_squash(self):
        self._start_anim("squash", 26)

    def _anim_shake(self):
        self._start_anim("shake", 20)

    def _start_anim(self, state, frames):
        self._set_state(state)
        self.anim_frame = 0
        self.anim_total = frames
        self.base_x = self.x()
        self.base_y = self.y()
        self.anim_timer.start(16)

    def _anim_tick(self):
        self.anim_frame += 1
        if self.state == "jump":
            t = self.anim_frame / self.anim_total
            jump_h = 80 * math.sin(t * math.pi)
            self.move(self.base_x, int(self.base_y - jump_h))
        elif self.state == "shake":
            t = self.anim_frame / self.anim_total
            offset = int(12 * math.sin(t * math.pi * 4))
            self.move(self.base_x + offset, self.base_y)
        elif self.state == "squash":
            pass  # 压扁在 paintEvent 里处理
        self.update()

        if self.anim_frame >= self.anim_total:
            self.anim_timer.stop()
            if self.state in ("jump", "shake"):
                self.move(self.base_x, self.base_y)
            self._set_state("idle")
            self.update()

    # ---------- 多帧动画播放器 ----------
    def _set_state(self, state):
        """统一状态入口：切换状态并同步帧播放器"""
        self.state = state
        if hasattr(self, 'frame_timer'):
            self._sync_frame_timer()

    def _frame_tick(self):
        """帧播放器推进：只负责画面，位移/变形仍由原 anim_timer 负责"""
        self.frame_idx += 1
        self.update()

    def _sync_frame_timer(self):
        """根据当前状态决定帧播放器是否运行、帧率多少"""
        key = STATE_FRAME_MAP.get(self.state, self.state)
        fs = self.frame_sets.get(key)
        if fs:
            fps = FRAME_FPS.get(self.state, 8)
            self.frame_timer.start(int(1000 / fps))
            if self.frame_idx >= len(fs):
                self.frame_idx = 0
        else:
            self.frame_timer.stop()
            self.frame_idx = 0

    # ---------- 对话气泡 ----------
    def _say(self, text, duration=2500):
        # 气泡放在角色头顶上方，不遮挡
        self.bubble.show_text(text, duration)
        self._position_bubble()

    def _position_bubble(self):
        # 气泡居中于角色顶部上方
        bx = self.x() + self.width() // 2 - self.bubble.width() // 2
        by = self.y() - self.bubble.height() - 5
        # 防止超出屏幕顶部
        screen = QApplication.primaryScreen().availableGeometry()
        if by < screen.top() + 5:
            by = self.y() + 10  # 放右侧
            bx = self.x() + self.width() + 5
        # 钳制在屏幕内（长回复大气泡不超出左右边缘）
        bx = max(screen.left() + 4, min(bx, screen.right() - self.bubble.width() - 4))
        self.bubble.move(bx, by)
        self.bubble.raise_()

    def moveEvent(self, e):
        super().moveEvent(e)
        if hasattr(self, 'bubble') and self.bubble.isVisible():
            self._position_bubble()

    def _random_chat(self):
        # 提醒优先级最高：全屏动画期间不随机说话打扰
        if ReminderOverlay.instance().is_active:
            self.chat_timer.start(15000)
            return
        if self.state == "idle":
            # 25% 概率说时间问候，30% 概率触发待机小动作，其余随机台词
            r = random.random()
            if r < 0.25:
                self._say(self._time_greeting())
            elif r < 0.55:
                self._idle_action()
            else:
                self._say(random.choice(self.chat_lines))
        self.chat_timer.start(random.randint(30000, 60000))

    # ---------- 右键菜单 ----------
    def _show_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background: white; border: 1px solid #ffc0cb; border-radius: 8px; padding: 4px; }
            QMenu::item { padding: 8px 24px; border-radius: 4px; font-family: Microsoft YaHei; font-size: 13px; }
            QMenu::item:selected { background: #ffe4ec; }
        """)
        a_chat = menu.addAction("💬 陪我聊聊天")
        a_group = menu.addAction("🎭 问他俩（多桌宠讨论）")
        a_explain = menu.addAction("🔍 解释剪贴板文字")
        a_snap = menu.addAction("📷 问我截图")
        a_log = menu.addAction("📜 聊天记录")
        a_pet = menu.addAction("🤚 摸摸头")
        a_feed = menu.addAction("🍰 喂吃的")
        menu.addSeparator()
        a_walk = menu.addAction("🚶 让她走路")
        a_sleep = menu.addAction("😴 让她睡觉")
        a_follow = menu.addAction("👀 跟随鼠标")
        menu.addSeparator()
        a_rps = menu.addAction("✊✌️✋ 猜拳")
        a_dice = menu.addAction("🎲 掷骰子")
        a_guess = menu.addAction("🔢 猜数字")
        menu.addSeparator()
        a_stats = menu.addAction("📊 查看状态")
        a_size = menu.addAction("🔍 调整大小")
        a_top = menu.addAction("📌 置顶开关")
        menu.addSeparator()
        # 双桌宠单独开关
        a_hide_self = menu.addAction(f"🙈 隐藏{self.name}")
        a_show_other = menu.addAction(f"👋 显示{self.partner.name if self.partner else '对方'}")
        menu.addSeparator()
        a_quit = menu.addAction("❌ 退出程序")

        action = menu.exec_(self.mapToGlobal(pos))
        if action == a_chat:
            self._do_chat()
        elif action == a_group:
            self._group_chat()
        elif action == a_explain:
            self._explain_clipboard()
        elif action == a_snap:
            self._ask_screenshot()
        elif action == a_log:
            ChatLogWindow.ACTIVE_PET = self
            w = ChatLogWindow.instance()
            w.show()
            w.raise_()
            w.activateWindow()
        elif action == a_pet:
            self._do_pet()
        elif action == a_feed:
            self._do_feed()
        elif action == a_walk:
            self._do_walk()
        elif action == a_sleep:
            self._do_sleep()
        elif action == a_follow:
            self._do_follow()
        elif action == a_rps:
            self._do_rock_paper()
        elif action == a_dice:
            self._do_dice()
        elif action == a_guess:
            self._do_guess_number()
        elif action == a_stats:
            self._show_stats()
        elif action == a_size:
            self._do_size()
        elif action == a_top:
            self._toggle_top()
        elif action == a_hide_self:
            # 禁止同时隐藏两个桌宠
            if self.partner and not self.partner.isVisible():
                QMessageBox.information(self, "提示",
                                        f"{self.partner.name} 已隐藏，不能同时隐藏两个桌宠")
            else:
                self.hide()  # 隐藏自己
        elif action == a_show_other:
            if self.partner:
                self.partner.show()  # 显示对方
        elif action == a_quit:
            self._save_settings()
            self.bubble.close()
            QApplication.quit()

    def _chat_input(self, prompt):
        """可爱风格的聊天输入界面（粉色圆角 + 大输入框 + 回车发送）"""
        dlg = QDialog(self)
        dlg.setWindowTitle("💬 和她说说话")
        dlg.setFixedWidth(340)
        dlg.setStyleSheet("""
            QDialog { background: #fff5f7; }
            QLabel { color: #5a4a52; font-family: "Microsoft YaHei"; }
            QLineEdit { background: #ffffff; border: 2px solid #ffd0dc;
                        border-radius: 12px; font-family: "Microsoft YaHei";
                        font-size: 16px; color: #5a4a52; padding: 10px 12px;
                        min-height: 40px; selection-background-color: #ffb6c1; }
            QLineEdit:focus { border: 2px solid #ff8fa3; }
            QPushButton { background: #ffb6c1; color: white; border: none;
                          border-radius: 14px; padding: 10px 44px;
                          font-family: "Microsoft YaHei"; font-size: 16px; font-weight: bold; }
            QPushButton:hover { background: #ff8fa3; }
            QPushButton:pressed { background: #ff7590; }
        """)
        lay = QVBoxLayout(dlg)
        lay.setSpacing(14)
        lay.setContentsMargins(26, 22, 26, 20)
        tip = QLabel(f"<div style='text-align:center;font-size:16px;font-weight:bold'>{prompt}</div>")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        edit = QLineEdit()
        edit.setPlaceholderText("想和我说点什么呢～")
        edit.setAlignment(Qt.AlignLeft)
        edit.returnPressed.connect(dlg.accept)   # 回车即发送
        lay.addWidget(edit)
        ok = QPushButton("💌 发送")
        ok.clicked.connect(dlg.accept)
        lay.addWidget(ok, alignment=Qt.AlignCenter)
        edit.setFocus()
        if dlg.exec_():
            return edit.text().strip()
        return None

    # ---------- V2: Function Calling 工具 ----------
    TOOLS_DEFS = [
        {"type": "function", "function": {
            "name": "set_reminder",
            "description": "设置一个定时提醒，到点桌宠会弹气泡提醒用户",
            "parameters": {"type": "object", "properties": {
                "minutes": {"type": "integer", "description": "多少分钟后提醒（1-720）"},
                "text": {"type": "string", "description": "提醒内容，如'该喝水啦'"}},
                "required": ["minutes", "text"]}}},
        {"type": "function", "function": {
            "name": "add_memo",
            "description": "把用户想记住的事记到备忘录（持久化保存）",
            "parameters": {"type": "object", "properties": {
                "content": {"type": "string", "description": "要记下的内容"}},
                "required": ["content"]}}},
        {"type": "function", "function": {
            "name": "start_timer",
            "description": "启动番茄钟专注计时，到点提醒休息",
            "parameters": {"type": "object", "properties": {
                "minutes": {"type": "integer", "description": "专注时长（默认25分钟）"}},
                "required": ["minutes"]}}},
        {"type": "function", "function": {
            "name": "query_memo",
            "description": "查询备忘录里记录的内容（用户让桌宠记住的事）",
            "parameters": {"type": "object", "properties": {
                "keyword": {"type": "string", "description": "可选，按关键词过滤（不传则返回全部）"}},
                "required": []}}},
        {"type": "function", "function": {
            "name": "play_minigame",
            "description": "在桌面上触发一个小游戏动画：猜拳(rps)、掷骰子(dice)、猜数字(guess)",
            "parameters": {"type": "object", "properties": {
                "game": {"type": "string", "enum": ["rps", "dice", "guess"],
                         "description": "游戏名：rps=猜拳 dice=掷骰子 guess=猜数字"}},
                "required": ["game"]}}},
        {"type": "function", "function": {
            "name": "get_time",
            "description": "获取当前的日期和时间（年月日/星期/时分），回答时间相关问题时调用",
            "parameters": {"type": "object", "properties": {}}}},
        {"type": "function", "function": {
            "name": "calc",
            "description": "执行数学计算（加减乘除/括号/百分号），用户要算数时调用",
            "parameters": {"type": "object", "properties": {
                "expr": {"type": "string", "description": "数学表达式，如 (15+7)*3"}},
                "required": ["expr"]}}},
        {"type": "function", "function": {
            "name": "list_reminders",
            "description": "列出当前所有已设置的提醒（时间+内容），用户问'有哪些提醒'时调用",
            "parameters": {"type": "object", "properties": {}}}},
        {"type": "function", "function": {
            "name": "cancel_reminder",
            "description": "取消一个已设置的提醒（按序号，序号从 list_reminders 的结果里看）",
            "parameters": {"type": "object", "properties": {
                "index": {"type": "integer", "description": "要取消的提醒序号（从1开始）"}},
                "required": ["index"]}}},
        {"type": "function", "function": {
            "name": "get_stats",
            "description": "获取桌宠自己的状态（心情/饱食度），用户问'你心情怎么样/你饿不饿'时调用",
            "parameters": {"type": "object", "properties": {}}}},
        {"type": "function", "function": {
            "name": "search_web",
            "description": "联网搜索获取实时信息（新闻/天气/百科/菜谱等），回答需要最新信息的问题时调用",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string", "description": "搜索关键词，尽量简短准确"}},
                "required": ["query"]}}},
    ]

    def _data_dir(self):
        """数据文件目录：exe 同目录优先（打包后用户可见），源码目录兜底"""
        d = os.path.dirname(os.path.abspath(sys.argv[0]))
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass
        return d

    def _memo_path(self):
        return os.path.join(self._data_dir(), "memos.json")

    def _register_ai_tools(self):
        """把工具 schema + handlers 注册给 AI 引擎（V2 Function Calling）"""
        pet = self

        def h_set_reminder(args):
            minutes = max(1, min(720, int(args.get("minutes", 5))))
            text = str(args.get("text", "提醒时间到啦～"))
            pet.reminder_signal.emit(minutes, text)  # 信号 → 主线程启动定时器
            return {"ok": True, "msg": f"已设置 {minutes} 分钟后提醒：{text}"}

        def h_add_memo(args):
            content = str(args.get("content", "")).strip()
            if not content:
                return {"ok": False, "msg": "内容为空"}
            try:
                memos = []
                if os.path.exists(pet._memo_path()):
                    with open(pet._memo_path(), "r", encoding="utf-8") as f:
                        memos = json.load(f)
                memos.append({"time": time.strftime("%m-%d %H:%M"), "content": content})
                with open(pet._memo_path(), "w", encoding="utf-8") as f:
                    json.dump(memos, f, ensure_ascii=False, indent=2)
                # 增量更新知识库（马上能检索到）
                try:
                    pet.ai.kb.add_doc(content, "备忘")
                except Exception:
                    pass
                return {"ok": True, "msg": f"已记下备忘录（共{len(memos)}条）"}
            except Exception as exc:
                return {"ok": False, "msg": f"保存失败: {exc}"}

        def h_start_timer(args):
            minutes = max(1, min(180, int(args.get("minutes", 25))))
            pet.reminder_signal.emit(minutes, "⏰ 番茄钟结束啦！休息一下，喝口水吧～")
            return {"ok": True, "msg": f"番茄钟已启动，{minutes} 分钟后提醒你休息"}

        def h_query_memo(args):
            """查询备忘录（可按关键词过滤）"""
            try:
                memos = []
                if os.path.exists(pet._memo_path()):
                    with open(pet._memo_path(), "r", encoding="utf-8") as f:
                        memos = json.load(f)
                keyword = str(args.get("keyword", "")).strip()
                if keyword:
                    memos = [m for m in memos if keyword in m.get("content", "")]
                if not memos:
                    return {"ok": True, "msg": "备忘录是空的"}
                lines = [f"{m.get('time','')} {m.get('content','')}" for m in memos[-8:]]
                return {"ok": True, "msg": "；".join(lines)}
            except Exception as exc:
                return {"ok": False, "msg": f"查询失败: {exc}"}

        def h_play_minigame(args):
            game = str(args.get("game", "dice"))
            pet.minigame_signal.emit(game)  # 信号 → 主线程触发游戏弹窗
            return {"ok": True, "msg": f"正在打开游戏：{game}"}

        def h_get_time(args):
            now = datetime.datetime.now()
            week = "一二三四五六日"[now.weekday()]
            return {"ok": True,
                    "msg": f"{now.year}年{now.month}月{now.day}日 星期{week} {now.strftime('%H:%M')}"}

        def h_calc(args):
            expr = str(args.get("expr", "")).strip()
            try:
                # 安全计算：只允许数字/运算符/括号/小数点/百分号
                tree = ast.parse(expr, mode="eval")
                allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Num,
                           ast.Constant, ast.Add, ast.Sub, ast.Mult, ast.Div,
                           ast.Mod, ast.Pow, ast.USub, ast.UAdd)
                for node in ast.walk(tree):
                    if not isinstance(node, allowed):
                        return {"ok": False, "msg": "表达式含不允许的内容"}
                result = eval(compile(tree, "<calc>", "eval"),
                              {"__builtins__": {}}, {})
                return {"ok": True, "msg": f"{expr} = {result}"}
            except Exception as exc:
                return {"ok": False, "msg": f"计算失败: {exc}"}

        def h_list_reminders(args):
            if not pet._reminders:
                return {"ok": True, "msg": "当前没有设置任何提醒"}
            lines = []
            for i, r in enumerate(pet._reminders, 1):
                lines.append(f"{i}. {r['minutes']}分钟后({r['time']}设) {r['text']}")
            return {"ok": True, "msg": "；".join(lines)}

        def h_cancel_reminder(args):
            idx = int(args.get("index", 0))
            if pet._cancel_reminder(idx):
                return {"ok": True, "msg": f"已取消第 {idx} 个提醒"}
            return {"ok": False, "msg": f"没有第 {idx} 个提醒"}

        def h_get_stats(args):
            return {"ok": True,
                    "msg": f"心情 {pet.mood}/100，饱食度 {pet.full}/100"}

        def h_search_web(args):
            """联网搜索：必应抓取前几条结果（标题+摘要）"""
            import re
            import urllib.request
            import html as _html
            query = str(args.get("query", "")).strip()
            if not query:
                return {"ok": False, "msg": "搜索词为空"}
            try:
                url = ("https://www.bing.com/search?q=" +
                       urllib.parse.quote(query) + "&setlang=zh-hans&count=5")
                req = urllib.request.Request(url, headers={
                    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                   "AppleWebKit/537.36 Chrome/120 Safari/537.36")})
                html = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", errors="ignore")
                # 按 li.b_algo 分块，块内查找链接/标题/摘要（更健壮）
                blocks = re.findall(r'<li class="b_algo"[^>]*>(.*?)</li>', html, re.S)
                results = []
                for li in blocks[:5]:
                    m = re.search(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', li, re.S)
                    if not m:
                        continue
                    title = _html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
                    p = re.search(r'<p[^>]*>(.*?)</p>', li, re.S)
                    snippet = _html.unescape(re.sub(r"<[^>]+>", "", p.group(1))).strip() if p else ""
                    if title:
                        results.append(f"{title}：{snippet[:70]}")
                if not results:
                    return {"ok": False, "msg": "没搜到结果，换个关键词试试"}
                return {"ok": True, "msg": "；".join(results[:5])}
            except Exception as exc:
                return {"ok": False, "msg": f"搜索失败: {exc}"}

        self.reminder_signal.connect(self._on_reminder)
        self.minigame_signal.connect(self._on_minigame)
        # 工具调用可视化：worker 线程 → 信号 → 聊天记录窗口
        self.ai.on_tool_call = lambda name, args: self.tool_call_signal.emit(
            f"{name}({json.dumps(args, ensure_ascii=False)[:40]})")
        # ReAct 推理链：思考过程（每轮只显示开头一次，防刷屏）/ 工具结果
        def _reason_emit(text):
            if not getattr(self, '_reason_shown', False):
                self._reason_shown = True
                self.reason_signal.emit(text.strip()[:80])
        self.ai.on_reason = _reason_emit
        self.ai.on_observe = lambda name, result: self.observe_signal.emit(
            f"{name} → {str(result)[:50]}")
        self.ai.register_tools(self.TOOLS_DEFS, {
            "set_reminder": h_set_reminder,
            "add_memo": h_add_memo,
            "start_timer": h_start_timer,
            "query_memo": h_query_memo,
            "play_minigame": h_play_minigame,
            "get_time": h_get_time,
            "calc": h_calc,
            "list_reminders": h_list_reminders,
            "cancel_reminder": h_cancel_reminder,
            "get_stats": h_get_stats,
            "search_web": h_search_web,
        })

    def _on_reminder(self, minutes, text):
        """主线程执行：minutes 分钟后全屏动画提醒（优先级最高），注册进提醒列表可管理"""
        minutes = max(1, minutes)

        def _fire():
            self._stop_all()                            # 打断走路/跟随/睡眠/互动等一切活动
            if self.partner:
                self.partner._stop_all()                # 另一桌宠也安静
            ReminderOverlay.instance().show_reminder(text)  # 全屏动画（最高优先级）
            self._say(text, 5000)                       # 气泡辅助
            # 触发后从列表移除
            for r in list(self._reminders):
                if r.get("text") == text:
                    try:
                        self._reminders.remove(r)
                    except ValueError:
                        pass

        t = QTimer(self)
        t.setSingleShot(True)
        t.timeout.connect(_fire)
        t.start(minutes * 60000)
        self._reminders.append({
            "timer": t, "text": text,
            "minutes": minutes,
            "time": datetime.datetime.now().strftime("%H:%M"),
        })
        self._say(f"⏰ 已设置 {minutes} 分钟后提醒～", 3000)

    def _cancel_reminder(self, idx):
        """按序号取消提醒（1 起）"""
        try:
            r = self._reminders[idx - 1]
        except (IndexError, TypeError):
            return False
        try:
            r["timer"].stop()
        except Exception:
            pass
        try:
            self._reminders.remove(r)
        except ValueError:
            pass
        return True

    def _on_tool_call_msg(self, desc):
        """工具调用可视化（主线程）：聊天记录窗口显示 🔧 调用信息"""
        ChatLogWindow.instance().add_system(f"🔧 行动：调用工具 {desc}")

    def _on_reason_msg(self, text):
        """ReAct 思考过程（主线程）"""
        if text.strip():
            ChatLogWindow.instance().add_system(f"🤔 思考：{text}")

    def _on_observe_msg(self, desc):
        """ReAct 工具观察（主线程）"""
        ChatLogWindow.instance().add_system(f"👀 观察：{desc}")

    def _on_minigame(self, game):
        """主线程执行：LLM 触发小游戏"""
        if game == "rps":
            self._do_rock_paper()
        elif game == "guess":
            self._do_guess_number()
        else:
            self._do_dice()

    def _do_chat(self):
        # AI 聊天：弹出输入框（流式输出，失败时兜底用本地台词）
        text = self._chat_input("想和我聊什么呀～<br><span style='font-size:13px;color:#b08a96'>（她真的会回你哦）</span>")
        if not text:
            return
        self._chat_with(text)

    def _group_chat(self):
        """多 Agent 协作（群聊）：同一问题发给所有桌宠，各自独立人格回答"""
        text = self._chat_input("想问他们俩什么？<br><span style='font-size:13px;color:#b08a96'>（欣悦和业成都会回答你）</span>")
        if not text:
            return
        pets = list(ChatLogWindow.PET_INSTANCES.values())
        if not pets:
            self._say("还没有桌宠在呢～", 3000)
            return
        self._say("好呀，让他们俩都说说～", 2500)
        for pet in pets:
            if pet:
                # 各自独立实例可并行对话（不同 agent 独立人格/记忆/工具）
                pet._chat_with(text)

    def _chat_with(self, text):
        """发起一次流式对话（聊天/划词问答/截图问答共用）"""
        # 防止连点：上一次对话还没回复时忽略新的聊天请求
        if getattr(self, '_chatting', False):
            self._say("我还在想上一句呢～稍等！", 2500)
            return
        self._stop_all()
        self._chatting = True
        self._stream_started = False
        self._last_user_text = text  # 供对话后提取长期事实
        self._reason_shown = False  # ReAct 思考每轮只显示一次
        # 记录到聊天窗口（用户消息靠右）+ 设为活跃桌宠（对话框发送的回复者）
        ChatLogWindow.ACTIVE_PET = self
        ChatLogWindow.instance().add_message("user", text)
        # 自动弹出聊天记录窗口（对话过程可视化，不抢焦点）
        try:
            _w = ChatLogWindow.instance()
            _w.show()
            _w.raise_()
        except Exception:
            pass
        # 流式输出：无思考气泡，首字 1 秒内到达直接逐字显示
        try:
            # 流式：增量走 ai_delta_signal，完成走 ai_done_signal（均线程安全）
            self.ai.chat_async_stream(text.strip(),
                                      self.ai_delta_signal.emit,
                                      self.ai_done_signal.emit,
                                      mood=self.mood, full=self.full, timeout=45)
        except Exception:
            self._chatting = False
            self._say(random.choice(self.chat_lines), 3000)

    def _explain_clipboard(self):
        """划词问答：解释剪贴板里复制的文字"""
        text = QApplication.clipboard().text()
        if not text or not text.strip():
            self._say("剪贴板没有文字哦，先 Ctrl+C 复制一段试试～", 3500)
            return
        snippet = text.strip()[:500]
        self._say("看到啦，让我看看这段文字～", 2500)
        self._chat_with(f"请用简单易懂的话解释下面这段文字是什么意思（用户刚复制的）：\n{snippet}")

    def _ocr_script_path(self):
        """定位 ocr.ps1：exe 同目录 → 源码目录 → _MEIPASS"""
        cands = [
            os.path.join(self._data_dir(), "ocr.ps1"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "ocr.ps1"),
            os.path.join(getattr(sys, '_MEIPASS', ''), "ocr.ps1"),
        ]
        for c in cands:
            if c and os.path.exists(c):
                return c
        return None

    def _run_ocr(self, img_path):
        """Windows 内置 OCR（WinRT），返回识别文字"""
        script = self._ocr_script_path()
        if not script:
            return ""
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", script, "-Path", img_path],
                capture_output=True, timeout=40)
            text = r.stdout.decode("utf-8", errors="ignore").strip()
            if "OCR_ERROR" in text or "NO_ENGINE" in text:
                return ""
            return " ".join(text.split())  # 清理多余空格
        except Exception:
            return ""

    def _ask_screenshot(self):
        """截图问答：先问用户想了解截图的什么方向 → 识别剪贴板图片 → OCR → LLM 按问题回答"""
        img = QApplication.clipboard().image()
        if img.isNull():
            self._say("剪贴板没有图片哦，先 Win+Shift+S 截图～", 3500)
            return
        # 用户输入针对截图的具体问题（可取消）
        question = self._chat_input(
            "想问截图什么呀？<br><span style='font-size:13px;color:#b08a96'>"
            "（比如：总结一下 / 这是什么功能 / 帮我翻译 / 里面有什么重点）</span>")
        if not question:
            return  # 用户取消
        self._say("正在看你的截图…", 2500)
        # 后台线程 OCR，结果（含问题）经信号回主线程
        def worker():
            try:
                tmp = os.path.join(self._data_dir(), "_ocr_tmp.png")
                img.save(tmp, "PNG")
                text = self._run_ocr(tmp)
            except Exception:
                text = ""
            self.screenshot_signal.emit(text.strip() + "\n<问题>:" + question)
        threading.Thread(target=worker, daemon=True).start()

    def _on_screenshot_text(self, payload):
        """截图 OCR 完成（主线程）：识别到文字 → 按用户问题对话；否则提示"""
        parts = payload.split("\n<问题>:", 1)
        text = parts[0]
        question = parts[1] if len(parts) > 1 else ""
        if not text:
            self._say("截图里没有识别到文字呢（我暂时只会看文字）～", 3500)
            return
        if question:
            self._chat_with(
                f"用户发来一张截图，识别到以下文字：\n{text}\n"
                f"用户想知道：{question}。请结合截图内容回答。")
        else:
            self._chat_with(
                f"用户发来一张截图，识别到以下文字：\n{text}\n"
                f"请根据内容回答用户可能的疑问。")

    def _on_ai_delta(self, delta):
        """流式增量（主线程）：塞入打字机缓冲，逐字显示"""
        if not delta:
            return
        self._type_buf += delta
        if not self._type_timer.isActive():
            self._type_timer.start(30)  # 打字机节奏：每 30ms 弹一个字

    def _type_tick(self):
        """打字机：每次弹出一个可见单元（字符或 [表情] 标签→emoji）"""
        if not self._type_buf:
            self._type_timer.stop()
            return
        ch = self._type_buf[0]
        if ch == "[":
            # 表情标签：等读到 ] 再一次性输出转换后的 emoji（未知标签删掉）
            end = self._type_buf.find("]", 1)
            if end == -1:
                return  # 标签未完整，等下一个 tick
            tag = self._type_buf[:end + 1]
            self._type_buf = self._type_buf[end + 1:]
            out = EMOJI_MAP.get(tag[1:-1], "")
            new_text = self.bubble._text + out
        else:
            self._type_buf = self._type_buf[1:]
            new_text = self.bubble._text + ch
        if not getattr(self, '_stream_started', False):
            self._stream_started = True  # 首字实际显示时标记
        self.bubble.set_stream_text(new_text)
        self._position_bubble()

    def _on_ai_done(self, ok):
        """流式完成（主线程）"""
        self._chatting = False
        self._type_timer.stop()
        if ok and self._type_buf:
            # 剩余未打完的字一次性排空（不再逐字，直接显示完整）
            self.bubble.set_stream_text(self.bubble._text + self._type_buf)
            self._type_buf = ""
            self._position_bubble()
        if ok and (getattr(self, '_stream_started', False) or self.bubble._text):
            # 已逐字显示完，补收尾：粒子 + 心情 + 记录到聊天窗口
            self.mood = min(100, self.mood + 5)
            self._spawn_hearts(2)
            self.bubble._timer.start(8000)  # 流式结束后再保留 8 秒
            if self.bubble._text.strip():
                ChatLogWindow.instance().add_message(self.name, self.bubble._text)
            # 长期记忆：后台提取值得记住的事实（用户偏好/重要事件）
            try:
                _reply = self.bubble._text.strip()
                _user = getattr(self, "_last_user_text", "") or ""
                if _user and _reply:
                    self.ai.extract_facts_async(
                        _user, _reply,
                        on_done=lambda fs: self.ai.add_facts(fs))
            except Exception:
                pass
        elif ok:
            # 流式完成但无内容（工具调用类回复）
            self._say("搞定啦～", 3000)
        else:
            # 网络/超时兜底：明确告知，避免以为卡死
            self._say("网络有点卡…" + random.choice(self.chat_lines), 3500)

    def _on_ai_reply(self, reply):
        """AI 回复回调（主线程）"""
        self._chatting = False
        if reply:
            self._say(reply, 8000)  # AI 回复保留 8 秒（长回复可读完）
            self.mood = min(100, self.mood + 5)
            self._spawn_hearts(2)
        else:
            # 网络/超时兜底：明确告知，避免以为卡死
            self._say("网络有点卡…" + random.choice(self.chat_lines), 3500)

    def _do_pet(self):
        self._stop_all()
        self._set_state("pet")
        self.pet_anim = 0
        self.pet_timer.start(70)   # 卡通手摸头动画
        self.mood = min(100, self.mood + 10)  # 摸摸头涨心情
        self._spawn_hearts(2)
        self._say(random.choice(self.pet_lines))

    def _do_feed(self):
        self._stop_all()
        self.full = min(100, self.full + 25)  # 喂食涨饱食度
        self.mood = min(100, self.mood + 5)
        self._say(random.choice(self.feed_lines))
        self._spawn_hearts(4)
        # 随机卡通食物：嘴巴同水平线出现 → 移到嘴边 → 分3口啃食掉
        foods = ['🍰', '🍎', '🍕', '🍜', '🍗', '🍦', '🥟', '🍣', '🍩', '🍓', '🍔', '🍉']
        mouth_x = int(self.width() * 0.62)   # 嘴巴位置
        mouth_y = int(self.height() * 0.52)  # 嘴巴水平线
        self.food = {
            'emoji': random.choice(foods),
            'sx': mouth_x + 90,     # 起点：嘴巴右侧同一水平线
            'tx': mouth_x,          # 终点：嘴边
            'y': mouth_y,
            'phase': 'move',        # move(水平移近) → bite(啃食)
            't': 0.0,
            'bite': 0,              # 已咬口数 0-3
            'bite_t': 0.0,          # 当前口进度
            'size': 30,
        }
        # 确保粒子定时器运行（驱动食物动画）
        if not self.particle_timer.isActive():
            self.particle_timer.start(30)
        # 喂吃的：轻微跳跃
        QTimer.singleShot(300, self._anim_jump)

    def _do_walk(self):
        if self.state == "walk":
            self._stop_all()
            self._say("不走啦～")
            return
        self._stop_all()
        self._set_state("walk")
        self.walk_dir = 1
        self.base_y = self.y()
        self.anim_frame = 0
        self.anim_timer.start(30)
        self._say(random.choice(self.walk_lines))

    def _do_sleep(self):
        if self.state == "sleep":
            self._stop_all()
            self._say("睡醒啦！")
            return
        self._stop_all()
        self._set_state("sleep")
        self.anim_timer.stop()
        self.update()
        self._say(random.choice(self.sleep_lines), 3000)

    def _do_follow(self):
        if self.state == "follow":
            self._stop_all()
            self._say("不跟啦～")
            return
        self._stop_all()
        self._set_state("follow")
        self.anim_frame = 0
        self.anim_timer.start(20)
        self._say(random.choice(self.follow_lines))

    def _do_size(self):
        size, ok = QInputDialog.getInt(self, "调整大小", "缩放百分比 (%):",
                                       int(self.scale * 100), 8, 150, 5)
        if ok:
            cx = self.x() + self.width() // 2
            cy = self.y() + self.height() // 2
            self.scale = size / 100.0
            self._update_size()
            self.move(cx - self.width() // 2, cy - self.height() // 2)
            self.update()

    def _toggle_top(self):
        self._always_on_top = not self._always_on_top
        flags = self.windowFlags()
        if self._always_on_top:
            flags |= Qt.WindowStaysOnTopHint
            self._say("已置顶～")
        else:
            flags &= ~Qt.WindowStaysOnTopHint
            self._say("取消置顶")
        self.setWindowFlags(flags)
        self.show()

    def _stop_all(self):
        self.anim_timer.stop()
        if hasattr(self, 'pet_timer'):
            self.pet_timer.stop()
            self.pet_anim = 0
        self.food = None
        self._set_state("idle")
        self.flip = False
        self.update()

    # ---------- 走路 / 跟随 的 tick（覆盖通用 tick） ----------
    # 重新实现 _anim_tick 以支持 walk/follow
    # （上面的 _anim_tick 已处理 jump/shake/squash，这里扩展）


# 由于 walk/follow 需要不同逻辑，用 monkey-patch 方式扩展
_orig_tick = PetWindow._anim_tick


def _extended_tick(self):
    if self.state == "walk":
        screen = QApplication.primaryScreen().availableGeometry()
        step = 4
        new_x = self.x() + self.walk_dir * step
        # 边界反弹
        if new_x <= screen.left():
            new_x = screen.left()
            self.walk_dir = 1
        elif new_x + self.width() >= screen.right():
            new_x = screen.right() - self.width()
            self.walk_dir = -1
        self.flip = (self.walk_dir < 0)
        # 上下浮动（基于起始 y）
        self.anim_frame += 1
        bob = int(5 * math.sin(self.anim_frame * 0.35))
        self.move(new_x, self.base_y + bob)
        self.update()
        return
    if self.state == "follow":
        cursor = QApplication.primaryScreen().cursor().pos() if hasattr(QApplication.primaryScreen(), 'cursor') else QApplication.desktop().cursor().pos()
        # 目标点：鼠标下方；伙伴也在跟随时错开站位（各自停在不同位置，避免互相挤压振荡）
        tx = cursor.x()
        ty = cursor.y() - 70
        p = self.partner
        if p and p.isVisible() and p.state == "follow":
            ox = self.x() - p.x()
            oy = self.y() - p.y()
            od = math.hypot(ox, oy)
            if od > 10:
                tx += ox / od * 80
                ty += oy / od * 40
            else:
                tx += 80
        cx = self.x() + self.width() // 2
        cy = self.y() + self.height() // 2
        dx = tx - cx
        dy = ty - cy
        dist = math.hypot(dx, dy)
        if dist > 12:
            speed = min(self.follow_speed, dist / 12)
            nx = self.x() + int(dx / dist * speed)
            ny = self.y() + int(dy / dist * speed)
            self.flip = (dx < 0)
            self.move(nx, ny)
        self.anim_frame += 1
        self.update()
        return
    _orig_tick(self)


PetWindow._anim_tick = _extended_tick


class PetManager:
    """多桌宠互动管理器：防重叠推开 + 靠近打招呼"""
    def __init__(self, pets):
        self.pets = pets
        self.last_greet = 0.0
        self.locked = False   # 贴贴等互动期间锁定坐标（不再移动）
        self.timer = QTimer()
        self.timer.timeout.connect(self._check)
        self.timer.start(100)   # 100ms 检查（防重叠更及时）

    def _check(self):
        if len(self.pets) < 2:
            return
        # 提醒优先级最高：全屏动画期间不触发任何互动（打招呼/贴贴/撞飞）
        if ReminderOverlay.instance().is_active:
            return
        a, b = self.pets[0], self.pets[1]
        if not a.isVisible() or not b.isVisible():
            return  # 有桌宠被隐藏时不互动
        if self.locked:
            return  # 贴贴锁定期间：不移动、不互动
        ax = a.x() + a.width() / 2
        ay = a.y() + a.height() / 2
        bx = b.x() + b.width() / 2
        by = b.y() + b.height() / 2
        dist = math.hypot(bx - ax, by - ay)
        # 圆形碰撞体积
        ra = a.width() * 0.40
        rb = b.width() * 0.40
        contact = dist < (ra + rb) * 0.9
        # 二次碰撞（动量定理）：飞行中的桌宠相撞 → 交换动量、双方弹开
        # 拖拽中的桌宠处于无敌状态（不参与动量碰撞，只走静态推开）
        if contact and (a.state == "throw" or b.state == "throw") \
                and a.state != "drag" and b.state != "drag":
            self._momentum_collide(a, b, ax, ay, bx, by, dist, ra, rb)
            return
        # 静态兜底推开（严格不重叠）
        if contact:
            dx = ax - bx
            dy = ay - by
            if math.hypot(dx, dy) < 1:
                dx, dy = 1, 0
            push = 40
            nx = b.x() - int(dx / math.hypot(dx, dy) * push)
            ny = b.y() - int(dy / math.hypot(dx, dy) * push)
            sw = QApplication.primaryScreen().availableGeometry().width()
            sh = QApplication.primaryScreen().availableGeometry().height()
            nx = max(0, min(nx, sw - b.width()))
            ny = max(0, min(ny, sh - b.height()))
            b.move(nx, ny)
        # 靠近打招呼（距离 < 250px 且冷却 > 5 秒；睡觉时不打搅）
        now = time.monotonic()
        if dist < 250 and now - self.last_greet > 5 \
                and a.state != "sleep" and b.state != "sleep":
            self.last_greet = now
            greet_a = random.choice(["嗨～你来啦", "嘿！", "在一起嘛～", "嘿嘿~", "好开心！"])
            greet_b = random.choice(["嗯嗯！", "在呢～", "走走走", "🤗", "嘻嘻！"])
            a._say(greet_a, 2500)
            QTimer.singleShot(500, lambda: b._say(greet_b, 2500))
            a._spawn_hearts(3)
            b._spawn_hearts(3)
        # 随机互动触发（每 30~60 秒一次）
        if now > getattr(self, "_next_interact", 0):
            self._next_interact = now + random.randint(30, 60)
            self._trigger_interaction()

    # ---------- 动量碰撞（二次碰撞） ----------
    def _momentum_collide(self, a, b, ax, ay, bx, by, dist, ra, rb):
        """弹性碰撞：交换沿碰撞方向的动量分量，双方弹开（可连续发生）"""
        # 碰撞法线方向（a → b）
        nx = bx - ax
        ny = by - ay
        nd = math.hypot(nx, ny)
        if nd < 1:
            nx, ny, nd = 1, 0, 1
        nx /= nd
        ny /= nd
        # 双方当前速度
        va = [a.throw_vel[0] if a.state == "throw" else 0.0,
              a.throw_vel[1] if a.state == "throw" else 0.0]
        vb = [b.throw_vel[0] if b.state == "throw" else 0.0,
              b.throw_vel[1] if b.state == "throw" else 0.0]
        # 质量（按窗口面积近似）
        ma = max(1, a.width() * a.height())
        mb = max(1, b.width() * b.height())
        # 法线速度分量
        v1n = va[0] * nx + va[1] * ny
        v2n = vb[0] * nx + vb[1] * ny
        # 一维弹性碰撞（恢复系数 e≈0.9）动量守恒公式
        e = 0.9
        v1n_new = (ma * v1n + mb * v2n - mb * e * (v1n - v2n)) / (ma + mb)
        v2n_new = (ma * v1n + mb * v2n + ma * e * (v1n - v2n)) / (ma + mb)
        # 保留切向分量，替换法线分量
        for pet, v, vn in ((a, va, v1n_new), (b, vb, v2n_new)):
            tang_x = v[0] - (v[0] * nx + v[1] * ny) * nx
            tang_y = v[1] - (v[0] * nx + v[1] * ny) * ny
            pet.throw_vel = [tang_x + vn * nx, tang_y + vn * ny]
            if math.hypot(*pet.throw_vel) > 12:
                if pet.state != "throw":
                    pet.throw_angle = 0
                    pet._set_state("throw")
                    pet.throw_timer.start(16)
            else:
                if pet.state == "throw":
                    pet.throw_timer.stop()
                    pet._set_state("idle")
        # 分离（沿法线推开，避免粘住）
        push = (ra + rb) * 0.9 - dist + 6
        if push > 0:
            a.move(a.x() - int(nx * push), a.y() - int(ny * push))
            b.move(b.x() + int(nx * push), b.y() + int(ny * push))
        # 碰撞火花
        a._spawn_hearts(2)
        b._spawn_hearts(2)

    def _trigger_interaction(self):
        a, b = self.pets[0], self.pets[1]
        # 陪睡优先：一个睡觉时另一个走过去一起睡
        if a.state == "sleep" and b.state != "sleep":
            self._sleep_together(b, a)
            return
        if b.state == "sleep" and a.state != "sleep":
            self._sleep_together(a, b)
            return
        if a.state == "sleep" or b.state == "sleep":
            return  # 都在睡：不触发任何其他互动
        if a.state == "drag" or b.state == "drag":
            return  # 拖动中不触发
        r = random.random()
        if r < 0.12:
            self._do_gift()
        elif r < 0.24:
            self._do_flower()
        elif r < 0.36:
            self._do_dance()
        elif r < 0.48:
            self._do_whisper()
        elif r < 0.60:
            self._do_hug()
        elif r < 0.70:
            self._do_chase()
        elif r < 0.80:
            self._do_rps()
        elif r < 0.90:
            self._do_highfive()
        elif r < 0.95:
            self._do_photo()
        else:
            self._do_hearts()

    def _do_gift(self):
        """互赠礼物：一个送爱心/食物，另一个收下涨心情"""
        a, b = self.pets[0], self.pets[1]
        sender, receiver = random.choice([(a, b), (b, a)])
        gift = random.choice(["❤️", "🍰", "⭐", "🍓"])
        sender._say(f"给你～{gift}", 2000)
        receiver.mood = min(100, receiver.mood + 8)
        QTimer.singleShot(600, lambda: receiver._say(
            random.choice(["谢谢～", "谢了。", "哇，好耶！"]), 2000))
        sender._spawn_hearts(3)
        receiver._spawn_hearts(3)

    def _do_chase(self):
        """追逐嬉戏：一个追一个跑，追到后贴贴"""
        a, b = self.pets[0], self.pets[1]
        chaser, runner = random.choice([(a, b), (b, a)])
        chaser._set_state("walk")
        runner._set_state("walk")
        runner._say(random.choice(["来追我呀～", "……来追我。", "快跑！"]), 2000)
        for i in range(22):
            QTimer.singleShot(i * 100, lambda c=chaser, r=runner: self._chase_step(c, r))
        QTimer.singleShot(2300, lambda: (chaser._set_state("idle"),
                                         runner._set_state("idle"),
                                         self._do_highfive()))

    def _chase_step(self, chaser, runner):
        if chaser.state != "walk" or not chaser.isVisible():
            return
        dx = runner.x() - chaser.x()
        dy = runner.y() - chaser.y()
        d = math.hypot(dx, dy)
        if d < 40:
            return  # 追到了
        step = 14
        chaser.move(chaser.x() + int(dx / d * step),
                    chaser.y() + int(dy / d * step))
        chaser.flip = (dx < 0)

    def _do_rps(self):
        """自动猜拳：同时出拳，输的跳脚赢的蹦跶"""
        a, b = self.pets[0], self.pets[1]
        emojis = ["✊", "✌️", "✋"]
        a_choice, b_choice = random.randint(0, 2), random.randint(0, 2)
        a._say(emojis[a_choice], 1600)
        QTimer.singleShot(700, lambda: b._say(emojis[b_choice], 1600))
        diff = (a_choice - b_choice) % 3
        QTimer.singleShot(1700, lambda: self._rps_result(diff, a, b))

    def _rps_result(self, diff, a, b):
        if diff == 0:
            a._say("平局～", 1800)
            b._say("嗯。", 1800)
        elif diff == 2:
            a._anim_jump()      # a 赢 → 蹦跶
            b._anim_squash()    # b 输 → 跳脚
        else:
            a._anim_squash()
            b._anim_jump()

    def _do_highfive(self):
        """击掌贴贴：先确认距离近（>200px 先互相走近），贴贴期间锁定坐标"""
        a, b = self.pets[0], self.pets[1]
        if not a.isVisible() or not b.isVisible():
            return
        ax = a.x() + a.width() / 2
        ay = a.y() + a.height() / 2
        bx = b.x() + b.width() / 2
        by = b.y() + b.height() / 2
        dist = math.hypot(bx - ax, by - ay)
        if dist > 180:
            # 太远：先互相走近再贴贴
            for i in range(12):
                QTimer.singleShot(i * 120, self._close_step)
            QTimer.singleShot(1500, self._do_highfive_now)
            return
        self._do_highfive_now()

    def _close_step(self):
        """双方各向对方走近一步"""
        if self.locked:
            return
        a, b = self.pets[0], self.pets[1]
        ax = a.x() + a.width() / 2
        ay = a.y() + a.height() / 2
        bx = b.x() + b.width() / 2
        by = b.y() + b.height() / 2
        d = math.hypot(bx - ax, by - ay)
        if d < 150:
            return
        step = 10
        a.move(a.x() + int((bx - ax) / d * step), a.y() + int((by - ay) / d * step))
        b.move(b.x() + int((ax - bx) / d * step), b.y() + int((ay - by) / d * step))

    def _do_highfive_now(self):
        """贴贴：锁定坐标 + 一起蹦跳 + 飘爱心"""
        a, b = self.pets[0], self.pets[1]
        if not a.isVisible() or not b.isVisible():
            return
        ax = a.x() + a.width() / 2
        ay = a.y() + a.height() / 2
        bx = b.x() + b.width() / 2
        by = b.y() + b.height() / 2
        if math.hypot(bx - ax, by - ay) > 220:
            return  # 没走近成功就不贴
        self.locked = True   # 锁定坐标
        a._anim_jump()
        b._anim_jump()
        a._say("贴贴！", 2000)
        QTimer.singleShot(400, lambda: b._say("嗯！", 2000))
        a._spawn_hearts(4)
        b._spawn_hearts(4)
        QTimer.singleShot(2000, self._unlock)

    def _unlock(self):
        """贴贴结束：解锁坐标"""
        self.locked = False

    def _do_hearts(self):
        """心心相印：头顶飘心 + 中间合成大爱心"""
        a, b = self.pets[0], self.pets[1]
        a._spawn_hearts(3)
        b._spawn_hearts(3)
        QTimer.singleShot(500, lambda: a._spawn_hearts(3))
        QTimer.singleShot(700, lambda: b._spawn_hearts(3))
        a._say("💗", 1500)
        QTimer.singleShot(400, lambda: b._say("💙", 1500))

    # ---------- 新增互动场景 ----------
    def _do_flower(self):
        """送花：一个送🌹，另一个开心收下"""
        a, b = self.pets[0], self.pets[1]
        sender, receiver = random.choice([(a, b), (b, a)])
        sender._say("给你🌹", 2000)
        receiver.mood = min(100, receiver.mood + 8)
        QTimer.singleShot(500, lambda: receiver._say(
            random.choice(["哇！谢谢～", "😳 好漂亮！", "谢谢🌹嘿嘿"]), 2000))
        sender._spawn_hearts(3)
        QTimer.singleShot(700, lambda: receiver._spawn_hearts(4))

    def _do_dance(self):
        """一起跳舞：同步左右摇摆"""
        a, b = self.pets[0], self.pets[1]
        a._say("♪ 一起跳舞吧～", 2000)
        QTimer.singleShot(400, lambda: b._say("♪♪♪", 1500))
        a._set_state("walk")
        b._set_state("walk")
        base_a, base_b = a.x(), b.x()
        for i in range(20):
            sway = 8 if i % 2 == 0 else -8
            QTimer.singleShot(i * 120, lambda aa=a, ba=base_a, s=sway: self._dance_step(aa, ba, s))
            QTimer.singleShot(i * 120, lambda bb=b, bb2=base_b, s=-sway: self._dance_step(bb, bb2, s))
        QTimer.singleShot(2600, lambda: (a._set_state("idle"), b._set_state("idle")))

    def _dance_step(self, pet, base_x, sway):
        if pet.state != "walk" or not pet.isVisible():
            return
        pet.move(base_x + sway, pet.y())

    def _do_whisper(self):
        """说悄悄话：一个凑近另一个耳边"""
        a, b = self.pets[0], self.pets[1]
        speaker, listener = random.choice([(a, b), (b, a)])
        for i in range(5):
            QTimer.singleShot(i * 120, lambda p=speaker, l=listener: self._step_toward(p, l))
        QTimer.singleShot(650, lambda: speaker._say(
            random.choice(["悄悄告诉你……", "我跟你说哦～", "嘘……别告诉别人"]), 2500))
        QTimer.singleShot(1300, lambda: listener._say(
            random.choice(["嗯嗯？", "啊？真的吗", "好嘟好嘟"]), 2000))

    def _step_toward(self, pet, other):
        if not pet.isVisible():
            return
        dx = other.x() - pet.x()
        dy = other.y() - pet.y()
        d = math.hypot(dx, dy)
        if d < 20:
            return
        pet.move(pet.x() + int(dx / d * 24), pet.y() + int(dy / d * 24))

    def _do_hug(self):
        """拥抱：靠近 + 爱心环绕 + 锁定"""
        a, b = self.pets[0], self.pets[1]
        for i in range(8):
            QTimer.singleShot(i * 100, self._close_step)
        QTimer.singleShot(1000, self._hug_now)

    def _hug_now(self):
        a, b = self.pets[0], self.pets[1]
        if not a.isVisible() or not b.isVisible():
            return
        self.locked = True
        a._anim_jump()
        b._anim_jump()
        a._say("抱抱～", 2000)
        QTimer.singleShot(300, lambda: b._say("嘿嘿 抱～", 2000))
        for delay in (0, 400, 800):
            QTimer.singleShot(delay, lambda: a._spawn_hearts(4))
            QTimer.singleShot(delay + 150, lambda: b._spawn_hearts(4))
        QTimer.singleShot(2200, self._unlock)

    def _do_photo(self):
        """一起拍照：站好 + 咔嚓闪光"""
        a, b = self.pets[0], self.pets[1]
        a._say("📸 一起拍张照！", 2000)
        QTimer.singleShot(400, lambda: b._say("嗯！", 1500))
        QTimer.singleShot(900, lambda: a._say("咔嚓！📸", 2500))
        QTimer.singleShot(1100, lambda: b._say("好看！", 2000))
        for delay in (1000, 1200, 1400):
            QTimer.singleShot(delay, lambda: a._spawn_hearts(3))
            QTimer.singleShot(delay + 120, lambda: b._spawn_hearts(3))
        a.mood = min(100, a.mood + 5)
        b.mood = min(100, b.mood + 5)

    def _sleep_together(self, walker, sleeper):
        """陪睡：walker 走到 sleeper 旁边一起睡"""
        target_x = sleeper.x() + sleeper.width() + 20
        target_y = sleeper.y()
        walker._set_state("walk")
        for i in range(14):
            QTimer.singleShot(i * 100,
                              lambda p=walker: self._step_to(p, target_x, target_y))
        QTimer.singleShot(1500, lambda: (walker._set_state("idle"),
                                         walker._do_sleep()))

    def _step_to(self, pet, tx, ty):
        if not pet.isVisible():
            return
        dx = tx - pet.x()
        dy = ty - pet.y()
        d = math.hypot(dx, dy)
        if d < 10:
            return
        step = 20
        pet.move(pet.x() + int(dx / d * step), pet.y() + int(dy / d * step))
        pet.flip = (dx < 0)


def load_pets_config():
    """读取 pets_config.json（桌宠生成器产出），无配置时用默认双桌宠。
    配置格式：
    {"pets": [
        {"name": "欣悦", "frames": "frames", "theme": "pink", "persona": "persona.md"},
        {"name": "业成", "frames": "frames/B", "theme": "blue", "persona": "persona_b.md"}
    ]}
    frames 为相对本目录的角色素材目录；persona 为相对本目录的人格文件。
    """
    default = [
        {"name": "欣悦", "frames": "frames", "theme": "pink", "persona": "persona.md"},
        {"name": "业成", "frames": "frames/B", "theme": "blue", "persona": "persona_b.md"},
    ]
    cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pets_config.json")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            pets = data.get("pets", [])
            if isinstance(pets, list) and pets:
                return pets
        except Exception:
            pass
    return default


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    # 单实例保护：已有实例在运行则直接退出（防止重复启动）
    probe = QLocalSocket()
    probe.connectToServer("DeskPet_SingleInstance")
    if probe.waitForConnected(100):
        # 已有实例 → 通知它并退出
        probe.disconnectFromServer()
        sys.exit(0)
    probe.disconnectFromServer()
    server = QLocalServer()
    server.removeServer("DeskPet_SingleInstance")
    # 关键：listen 失败必须退出（两个实例同时启动的竞态下，第二个 listen 会失败）
    if not server.listen("DeskPet_SingleInstance"):
        sys.exit(0)
    # 从 pets_config.json 读取桌宠配置（无配置时用默认双桌宠）
    pets_cfg = load_pets_config()
    pets = []
    _here = os.path.dirname(os.path.abspath(__file__))
    for i, cfg in enumerate(pets_cfg):
        pet = PetWindow(
            frames_dir=os.path.join(_here, cfg.get("frames", "frames")),
            name=cfg.get("name", f"桌宠{i + 1}"),
            theme=cfg.get("theme", "pink"),
            persona_file=cfg.get("persona"),
        )
        pets.append(pet)
    # 相邻配对（互动对象）
    n = len(pets)
    for i, pet in enumerate(pets):
        pet.partner = pets[(i + 1) % n] if n > 1 else None
    # 初始大小：原图缩放 13%
    INIT_SCALE = 0.13
    for pet in pets:
        pet.scale = INIT_SCALE
        pet._update_size()
    # 初始位置：横向排开
    sw = QApplication.primaryScreen().availableGeometry().width()
    screen_h = QApplication.primaryScreen().availableGeometry().height()
    total_w = sum(p.width() for p in pets) + 120 * max(0, n - 1)
    x0 = int((sw - total_w) / 2)
    for idx, pet in enumerate(pets):
        pet.show()
        pet.move(x0 + sum(p.width() + 120 for p in pets[:idx]),
                 int((screen_h - pet.height()) / 2) + (40 if idx % 2 else 0))
    # 启动互动管理器
    manager = PetManager(pets)
    for pet in pets:
        pet.manager = manager
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
