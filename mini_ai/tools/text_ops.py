"""
text_ops.py – Advanced text processing, JSON formatting, template rendering, markdown ops.
"""
from __future__ import annotations

import json
import re
from typing import Any


def text_op(operation: str, input_text: str, options: str = "") -> dict[str, Any]:
    """Advanced text processing.

    Operations:
    - sort_lines: sort lines (options: 'reverse', 'numeric', 'unique')
    - deduplicate: remove duplicate lines
    - column: extract column (options: column number or range, delimiter)
    - wrap: word wrap (options: width, default 80)
    - reverse: reverse text or lines
    - number_lines: add line numbers
    - trim: trim whitespace from each line
    - frequency: word frequency analysis
    """
    operation = operation.lower().strip()

    if operation == "sort_lines":
        lines = input_text.splitlines()
        if "numeric" in options:
            lines.sort(key=lambda l: float(re.search(r'-?\d+\.?\d*', l).group()) if re.search(r'-?\d+\.?\d*', l) else 0)
        elif "reverse" in options:
            lines.sort(reverse=True)
        else:
            lines.sort()
        if "unique" in options:
            lines = list(dict.fromkeys(lines))
        return {"success": True, "result": "\n".join(lines)}

    elif operation == "deduplicate":
        lines = input_text.splitlines()
        seen = set()
        unique = []
        for line in lines:
            if line not in seen:
                seen.add(line)
                unique.append(line)
        removed = len(lines) - len(unique)
        return {"success": True, "result": "\n".join(unique), "removed": removed}

    elif operation == "column":
        delimiter = "\t"
        col_idx = 0
        if options:
            parts = options.split()
            try:
                col_idx = int(parts[0]) - 1
            except (ValueError, IndexError):
                pass
            if len(parts) > 1:
                delimiter = parts[1]
        lines = input_text.splitlines()
        extracted = []
        for line in lines:
            cols = line.split(delimiter)
            if 0 <= col_idx < len(cols):
                extracted.append(cols[col_idx].strip())
        return {"success": True, "result": "\n".join(extracted)}

    elif operation == "wrap":
        width = 80
        if options.strip().isdigit():
            width = int(options.strip())
        import textwrap
        wrapped = textwrap.fill(input_text, width=width)
        return {"success": True, "result": wrapped}

    elif operation == "reverse":
        if "lines" in options:
            return {"success": True, "result": "\n".join(reversed(input_text.splitlines()))}
        return {"success": True, "result": input_text[::-1]}

    elif operation == "number_lines":
        lines = input_text.splitlines()
        width = len(str(len(lines)))
        numbered = [f"{i+1:>{width}} | {line}" for i, line in enumerate(lines)]
        return {"success": True, "result": "\n".join(numbered)}

    elif operation == "trim":
        lines = [line.strip() for line in input_text.splitlines()]
        return {"success": True, "result": "\n".join(lines)}

    elif operation == "frequency":
        words = re.findall(r'\b\w+\b', input_text.lower())
        freq: dict[str, int] = {}
        for w in words:
            freq[w] = freq.get(w, 0) + 1
        top = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:20]
        lines = [f"  {count:>5}  {word}" for word, count in top]
        return {"success": True, "result": f"Word frequency (top 20, {len(words)} total words):\n" + "\n".join(lines)}

    else:
        return {"success": False, "error": f"Unknown operation: '{operation}'. Available: sort_lines, deduplicate, column, wrap, reverse, number_lines, trim, frequency"}


def json_format(input_text: str, operation: str = "pretty") -> dict[str, Any]:
    """JSON formatting operations.

    Operations: pretty, compact, validate, keys, flatten, merge
    """
    operation = operation.lower().strip()

    if operation == "validate":
        try:
            json.loads(input_text)
            return {"success": True, "result": "Valid JSON ✓"}
        except json.JSONDecodeError as e:
            return {"success": False, "error": f"Invalid JSON at line {e.lineno}, col {e.colno}: {e.msg}"}

    if operation == "pretty":
        try:
            data = json.loads(input_text)
            return {"success": True, "result": json.dumps(data, indent=2, ensure_ascii=False)}
        except json.JSONDecodeError as e:
            return {"success": False, "error": f"Invalid JSON: {e}"}

    elif operation == "compact":
        try:
            data = json.loads(input_text)
            return {"success": True, "result": json.dumps(data, separators=(",", ":"), ensure_ascii=False)}
        except json.JSONDecodeError as e:
            return {"success": False, "error": f"Invalid JSON: {e}"}

    elif operation == "keys":
        try:
            data = json.loads(input_text)
            if isinstance(data, dict):
                return {"success": True, "result": "\n".join(sorted(data.keys()))}
            return {"success": False, "error": "Input is not a JSON object"}
        except json.JSONDecodeError as e:
            return {"success": False, "error": f"Invalid JSON: {e}"}

    elif operation == "flatten":
        try:
            data = json.loads(input_text)
            flat = _flatten_json(data)
            return {"success": True, "result": json.dumps(flat, indent=2, ensure_ascii=False)}
        except json.JSONDecodeError as e:
            return {"success": False, "error": f"Invalid JSON: {e}"}

    else:
        return {"success": False, "error": f"Unknown operation: '{operation}'. Available: pretty, compact, validate, keys, flatten"}


