#!/usr/bin/env python3
"""Convert a UTF-8 Markdown file to a UTF-8 HTML file."""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path


class MarkdownConversionError(Exception):
    """Raised when Markdown conversion cannot be completed."""


def read_markdown(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise MarkdownConversionError(f"Input file does not exist: {path}") from exc
    except IsADirectoryError as exc:
        raise MarkdownConversionError(f"Input path is a directory, not a file: {path}") from exc
    except UnicodeDecodeError as exc:
        raise MarkdownConversionError(f"Input file is not valid UTF-8: {path}") from exc
    except OSError as exc:
        raise MarkdownConversionError(f"Could not read input file {path}: {exc}") from exc


def write_html(path: Path, content: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise MarkdownConversionError(f"Could not write output file {path}: {exc}") from exc


def _stash_math_placeholders(markdown_text: str) -> tuple[str, dict[str, str]]:
    placeholders: dict[str, str] = {}

    def stash(rendered: str) -> str:
        key = f"\u0001MATH{len(placeholders)}\u0001"
        placeholders[key] = rendered
        return key

    pattern = re.compile(r"(?<!\\)\$\$(.+?)(?<!\\)\$\$|(?<!\\)\$(.+?)(?<!\\)\$", re.DOTALL)

    def repl(match: re.Match[str]) -> str:
        display_expr = match.group(1)
        inline_expr = match.group(2)
        if display_expr is not None:
            expr = html.escape(display_expr.strip(), quote=False)
            return stash(f'<div class="math math-display">{expr}</div>')

        expr = html.escape(inline_expr.strip(), quote=False)
        return stash(f'<span class="math math-inline">{expr}</span>')

    processed = pattern.sub(repl, markdown_text)
    processed = processed.replace(r"\$", "$")
    return processed, placeholders


def _restore_math_placeholders(html_text: str, placeholders: dict[str, str]) -> str:
    for key, value in placeholders.items():
        html_text = html_text.replace(key, value).replace(html.escape(key), value)
    return html_text


def convert_inline(markdown_text: str) -> str:
    placeholders: dict[str, str] = {}

    def stash(value: str) -> str:
        key = f"\u0000{len(placeholders)}\u0000"
        placeholders[key] = value
        return key

    def replace_code(match: re.Match[str]) -> str:
        return stash(f"<code>{html.escape(match.group(1), quote=False)}</code>")

    def replace_image(match: re.Match[str]) -> str:
        alt = html.escape(match.group(1), quote=True)
        src = html.escape(match.group(2), quote=True)
        return stash(f'<img src="{src}" alt="{alt}">')

    def replace_link(match: re.Match[str]) -> str:
        label = convert_inline(match.group(1))
        href = html.escape(match.group(2), quote=True)
        return stash(f'<a href="{href}">{label}</a>')

    text = re.sub(r"`([^`\n]+)`", replace_code, markdown_text)
    text = html.escape(text, quote=False)
    text = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)", replace_image, text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", replace_link, text)
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__([^_\n]+)__", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", text)
    text = re.sub(r"(?<!_)_([^_\n]+)_(?!_)", r"<em>\1</em>", text)

    for key, value in placeholders.items():
        text = text.replace(html.escape(key), value).replace(key, value)
    return text


def convert_markdown(markdown_text: str, *, full_document: bool = False) -> str:
    preprocessed, math_placeholders = _stash_math_placeholders(markdown_text)
    lines = preprocessed.splitlines()
    body = _restore_math_placeholders(_convert_blocks(lines), math_placeholders)
    if not full_document:
        return body
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '  <meta charset="utf-8">',
            "  <title>Markdown Output</title>",
            "</head>",
            "<body>",
            body,
            "</body>",
            "</html>",
        ]
    )


