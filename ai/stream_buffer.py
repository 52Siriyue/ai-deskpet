# -*- coding: utf-8 -*-
"""流式文本的「打字机」状态机 —— 纯逻辑，不依赖 Qt。

## 为什么要单独抽出来

这些状态（缓冲、已显示文本、done 标记、首字标记）原本和 Qt 渲染混在 PetWindow 里，
只能由 QTimer 回调驱动。后果是两类边界**无法自动化验证**：

1. `done` 与缓冲的时序（done 先到、缓冲还没吐完）
2. 表情标签被服务端 chunk 拆散（`[微笑]` 被切成 `[微` + `笑]`）

当年遇到问题是「加个 15 秒兜底」而不是「写个测试测出来」。抽成纯类之后，
这两类边界都能用普通单测固化下来。

## 并发隔离

每个 Agent 各持一份实例 —— 隔离由构造保证，不再依赖 `self.name` 字符串约定。
"""
import re


class StreamBuffer:
    """把「服务端增量」逐字变成「可见文本」。

    典型用法（Qt 侧）：

        sb = StreamBuffer(EMOJI_MAP)
        sb.feed(delta)                    # 收到增量
        shown = sb.drain()               # 定时器每次 tick 调一次
        if sb.is_finished():             # 缓冲排空 且 done 已到 → 收尾
            finish()

    属性：
        buf     尚未显示的原始文本（可能含未闭合的表情标签）
        text    已显示的文本（独立累积：气泡被台词覆盖也能正确重建）
        done    服务端流是否已结束
        started 是否已显示过内容（首字标记）
    """

    def __init__(self, emoji_map=None):
        self.emoji = emoji_map if emoji_map is not None else {}
        self.buf = ""
        self.text = ""
        self.done = False
        self.started = False

    # ---------- 输入 ----------
    def feed(self, delta):
        """接住一段服务端增量。空增量直接忽略。"""
        if delta:
            self.buf += delta
        return self

    def mark_done(self):
        """服务端流已结束（**不**等缓冲排空 —— 是否收尾由 is_finished 判断）。"""
        self.done = True
        return self

    # ---------- 输出 ----------
    def drain(self):
        """吐出一个可见单元。

        返回 `(consumed, shown)`：

        - `consumed=True`  —— 缓冲被推进了（普通字符，或一个完整的表情标签）
        - `consumed=False` —— 这次不能推进，调用方应保留定时器等下一次

        为什么需要 `consumed` 这个额外标记：表情标签被 chunk 拆散时
        （缓冲是 `"[微"`）**既没内容可显示、也不能丢弃**，必须等后续 chunk。
        而如果一个标签完整但不在映射表里，它应当被消费掉（丢弃）——
        这两种情况都表现为 `shown == ""`，只有 `consumed` 能区分开。
        """
        if not self.buf:
            return False, ""
        if self.buf[0] == "[":
            end = self.buf.find("]", 1)
            if end == -1:
                # 标签还没收全（被 chunk 拆散）：等下一次 drain
                return False, ""
            tag = self.buf[:end + 1]
            self.buf = self.buf[end + 1:]
            shown = self.emoji.get(tag[1:-1], "")   # 未知标签 → 丢弃
        else:
            shown = self.buf[0]
            self.buf = self.buf[1:]
        self.text += shown
        self.started = True     # 只要推进过就算「已开始」（与原实现一致）
        return True, shown

    # ---------- 查询 ----------
    @property
    def pending(self):
        """还有没吐完的内容"""
        return bool(self.buf)

    def is_finished(self):
        """缓冲排空 且 服务端已结束 → 可以收尾。

        注意：`done` 单独为真不算完成 —— 这正是「done 先到就打断打字机」
        那个旧问题的判定依据。
        """
        return self.done and not self.buf

    # ---------- 兜底 ----------
    def flush(self):
        """把剩余缓冲一次性处理完，返回完整文本（停止 / 超时兜底用）。

        未闭合的表情标签会原样保留 —— 与旧实现 `fix_emoji(text + buf)` 行为一致。
        """
        if self.buf:
            self.text += strip_tags(self.buf, self.emoji)
            self.buf = ""
        return self.text

    # ---------- 重置 ----------
    def reset(self):
        """停止输出 / 重新开始一条流"""
        self.buf = ""
        self.text = ""
        self.done = False
        self.started = False
        return self

    def __repr__(self):
        return "StreamBuffer(text=%r, buf=%r, done=%s, started=%s)" % (
            self.text, self.buf, self.done, self.started)


_TAG_RE = re.compile(r"\[[^\[\]]*\]")


def strip_tags(text, emoji_map=None):
    """把文本里的表情标签替换成对应 emoji（未知名丢弃）。

    给「兜底全量刷出」用：停止/超时时需要一次性把剩余文本处理干净，
    不必逐个 drain。
    """
    if not text:
        return ""
    if emoji_map is None:
        return _TAG_RE.sub("", text)
    return _TAG_RE.sub(lambda m: emoji_map.get(m.group(0)[1:-1], ""), text)
