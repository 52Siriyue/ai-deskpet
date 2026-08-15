# -*- coding: utf-8 -*-
"""RAG 知识库：轻量中文检索（字符 bigram 重合度，零依赖）。
知识源：备忘录 / 聊天历史 / 文档。提问时检索最相关片段注入 prompt。
"""
import os
import json
import re


class KnowledgeBase:
    """本地 RAG 知识库"""

    def __init__(self):
        self.docs = []    # [(text, source), ...]
        self.index = []   # [bigram_set, ...] 与 docs 对齐

    @staticmethod
    def _bigrams(text):
        s = re.sub(r"[^\w\u4e00-\u9fff]+", "", str(text))  # 去标点/空格
        return {s[i:i + 2] for i in range(len(s) - 1)} if len(s) >= 2 else set(s)

    def add_doc(self, text, source="知识"):
        text = (text or "").strip()
        if len(text) < 4:
            return
        self.docs.append((text, source))
        self.index.append(self._bigrams(text))

    def search(self, query, top_k=3, min_score=0.12):
        """返回最相关的文档 [(text, source), ...]。评分 = 查询 bigram 覆盖率。"""
        qb = self._bigrams(query)
        if not qb:
            return []
        scored = []
        for i, db in enumerate(self.index):
            inter = len(qb & db)
            if inter:
                score = inter / len(qb)  # 查询覆盖率（长文档不吃亏）
                if score >= min_score:
                    scored.append((score, i))
        scored.sort(key=lambda x: -x[0])
        return [self.docs[i] for _, i in scored[:top_k]]

    def load_files(self, paths):
        """批量加载知识源文件：
        - memos.json: [{"content": ...}]
        - chat_history_*.json: [{"role":..., "content":...}]
        - *.md: 全文按句切分
        """
        for path in (paths or []):
            if not path or not os.path.exists(path):
                continue
            try:
                if path.endswith(".json"):
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict):
                                content = item.get("content", "") or ""
                                if content:
                                    self.add_doc(content, "备忘" if "memo" in path else "对话")
                elif path.endswith((".md", ".txt")):
                    with open(path, "r", encoding="utf-8") as f:
                        text = f.read()
                    for line in re.split(r"[\n。！？!?]", text):
                        line = line.strip()
                        if len(line) >= 6:
                            self.add_doc(line, "文档")
            except Exception:
                continue

    def build_prompt(self, query, top_k=3):
        """检索并生成注入 prompt 片段（无结果返回空串）"""
        hits = self.search(query, top_k)
        if not hits:
            return ""
        lines = [f"- {text}" for text, _ in hits]
        return "\n【桌宠已知的信息（可参考回答，不确定就明说）】\n" + "\n".join(lines)
