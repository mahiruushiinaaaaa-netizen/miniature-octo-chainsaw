"""
data_tools.py – Data processing tools for JSON, CSV, text transformation,
regex operations, math calculations, and date/time utilities.

Provides pure-Python implementations that don't require external dependencies.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import math
import os
import re
import statistics
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# JSON Query
# ---------------------------------------------------------------------------

def json_query(file_path: str, query: str) -> dict[str, Any]:
    """Query a JSON file using dot-notation path expressions.
    
    Supports:
    - Dot notation: data.users[0].name
    - Array indexing: items[2]
    - keys(@): list all keys
    - length(path): count items
    - values(@): list all values
    """
    path = Path(file_path)
    if not path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}
    
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return {"success": False, "error": f"Invalid JSON: {e}"}
    
    try:
        result = _evaluate_json_query(data, query)
        # Format output nicely
        if isinstance(result, (dict, list)):
            output = json.dumps(result, indent=2, ensure_ascii=False, default=str)
        else:
            output = str(result)
        return {"success": True, "result": output}
    except Exception as e:
        return {"success": False, "error": f"Query error: {e}"}


def _evaluate_json_query(data: Any, query: str) -> Any:
    """Evaluate a simple path query against JSON data."""
    query = query.strip()
    
    # Special functions
    if query == "keys(@)" or query == "keys()":
        if isinstance(data, dict):
            return list(data.keys())
        return []
    if query == "values(@)" or query == "values()":
        if isinstance(data, dict):
            return list(data.values())
        return []
    if query.startswith("length(") and query.endswith(")"):
        inner = query[7:-1].strip()
        if inner == "@" or inner == "":
            target = data
        else:
            target = _evaluate_json_query(data, inner)
        if hasattr(target, "__len__"):
            return len(target)
        return 0
    if query == "@" or query == ".":
        return data
    
    # Navigate path
    current = data
    parts = _split_json_path(query)
    
    for part in parts:
        if part.startswith("[") and part.endswith("]"):
            idx = int(part[1:-1])
            if isinstance(current, list) and -len(current) <= idx < len(current):
                current = current[idx]
            else:
                raise ValueError(f"Index {idx} out of range")
        elif isinstance(current, dict):
            if part in current:
                current = current[part]
            else:
                raise ValueError(f"Key '{part}' not found. Available: {list(current.keys())[:10]}")
        elif isinstance(current, list):
            # Try numeric index
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                raise ValueError(f"Cannot access '{part}' on list")
        else:
            raise ValueError(f"Cannot navigate into {type(current).__name__}")
    
    return current


def _split_json_path(path: str) -> list[str]:
    """Split a JSON path like 'data.users[0].name' into parts."""
    parts = []
    current = ""
    i = 0
    while i < len(path):
        ch = path[i]
        if ch == ".":
            if current:
                parts.append(current)
                current = ""
        elif ch == "[":
            if current:
                parts.append(current)
                current = ""
            end = path.index("]", i)
            parts.append(path[i:end + 1])
            i = end
        else:
            current += ch
        i += 1
    if current:
        parts.append(current)
    return parts


# ---------------------------------------------------------------------------
# CSV Query
# ---------------------------------------------------------------------------

def csv_query(file_path: str, operation: str, args: str = "") -> dict[str, Any]:
    """Query and analyze CSV files.
    
    Operations:
    - head: First N rows (default 10)
    - tail: Last N rows (default 10)
    - columns: List column names
    - count: Count rows
    - stats: Basic statistics for numeric columns
    - filter: Filter rows (args: "column operator value", e.g. "age > 25")
    - sort: Sort by column (args: "column [asc|desc]")
    """
    path = Path(file_path)
    if not path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}
    
    try:
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
            # Detect delimiter
            sample = f.read(4096)
            f.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample)
                reader = csv.DictReader(f, dialect=dialect)
            except csv.Error:
                reader = csv.DictReader(f)
            
            rows = list(reader)
            columns = reader.fieldnames or []
    except Exception as e:
        return {"success": False, "error": f"CSV read error: {e}"}
    
    operation = operation.lower().strip()
    
    if operation == "columns":
        return {"success": True, "result": f"Columns ({len(columns)}): {', '.join(columns)}\nRows: {len(rows)}"}
    
    elif operation == "count":
        return {"success": True, "result": f"Total rows: {len(rows)}"}
    
    elif operation == "head":
        n = int(args) if args.isdigit() else 10
        subset = rows[:n]
        return {"success": True, "result": _format_csv_rows(subset, columns)}
    
    elif operation == "tail":
        n = int(args) if args.isdigit() else 10
        subset = rows[-n:]
        return {"success": True, "result": _format_csv_rows(subset, columns)}
    
    elif operation == "stats":
        return {"success": True, "result": _csv_stats(rows, columns, args)}
    
    elif operation == "filter":
        filtered = _csv_filter(rows, args)
        return {"success": True, "result": f"Matched {len(filtered)} rows:\n{_format_csv_rows(filtered[:20], columns)}"}
    
    elif operation == "sort":
        sorted_rows = _csv_sort(rows, args)
        return {"success": True, "result": _format_csv_rows(sorted_rows[:20], columns)}
    
    else:
        return {"success": False, "error": f"Unknown operation: {operation}. Use: head, tail, columns, count, stats, filter, sort"}


def _format_csv_rows(rows: list[dict], columns: list[str]) -> str:
    """Format CSV rows as a readable table."""
    if not rows:
        return "(no rows)"
    cols = columns or list(rows[0].keys())
    # Truncate wide columns
    col_widths = {c: min(max(len(c), max((len(str(r.get(c, ""))[:30]) for r in rows), default=0)), 30) for c in cols}
    
    header = " | ".join(c.ljust(col_widths[c])[:30] for c in cols)
    sep = "-+-".join("-" * col_widths[c] for c in cols)
    lines = [header, sep]
    for row in rows:
        line = " | ".join(str(row.get(c, "")).ljust(col_widths[c])[:30] for c in cols)
        lines.append(line)
    return "\n".join(lines)


def _csv_stats(rows: list[dict], columns: list[str], target_col: str = "") -> str:
    """Calculate basic statistics for numeric columns."""
    cols_to_check = [target_col.strip()] if target_col.strip() else columns
    results = []
    
    for col in cols_to_check:
        values = []
        for row in rows:
            try:
                values.append(float(row.get(col, "")))
            except (ValueError, TypeError):
                continue
        
        if values:
            results.append(f"Column: {col}")
            results.append(f"  Count: {len(values)}")
            results.append(f"  Mean: {statistics.mean(values):.2f}")
            results.append(f"  Median: {statistics.median(values):.2f}")
            results.append(f"  Std Dev: {statistics.stdev(values):.2f}" if len(values) > 1 else "  Std Dev: N/A")
            results.append(f"  Min: {min(values):.2f}")
            results.append(f"  Max: {max(values):.2f}")
            results.append("")
    
    return "\n".join(results) if results else "No numeric columns found"


def _csv_filter(rows: list[dict], expr: str) -> list[dict]:
    """Filter rows by expression like 'age > 25' or 'name == John'."""
    match = re.match(r'(\w+)\s*(==|!=|>|<|>=|<=|contains|startswith|endswith)\s*(.+)', expr.strip())
    if not match:
        return rows
    
    col, op, val = match.group(1), match.group(2), match.group(3).strip().strip("'\"")
    
    filtered = []
    for row in rows:
        cell = str(row.get(col, ""))
        try:
            if op == "==" and cell == val:
                filtered.append(row)
            elif op == "!=" and cell != val:
                filtered.append(row)
            elif op == "contains" and val.lower() in cell.lower():
                filtered.append(row)
            elif op == "startswith" and cell.lower().startswith(val.lower()):
                filtered.append(row)
            elif op == "endswith" and cell.lower().endswith(val.lower()):
                filtered.append(row)
            elif op in (">", "<", ">=", "<="):
                try:
                    cell_num = float(cell)
                    val_num = float(val)
                    if op == ">" and cell_num > val_num:
                        filtered.append(row)
                    elif op == "<" and cell_num < val_num:
                        filtered.append(row)
                    elif op == ">=" and cell_num >= val_num:
                        filtered.append(row)
                    elif op == "<=" and cell_num <= val_num:
                        filtered.append(row)
                except ValueError:
                    pass
        except Exception:
            continue
    return filtered


def _csv_sort(rows: list[dict], args: str) -> list[dict]:
    """Sort rows by column. Args: 'column [asc|desc]'."""
    parts = args.strip().split()
    col = parts[0] if parts else ""
    desc = len(parts) > 1 and parts[1].lower() == "desc"
    
    def sort_key(row):
        val = row.get(col, "")
        try:
            return (0, float(val))
        except (ValueError, TypeError):
            return (1, str(val).lower())
    
    return sorted(rows, key=sort_key, reverse=desc)


# ---------------------------------------------------------------------------
# Text Transform
# ---------------------------------------------------------------------------

def text_transform(input_text: str, operation: str, pattern: str = "", replacement: str = "", is_file: bool = False) -> dict[str, Any]:
    """Transform text with various operations.
    
    Operations:
    - regex_replace: Replace pattern matches
    - extract: Extract all pattern matches
    - split: Split by pattern
    - join: Join lines with pattern as separator
    - base64_encode / base64_decode
    - url_encode / url_decode
    - hash: Generate hash (pattern = algorithm: md5, sha1, sha256)
    - template: Simple template substitution
    - upper / lower / title / strip
    - count_lines / count_words / count_chars
    """
    # If input is a file path, read it
    text = input_text
    if is_file or (len(input_text) < 260 and Path(input_text).exists()):
        try:
            text = Path(input_text).read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass  # Use input_text as-is
    
    operation = operation.lower().strip()
    
    try:
        if operation == "regex_replace":
            result = re.sub(pattern, replacement, text)
            return {"success": True, "result": result}
        
        elif operation == "extract":
            matches = re.findall(pattern, text)
            return {"success": True, "result": "\n".join(str(m) for m in matches), "count": len(matches)}
        
        elif operation == "split":
            parts = re.split(pattern or r"\n", text)
            return {"success": True, "result": "\n".join(f"[{i}] {p}" for i, p in enumerate(parts)), "count": len(parts)}
        
        elif operation == "join":
            lines = text.splitlines()
            sep = pattern or ", "
            return {"success": True, "result": sep.join(lines)}
        
        elif operation == "base64_encode":
            encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
            return {"success": True, "result": encoded}
        
        elif operation == "base64_decode":
            decoded = base64.b64decode(text.encode("ascii")).decode("utf-8")
            return {"success": True, "result": decoded}
        
        elif operation == "url_encode":
            return {"success": True, "result": urllib.parse.quote(text, safe="")}
        
        elif operation == "url_decode":
            return {"success": True, "result": urllib.parse.unquote(text)}
        
        elif operation == "hash":
            algo = pattern.lower() if pattern else "sha256"
            if algo == "md5":
                h = hashlib.md5(text.encode()).hexdigest()
            elif algo == "sha1":
                h = hashlib.sha1(text.encode()).hexdigest()
            elif algo == "sha256":
                h = hashlib.sha256(text.encode()).hexdigest()
            elif algo == "sha512":
                h = hashlib.sha512(text.encode()).hexdigest()
            else:
                return {"success": False, "error": f"Unknown hash algorithm: {algo}"}
            return {"success": True, "result": f"{algo}: {h}"}
        
        elif operation == "upper":
            return {"success": True, "result": text.upper()}
        elif operation == "lower":
            return {"success": True, "result": text.lower()}
        elif operation == "title":
            return {"success": True, "result": text.title()}
        elif operation == "strip":
            return {"success": True, "result": text.strip()}
        
        elif operation == "count_lines":
            return {"success": True, "result": str(len(text.splitlines()))}
        elif operation == "count_words":
            return {"success": True, "result": str(len(text.split()))}
        elif operation == "count_chars":
            return {"success": True, "result": str(len(text))}
        
        else:
            return {"success": False, "error": f"Unknown operation: {operation}"}
    
    except Exception as e:
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Regex Tool
# ---------------------------------------------------------------------------

def regex_tool(operation: str, pattern: str, text: str = "", replacement: str = "", flags_str: str = "") -> dict[str, Any]:
    """Perform regex operations.
    
    Operations: match, findall, replace, split, test, explain
    """
    # Parse flags
    flags = 0
    if "i" in flags_str:
        flags |= re.IGNORECASE
    if "m" in flags_str:
        flags |= re.MULTILINE
    if "s" in flags_str:
        flags |= re.DOTALL
    
    operation = operation.lower().strip()
    
    try:
        compiled = re.compile(pattern, flags)
        
        if operation == "test":
            found = bool(compiled.search(text))
            return {"success": True, "result": f"Pattern {'matches' if found else 'does NOT match'} the text", "match": found}
        
        elif operation == "match":
            m = compiled.search(text)
            if m:
                groups = m.groups()
                return {"success": True, "result": f"Match: '{m.group()}' at position {m.start()}-{m.end()}", "groups": list(groups)}
            return {"success": True, "result": "No match found", "match": False}
        
        elif operation == "findall":
            matches = compiled.findall(text)
            return {"success": True, "result": "\n".join(str(m) for m in matches), "count": len(matches)}
        
        elif operation == "replace":
            result = compiled.sub(replacement, text)
            return {"success": True, "result": result}
        
        elif operation == "split":
            parts = compiled.split(text)
            return {"success": True, "result": "\n".join(f"[{i}] {p}" for i, p in enumerate(parts)), "count": len(parts)}
        
        elif operation == "explain":
            explanation = _explain_regex(pattern)
            return {"success": True, "result": explanation}
        
        else:
            return {"success": False, "error": f"Unknown operation: {operation}"}
    
    except re.error as e:
        return {"success": False, "error": f"Invalid regex: {e}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _explain_regex(pattern: str) -> str:
    """Provide a human-readable explanation of a regex pattern."""
    explanations = {
        r"\d": "digit (0-9)",
        r"\w": "word character (letter, digit, underscore)",
        r"\s": "whitespace",
        r"\b": "word boundary",
        r".": "any character",
        r"^": "start of string/line",
        r"$": "end of string/line",
        r"*": "zero or more",
        r"+": "one or more",
        r"?": "zero or one (optional)",
    }
    
    lines = [f"Pattern: {pattern}", ""]
    for token, desc in explanations.items():
        if token in pattern:
            lines.append(f"  {token} → {desc}")
    
    # Detect groups
    groups = re.findall(r'\((?:\?P<(\w+)>)?', pattern)
    if groups:
        lines.append(f"\n  Groups: {len(groups)}")
        for i, g in enumerate(groups, 1):
            if g:
                lines.append(f"    Group {i}: named '{g}'")
    
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Math/Calculate
# ---------------------------------------------------------------------------

# Safe math namespace
_MATH_NAMESPACE = {
    "abs": abs, "round": round, "min": min, "max": max, "sum": sum, "len": len,
    "int": int, "float": float, "pow": pow,
    "pi": math.pi, "e": math.e, "tau": math.tau, "inf": math.inf,
    "sqrt": math.sqrt, "log": math.log, "log2": math.log2, "log10": math.log10,
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan, "atan2": math.atan2,
    "ceil": math.ceil, "floor": math.floor, "trunc": math.trunc,
    "factorial": math.factorial, "gcd": math.gcd,
    "degrees": math.degrees, "radians": math.radians,
    "mean": statistics.mean, "median": statistics.median,
    "stdev": statistics.stdev, "variance": statistics.variance,
    "hypot": math.hypot, "exp": math.exp,
    "__builtins__": {},
}


def calculate(expression: str) -> dict[str, Any]:
    """Safely evaluate a mathematical expression."""
    try:
        # Basic sanitization - block dangerous patterns
        dangerous = ["import", "exec", "eval", "open", "os.", "sys.", "__", "subprocess", "compile"]
        expr_lower = expression.lower()
        for d in dangerous:
            if d in expr_lower:
                return {"success": False, "error": f"Blocked: '{d}' not allowed in expressions"}
        
        result = eval(expression, _MATH_NAMESPACE)
        return {"success": True, "result": str(result)}
    except Exception as e:
        return {"success": False, "error": f"Calculation error: {e}"}


# ---------------------------------------------------------------------------
# Date/Time Utilities
# ---------------------------------------------------------------------------

def datetime_util(operation: str, value: str = "", fmt: str = "", tz_name: str = "") -> dict[str, Any]:
    """Date/time operations.
    
    Operations:
    - now: Current date/time
    - format: Format a date string
    - parse: Parse a date string
    - diff: Difference between two dates (value = "date1 | date2")
    - add: Add duration to date (value = "date | duration", e.g. "2024-01-01 | 5d")
    - timezone: Convert between timezones
    """
    operation = operation.lower().strip()
    
    try:
        if operation == "now":
            now = datetime.now()
            utc_now = datetime.now(timezone.utc)
            result = f"Local: {now.strftime('%Y-%m-%d %H:%M:%S')}\nUTC: {utc_now.strftime('%Y-%m-%d %H:%M:%S')}\nTimestamp: {int(now.timestamp())}\nISO: {now.isoformat()}"
            return {"success": True, "result": result}
        
        elif operation == "format":
            dt = _parse_datetime(value)
            output_fmt = fmt or "%Y-%m-%d %H:%M:%S"
            return {"success": True, "result": dt.strftime(output_fmt)}
        
        elif operation == "parse":
            dt = _parse_datetime(value)
            return {"success": True, "result": f"Parsed: {dt.isoformat()}\nTimestamp: {int(dt.timestamp())}\nWeekday: {dt.strftime('%A')}\nWeek: {dt.isocalendar()[1]}"}
        
        elif operation == "diff":
            parts = value.split("|")
            if len(parts) != 2:
                return {"success": False, "error": "Use format: 'date1 | date2'"}
            dt1 = _parse_datetime(parts[0].strip())
            dt2 = _parse_datetime(parts[1].strip())
            diff = dt2 - dt1
            days = diff.days
            hours, remainder = divmod(abs(diff.seconds), 3600)
            minutes = remainder // 60
            return {"success": True, "result": f"Difference: {days} days, {hours} hours, {minutes} minutes\nTotal seconds: {int(diff.total_seconds())}"}
        
        elif operation == "add":
            parts = value.split("|")
            if len(parts) != 2:
                return {"success": False, "error": "Use format: 'date | duration' (e.g. '2024-01-01 | 5d')"}
            dt = _parse_datetime(parts[0].strip())
            duration = _parse_duration(parts[1].strip())
            result_dt = dt + duration
            return {"success": True, "result": f"Result: {result_dt.isoformat()}"}
        
        elif operation == "timestamp":
            if value:
                ts = int(float(value))
                dt = datetime.fromtimestamp(ts)
                return {"success": True, "result": f"Timestamp {ts} = {dt.isoformat()}"}
            else:
                return {"success": True, "result": str(int(datetime.now().timestamp()))}
        
        else:
            return {"success": False, "error": f"Unknown operation: {operation}"}
    
    except Exception as e:
        return {"success": False, "error": str(e)}


def _parse_datetime(value: str) -> datetime:
    """Try multiple formats to parse a datetime string."""
    value = value.strip()
    
    # Try timestamp
    try:
        ts = float(value)
        if ts > 1e9:  # Likely a Unix timestamp
            return datetime.fromtimestamp(ts)
    except ValueError:
        pass
    
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%B %d, %Y",
        "%b %d, %Y",
        "%d %B %Y",
        "%Y-%m-%d %H:%M",
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    
    # Last resort: try "now" or "today"
    if value.lower() in ("now", "today"):
        return datetime.now()
    if value.lower() == "yesterday":
        return datetime.now() - timedelta(days=1)
    if value.lower() == "tomorrow":
        return datetime.now() + timedelta(days=1)
    
    raise ValueError(f"Cannot parse date: '{value}'")


def _parse_duration(value: str) -> timedelta:
    """Parse duration strings like '5d', '3h', '30m', '2w'."""
    value = value.strip().lower()
    
    match = re.match(r'^(\d+)\s*(s|sec|seconds?|m|min|minutes?|h|hr|hours?|d|days?|w|weeks?)$', value)
    if match:
        num = int(match.group(1))
        unit = match.group(2)[0]
        if unit == "s":
            return timedelta(seconds=num)
        elif unit == "m":
            return timedelta(minutes=num)
        elif unit == "h":
            return timedelta(hours=num)
        elif unit == "d":
            return timedelta(days=num)
        elif unit == "w":
            return timedelta(weeks=num)
    
    raise ValueError(f"Cannot parse duration: '{value}'. Use format like '5d', '3h', '30m'")
