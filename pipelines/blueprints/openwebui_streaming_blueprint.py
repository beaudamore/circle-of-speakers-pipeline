"""
title: OpenWebUI Streaming Blueprint
author: beaudamore
date: 2025-09-15
version: 1.0
license: MIT
description: Base blueprint for OpenWebUI streaming pipelines - provides reusable API integration, streaming, debugging, and model management
"""

from typing import List, Generator, Dict, Optional
import json
import re
from pydantic import BaseModel, Field
import requests


class Pipeline:
    """Base OpenWebUI Streaming Pipeline Blueprint - inherit from this for custom pipelines"""

    class Valves(BaseModel):
        """Base configuration valves for OpenWebUI integration"""

        # Global Settings
        OPENWEBUI_ENDPOINT: str = "http://host.docker.internal:3000"
                 
        OPENWEBUI_API_KEY: str = Field(
            default="",
            description="Must use JWT token",
        )
        
        USER_AGENT: str = Field(
            default="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            description="User-Agent header to use for all API requests to OpenWebUI.",
        )

        # History Truncation
        HISTORY_MAX_ROUNDS: int = Field(
            default=0,
            description="Maximum number of conversation rounds (user+assistant pairs) to keep in history. "
                        "Older rounds are dropped to stay within model context limits (e.g., --max-model-len 8192). "
                        "System messages are always preserved. 0 = no truncation (keep all history).",
        )

        # Two-tier debug controls
        enable_full_debug: bool = Field(
            default=False,
            description="Enable heavy debugging logs, including payloads/results (masked & truncated)."
        )
        enable_step_debug: bool = Field(
            default=False,
            description="Enable step-by-step progress logs (concise, truncated)."
        )

    def __init__(self):
        self.name = "OpenWebUI Streaming Blueprint"
        self.valves = self.Valves()
        self.available_models: List[dict] = []

    # --- Centralized debugging helpers ---
    def _is_full_debug(self) -> bool:
        v = getattr(self, "valves", None)
        return bool(getattr(v, "enable_full_debug", False) or getattr(v, "ENABLE_FULL_DEBUG", False))

    def _is_step_debug(self) -> bool:
        v = getattr(self, "valves", None)
        return bool(
            getattr(v, "enable_step_debug", False)
            or getattr(v, "ENABLE_STEP_DEBUG", False)
            or self._is_full_debug()
        )

    def _truncate(self, text, n: int = 200):
        try:
            s = str(text)
        except Exception:
            return text
        if len(s) <= n:
            return s
        return s[: n - 1] + "…"

    def _mask(self, value):
        _re = re

        def mask_str(s: str) -> str:
            out = s
            out = _re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[REDACTED_EMAIL]", out)
            out = _re.sub(r"\+?\d[\d\-\.\s()]{6,}\d", "[REDACTED_PHONE]", out)
            out = _re.sub(r"([A-Za-z0-9-_]{20,})", "[REDACTED_TOKEN]", out)
            return out

        if isinstance(value, str):
            return mask_str(value)
        if isinstance(value, dict):
            red = {}
            for k, v in value.items():
                kl = str(k).lower()
                if kl in {"authorization", "api_key", "apikey", "token", "secret", "password"}:
                    red[k] = "[REDACTED]"
                else:
                    red[k] = self._mask(v)
            return red
        if isinstance(value, list):
            return [self._mask(v) for v in value]
        if isinstance(value, tuple):
            return tuple(self._mask(v) for v in value)
        return value

    def _print_safely(self, *parts):
        try:
            print(*parts)
        except Exception:
            pass

    def _dbg_step(self, *parts):
        if self._is_step_debug():
            self._print_safely(*parts)

    def _dbg_full(self, *parts):
        if self._is_full_debug():
            self._print_safely(*parts)

    # --- OpenWebUI API Methods ---

    def _fetch_available_models_sync(self) -> list:
        """Fetch available OpenWebUI Models - synchronous - returns a list of models"""
        self._dbg_step("--- Model Fetch Debug ---")
        base_endpoint = f"{self.valves.OPENWEBUI_ENDPOINT}/api/v1/models/list"
        headers = {
            "accept": "application/json",
            "Origin": self.valves.OPENWEBUI_ENDPOINT,
            "User-Agent": self.valves.USER_AGENT,
        }
        api_key = getattr(self.valves, "OPENWEBUI_API_KEY", None)
        if not api_key or not str(api_key).strip():
            raise ValueError("OPENWEBUI_API_KEY is required for OpenWebUI API access and is not set.")
        headers["Authorization"] = f"Bearer {self.valves.OPENWEBUI_API_KEY}"

        self._dbg_full("  Headers:", headers)
        aggregated: list = []
        page = 1
        max_pages = 1000

        try:
            while page <= max_pages:
                endpoint = f"{base_endpoint}?page={page}"
                self._dbg_step(f"  Fetching page {page}: {endpoint}")
                with requests.get(endpoint, headers=headers, timeout=60) as response:
                    self._dbg_step(f"    Status: {response.status_code}")
                    if response.status_code != 200:
                        self._dbg_step("    Non-200 encountered; stopping pagination")
                        break
                    raw_text = response.text
                    if not raw_text.strip():
                        self._dbg_step("    Empty body encountered; stopping")
                        break
                    try:
                        data = response.json()
                    except json.JSONDecodeError as e:
                        self._dbg_step(f"    JSON decode failed on page {page}: {e}")
                        break

                    if not isinstance(data, dict):
                        self._dbg_step(f"    Unexpected non-dict response type {type(data)}; stopping")
                        break
                    if "items" not in data or not isinstance(data["items"], list):
                        self._dbg_step(f"    Missing 'items' list key (keys={list(data.keys())}); stopping")
                        break
                    items = data["items"]

                    self._dbg_step(f"    Page {page} items: {len(items)}")
                    aggregated.extend([m for m in items if isinstance(m, dict)])

                    total_val = data.get("total")
                    if total_val == 0 or len(items) == 0:
                        self._dbg_step(f"    Termination condition met (total={total_val}, items={len(items)}); stopping")
                        break
                    page += 1

            seen = set()
            deduped = []
            for m in aggregated:
                mid = m.get("id")
                if not mid or mid in seen:
                    continue
                seen.add(mid)
                deduped.append(m)

            self.available_models = deduped
            self._dbg_step(f"  Pagination complete. Pages fetched: {page}. Models loaded: {len(self.available_models)}")
            return self.available_models

        except requests.exceptions.RequestException as e:
            self._dbg_step(f"  Result: CRITICAL - Request to OpenWebUI failed. Error: {e}")
            self.available_models = []
            return []

    def _resolve_model_id(self, model_display_name: str) -> str:
        """Resolve display name to actual model ID"""
        self._dbg_step("🔧 **MODEL RESOLUTION DEBUG**:")
        self._dbg_step(f"   Original: '{model_display_name}'")
        self._dbg_step(f"   Available models count: {len(self.available_models)}")

        if not model_display_name:
            self._dbg_step("   ❌ Empty model name provided")
            return ""

        self._dbg_step(f"🔍 **SEARCHING FOR**: '{model_display_name}'")
        for model in self.available_models:
            model_name = model.get("name", "")
            if model_name.lower() == model_display_name.lower():
                model_id = model.get("id", "")
                self._dbg_step(f"   ✅ **FOUND BY NAME**: '{model_name}' -> ID: '{model_id}'")
                return model_id

        for model in self.available_models:
            model_id = model.get("id", "")
            if model_id.lower() == model_display_name.lower():
                self._dbg_step(f"   ✅ **FOUND BY ID**: '{model_id}'")
                return model_id

        self._dbg_step(
            f"   ❌ **NOT FOUND** in {len(self.available_models)} available models - returning original"
        )
        return model_display_name

    def _get_model_tool_ids(self, model_id: str) -> List[str]:
        """Get the tool IDs associated with a model from the available_models data"""
        self._dbg_step(f"🔧 **TOOL LOOKUP**: Searching for tools for model '{model_id}'")
        self._dbg_step(f"   📊 Total models in available_models: {len(self.available_models)}")
        
        for model in self.available_models:
            model_id_field = model.get("id")
            model_name_field = model.get("name")
            self._dbg_step(f"   🔍 Checking model: id='{model_id_field}', name='{model_name_field}'")
            
            if model_id_field == model_id or model_name_field == model_id:
                self._dbg_step("   ✅ MATCH! Examining model structure…")
                self._dbg_step(f"   🔑 Model keys: {list(model.keys())}")
                
                if "meta" in model and isinstance(model["meta"], dict):
                    meta = model["meta"]
                    tool_ids = meta.get("toolIds", [])
                    
                    if tool_ids:
                        self._dbg_step(f"   ✅ Found {len(tool_ids)} tool(s) in meta.toolIds: {tool_ids}")
                        return tool_ids
                    else:
                        self._dbg_step("   ℹ️ Model has no tools configured (meta.toolIds is empty)")
                        return []
                else:
                    raise ValueError(f"Model '{model_id}' has invalid structure - missing 'meta' object")
        
        raise ValueError(f"Model '{model_id}' not found in available models. Available model IDs: {[m.get('id') for m in self.available_models]}")

    def _query_openwebui_model_streaming(
        self, model_name: str, messages: List[dict], tool_ids: Optional[List[str]] = None, include_usage: bool = False
    ) -> Generator[str, None, None]:
        """Query OpenWebUI model with streaming response. Automatically detects thinking/reasoning in output."""

        url = f"{self.valves.OPENWEBUI_ENDPOINT}/api/v1/chat/completions"
        self._dbg_step(f"--- DEBUG: Streaming Query to {model_name} ---")

        try:
            api_key = getattr(self.valves, "OPENWEBUI_API_KEY", None)
            if not api_key or not str(api_key).strip():
                raise ValueError("OPENWEBUI_API_KEY is required for chat completions and is not set.")

            payload = {
                "model": model_name,
                "messages": messages,
                "stream": True,
                # Empty string avoids open-webui's get_event_emitter None.startswith() crash
                # while keeping `if chat_id` falsy downstream — matches pre-update behavior.
                "chat_id": "",
            }
            
            # Only request usage if explicitly enabled
            if include_usage:
                payload["stream_options"] = {"include_usage": True}
                self._dbg_step("  📊 Usage tracking enabled")
            
            self._dbg_step(f"  payload: {payload}")
            
            if tool_ids:
                payload["metadata"] = {
                    "tool_ids": tool_ids
                }
                self._dbg_step(f"  ✅ Tool IDs included in metadata: {tool_ids}")
            else:
                self._dbg_step("  ⚠️ No tool_ids provided - payload will NOT include tools")

            headers = {
                "Content-Type": "application/json",
                "Origin": self.valves.OPENWEBUI_ENDPOINT,
                "User-Agent": self.valves.USER_AGENT,
            }
            headers["Authorization"] = f"Bearer {self.valves.OPENWEBUI_API_KEY}"

            self._dbg_step(f"  URL: {url}")
            self._dbg_full("  Headers:", headers)
            self._dbg_step(f"  📋 Payload contains {len(messages)} messages")

            reasoning_buffer = []
            reasoning_active = False
            in_thinking_tags = False  # Track XML <think>/<thinking> tag state across chunks
            captured_usage = None  # Track usage from stream
            sse_lines_seen = 0
            content_chars_yielded = 0

            with requests.post(
                url, headers=headers, json=payload, stream=True, timeout=120
            ) as response:
                self._dbg_step(f"  Response Status: {response.status_code}")
                if response.status_code == 200:
                    for line in response.iter_lines():
                        if not line:
                            continue
                        sse_lines_seen += 1
                        line_str = line.decode("utf-8")
                        self._dbg_full(f"  SSE line #{sse_lines_seen}: {self._truncate(line_str, 400)}")
                        if line_str.startswith("data: "):
                            data_str = line_str[6:]
                            if data_str.strip() == "[DONE]":
                                self._dbg_step(f"  Stream finished: [DONE] received. SSE lines={sse_lines_seen} yielded_chars={content_chars_yielded}")
                                # Yield usage data as special marker before finishing
                                if captured_usage:
                                    yield f"__USAGE_DATA__:{json.dumps(captured_usage)}"
                                return
                            try:
                                data = json.loads(data_str)
                            except json.JSONDecodeError:
                                self._dbg_step("    ⚠️ JSON Decode Error on data:", data_str)
                                yield data_str
                                continue

                            # Check for usage data in the stream chunk
                            if isinstance(data, dict) and "usage" in data:
                                captured_usage = data["usage"]
                                self._dbg_step(f"  📊 Usage captured: {captured_usage}")

                            if isinstance(data, dict) and "choices" in data and isinstance(data["choices"], list) and data["choices"]:
                                delta = data["choices"][0].get("delta") or {}
                                
                                reasoning = delta.get("reasoning_content") or delta.get("reasoning") or delta.get("thinking")
                                if isinstance(reasoning, str) and reasoning:
                                    reasoning_active = True
                                    reasoning_buffer.append(reasoning)
                                    yield f"__REASONING_CHUNK__:{reasoning}"
                                    continue
                                
                                content = delta.get("content") if isinstance(delta, dict) else None
                                if not isinstance(content, str) or not content:
                                    # Fallback: delta might be a string directly
                                    if isinstance(delta, str) and delta:
                                        content = delta
                                    else:
                                        content = None

                                if content:
                                    if reasoning_active:
                                        reasoning_active = False

                                    if in_thinking_tags:
                                        # We're inside <think>...</think> - check for closing tag
                                        close_match = re.search(r'</think>|</thinking>', content)
                                        if close_match:
                                            thinking_part = content[:close_match.start()]
                                            regular_part = content[close_match.end():]
                                            if thinking_part:
                                                yield f"__THINKING_TAG_CONTENT__:{thinking_part}"
                                            yield "__THINKING_TAG_CLOSE__"
                                            in_thinking_tags = False
                                            if regular_part:
                                                yield regular_part
                                        else:
                                            yield f"__THINKING_TAG_CONTENT__:{content}"
                                    elif "<think>" in content or "<thinking>" in content:
                                        # Opening tag found - enter thinking state
                                        open_match = re.search(r'<think>|<thinking>', content)
                                        if open_match:
                                            before = content[:open_match.start()]
                                            after = content[open_match.end():]
                                        else:
                                            before = ""
                                            after = content
                                        if before:
                                            yield before
                                        in_thinking_tags = True
                                        # Check if closing tag is also in this chunk (complete block)
                                        close_match = re.search(r'</think>|</thinking>', after)
                                        if close_match:
                                            thinking_part = after[:close_match.start()]
                                            regular_part = after[close_match.end():]
                                            if thinking_part:
                                                yield f"__THINKING_TAG_CONTENT__:{thinking_part}"
                                            yield "__THINKING_TAG_CLOSE__"
                                            in_thinking_tags = False
                                            if regular_part:
                                                yield regular_part
                                        else:
                                            if after:
                                                yield f"__THINKING_TAG_CONTENT__:{after}"
                                    else:
                                        content_chars_yielded += len(content)
                                        yield content

                                if isinstance(delta, dict):
                                    images = delta.get("images") or delta.get("image")
                                    if isinstance(images, list):
                                        for img in images:
                                            img_url = None
                                            if isinstance(img, dict):
                                                img_url = img.get("image_url") or img.get("url")
                                            if isinstance(img, str):
                                                img_url = img
                                            if img_url:
                                                yield f"\n\n![image]({img_url})\n\n"
                else:
                    error_content = response.text
                    self._dbg_step(
                        f"  ERROR: Model '{model_name}' returned status {response.status_code}."
                    )
                    self._dbg_full("  Error content:", error_content)
                    yield f"❌ Model {model_name} error: {response.status_code} - {error_content}"

        except requests.exceptions.RequestException as e:
            self._dbg_step(
                f"  CRITICAL ERROR: Could not reach OpenWebUI model '{model_name}'. Exception: {str(e)}"
            )
            yield f"❌ Error: Could not reach OpenWebUI model {model_name} - {str(e)}"
        except (ValueError, TypeError) as e:
            self._dbg_step(
                f"  CRITICAL ERROR: An unexpected error occurred with model '{model_name}'. Exception: {str(e)}"
            )
            yield f"❌ An unexpected error occurred with model {model_name}: {str(e)}"
        self._dbg_step(f"--- END DEBUG: Streaming Query for {model_name} ---")

    def _generate_tool_citations(self, tool_ids: List[str], speaker_name: str, response_content: str = ""):
        """Generate citation events for tools configured for a speaker."""
        for tool_id in tool_ids:
            snippet = response_content[:300] if response_content else f"Tool used by {speaker_name}"
            
            citation_event = {
                "event": {
                    "type": "citation",
                    "data": {
                        "document": [snippet],
                        "metadata": [{"source": tool_id}],
                        "source": {"name": f"Tool: {tool_id.replace('_', ' ').title()}"}
                    }
                }
            }
            yield citation_event

    def _truncate_history(self, messages: List[dict]) -> List[dict]:
        """Truncate conversation history to the last N rounds (user+assistant pairs).

        Keeps all system messages and the most recent HISTORY_MAX_ROUNDS rounds.
        A 'round' is one user message followed by one assistant message.
        Returns the original list unchanged if HISTORY_MAX_ROUNDS is 0 (disabled).
        """
        max_rounds = getattr(self.valves, "HISTORY_MAX_ROUNDS", 0)
        if max_rounds <= 0 or not messages:
            return messages

        # Separate system messages from conversation messages
        system_msgs = [m for m in messages if m.get("role") == "system"]
        conv_msgs = [m for m in messages if m.get("role") != "system"]

        if not conv_msgs:
            return messages

        # Count rounds by walking backward through user messages
        rounds_seen = 0
        cut_index = len(conv_msgs)
        i = len(conv_msgs) - 1
        while i >= 0:
            if conv_msgs[i].get("role") == "user":
                rounds_seen += 1
                if rounds_seen > max_rounds:
                    cut_index = i + 1  # Keep from the next message onward
                    break
            i -= 1

        truncated_conv = conv_msgs[cut_index:] if rounds_seen > max_rounds else conv_msgs
        total_original = len(conv_msgs)
        total_kept = len(truncated_conv)

        if total_kept < total_original:
            dropped = total_original - total_kept
            self._dbg_step(
                f"\u2702\ufe0f History truncated: kept {total_kept}/{total_original} messages "
                f"({dropped} dropped, max_rounds={max_rounds})"
            )
        else:
            self._dbg_step(f"\u2702\ufe0f History within limits: {total_original} messages, max_rounds={max_rounds}")

        return system_msgs + truncated_conv

    def _extract_pipeline_system_prompt(self, body: dict) -> str:
        """Return the pipeline's own system prompt from body['messages']."""
        body_messages = body.get("messages", [])
        
        if not body_messages:
            self._dbg_step("   ❌ No messages found in body dict")
            return ""
        
        for msg in body_messages:
            if msg.get("role") == "system":
                system_prompt = msg.get("content", "")
                if system_prompt:
                    self._dbg_step(f"   ✅ Found pipeline system prompt in body['messages'] ({len(system_prompt)} chars)")
                    return system_prompt
                break
        
        self._dbg_step("   ❌ No system message found in body['messages']")
        return ""

    # --- Lifecycle Methods (override in subclass) ---

    async def on_startup(self):
        """Called when the pipeline starts up"""
        self._dbg_step(f"🎭 Starting {self.name}")

    async def on_shutdown(self):
        """Called when the pipeline shuts down"""
        self._dbg_step(f"🛑 Shutting down {self.name}")
        self._dbg_step(f"✅ {self.name} shutdown complete.")

    async def on_valves_updated(self):
        """Called when valve settings are updated"""
        self._dbg_step("⚙️ Pipeline valves updated")

    def pipe(self, user_message: str, messages: List[dict], body: dict, **kwargs):
        """Main pipeline method - override in subclass"""
        yield "❌ Blueprint pipe() not implemented - inherit and override this method"
