# -*- coding: utf-8 -*-
"""
AI 引擎（V1）：美团 LongCat-2.0 LLM 客户端
- OpenAI 兼容协议（base_url: https://api.longcat.chat/openai）
- 后台线程调用（不阻塞 UI）+ 对话历史管理 + 人格注入
- API Key 从 .env 读取（绝不写入代码）
"""
import os
import sys
import json
import re
import threading
import urllib.request
import urllib.error


class KnowledgeBase:
    """本地 RAG 知识库：轻量中文检索（字符 bigram 重合度，零依赖）。
    知识源：备忘录 / 聊天历史 / 文档。提问时检索最相关片段注入 prompt。
    """

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


def load_env(env_path=None):
    """从 .env 文件加载环境变量（不覆盖已存在的环境变量）。
    候选位置：源码目录 / exe 同目录 / PyInstaller _MEIPASS，保证打包后也能读到。
    """
    if env_path is None:
        candidates = []
        here = os.path.dirname(os.path.abspath(__file__))
        candidates.append(os.path.join(here, ".env"))
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), ".env"))
        candidates.append(os.path.join(getattr(sys, '_MEIPASS', ''), ".env"))
        for c in candidates:
            if c and os.path.exists(c):
                env_path = c
                break
    if env_path and os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip()
                    if k and k not in os.environ:
                        os.environ[k] = v


