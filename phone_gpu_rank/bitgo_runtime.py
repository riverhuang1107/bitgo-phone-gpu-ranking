from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus


DEFAULT_ENDPOINT = "https://api-token-enigmhaven.expvent.com.cn:1111/v1/messages"
DEFAULT_TOOLS = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 8}]
SEARCH_KEYWORDS = [
    "2026年5月 手机 GPU 性能排行",
    "2026 May smartphone GPU ranking",
    "AnTuTu Android flagship GPU ranking May 2026",
    "3DMark Wild Life Extreme smartphone ranking 2026",
]


@dataclass(frozen=True)
class BitgoConfig:
    wallet_chain: str
    wallet_address: str
    money: str
    money_id: str
    wallet_private_key: str
    model: str
    endpoint: str = DEFAULT_ENDPOINT
    max_tokens: int = 4096
    timeout_seconds: int = 300
    tools: list[dict[str, Any]] | None = None

    @classmethod
    def from_env(cls) -> "BitgoConfig":
        required = {
            "BITGO_WALLET_CHAIN": os.getenv("BITGO_WALLET_CHAIN"),
            "BITGO_WALLET_ADDRESS": os.getenv("BITGO_WALLET_ADDRESS"),
            "BITGO_MONEY": os.getenv("BITGO_MONEY"),
            "BITGO_MONEY_ID": os.getenv("BITGO_MONEY_ID"),
            "BITGO_WALLET_PRIVATE_KEY": os.getenv("BITGO_WALLET_PRIVATE_KEY"),
            "BITGO_MODEL": os.getenv("BITGO_MODEL"),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
        return cls(
            wallet_chain=required["BITGO_WALLET_CHAIN"] or "",
            wallet_address=required["BITGO_WALLET_ADDRESS"] or "",
            money=required["BITGO_MONEY"] or "",
            money_id=required["BITGO_MONEY_ID"] or "",
            wallet_private_key=required["BITGO_WALLET_PRIVATE_KEY"] or "",
            model=required["BITGO_MODEL"] or "",
            endpoint=os.getenv("BITGO_ENDPOINT", DEFAULT_ENDPOINT),
            max_tokens=int(os.getenv("BITGO_MAX_TOKENS", "4096")),
            timeout_seconds=int(os.getenv("BITGO_TIMEOUT_SECONDS", "300")),
            tools=json.loads(os.getenv("BITGO_TOOLS_JSON", "null")) or DEFAULT_TOOLS,
        )


class BitgoClient:
    def __init__(self, config: BitgoConfig, repo_root: Path | None = None) -> None:
        self.config = config
        self.repo_root = repo_root or Path(__file__).resolve().parents[1]

    def create_message(self, prompt: str) -> str:
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        last_raw = ""
        for _ in range(4):
            last_raw = self._post(self._request_body(messages))
            payload = json.loads(last_raw)
            if payload.get("stop_reason") != "tool_use":
                return last_raw
            tool_results = [
                self._execute_tool(item)
                for item in payload.get("content", [])
                if isinstance(item, dict) and item.get("type") == "tool_use"
            ]
            if not tool_results:
                return last_raw
            messages.append({"role": "assistant", "content": payload.get("content", [])})
            messages.append({"role": "user", "content": tool_results})
        return last_raw

    def _request_body(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        body = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "stream": False,
            "system": (
                "You are a careful benchmark research analyst. Use web_search tools when needed. "
                "After receiving tool results, return the final answer in Chinese Markdown only."
            ),
            "messages": messages,
        }
        if not _has_tool_result(messages):
            body["tools"] = self.config.tools or DEFAULT_TOOLS
        return body

    def _post(self, body: dict[str, Any]) -> str:
        headers = self._signed_headers()
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(self.config.endpoint, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"bitgo API returned HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"bitgo API request failed: {exc.reason}") from exc

    def _execute_tool(self, tool_use: dict[str, Any]) -> dict[str, Any]:
        content = run_web_search(_tool_query(tool_use)) if tool_use.get("name") == "web_search" else "Unsupported tool"
        return {"type": "tool_result", "tool_use_id": tool_use.get("id"), "content": content}

    def _signed_headers(self) -> dict[str, str]:
        signer_input = {
            "wallet_chain": self.config.wallet_chain,
            "wallet_address": self.config.wallet_address,
            "money": self.config.money,
            "money_id": self.config.money_id,
            "wallet_private_key": self.config.wallet_private_key,
        }
        go_env = os.environ.copy()
        for key, dirname in {"GOCACHE": ".tmp-go-cache", "GOMODCACHE": ".tmp-go-modcache", "GOPATH": ".tmp-go-path"}.items():
            path = self.repo_root / dirname
            path.mkdir(parents=True, exist_ok=True)
            go_env[key] = str(path)
        go_env["GOFLAGS"] = (go_env.get("GOFLAGS", "") + " -modcacherw").strip()
        proc = subprocess.run(
            ["go", "run", "./cmd/bitgo-signer"],
            cwd=self.repo_root,
            input=json.dumps(signer_input),
            text=True,
            capture_output=True,
            check=False,
            env=go_env,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"bitgo signer failed: {proc.stderr.strip() or proc.stdout.strip()}")
        return json.loads(proc.stdout)


def build_report_prompt() -> str:
    keywords = "\n".join(f"- {keyword}" for keyword in SEARCH_KEYWORDS)
    return f"""请现在使用 web_search 工具联网检索，并直接生成《2026年5月最新手机GPU性能排行》的最终报告。

不要输出“我将搜索”“正在检索”“下面我会”等过程说明；最终回答只能是完整中文 Markdown 报告。

必须逐个搜索这些关键词：
{keywords}

输出要求：
1. 用中文 Markdown 输出。
2. 按 GPU / 芯片 / 代表机型 / 跑分或排名 整理主表。
3. 标注每条数据口径，例如安兔兔、3DMark Wild Life Extreme、GFXBench。
4. 如果来源之间排名或跑分不一致，单独说明差异和可能原因。
5. 给出至少 3 条搜索结果摘要，格式为：来源名称 + 日期 + 关键排行数据 + URL。
6. 明确说明这是 2026 年 5 月口径，不要混入其他月份作为主排行。
"""


def parse_model_text(raw_response: str) -> str:
    try:
        payload = json.loads(raw_response)
    except json.JSONDecodeError:
        return raw_response.strip()
    body = payload.get("body", payload)
    content = body.get("content")
    if isinstance(content, list):
        parts = [item["text"] for item in content if isinstance(item, dict) and isinstance(item.get("text"), str)]
        if parts:
            return "\n\n".join(parts).strip()
    if isinstance(content, str):
        return content.strip()
    if isinstance(body.get("text"), str):
        return body["text"].strip()
    print("Warning: could not find text content in bitgo response; writing JSON response.", file=sys.stderr)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _tool_query(tool_use: dict[str, Any]) -> str:
    tool_input = tool_use.get("input")
    if isinstance(tool_input, dict):
        for key in ("query", "q", "search_query"):
            value = tool_input.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return " ".join(SEARCH_KEYWORDS)


def _has_tool_result(messages: list[dict[str, Any]]) -> bool:
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "tool_result":
                    return True
    return False


def run_web_search(query: str) -> str:
    request = urllib.request.Request(
        "https://duckduckgo.com/html/?q=" + quote_plus(query),
        headers={"User-Agent": "Mozilla/5.0 phone-gpu-rank/0.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            html_text = response.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return f"Search query: {query}\nSearch failed: {exc}"
    parser = DuckDuckGoParser()
    parser.feed(html_text)
    if not parser.results:
        return f"Search query: {query}\nNo parseable results returned."
    lines = [f"Search query: {query}", "Results:"]
    for idx, result in enumerate(parser.results[:5], start=1):
        lines.append(f"{idx}. {result['title']}\n   URL: {result['url']}\n   Snippet: {result['snippet']}")
    return "\n".join(lines)


class DuckDuckGoParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._in_link = False
        self._in_snippet = False
        self._current_title: list[str] = []
        self._current_snippet: list[str] = []
        self._current_url = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        classes = attrs_dict.get("class", "")
        if tag == "a" and "result__a" in classes:
            self._in_link = True
            self._current_title = []
            self._current_snippet = []
            self._current_url = attrs_dict.get("href", "") or ""
        elif "result__snippet" in classes:
            self._in_snippet = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_link:
            self._in_link = False
        elif tag in {"a", "div"} and self._in_snippet:
            self._in_snippet = False
            if self._current_url and self._current_title:
                self.results.append(
                    {
                        "title": " ".join("".join(self._current_title).split()),
                        "url": self._current_url,
                        "snippet": " ".join("".join(self._current_snippet).split()),
                    }
                )

    def handle_data(self, data: str) -> None:
        if self._in_link:
            self._current_title.append(data)
        elif self._in_snippet:
            self._current_snippet.append(data)
