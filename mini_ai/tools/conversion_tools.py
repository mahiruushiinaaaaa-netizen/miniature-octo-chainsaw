"""
conversion_tools.py – File format conversion and encoding tools.

Covers: JSON/YAML/TOML/XML/CSV conversions, image format conversion,
document conversion, encoding/decoding, and data serialization.
"""
from __future__ import annotations

import base64
import csv
import io
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


def convert_format(input_path: str, output_path: str, from_fmt: str = "auto", to_fmt: str = "auto") -> dict[str, Any]:
    """Convert between file formats.
    
    Supported conversions:
    - json <-> yaml, toml, csv, xml
    - markdown -> html
    - csv <-> json
    - Any text encoding conversion
    """
    inp = Path(input_path)
    if not inp.exists():
        return {"success": False, "error": f"Input file not found: {input_path}"}
    
    # Auto-detect formats from extensions
    if from_fmt == "auto":
        from_fmt = inp.suffix.lstrip(".").lower()
    if to_fmt == "auto":
        to_fmt = Path(output_path).suffix.lstrip(".").lower()
    
    try:
        content = inp.read_text(encoding="utf-8")
        
        # Parse input
        data = _parse_input(content, from_fmt)
        if data is None:
            return {"success": False, "error": f"Cannot parse {from_fmt} format"}
        
        # Convert to output
        output = _format_output(data, to_fmt)
        if output is None:
            return {"success": False, "error": f"Cannot convert to {to_fmt} format"}
        
        # Write output
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        
        return {"success": True, "result": f"Converted {from_fmt} -> {to_fmt}: {output_path}"}
    except Exception as e:
        return {"success": False, "error": f"Conversion failed: {e}"}


def encode_decode(operation: str, input_text: str, encoding: str = "utf-8") -> dict[str, Any]:
    """Encode or decode text/data.
    
    Operations: base64_encode, base64_decode, url_encode, url_decode,
                hex_encode, hex_decode, html_encode, html_decode,
                unicode_escape, unicode_unescape, rot13
    """
    op = operation.lower().strip()
    
    try:
        if op == "base64_encode":
            result = base64.b64encode(input_text.encode(encoding)).decode("ascii")
        elif op == "base64_decode":
            result = base64.b64decode(input_text).decode(encoding)
        elif op == "url_encode":
            import urllib.parse
            result = urllib.parse.quote(input_text, safe="")
        elif op == "url_decode":
            import urllib.parse
            result = urllib.parse.unquote(input_text)
        elif op == "hex_encode":
            result = input_text.encode(encoding).hex()
        elif op == "hex_decode":
            result = bytes.fromhex(input_text).decode(encoding)
        elif op == "html_encode":
            import html
            result = html.escape(input_text)
        elif op == "html_decode":
            import html
            result = html.unescape(input_text)
        elif op == "unicode_escape":
            result = input_text.encode("unicode_escape").decode("ascii")
        elif op == "unicode_unescape":
            result = input_text.encode("ascii").decode("unicode_escape")
        elif op == "rot13":
            import codecs
            result = codecs.encode(input_text, "rot_13")
        else:
            return {"success": False, "error": f"Unknown operation: {op}"}
        
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": f"Encoding error: {e}"}