class AIEngine:
    """LLM 对话引擎：美团 LongCat-2.0，OpenAI 兼容。V2 支持 Function Calling 工具调用。"""

    def __init__(self, persona="", history_limit=20, history_file=None, facts_file=None):
        load_env()
        self.api_key = os.environ.get("LLM_API_KEY", "")
        self.base_url = os.environ.get("LLM_BASE_URL", "https://api.longcat.chat/openai").rstrip("/")
        self.model = os.environ.get("LLM_MODEL", "LongCat-2.0")
        self.persona = persona
        self.history_limit = history_limit
        self.history_file = history_file  # 记忆持久化文件（None = 不持久化）
        self.history = self._load_history()  # 对话历史（重启后仍记得）
        self.facts_file = facts_file  # 长期事实记忆文件
        self.facts = self._load_facts()  # 用户偏好/重要事件（LLM 自动提取）
        self.tools = []          # OpenAI 格式工具定义
        self.tool_handlers = {}  # name -> fn(args: dict) -> dict
        self.on_tool_call = None  # 工具调用回调 fn(name, args)（ReAct 可视化）
        self.on_reason = None     # 思考过程回调 fn(text)（ReAct 可视化）
        self.on_observe = None    # 工具结果回调 fn(name, result)（ReAct 可视化）
        self.kb = KnowledgeBase()  # 本地 RAG 知识库

    def _load_facts(self):
        if not self.facts_file or not os.path.exists(self.facts_file):
            return []
        try:
            with open(self.facts_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [x for x in data if isinstance(x, str)] if isinstance(data, list) else []
        except Exception:
            return []

    def _save_facts(self):
        if not self.facts_file:
            return
        try:
            with open(self.facts_file, "w", encoding="utf-8") as f:
                json.dump(self.facts[-50:], f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    def add_facts(self, new_facts):
        """合并去重新事实并持久化（LLM 提取结果）"""
        added = 0
        for f in new_facts or []:
            if isinstance(f, str) and f not in self.facts:
                self.facts.append(f)
                self.kb.add_doc(f, "记忆")
                added += 1
        if added:
            self._save_facts()
        return added

    def extract_facts_async(self, user_text, reply, on_done=None):
        """后台线程：让 LLM 从对话中提取值得长期记住的事实（JSON 数组），回调 on_done(facts)"""
        def worker():
            try:
                body = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content":
                         "从这段对话中提取值得长期记住的事实（用户偏好、习惯、重要日期、关键信息、承诺）。"
                         "只输出 JSON 数组字符串，如 [\"用户喜欢喝珍珠奶茶\"]。没有就输出 []。"},
                        {"role": "user", "content": f"用户：{user_text}\n桌宠：{reply}"},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 200,
                }
                data = self._post(body, 20)
                msg = data["choices"][0]["message"]
                # LongCat 有时先出 reasoning_content（思考），content 为空 → 兜底
                raw = (msg.get("content") or msg.get("reasoning_content") or "")
                m = re.search(r"\[.*?\]", raw, re.S)
                facts = json.loads(m.group(0)) if m else []
                if on_done:
                    on_done(facts)
            except Exception:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def build_knowledge(self, paths):
        """加载知识源到本地知识库（备忘录/聊天历史/文档）"""
        self.kb.load_files(paths)

    def _load_history(self):
        """从文件加载对话历史（重启后仍记得聊过什么）"""
        if not self.history_file or not os.path.exists(self.history_file):
            return []
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save_history(self):
        """把对话历史保存到文件（追加记忆）"""
        if not self.history_file:
            return
        try:
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(self.history[-self.history_limit * 2:], f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    def register_tools(self, tools_defs, handlers):
        """注册 Function Calling 工具：tools_defs 是 OpenAI schema 列表，handlers 是 {name: fn}"""
        self.tools = tools_defs
        self.tool_handlers = handlers

    def _build_messages(self, user_text, mood, full):
        system = self.persona or "你是桌面上的可爱桌宠，用简短口语化的方式说话，不要用列表和长句。"
        tools_hint = ""
        if self.tools:
            names = "、".join(t["function"]["name"] for t in self.tools)
            tools_hint = f"\n你拥有工具能力：{names}。当用户提出相关需求时，调用对应工具帮用户完成，然后用一句话确认结果。"
        system += f"\n（当前心情 {mood}/100，饱食度 {full}/100，回复控制在 1-2 句话，可用 emoji）{tools_hint}"
        # RAG：检索知识库相关片段注入
        kb_hint = self.kb.build_prompt(user_text) if getattr(self, "kb", None) else ""
        if kb_hint:
            system += kb_hint
        # 长期事实记忆注入（用户偏好/重要事件）
        if self.facts:
            system += "\n【关于用户，你长期记住的事实】" + "；".join(self.facts[-10:])
        messages = [{"role": "system", "content": system}]
        messages += self.history[-self.history_limit * 2:]
        messages.append({"role": "user", "content": user_text})
        return messages

    def _post(self, body, timeout):
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.api_key,
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def chat(self, user_text, mood=70, full=70, timeout=30):
        """同步调用 LLM（支持工具调用循环），返回最终回复文本。

        Function Calling 循环：LLM 返回 tool_calls → 逐个执行工具 → 结果回传
        → LLM 生成最终回复。最多循环 4 轮防止死循环。
        """
        messages = self._build_messages(user_text, mood, full)
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.8,
        }
        if self.tools:
            body["tools"] = self.tools
        data = self._post(body, timeout)
        msg = data["choices"][0]["message"]

        # 工具调用循环
        for _ in range(4):
            if not msg.get("tool_calls"):
                break
            messages.append(msg)  # assistant 的 tool_calls 消息
            for tc in msg["tool_calls"]:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                handler = self.tool_handlers.get(name)
                if handler:
                    try:
                        result = handler(args)
                    except Exception as exc:
                        result = {"ok": False, "msg": f"工具执行出错: {exc}"}
                else:
                    result = {"ok": False, "msg": f"未知工具 {name}"}
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": json.dumps(result, ensure_ascii=False),
                })
            body["messages"] = messages
            data = self._post(body, timeout)
            msg = data["choices"][0]["message"]

        reply = (msg.get("content") or "").strip()
        # 记录历史 + 持久化保存（重启不忘）
        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": reply})
        if len(self.history) > self.history_limit * 2:
            self.history = self.history[-self.history_limit * 2:]
        self._save_history()
        return reply

    # ---------- 流式输出（SSE） ----------
    def chat_async_stream(self, user_text, on_delta, on_done, mood=70, full=70, timeout=45):
        """流式聊天：后台线程边收边推，完成后回调。

        线程安全约定：on_delta / on_done 必须传 Qt 信号 emit（跨线程自动排队到主线程）。
        on_done(ok: bool) —— ok=True 流式完成，ok=False 出错（调用方兜底本地台词）。
        """
        def worker():
            ok = False
            try:
                self._chat_stream_impl(user_text, on_delta, mood, full, timeout)
                ok = True
            except Exception:
                ok = False
            on_done(ok)
        threading.Thread(target=worker, daemon=True).start()

    def _chat_stream_impl(self, user_text, emit_delta, mood, full, timeout):
        """流式主流程：工具调用循环兼容（LLM 可先调工具，再流式输出最终回复）"""
        messages = self._build_messages(user_text, mood, full)
        body = {"model": self.model, "messages": messages, "temperature": 0.8,
                "stream": True}
        if self.tools:
            body["tools"] = self.tools
        reply, tool_calls = self._stream_once(body, emit_delta, timeout)
        for _ in range(4):
            if not tool_calls:
                break
            messages.append({"role": "assistant",
                             "content": reply or None,
                             "tool_calls": tool_calls})
            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                # ReAct 可视化：通知 UI 正在调用工具
                if self.on_tool_call:
                    try:
                        self.on_tool_call(name, args)
                    except Exception:
                        pass
                handler = self.tool_handlers.get(name)
                if handler:
                    try:
                        result = handler(args)
                    except Exception as exc:
                        result = {"ok": False, "msg": f"工具执行出错: {exc}"}
                else:
                    result = {"ok": False, "msg": f"未知工具 {name}"}
                # ReAct 观察：通知 UI 工具执行结果
                if self.on_observe:
                    try:
                        self.on_observe(name, result)
                    except Exception:
                        pass
                messages.append({"role": "tool",
                                 "tool_call_id": tc.get("id", ""),
                                 "content": json.dumps(result, ensure_ascii=False)})
            body["messages"] = messages
            reply, tool_calls = self._stream_once(body, emit_delta, timeout)
        # 记录历史 + 持久化
        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": reply})
        if len(self.history) > self.history_limit * 2:
            self.history = self.history[-self.history_limit * 2:]
        self._save_history()

    def _stream_once(self, body, emit_delta, timeout):
        """发起一次流式请求，解析 SSE，返回 (累积文本, tool_calls列表或None)。
        若设置 on_reason，解析 reasoning_content（LLM 思考过程）并回调。"""
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.api_key},
        )
        full = ""
        tc_map = {}  # index -> {id, name, arguments}
        reason_buf = ""
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw in resp:  # 逐行读 SSE
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                delta = (obj.get("choices") or [{}])[0].get("delta", {}) or {}
                c = delta.get("content")
                if c:
                    full += c
                    emit_delta(c)
                # ReAct 思考过程（reasoning_content）→ 累积后一次性回调
                rc = delta.get("reasoning_content")
                if rc:
                    reason_buf += rc
                if reason_buf and self.on_reason:
                    try:
                        self.on_reason(reason_buf)
                        reason_buf = ""
                    except Exception:
                        pass
                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    entry = tc_map.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if tc.get("id"):
                        entry["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        entry["name"] += fn["name"]
                    if fn.get("arguments"):
                        entry["arguments"] += fn["arguments"]
        tool_calls = None
        if tc_map:
            tool_calls = [{"id": e["id"],
                           "function": {"name": e["name"], "arguments": e["arguments"]}}
                          for _, e in sorted(tc_map.items())]
        return full, tool_calls

    def chat_async(self, user_text, on_done, mood=70, full=70, timeout=30):
        """后台线程调用 LLM，完成后回调 on_done(reply)。

        线程安全约定：on_done 必须传 Qt 信号 emit（如 pet.ai_reply_signal.emit），
        信号跨线程 emit 会自动排队到主线程执行，杜绝"工作线程直接操作 UI"
        导致的气泡不显示 / 粒子定时器异常等问题。
        """
        def worker():
            try:
                reply = self.chat(user_text, mood, full, timeout)
            except Exception as exc:
                reply = None
            on_done(reply)
        threading.Thread(target=worker, daemon=True).start()
