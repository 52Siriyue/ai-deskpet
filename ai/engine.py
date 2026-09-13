# -*- coding: utf-8 -*-
"""
AI 引擎：美团 LongCat-2.0 LLM 客户端（OpenAI 兼容）
- 流式输出（SSE）+ 打字机回调 + ReAct 思考过程
- Function Calling 工具注册 + 调用循环 + 多步编排
- 对话历史持久化 + 长期事实记忆（LLM 自动提取）
- RAG 知识库注入（见 ai.knowledge）
"""
import os
import sys
import json
import re
import time
import threading
import urllib.error
import urllib.request

from .knowledge import KnowledgeBase


class _StreamCancelled(Exception):
    """用户主动停止流式输出：worker 静默退出，不发 done"""


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
    """LLM 对话引擎：OpenAI 兼容接口（默认硅基流动 Qwen3.5-9B，可切智谱/LongCat）。

    支持 Function Calling 工具循环 + 流式输出 + RAG 知识库 + 长期记忆 + ReAct 回调。
    模型通道由 .env 的 LLM_BASE_URL / LLM_MODEL / LLM_API_KEY 决定。
    """

    def __init__(self, persona="", history_limit=20, history_file=None, facts_file=None):
        load_env()
        # 主通道（向后兼容：只配 LLM_* 也能正常工作）
        self.api_key = os.environ.get("LLM_API_KEY", "")
        self.base_url = os.environ.get("LLM_BASE_URL", "https://api.longcat.chat/openai").rstrip("/")
        self.model = os.environ.get("LLM_MODEL", "LongCat-2.0")
        # 多通道容错：主通道失败自动降级到备用通道（链的构建见 _load_providers）
        self.providers = self._load_providers()
        self._provider_idx = 0            # 当前使用链上的第几个通道
        self._failed_idx = set()          # 本轮已失败的通道下标（避免重复试同一个）
        self._main_cooldown_until = 0.0   # 主通道冷却截止（失败后一段时间内不再先试它）
        self.main_cooldown_sec = 60       # 冷却时长（秒）
        self.on_provider_switch = None    # 切换回调 fn(from_name, to_name, reason)
        self._apply_provider()
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
        self._cancel = threading.Event()  # 用户停止输出：设置后 worker 尽快停止
        self._extracting = False  # 事实提取线程互斥（防止并发写 facts.json）
        self.last_error = None    # 最近一次流式失败的原因（便于排查静默失败）

    def cancel(self):
        """取消当前流式输出：后台线程尽快停止，不再推送增量"""
        self._cancel.set()

    def _reset_cancel(self):
        self._cancel.clear()

    # ---------- 多通道容错（fallback 链） ----------
    def _load_providers(self):
        """按顺序收集可用通道：LLM_*（主）→ 各方括号前缀 → FALLBACK{n}_*。

        同一 base_url+model 只保留一次（去重），避免主通道与备用通道重复。
        一个都没配全时退化为仅用 LLM_*，保持与旧版本完全一致的行为。
        """
        chain = []

        def add(name, prefix, require_key=True):
            base = os.environ.get(prefix + "_BASE_URL", "").strip().rstrip("/")
            model = os.environ.get(prefix + "_MODEL", "").strip()
            key = os.environ.get(prefix + "_API_KEY", "").strip()
            if not base or not model:
                return
            if require_key and not key:
                return  # 备用通道必须有 key 才加入链
            if any(p["base_url"] == base and p["model"] == model for p in chain):
                return
            chain.append({"name": name, "base_url": base, "model": model, "api_key": key})

        add("主通道", "LLM", require_key=False)  # 主通道允许空 key（本地推理服务常见）
        for prefix, label in (("ZHIPU", "智谱"), ("SILICONFLOW", "硅基流动"),
                              ("DEEPSEEK", "DeepSeek"), ("OPENROUTER", "OpenRouter")):
            add(label, prefix)
        for i in (1, 2, 3, 4):
            add("备用%d" % i, "FALLBACK%d" % i)
        if not chain:  # 兜底：与旧版本行为一致
            chain.append({"name": "主通道", "base_url": self.base_url,
                          "model": self.model, "api_key": self.api_key})
        return chain

    def _apply_provider(self):
        """把当前通道参数同步到 base_url / api_key / model（其余代码只认这三个属性）。"""
        p = self.providers[self._provider_idx]
        self.base_url = p["base_url"]
        self.api_key = p["api_key"]
        self.model = p["model"]

    def provider_label(self):
        """当前通道的可读名称（日志 / UI 用）。"""
        return "%s｜%s" % (self.providers[self._provider_idx]["name"], self.model)

    def _begin_request(self):
        """每轮请求开始：清空失败记录；若主通道在冷却期内，直接从备用通道起步。"""
        self._failed_idx.clear()
        self._provider_idx = 0
        if (len(self.providers) > 1 and self._main_cooldown_until
                and time.time() < self._main_cooldown_until):
            self._provider_idx = 1  # 主通道刚失败过，别浪费一次超时
        self._apply_provider()

    def _rotate_provider(self, exc=None):
        """当前通道失败 → 切到下一个未失败的通道。返回是否切换成功。"""
        self._failed_idx.add(self._provider_idx)
        if self._provider_idx == 0:
            self._main_cooldown_until = time.time() + self.main_cooldown_sec
        for step in range(1, len(self.providers) + 1):
            nxt = (self._provider_idx + step) % len(self.providers)
            if nxt in self._failed_idx:
                continue
            old_name = self.providers[self._provider_idx]["name"]
            self._provider_idx = nxt
            self._apply_provider()
            try:
                print("[AIEngine] 通道降级: %s → %s（原因: %s）"
                      % (old_name, self.providers[nxt]["name"],
                         type(exc).__name__ if exc else "未知"), file=sys.stderr)
            except Exception:
                pass
            if self.on_provider_switch:
                try:
                    self.on_provider_switch(old_name, self.providers[nxt]["name"], exc)
                except Exception:
                    pass
            return True
        return False   # 所有通道都试过了

    @staticmethod
    def _is_retryable(exc):
        """判断异常是否值得换个通道重试。

        值得：网络层错误（连不上 / 超时 / 被重置）、限流 429、服务端 5xx。
        401/403 是 key 失效或无权限，也值得换。
        400 等参数类错误换了通道也一样报，不重试（免得掩盖请求本身的 bug）。
        """
        if isinstance(exc, urllib.error.HTTPError):
            code = getattr(exc, "code", 0)
            return code == 429 or code >= 500 or code in (401, 403)
        return isinstance(exc, (urllib.error.URLError, OSError, TimeoutError))

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
        """后台线程：让 LLM 从对话中提取值得长期记住的事实（JSON 数组），回调 on_done(facts)
        同一时间只允许一个提取线程（防止并发写 facts.json 竞态）"""
        if getattr(self, "_extracting", False):
            return
        self._extracting = True
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
            finally:
                self._extracting = False
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
        # 全局规则：集体代词响应（防止 LLM 在"你们/大家"语境下自我认知混乱）
        system += ("\n\n## 集体代词响应规则\n"
                   "用户称呼\"你们/大家/两个/都\"时，你和欣悦/业成是各自独立的桌宠，"
                   "你只回答你自己的部分（不要代替另一只桌宠说话，不要质疑对方是否存在，"
                   "不要编造\"只有我一个/对方不在\"之类的话）。直接回答用户问题即可。")
        # 全局红线：个性可以有，但绝不攻击用户
        system += ("\n\n## 行为红线\n"
                   "语气可以有个性（嘴硬/傲娇/吐槽都行），但**绝不输出贬低、侮辱、攻击、"
                   "嘲讽用户的话**（禁止\"你是不是该吃药了\"\"你有病吧\"等），"
                   "也不要在用户没问你身份时莫名其妙自报家门或反问\"你是不是在质疑我是谁\"。"
                   "正常回答用户的问题。")
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
        """非流式请求。失败时自动降级到备用通道（见 _rotate_provider）。"""
        self._begin_request()
        while True:
            body["model"] = self.model  # 切通道后模型名会变，必须同步
            req = urllib.request.Request(
                self.base_url + "/chat/completions",
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + self.api_key,
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except Exception as exc:
                if not self._is_retryable(exc) or not self._rotate_provider(exc):
                    raise

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
        self._reset_cancel()
        def worker():
            ok = False
            try:
                self._chat_stream_impl(user_text, on_delta, mood, full, timeout)
                ok = True
            except _StreamCancelled:
                return  # 用户主动停止：不发 done，由主线程 stop_stream 收尾
            except Exception as exc:
                # 不要静默吞异常：以前这里什么都不记，导致"工具调用后气泡空了"
                # 这类问题完全无法定位。现在打印到 stderr 并留一份 last_error 供排查。
                ok = False
                self.last_error = exc
                try:
                    import traceback
                    print(f"[AIEngine] 流式失败: {type(exc).__name__}: {exc}", file=sys.stderr)
                    traceback.print_exc(file=sys.stderr)
                except Exception:
                    pass
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
        """流式请求 + 多通道降级。

        安全约束：只在「尚未向 UI 推送任何增量」时才允许换通道重试——
        已经吐过字再重试会让用户看到重复/错乱的内容，此时直接抛错交给上层兜底。

        另外把「静默空回复」也当成失败：上游中途断连时 SSE 循环会正常结束、
        不抛异常，结果就成了一段空气泡。这种情况在换通道后往往能拿到正常回复。
        """
        self._begin_request()
        while True:
            body["model"] = self.model  # 切通道后模型名会变，必须同步
            emitted = []
            try:
                text, tool_calls = self._stream_once_raw(body, emit_delta, timeout, emitted)
            except _StreamCancelled:
                raise  # 用户主动停止，不重试
            except Exception as exc:
                if emitted:
                    raise  # 已经有输出，重试会导致重复
                if not self._is_retryable(exc) or not self._rotate_provider(exc):
                    raise
                continue
            # 既没内容也没工具调用 → 空回复，换通道再试
            if not text and not tool_calls and not emitted:
                if self._rotate_provider(None):
                    continue
                # 所有通道都返回空：认命，把空结果返回给上层去兜底
            return text, tool_calls

    def _stream_once_raw(self, body, emit_delta, timeout, emitted):
        """发起一次流式请求，解析 SSE，返回 (累积文本, tool_calls列表或None)。
        若设置 on_reason，解析 reasoning_content（LLM 思考过程）并回调。
        emitted —— 已被推送的增量标记列表，供上层判断能否安全重试。"""
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
                if self._cancel.is_set():
                    raise _StreamCancelled()  # 用户停止：立即终止流式
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
                    emitted.append(1)  # 已推送过内容，之后失败不再重试（避免重复文本）
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
            # 注意：必须带 "type": "function"。OpenAI 规范要求每个 tool_call 声明类型，
            # 缺了它 SiliconFlow/通义等严格校验的服务会回 400
            # （"Input should be 'function'"），导致工具结果回灌失败、桌宠静默不说话。
            # LongCat 等宽容服务不报错，容易掩盖这个问题。
            tool_calls = [{"id": e["id"],
                           "type": "function",
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
