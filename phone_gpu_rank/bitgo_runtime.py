from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html import unescape as html_unescape
from datetime import datetime, timezone
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
SUPPLEMENTAL_SEARCH_QUERIES = [
    "site:antutu.com/web/ranking Android flagship performance ranking May 2026",
    "AnTuTu May 2026 Android flagship ranking GPU score",
    "site:3dmark.com smartphone Wild Life Extreme score Snapdragon 8 Elite Gen 5 Dimensity 9500",
    "Snapdragon 8 Elite Gen 5 Dimensity 9500 3DMark Wild Life Extreme score",
    "GFXBench smartphone GPU ranking Snapdragon 8 Elite Gen 5 Dimensity 9500",
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
        search_results = run_required_searches()
        write_search_audit(self.repo_root / "output" / "search-audit.json", search_results)
        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": prompt + "\n\n已逐个执行的 web_search 搜索结果如下，请只基于这些结果和可核验 URL 生成报告：\n\n" + format_search_results(search_results),
            }
        ]
        last_raw = ""
        usages: list[dict[str, Any]] = []
        for _ in range(4):
            last_raw = self._post(self._request_body(messages))
            payload = json.loads(last_raw)
            if isinstance(payload.get("usage"), dict):
                usages.append(payload["usage"])
            if payload.get("stop_reason") != "tool_use":
                return _with_usage_summary(payload, usages)
            tool_results = [
                self._execute_tool(item)
                for item in payload.get("content", [])
                if isinstance(item, dict) and item.get("type") == "tool_use"
            ]
            if not tool_results:
                return _with_usage_summary(payload, usages)
            messages.append({"role": "assistant", "content": payload.get("content", [])})
            messages.append({"role": "user", "content": tool_results})
        return _with_usage_summary(json.loads(last_raw), usages)

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
        content = run_web_search(_tool_query(tool_use)).to_tool_text() if tool_use.get("name") == "web_search" else "Unsupported tool"
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
            return _append_usage_section("\n\n".join(parts).strip(), body)
    if isinstance(content, str):
        return _append_usage_section(content.strip(), body)
    if isinstance(body.get("text"), str):
        return _append_usage_section(body["text"].strip(), body)
    print("Warning: could not find text content in bitgo response; writing JSON response.", file=sys.stderr)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _with_usage_summary(payload: dict[str, Any], usages: list[dict[str, Any]]) -> str:
    payload["bitgo_usage"] = {
        "calls": len(usages),
        "total": _sum_usages(usages),
        "responses": usages,
    }
    return json.dumps(payload, ensure_ascii=False)


def _sum_usages(usages: list[dict[str, Any]]) -> dict[str, Any]:
    numeric_fields = [
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
        "consume_amount",
    ]
    total: dict[str, Any] = {}
    for field in numeric_fields:
        values = [usage.get(field) for usage in usages if isinstance(usage.get(field), int)]
        if values:
            total[field] = sum(values)
    for field in ("balance", "input_token_unit_price", "output_token_unit_price"):
        for usage in reversed(usages):
            if field in usage:
                total[field] = usage[field]
                break
    return total


def _append_usage_section(markdown: str, body: dict[str, Any]) -> str:
    usage = body.get("bitgo_usage")
    if not isinstance(usage, dict):
        return markdown
    total = usage.get("total")
    if not isinstance(total, dict):
        return markdown

    lines = [
        "",
        "## bitgo 推理 API token 使用情况",
        "",
        f"- API 调用轮次：{usage.get('calls', 0)}",
        f"- 输入 tokens：{total.get('input_tokens', 0)}",
        f"- 输出 tokens：{total.get('output_tokens', 0)}",
        f"- 缓存创建输入 tokens：{total.get('cache_creation_input_tokens', 0)}",
        f"- 缓存读取输入 tokens：{total.get('cache_read_input_tokens', 0)}",
        f"- 实际消耗金额：{_format_scaled_amount(total.get('consume_amount'))}（原始值：{total.get('consume_amount', 0)}，缩放：10^-8）",
        f"- 实际剩余额度：{_format_scaled_amount(total.get('balance'))}（原始值：{total.get('balance', '未知')}，缩放：10^-8）",
        f"- 输入单价：{_format_unit_price(total.get('input_token_unit_price'))} / 1000 tokens（原始值：{total.get('input_token_unit_price', '未知')}，缩放：10^-5）",
        f"- 输出单价：{_format_unit_price(total.get('output_token_unit_price'))} / 1000 tokens（原始值：{total.get('output_token_unit_price', '未知')}，缩放：10^-5）",
    ]
    return markdown.rstrip() + "\n" + "\n".join(lines)


def _format_scaled_amount(value: Any) -> str:
    if not isinstance(value, int):
        return "未知"
    whole, fractional = divmod(value, 100_000_000)
    return f"{whole}.{fractional:08d}"


