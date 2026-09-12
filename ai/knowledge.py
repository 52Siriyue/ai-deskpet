# -*- coding: utf-8 -*-
"""RAG 知识库：轻量中文检索（字符 bigram 词元 + TF-IDF 加权，零依赖）。
知识源：备忘录 / 聊天历史 / 文档。提问时检索最相关片段注入 prompt。
"""
import os
import json
import re
import math


class KnowledgeBase:
    """本地 RAG 知识库（TF-IDF 检索，比纯重合度更精准）"""

    def __init__(self):
        self.docs = []       # [(text, source), ...]
        self._terms = []     # 每文档的 term 计数 {term: count}，与 docs 对齐
        self._df = {}        # term -> 出现该 term 的文档数
        self._total = 0      # 文档总数

    @staticmethod
    def _tokenize(text):
        """分词：去标点/空格 → 字符 bigram（中文无需分词库的轻量方案）"""
        s = re.sub(r"[^\w\u4e00-\u9fff]+", "", str(text))
        if len(s) < 2:
            return list(s)
        return [s[i:i + 2] for i in range(len(s) - 1)]

    def _term_counts(self, text):
        counts = {}
        for t in self._tokenize(text):
            counts[t] = counts.get(t, 0) + 1
        return counts

    def add_doc(self, text, source="知识"):
        text = (text or "").strip()
        if len(text) < 4:
            return
        counts = self._term_counts(text)
        self.docs.append((text, source))
        self._terms.append(counts)
        for t in counts:
            self._df[t] = self._df.get(t, 0) + 1
        self._total = len(self.docs)

    def search(self, query, top_k=3, min_score=0.02):
        """返回最相关的文档 [(text, source), ...]。TF-IDF 加权点积评分。"""
        qc = self._term_counts(query)
        if not qc or not self._total:
            return []
        qn = sum(qc.values())
        n = self._total
        scored = []
        for i, counts in enumerate(self._terms):
            dl = max(1, sum(counts.values()))
            score = 0.0
            for t, qf in qc.items():
                tf_d = counts.get(t, 0) / dl
                if tf_d <= 0:
                    continue
                idf = math.log((n + 1) / (self._df.get(t, 0) + 1)) + 1.0
                score += (qf / qn) * idf * tf_d * idf
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
