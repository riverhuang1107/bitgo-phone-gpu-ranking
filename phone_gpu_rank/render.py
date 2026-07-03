from __future__ import annotations

import html
from pathlib import Path


OUTPUT_BASENAME = "phone-gpu-ranking-2026-05"


def write_outputs(markdown: str, output_dir: Path, output_format: str) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    if output_format in {"markdown", "both"}:
        md_path = output_dir / f"{OUTPUT_BASENAME}.md"
        md_path.write_text(markdown.rstrip() + "\n", encoding="utf-8")
        paths["markdown"] = md_path
    if output_format in {"html", "both"}:
        html_path = output_dir / f"{OUTPUT_BASENAME}.html"
        html_path.write_text(render_html(markdown), encoding="utf-8")
        paths["html"] = html_path
    return paths


def render_html(markdown: str) -> str:
    body = _markdown_to_html(markdown)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>2026年5月手机GPU性能排行</title>
  <style>
    body {{ margin: 0; background: #f6f8fb; color: #172033; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif; line-height: 1.68; }}
    main {{ max-width: 1080px; margin: 0 auto; padding: 36px 18px 56px; }}
    article {{ background: #ffffff; border: 1px solid #d8e0ec; border-radius: 8px; padding: 28px; }}
    h1 {{ margin-top: 0; font-size: 30px; line-height: 1.25; }}
    h2 {{ margin-top: 30px; padding-top: 18px; border-top: 1px solid #e4e9f1; font-size: 22px; }}
    h3 {{ margin-top: 24px; font-size: 18px; }}
    table {{ width: 100%; border-collapse: collapse; margin: 18px 0; font-size: 14px; }}
    th, td {{ border: 1px solid #d8e0ec; padding: 10px 12px; vertical-align: top; }}
    th {{ background: #172033; color: #ffffff; text-align: left; }}
    code {{ background: #eef3fa; border-radius: 4px; padding: 2px 5px; }}
    a {{ color: #075cc8; }}
    blockquote {{ margin: 16px 0; padding: 12px 16px; border-left: 4px solid #2f6fed; background: #f0f5ff; }}
    @media (max-width: 720px) {{ article {{ padding: 18px; }} table {{ display: block; overflow-x: auto; }} }}
  </style>
</head>
<body>
  <main>
    <article>
{body}
    </article>
  </main>
</body>
</html>
"""


def _markdown_to_html(markdown: str) -> str:
    lines = markdown.splitlines()
    html_lines: list[str] = []
    in_ul = False
    in_table = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            if in_table:
                html_lines.append("</tbody></table>")
                in_table = False
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if all(set(cell) <= {"-", ":", " "} for cell in cells):
                continue
            tag = "th" if not in_table else "td"
            row = "".join(f"<{tag}>{_inline(cell)}</{tag}>" for cell in cells)
            if not in_table:
                html_lines.append("<table><thead><tr>" + row + "</tr></thead><tbody>")
                in_table = True
            else:
                html_lines.append("<tr>" + row + "</tr>")
            continue

        if in_table:
            html_lines.append("</tbody></table>")
            in_table = False

        if stripped.startswith("# "):
            html_lines.append(f"<h1>{_inline(stripped[2:])}</h1>")
        elif stripped.startswith("## "):
            html_lines.append(f"<h2>{_inline(stripped[3:])}</h2>")
        elif stripped.startswith("### "):
            html_lines.append(f"<h3>{_inline(stripped[4:])}</h3>")
        elif stripped.startswith("- "):
            if not in_ul:
                html_lines.append("<ul>")
                in_ul = True
            html_lines.append(f"<li>{_inline(stripped[2:])}</li>")
        elif stripped.startswith("> "):
            html_lines.append(f"<blockquote>{_inline(stripped[2:])}</blockquote>")
        else:
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            html_lines.append(f"<p>{_inline(stripped)}</p>")

    if in_ul:
        html_lines.append("</ul>")
    if in_table:
        html_lines.append("</tbody></table>")
    return "\n".join("      " + line for line in html_lines)


def _inline(text: str) -> str:
    escaped = html.escape(text)
    return escaped.replace("**", "")
