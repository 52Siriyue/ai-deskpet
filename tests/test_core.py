# -*- coding: utf-8 -*-
"""核心逻辑单元测试：表情转换 / RAG 检索 / 工具调用"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
os.chdir(BASE)

from ai_engine import KnowledgeBase, AIEngine
import main as m


def test_fix_emoji_known():
    assert m.fix_emoji("[捂脸]好嘟～") == "🤦好嘟～"
    assert m.fix_emoji("[嘿嘿]开始啦") == "😁开始啦"
    assert m.fix_emoji("[大笑]和[汗]") == "😂和😅"


def test_fix_emoji_unknown_removed():
    assert m.fix_emoji("[未知标签]删掉") == "删掉"
    assert m.fix_emoji("无表情文本") == "无表情文本"


def test_fix_emoji_mixed():
    assert m.fix_emoji("[捂脸]好的[嘿嘿]") == "🤦好的😁"


def test_kb_search_hit():
    kb = KnowledgeBase()
    kb.add_doc("明天下午三点开会，记得带电脑", "备忘")
    kb.add_doc("用户喜欢喝珍珠奶茶，半糖去冰", "对话")
    hits = kb.search("我明天有什么安排", top_k=2)
    assert any("开会" in t for t, _ in hits)


def test_kb_search_irrelevant():
    kb = KnowledgeBase()
    kb.add_doc("明天下午三点开会", "备忘")
    assert kb.search("今天天气怎么样") == []


def test_kb_build_prompt():
    kb = KnowledgeBase()
    kb.add_doc("用户喜欢喝珍珠奶茶", "对话")
    hint = kb.build_prompt("我喜欢喝什么")
    assert "珍珠奶茶" in hint


def test_load_pets_config_default():
    cfg = m.load_pets_config()
    assert len(cfg) >= 2
    assert cfg[0]["name"] in ("欣悦", "业成")


def test_emoji_regex_no_crash():
    # 纯括号串不构成 [表情] 格式 → 原样保留（不崩溃）
    s = "[" * 10 + "]" * 10
    assert m.fix_emoji(s) == s


def test_tools_registered():
    """AIEngine 工具定义合法（每个工具都有 name/parameters）"""
    eng = AIEngine(persona="t")
    from main import PetWindow
    tools = PetWindow.TOOLS_DEFS
    assert len(tools) >= 10
    for t in tools:
        assert t["function"]["name"]
        assert "parameters" in t["function"]