def _convert_blocks(lines: list[str]) -> str:
    output: list[str] = []
    paragraph: list[str] = []
    index = 0

    def flush_paragraph() -> None:
        if paragraph:
            output.append(f"<p>{convert_inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if not stripped:
            flush_paragraph()
            index += 1
            continue

        fence_match = re.match(r"^```([A-Za-z0-9_-]+)?\s*$", stripped)
        if fence_match:
            flush_paragraph()
            language = fence_match.group(1)
            code_lines: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code_lines.append(lines[index])
                index += 1
            if index == len(lines):
                raise MarkdownConversionError("Unclosed fenced code block.")
            output.append(_render_code_block(code_lines, language))
            index += 1
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading_match:
            flush_paragraph()
            level = len(heading_match.group(1))
            output.append(f"<h{level}>{convert_inline(heading_match.group(2).strip())}</h{level}>")
            index += 1
            continue

        if _is_table_start(lines, index):
            flush_paragraph()
            table_html, index = _consume_table(lines, index)
            output.append(table_html)
            continue

        list_match = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.+)$", line)
        if list_match:
            flush_paragraph()
            list_html, index = _consume_list(lines, index, ordered=list_match.group(2)[0].isdigit())
            output.append(list_html)
            continue

        if stripped.startswith(">"):
            flush_paragraph()
            quote_lines: list[str] = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote_lines.append(re.sub(r"^\s*>\s?", "", lines[index]))
                index += 1
            quote_body = _convert_blocks(quote_lines)
            output.append(f"<blockquote>\n{quote_body}\n</blockquote>")
            continue

        paragraph.append(stripped)
        index += 1

    flush_paragraph()
    return "\n".join(output)


def _render_code_block(code_lines: list[str], language: str | None) -> str:
    escaped_code = html.escape("\n".join(code_lines), quote=False)
    class_attr = f' class="language-{html.escape(language, quote=True)}"' if language else ""
    return f"<pre><code{class_attr}>{escaped_code}\n</code></pre>"


def _consume_list(lines: list[str], start: int, *, ordered: bool) -> tuple[str, int]:
    tag = "ol" if ordered else "ul"
    items: list[str] = []
    index = start
    pattern = r"^\s*\d+[.)]\s+(.+)$" if ordered else r"^\s*[-*+]\s+(.+)$"

    while index < len(lines):
        match = re.match(pattern, lines[index])
        if not match:
            break
        items.append(f"<li>{convert_inline(match.group(1).strip())}</li>")
        index += 1

    return f"<{tag}>\n" + "\n".join(items) + f"\n</{tag}>", index


def _is_table_start(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    header = lines[index].strip()
    separator = lines[index + 1].strip()
    return "|" in header and bool(re.match(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$", separator))


def _split_table_row(line: str) -> list[str]:
    trimmed = line.strip().strip("|")
    return [cell.strip() for cell in trimmed.split("|")]


def _consume_table(lines: list[str], start: int) -> tuple[str, int]:
    headers = _split_table_row(lines[start])
    index = start + 2
    rows: list[list[str]] = []

    while index < len(lines) and "|" in lines[index].strip() and lines[index].strip():
        rows.append(_split_table_row(lines[index]))
        index += 1

    output = ["<table>", "<thead>", "<tr>"]
    output.extend(f"<th>{convert_inline(header)}</th>" for header in headers)
    output.extend(["</tr>", "</thead>", "<tbody>"])
    for row in rows:
        output.append("<tr>")
        output.extend(f"<td>{convert_inline(cell)}</td>" for cell in row)
        output.append("</tr>")
    output.extend(["</tbody>", "</table>"])
    return "\n".join(output), index


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert a UTF-8 Markdown file to HTML.")
    parser.add_argument("input", type=Path, help="Path to the input Markdown file.")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Path to the output HTML file.")
    parser.add_argument(
        "--full-document",
        action="store_true",
        help="Wrap the converted HTML fragment in a complete HTML document.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        markdown_text = read_markdown(args.input)
        html_text = convert_markdown(markdown_text, full_document=args.full_document)
        write_html(args.output, html_text)
    except MarkdownConversionError as exc:
        parser.exit(1, f"error: {exc}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