def _format_unit_price(value: Any) -> str:
    if not isinstance(value, int):
        return "未知"
    whole, fractional = divmod(value, 100_000)
    return f"{whole}.{fractional:05d}"


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


@dataclass(frozen=True)
class SearchResult:
    query: str
    ok: bool
    results: list[dict[str, str]]
    error: str = ""

    def to_tool_text(self) -> str:
        if not self.ok:
            return f"Search query: {self.query}\nSearch failed: {self.error}"
        if not self.results:
            return f"Search query: {self.query}\nNo parseable results returned."
        lines = [f"Search query: {self.query}", "Results:"]
        for idx, result in enumerate(self.results[:5], start=1):
            lines.append(f"{idx}. {result['title']}\n   URL: {result['url']}\n   Snippet: {result['snippet']}")
        return "\n".join(lines)


def run_required_searches() -> list[SearchResult]:
    return [
        *[run_web_search(keyword) for keyword in [*SEARCH_KEYWORDS, *SUPPLEMENTAL_SEARCH_QUERIES]],
        fetch_antutu_ranking_table(),
    ]


def format_search_results(search_results: list[SearchResult]) -> str:
    return "\n\n".join(result.to_tool_text() for result in search_results)


def write_search_audit(path: Path, search_results: list[SearchResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "required_keywords": SEARCH_KEYWORDS,
        "supplemental_queries": SUPPLEMENTAL_SEARCH_QUERIES,
        "searched_keywords": [result.query for result in search_results],
        "all_required_keywords_searched": [result.query for result in search_results[: len(SEARCH_KEYWORDS)]] == SEARCH_KEYWORDS,
        "searches": [
            {
                "query": result.query,
                "ok": result.ok,
                "error": result.error,
                "results": result.results,
            }
            for result in search_results
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_web_search(query: str) -> SearchResult:
    bing_result = run_bing_rss_search(query)
    if bing_result.ok and bing_result.results:
        return bing_result

    request = urllib.request.Request(
        "https://duckduckgo.com/html/?q=" + quote_plus(query),
        headers={"User-Agent": "Mozilla/5.0 phone-gpu-rank/0.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            html_text = response.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return SearchResult(query=query, ok=False, results=[], error=str(exc))
    parser = DuckDuckGoParser()
    parser.feed(html_text)
    return SearchResult(query=query, ok=True, results=parser.results[:5])


def run_bing_rss_search(query: str) -> SearchResult:
    request = urllib.request.Request(
        "https://www.bing.com/search?format=rss&q=" + quote_plus(query),
        headers={"User-Agent": "Mozilla/5.0 phone-gpu-rank/0.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            xml_text = response.read().decode("utf-8", errors="replace")
        root = ET.fromstring(xml_text)
    except Exception as exc:  # noqa: BLE001
        return SearchResult(query=query, ok=False, results=[], error=str(exc))

    results = []
    for item in root.findall("./channel/item")[:5]:
        title = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        snippet = (item.findtext("description") or "").strip()
        if title and url:
            results.append({"title": title, "url": url, "snippet": snippet})
    return SearchResult(query=query, ok=True, results=results)


def fetch_antutu_ranking_table() -> SearchResult:
    url = "https://www.antutu.com/web/ranking"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 phone-gpu-rank/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            html_text = response.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return SearchResult(query="Direct source: AnTuTu official ranking table", ok=False, results=[], error=str(exc))

    rows = parse_antutu_rows(html_text)
    results = []
    for row in rows[:12]:
        snippet = (
            f"Rank {row['rank']}: {row['device']}; chip {row['chip']}; "
            f"CPU {row['cpu']}; GPU {row['gpu']}; MEM {row['mem']}; UX {row['ux']}; Total {row['total']}."
        )
        results.append(
            {
                "title": f"AnTuTu official ranking #{row['rank']} - {row['device']}",
                "url": url,
                "snippet": snippet,
            }
        )
    return SearchResult(query="Direct source: AnTuTu official ranking table", ok=True, results=results)


def parse_antutu_rows(html_text: str) -> list[dict[str, str]]:
    marker = "<tbody"
    start = html_text.find(marker)
    if start == -1:
        return []
    fragment = html_text[start : start + 50000]
    text = re.sub(r"<[^>]+>", "\n", fragment)
    lines = [html_unescape(line).strip() for line in text.splitlines() if html_unescape(line).strip()]
    rows = []
    idx = 0
    while idx + 7 < len(lines):
        if lines[idx].isdigit() and lines[idx + 3].startswith("| "):
            rows.append(
                {
                    "rank": lines[idx],
                    "device": lines[idx + 1],
                    "chip": lines[idx + 2],
                    "memory": lines[idx + 3].removeprefix("| ").strip(),
                    "cpu": lines[idx + 4],
                    "gpu": lines[idx + 5],
                    "mem": lines[idx + 6],
                    "ux": lines[idx + 7],
                    "total": lines[idx + 8] if idx + 8 < len(lines) else "",
                }
            )
            idx += 9
        else:
            idx += 1
    return rows


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
