from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_ENDPOINT = "https://api-token-enigmhaven.expvent.com.cn:1111/v1/messages"
DEFAULT_TOOLS = [{"type": "web_search"}]
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

        tools_json = os.getenv("BITGO_TOOLS_JSON")
        tools = json.loads(tools_json) if tools_json else DEFAULT_TOOLS
        max_tokens = int(os.getenv("BITGO_MAX_TOKENS", "4096"))
        return cls(
            wallet_chain=required["BITGO_WALLET_CHAIN"] or "",
            wallet_address=required["BITGO_WALLET_ADDRESS"] or "",
            money=required["BITGO_MONEY"] or "",
            money_id=required["BITGO_MONEY_ID"] or "",
            wallet_private_key=required["BITGO_WALLET_PRIVATE_KEY"] or "",
            model=required["BITGO_MODEL"] or "",
            endpoint=os.getenv("BITGO_ENDPOINT", DEFAULT_ENDPOINT),
            max_tokens=max_tokens,
            tools=tools,
        )


class BitgoClient:
    def __init__(self, config: BitgoConfig, repo_root: Path | None = None) -> None:
        self.config = config
        self.repo_root = repo_root or Path(__file__).resolve().parents[1]

    def create_message(self, prompt: str) -> str:
        body = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "stream": False,
            "tools": self.config.tools or DEFAULT_TOOLS,
            "system": (
                "You are a careful benchmark research analyst. Use web_search tools. "
                "Return the final answer in Chinese Markdown only."
            ),
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = self._signed_headers()
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(self.config.endpoint, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"bitgo API returned HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"bitgo API request failed: {exc.reason}") from exc

    def _signed_headers(self) -> dict[str, str]:
        signer_input = {
            "wallet_chain": self.config.wallet_chain,
            "wallet_address": self.config.wallet_address,
            "money": self.config.money,
            "money_id": self.config.money_id,
            "wallet_private_key": self.config.wallet_private_key,
        }
        go_env = os.environ.copy()
        for key, dirname in {
            "GOCACHE": ".tmp-go-cache",
            "GOMODCACHE": ".tmp-go-modcache",
            "GOPATH": ".tmp-go-path",
        }.items():
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
    return f"""请使用 web_search 工具联网检索并生成《2026年5月最新手机GPU性能排行》。

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
        parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
        if parts:
            return "\n\n".join(parts).strip()
    if isinstance(content, str):
        return content.strip()
    if isinstance(body.get("text"), str):
        return body["text"].strip()
    print("Warning: could not find text content in bitgo response; writing JSON response.", file=sys.stderr)
    return json.dumps(payload, ensure_ascii=False, indent=2)