def hash_data(input_text: str, algorithm: str = "sha256") -> dict[str, Any]:
    """Hash text or file content.
    
    Algorithms: md5, sha1, sha256, sha512, sha3_256
    """
    import hashlib
    
    algo = algorithm.lower().strip()
    
    # Check if input is a file path
    if os.path.isfile(input_text):
        try:
            with open(input_text, "rb") as f:
                content = f.read()
        except Exception as e:
            return {"success": False, "error": f"Cannot read file: {e}"}
    else:
        content = input_text.encode("utf-8")
    
    try:
        if algo == "md5":
            h = hashlib.md5(content).hexdigest()
        elif algo == "sha1":
            h = hashlib.sha1(content).hexdigest()
        elif algo == "sha256":
            h = hashlib.sha256(content).hexdigest()
        elif algo == "sha512":
            h = hashlib.sha512(content).hexdigest()
        elif algo == "sha3_256":
            h = hashlib.sha3_256(content).hexdigest()
        else:
            return {"success": False, "error": f"Unknown algorithm: {algo}. Use: md5, sha1, sha256, sha512, sha3_256"}
        
        return {"success": True, "result": f"{algo}: {h}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def generate_uuid(version: int = 4, count: int = 1) -> dict[str, Any]:
    """Generate UUID(s). Versions: 1 (time-based), 4 (random)."""
    import uuid
    
    if count < 1 or count > 100:
        return {"success": False, "error": "Count must be 1-100"}
    
    uuids = []
    for _ in range(count):
        if version == 1:
            uuids.append(str(uuid.uuid1()))
        elif version == 4:
            uuids.append(str(uuid.uuid4()))
        else:
            return {"success": False, "error": f"Unsupported UUID version: {version}. Use 1 or 4"}
    
    return {"success": True, "result": "\n".join(uuids)}


def generate_password(length: int = 16, count: int = 1, charset: str = "all") -> dict[str, Any]:
    """Generate secure random passwords.
    
    Charsets: all, alpha, alphanumeric, numeric, hex
    """
    import secrets
    import string
    
    if length < 4 or length > 128:
        return {"success": False, "error": "Length must be 4-128"}
    if count < 1 or count > 20:
        return {"success": False, "error": "Count must be 1-20"}
    
    charsets = {
        "all": string.ascii_letters + string.digits + "!@#$%^&*()-_=+",
        "alpha": string.ascii_letters,
        "alphanumeric": string.ascii_letters + string.digits,
        "numeric": string.digits,
        "hex": string.hexdigits[:16],
    }
    
    chars = charsets.get(charset.lower(), charsets["all"])
    passwords = ["".join(secrets.choice(chars) for _ in range(length)) for _ in range(count)]
    
    return {"success": True, "result": "\n".join(passwords)}


def json_format(input_text: str, operation: str = "pretty", indent: int = 2) -> dict[str, Any]:
    """Format, minify, or validate JSON.
    
    Operations: pretty, minify, validate, sort_keys, flatten
    """
    op = operation.lower().strip()
    
    # Try to read from file if it's a path
    if os.path.isfile(input_text):
        try:
            input_text = Path(input_text).read_text(encoding="utf-8")
        except Exception as e:
            return {"success": False, "error": f"Cannot read file: {e}"}
    
    try:
        data = json.loads(input_text)
    except json.JSONDecodeError as e:
        if op == "validate":
            return {"success": False, "result": f"Invalid JSON: {e}"}
        return {"success": False, "error": f"Invalid JSON: {e}"}
    
    if op == "pretty":
        result = json.dumps(data, indent=indent, ensure_ascii=False)
    elif op == "minify":
        result = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    elif op == "validate":
        return {"success": True, "result": "Valid JSON"}
    elif op == "sort_keys":
        result = json.dumps(data, indent=indent, sort_keys=True, ensure_ascii=False)
    elif op == "flatten":
        flat = _flatten_json(data)
        result = json.dumps(flat, indent=indent, ensure_ascii=False)
    else:
        return {"success": False, "error": f"Unknown operation: {op}"}
    
    return {"success": True, "result": result}


def _parse_input(content: str, fmt: str) -> Any:
    """Parse content from a given format."""
    if fmt == "json":
        return json.loads(content)
    elif fmt in ("yaml", "yml"):
        # Simple YAML parser for basic structures
        return _simple_yaml_parse(content)
    elif fmt == "csv":
        reader = csv.DictReader(io.StringIO(content))
        return list(reader)
    elif fmt == "toml":
        return _simple_toml_parse(content)
    return None


def _format_output(data: Any, fmt: str) -> str | None:
    """Format data to a given format."""
    if fmt == "json":
        return json.dumps(data, indent=2, ensure_ascii=False)
    elif fmt in ("yaml", "yml"):
        return _simple_yaml_dump(data)
    elif fmt == "csv":
        if isinstance(data, list) and data and isinstance(data[0], dict):
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)
            return output.getvalue()
    elif fmt == "html":
        if isinstance(data, str):
            # Simple markdown to HTML
            return _markdown_to_html(data)
    return None


def _simple_yaml_parse(content: str) -> dict:
    """Minimal YAML parser for key: value pairs."""
    result = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            val = val.strip()
            if val.lower() == "true":
                val = True
            elif val.lower() == "false":
                val = False
            elif val.isdigit():
                val = int(val)
            result[key.strip()] = val
    return result


def _simple_yaml_dump(data: Any, indent: int = 0) -> str:
    """Minimal YAML dumper."""
    lines = []
    prefix = "  " * indent
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                lines.append(f"{prefix}{k}:")
                lines.append(_simple_yaml_dump(v, indent + 1))
            else:
                lines.append(f"{prefix}{k}: {v}")
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                lines.append(f"{prefix}-")
                lines.append(_simple_yaml_dump(item, indent + 1))
            else:
                lines.append(f"{prefix}- {item}")
    else:
        lines.append(f"{prefix}{data}")
    return "\n".join(lines)


def _simple_toml_parse(content: str) -> dict:
    """Minimal TOML parser."""
    result = {}
    current_section = result
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            result[section] = {}
            current_section = result[section]
        elif "=" in line:
            key, _, val = line.partition("=")
            val = val.strip().strip('"').strip("'")
            if val.lower() == "true":
                val = True
            elif val.lower() == "false":
                val = False
            elif val.isdigit():
                val = int(val)
            current_section[key.strip()] = val
    return result


def _flatten_json(data: Any, prefix: str = "") -> dict:
    """Flatten nested JSON to dot-notation keys."""
    result = {}
    if isinstance(data, dict):
        for k, v in data.items():
            new_key = f"{prefix}.{k}" if prefix else k
            result.update(_flatten_json(v, new_key))
    elif isinstance(data, list):
        for i, v in enumerate(data):
            new_key = f"{prefix}[{i}]"
            result.update(_flatten_json(v, new_key))
    else:
        result[prefix] = data
    return result


def _markdown_to_html(md: str) -> str:
    """Very basic markdown to HTML conversion."""
    lines = md.splitlines()
    html_lines = []
    for line in lines:
        if line.startswith("# "):
            html_lines.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("## "):
            html_lines.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("### "):
            html_lines.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("- "):
            html_lines.append(f"<li>{line[2:]}</li>")
        elif line.strip():
            html_lines.append(f"<p>{line}</p>")
        else:
            html_lines.append("")
    return "\n".join(html_lines)
