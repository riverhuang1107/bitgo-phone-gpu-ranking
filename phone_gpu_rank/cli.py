from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .bitgo_runtime import BitgoClient, BitgoConfig, build_report_prompt, parse_model_text
from .mail import create_mail_assets
from .render import OUTPUT_BASENAME, write_outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="phone-gpu-rank",
        description="Generate a May 2026 smartphone GPU ranking report through bitgo.",
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Directory for generated report files. Default: output",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    report = subparsers.add_parser("report", help="Generate markdown and/or HTML report files.")
    report.add_argument(
        "--format",
        choices=("markdown", "html", "both"),
        default="both",
        help="Output format. Default: both",
    )
    report.add_argument(
        "--mock-response",
        help="Read a local mock bitgo response JSON file instead of calling the API.",
    )

    mail = subparsers.add_parser("mail", help="Create MIME/HTML mail assets and print agently-cli command.")
    mail.add_argument("--to", required=True, action="append", help="Recipient email address. Repeatable.")
    mail.add_argument(
        "--subject",
        default="2026年5月手机GPU性能排行",
        help="Email subject.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = Path(args.output_dir)

    if args.command == "report":
        markdown = _generate_markdown(args.mock_response)
        paths = write_outputs(markdown, output_dir, args.format)
        for kind, path in paths.items():
            print(f"{kind}: {path}")
        return 0

    if args.command == "mail":
        html_path = output_dir / f"{OUTPUT_BASENAME}.html"
        if not html_path.exists():
            print(
                f"HTML report not found: {html_path}. Run `python -m phone_gpu_rank report --format html` first.",
                file=sys.stderr,
            )
            return 2
        assets = create_mail_assets(html_path, output_dir, args.to, args.subject)
        print(f"mime: {assets.mime_path}")
        print("agently-cli send command:")
        print(assets.command)
        print("Run the command once to get a confirmation token, then rerun it with --confirmation-token after approval.")
        return 0

    return 2


def _generate_markdown(mock_response: str | None) -> str:
    if mock_response:
        text = Path(mock_response).read_text(encoding="utf-8")
        return parse_model_text(text)

    config = BitgoConfig.from_env()
    client = BitgoClient(config)
    response = client.create_message(build_report_prompt())
    return parse_model_text(response)
