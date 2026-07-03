from __future__ import annotations

import shlex
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

from .render import OUTPUT_BASENAME


@dataclass(frozen=True)
class MailAssets:
    mime_path: Path
    command: str


def create_mail_assets(html_path: Path, output_dir: Path, recipients: list[str], subject: str) -> MailAssets:
    html_body = html_path.read_text(encoding="utf-8")
    message = EmailMessage()
    message["Subject"] = subject
    message["To"] = ", ".join(recipients)
    message.set_content("请查看 HTML 邮件正文。")
    message.add_alternative(html_body, subtype="html")

    output_dir.mkdir(parents=True, exist_ok=True)
    mime_path = output_dir / f"{OUTPUT_BASENAME}.eml"
    mime_path.write_bytes(message.as_bytes())

    command_parts = ["agently-cli", "message", "+send"]
    for recipient in recipients:
        command_parts.extend(["--to", recipient])
    command_parts.extend(["--subject", subject, "--body-file", str(html_path)])
    command = " ".join(shlex.quote(part) for part in command_parts)
    return MailAssets(mime_path=mime_path, command=command)