def _flatten_json(data: Any, prefix: str = "") -> dict:
    """Flatten nested JSON to dot-notation keys."""
    result = {}
    if isinstance(data, dict):
        for k, v in data.items():
            new_key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, (dict, list)):
                result.update(_flatten_json(v, new_key))
            else:
                result[new_key] = v
    elif isinstance(data, list):
        for i, v in enumerate(data):
            new_key = f"{prefix}[{i}]"
            if isinstance(v, (dict, list)):
                result.update(_flatten_json(v, new_key))
            else:
                result[new_key] = v
    else:
        result[prefix] = data
    return result


def template_render(template: str, variables: str) -> dict[str, Any]:
    """Render a template with variable substitution.

    Template uses {{variable_name}} syntax.
    Variables: JSON string or 'key=value' pairs separated by commas.
    """
    if not template:
        return {"success": False, "error": "Template required"}

    # Parse variables
    var_dict = {}
    if variables.strip().startswith("{"):
        try:
            var_dict = json.loads(variables)
        except json.JSONDecodeError:
            return {"success": False, "error": "Invalid JSON for variables"}
    else:
        for pair in variables.split(","):
            if "=" in pair:
                k, _, v = pair.partition("=")
                var_dict[k.strip()] = v.strip()

    # Render
    result = template
    for key, value in var_dict.items():
        result = result.replace("{{" + key + "}}", str(value))
        result = result.replace("{{ " + key + " }}", str(value))

    # Check for unresolved variables
    unresolved = re.findall(r'\{\{\s*(\w+)\s*\}\}', result)
    if unresolved:
        return {"success": True, "result": result, "warning": f"Unresolved variables: {', '.join(unresolved)}"}

    return {"success": True, "result": result}


def markdown_op(operation: str, input_text: str) -> dict[str, Any]:
    """Markdown operations.

    Operations: toc, extract_links, extract_headings, to_html, word_count, stats
    """
    operation = operation.lower().strip()

    if operation == "toc":
        headings = re.findall(r'^(#{1,6})\s+(.+)$', input_text, re.MULTILINE)
        if not headings:
            return {"success": True, "result": "No headings found"}
        lines = []
        for hashes, title in headings:
            level = len(hashes)
            indent = "  " * (level - 1)
            anchor = re.sub(r'[^\w\s-]', '', title.lower()).replace(" ", "-")
            lines.append(f"{indent}- [{title}](#{anchor})")
        return {"success": True, "result": "\n".join(lines)}

    elif operation == "extract_links":
        links = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', input_text)
        if not links:
            return {"success": True, "result": "No links found"}
        lines = [f"  [{text}]({url})" for text, url in links]
        return {"success": True, "result": f"Links ({len(links)}):\n" + "\n".join(lines)}

    elif operation == "extract_headings":
        headings = re.findall(r'^(#{1,6})\s+(.+)$', input_text, re.MULTILINE)
        if not headings:
            return {"success": True, "result": "No headings found"}
        lines = [f"  {'#' * len(h)} {title}" for h, title in headings]
        return {"success": True, "result": f"Headings ({len(headings)}):\n" + "\n".join(lines)}

    elif operation == "word_count":
        words = len(input_text.split())
        chars = len(input_text)
        lines = len(input_text.splitlines())
        return {"success": True, "result": f"Words: {words}\nCharacters: {chars}\nLines: {lines}\nReading time: ~{max(1, words // 200)} min"}

    elif operation == "stats":
        headings = len(re.findall(r'^#{1,6}\s', input_text, re.MULTILINE))
        links = len(re.findall(r'\[.+?\]\(.+?\)', input_text))
        code_blocks = len(re.findall(r'```', input_text)) // 2
        images = len(re.findall(r'!\[.+?\]\(.+?\)', input_text))
        return {"success": True, "result": f"Markdown stats:\n  Headings: {headings}\n  Links: {links}\n  Code blocks: {code_blocks}\n  Images: {images}\n  Words: {len(input_text.split())}"}

    else:
        return {"success": False, "error": f"Unknown operation: '{operation}'. Available: toc, extract_links, extract_headings, to_html, word_count, stats"}
