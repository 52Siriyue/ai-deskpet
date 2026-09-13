# -*- coding: utf-8 -*-
"""StreamBuffer 单测 + 并发隔离实验。

设计说明：本文件**不依赖 PyQt5**，可直接 `python tests/test_stream_buffer.py` 运行，
也可以用 pytest 跑。这正是重构的目的 —— 这条路径以前必须起 GUI 才能验证。

覆盖：
- 4 类边界：表情标签被 chunk 拆散、未知标签、done 先到、空增量
- 逐字推进与 started 语义
- 并发隔离（双 Agent / 多 Agent 交错）
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.stream_buffer import StreamBuffer, strip_tags

EMOJI = {"微笑": "😊", "思考": "🤔", "爱心": "❤️"}
SB = lambda: StreamBuffer(EMOJI)          # noqa: E731


def chunks_of(text, size):
    return [text[i:i + size] for i in range(0, len(text), size)]


# ============ 基础推进 ============

def test_drain_one_unit_at_a_time():
    sb = SB()
    sb.feed("你好呀")
    assert sb.drain() == (True, "你")
    assert sb.drain() == (True, "好")
    assert sb.drain() == (True, "呀")
    assert sb.drain() == (False, "")      # 空了
    assert sb.text == "你好呀"


def test_empty_feed_is_ignored():
    sb = SB()
    sb.feed("")
    sb.feed(None)
    assert sb.buf == "" and sb.text == ""
    assert sb.drain() == (False, "")


def test_started_flag():
    sb = SB()
    assert sb.started is False
    sb.feed("a")
    sb.drain()
    assert sb.started is True


# ============ 边界 1：表情标签被 chunk 拆散 ============

def test_tag_split_across_chunks():
    """`[微笑]` 被服务端切成 `[微` + `笑]` —— 这是真实会遇到的情况"""
    sb = SB()
    sb.feed("[微")
    assert sb.drain() == (False, "")      # 不能推进，也不能丢弃
    assert sb.buf == "[微"                  # 原样保留等后续
    sb.feed("笑]")
    assert sb.drain() == (True, "😊")
    assert sb.text == "😊"


def test_tag_split_leaves_started_false():
    """标签未收全时不应置 started（否则会提前 begin_stream 出空气泡）"""
    sb = SB()
    sb.feed("[思")
    sb.drain()
    assert sb.started is False


def test_text_interleaved_with_tags():
    sb = SB()
    sb.feed("嗨[爱心]再见")
    out = []
    while True:
        c, s = sb.drain()
        if not c:
            break
        out.append(s)
    assert out == ["嗨", "❤️", "再", "见"]
    assert sb.text == "嗨❤️再见"


# ============ 边界 2：未知标签 ============

def test_unknown_tag_dropped_but_consumed():
    """未知标签要「消费掉但不显示」—— 与「等后续 chunk」是不同语义"""
    sb = SB()
    sb.feed("[不存在]好")
    assert sb.drain() == (True, "")        # consumed=True 但没内容
    assert sb.drain() == (True, "好")
    assert sb.text == "好"
    assert sb.buf == ""


# ============ 边界 3：done 先到，缓冲还没吐完 ============

def test_done_does_not_finish_while_buf_remains():
    """done 到达时缓冲还有内容 → 不能算完成（否则会打断打字机）"""
    sb = SB()
    sb.feed("abc")
    sb.mark_done()
    assert sb.is_finished() is False
    sb.drain()
    assert sb.is_finished() is False
    sb.drain()
    assert sb.is_finished() is False
    sb.drain()
    assert sb.is_finished() is True        # 排空后才算完成


def test_finished_requires_both_conditions():
    sb = SB()
    sb.feed("x")
    assert sb.is_finished() is False       # 未 done
    sb.drain()
    assert sb.is_finished() is False       # 排空但未 done
    sb.mark_done()
    assert sb.is_finished() is True


def test_done_with_empty_buffer_finishes_immediately():
    sb = SB()
    sb.mark_done()
    assert sb.is_finished() is True


# ============ 边界 4：停止 / 重置 ============

def test_reset_clears_everything():
    sb = SB()
    sb.feed("abc[微")
    sb.drain()
    sb.mark_done()
    sb.reset()
    assert (sb.buf, sb.text, sb.done, sb.started) == ("", "", False, False)
    assert sb.is_finished() is False


# ============ 兜底全量处理 ============

def test_strip_tags_full_flush():
    """停止/超时兜底：一次性把剩余文本处理干净"""
    assert strip_tags("嗨[爱心]再见", EMOJI) == "嗨❤️再见"
    assert strip_tags("[不存在]x", EMOJI) == "x"
    assert strip_tags("", EMOJI) == ""


# ============ 并发隔离 ============

def test_two_agents_do_not_cross_talk():
    """两个 Agent 交错流式：各自文本必须完整且互不污染。

    这是旧架构的核心问题所在 —— 当时聊天窗口没有按 Agent 隔离的流式通道。
    """
    a, b = SB(), SB()
    sa, sb_text = "你好呀[微笑]我是欣悦", "收到[思考]我是业成"
    ca, cb = chunks_of(sa, 1), chunks_of(sb_text, 2)
    ia = ib = 0
    oa, ob = [], []
    while ia < len(ca) or ib < len(cb):
        if ia < len(ca):
            a.feed(ca[ia]); ia += 1
        if ib < len(cb):
            b.feed(cb[ib]); ib += 1
        for sbuf, sink in ((a, oa), (b, ob)):
            if sbuf.pending:
                sink.append(sbuf.drain()[1])
    while a.pending:
        oa.append(a.drain()[1])
    while b.pending:
        ob.append(b.drain()[1])

    assert "".join(oa) == strip_tags(sa, EMOJI)
    assert "".join(ob) == strip_tags(sb_text, EMOJI)
    assert a.text == "你好呀😊我是欣悦"
    assert b.text == "收到🤔我是业成"
    assert "业成" not in a.text and "欣悦" not in b.text   # 无串台


def test_many_agents_stress():
    """N 个 Agent × M 轮随机交错，统计串台与丢字。"""
    random.seed(20260914)
    N, M = 8, 60
    payloads = ["第%d号桌宠[微笑]第%d句内容" % (i, j) for i in range(N) for j in range(M)]

    bufs = [SB() for _ in range(N)]
    sinks = [[] for _ in range(N)]
    # 每个 Agent 一条待发送文本
    texts = ["A%d开头[思考]中间内容A%d[爱心]结尾A%d" % (i, i, i) for i in range(N)]
    queues = [chunks_of(t, 1 if i % 2 == 0 else 3) for i, t in enumerate(texts)]

    rounds = 0
    while any(queues) or any(x.pending for x in bufs):
        rounds += 1
        for i in range(N):
            if queues[i]:
                bufs[i].feed(queues[i].pop(0))
        for i in range(N):
            if bufs[i].pending:
                sinks[i].append(bufs[i].drain()[1])
        if rounds > 10000:
            raise AssertionError("未能收敛，可能存在死循环")

    cross, lost = 0, 0
    for i in range(N):
        expect = strip_tags(texts[i], EMOJI)
        got = "".join(sinks[i])
        if got != expect:
            lost += 1
        # 串台检测：出现了别的 Agent 的标记
        for j in range(N):
            if j != i and ("A%d" % j) in got:
                cross += 1

    assert lost == 0, "有 %d 个 Agent 的文本不完整" % lost
    assert cross == 0, "发生 %d 次串台" % cross
    assert [x.text for x in bufs] == [strip_tags(t, EMOJI) for t in texts]
    print("      压力测试：%d 个 Agent、%d 轮交错、%d 次 drain，串台 %d、丢字 %d"
          % (N, rounds, sum(len(s) for s in sinks), cross, lost))


def test_instances_are_independent():
    """两个实例的状态必须完全独立（旧架构靠 name 字符串约定，这里靠构造）"""
    a, b = SB(), SB()
    a.feed("AAA"); a.mark_done()
    b.feed("BBB")
    assert a.text == "" and b.text == ""
    a.drain(); b.drain()
    assert a.text == "A" and b.text == "B"
    assert a.done is True and b.done is False
    assert a.reset() is a and b.buf == "BB"


# ============ 手动运行入口（不依赖 pytest）============

if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    passed, failed = 0, []
    print("=" * 68)
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print("  PASS  %s" % name)
        except Exception as exc:
            failed.append((name, exc))
            print("  FAIL  %s  →  %s: %s" % (name, type(exc).__name__, exc))
    print("=" * 68)
    print("  共 %d 个用例，通过 %d，失败 %d" % (len(tests), passed, len(failed)))
    if failed:
        sys.exit(1)
    print("  全部通过")
