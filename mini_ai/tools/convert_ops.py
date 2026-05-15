"""
convert_ops.py – Unit conversion, format conversion, and number base conversion.
All pure Python, no external dependencies.
"""
from __future__ import annotations

import json
import re
from typing import Any


# ---------------------------------------------------------------------------
# Unit Conversion
# ---------------------------------------------------------------------------

_UNITS = {
    "length": {
        "m": 1.0, "km": 1000.0, "cm": 0.01, "mm": 0.001, "mi": 1609.344,
        "yd": 0.9144, "ft": 0.3048, "in": 0.0254, "nm": 1852.0, "um": 1e-6,
    },
    "weight": {
        "kg": 1.0, "g": 0.001, "mg": 1e-6, "lb": 0.453592, "oz": 0.0283495,
        "ton": 1000.0, "st": 6.35029,
    },
    "temperature": {},  # special handling
    "speed": {
        "m/s": 1.0, "km/h": 0.277778, "mph": 0.44704, "knot": 0.514444, "ft/s": 0.3048,
    },
    "data_size": {
        "b": 1, "kb": 1024, "mb": 1024**2, "gb": 1024**3, "tb": 1024**4,
        "pb": 1024**5, "bit": 0.125,
    },
    "time": {
        "s": 1.0, "ms": 0.001, "us": 1e-6, "ns": 1e-9, "min": 60.0,
        "h": 3600.0, "d": 86400.0, "w": 604800.0, "y": 31536000.0,
    },
    "area": {
        "m2": 1.0, "km2": 1e6, "cm2": 1e-4, "ha": 10000.0, "acre": 4046.86,
        "ft2": 0.092903, "mi2": 2.59e6,
    },
    "volume": {
        "l": 1.0, "ml": 0.001, "m3": 1000.0, "gal": 3.78541, "qt": 0.946353,
        "pt": 0.473176, "cup": 0.236588, "fl_oz": 0.0295735, "tbsp": 0.0147868,
    },
}


def convert(category: str, value: str, from_unit: str, to_unit: str) -> dict[str, Any]:
    """Unit conversion.

    Categories: length, weight, temperature, speed, data_size, time, area, volume
    """
    category = category.lower().strip()
    from_unit = from_unit.lower().strip()
    to_unit = to_unit.lower().strip()

    try:
        num_value = float(value)
    except (ValueError, TypeError):
        return {"success": False, "error": f"Invalid number: '{value}'"}

    if category not in _UNITS:
        available = ", ".join(sorted(_UNITS.keys()))
        return {"success": False, "error": f"Unknown category: '{category}'. Available: {available}"}

    # Temperature special case
    if category == "temperature":
        return _convert_temperature(num_value, from_unit, to_unit)

    units = _UNITS[category]
    if from_unit not in units:
        available = ", ".join(sorted(units.keys()))
        return {"success": False, "error": f"Unknown {category} unit: '{from_unit}'. Available: {available}"}
    if to_unit not in units:
        available = ", ".join(sorted(units.keys()))
        return {"success": False, "error": f"Unknown {category} unit: '{to_unit}'. Available: {available}"}

    # Convert via base unit
    base_value = num_value * units[from_unit]
    result = base_value / units[to_unit]

    # Format nicely
    if abs(result) < 0.001 or abs(result) > 1e9:
        formatted = f"{result:.6e}"
    elif result == int(result):
        formatted = str(int(result))
    else:
        formatted = f"{result:.6g}"

    return {"success": True, "result": f"{value} {from_unit} = {formatted} {to_unit}"}


def _convert_temperature(value: float, from_u: str, to_u: str) -> dict[str, Any]:
    """Temperature conversion between C, F, K."""
    aliases = {"c": "c", "celsius": "c", "f": "f", "fahrenheit": "f", "k": "k", "kelvin": "k"}
    from_u = aliases.get(from_u, from_u)
    to_u = aliases.get(to_u, to_u)

    if from_u not in ("c", "f", "k") or to_u not in ("c", "f", "k"):
        return {"success": False, "error": "Temperature units: c (Celsius), f (Fahrenheit), k (Kelvin)"}

    # Convert to Celsius first
    if from_u == "f":
        celsius = (value - 32) * 5 / 9
    elif from_u == "k":
        celsius = value - 273.15
    else:
        celsius = value

    # Convert from Celsius to target
    if to_u == "f":
        result = celsius * 9 / 5 + 32
    elif to_u == "k":
        result = celsius + 273.15
    else:
        result = celsius

    return {"success": True, "result": f"{value}°{from_u.upper()} = {result:.2f}°{to_u.upper()}"}


# ---------------------------------------------------------------------------
# Format Conversion
# ---------------------------------------------------------------------------

def format_convert(operation: str, input_text: str, options: str = "") -> dict[str, Any]:
    """Convert between data formats.

    Operations: json_to_yaml, yaml_to_json, csv_to_json, json_to_csv,
                xml_to_json, markdown_to_html, toml_to_json, json_to_toml
    """
    operation = operation.lower().strip()

    try:
        if operation == "json_to_yaml":
            data = json.loads(input_text)
            return {"success": True, "result": _dict_to_yaml(data)}

        elif operation == "yaml_to_json":
            data = _simple_yaml_parse(input_text)
            return {"success": True, "result": json.dumps(data, indent=2, ensure_ascii=False)}

        elif operation == "csv_to_json":
            import csv
            import io
            reader = csv.DictReader(io.StringIO(input_text))
            rows = list(reader)
            return {"success": True, "result": json.dumps(rows, indent=2, ensure_ascii=False)}

        elif operation == "json_to_csv":
            data = json.loads(input_text)
            if not isinstance(data, list) or not data:
                return {"success": False, "error": "Input must be a JSON array of objects"}
            import csv
            import io
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)
            return {"success": True, "result": output.getvalue()}

        elif operation == "markdown_to_html":
            return {"success": True, "result": _simple_md_to_html(input_text)}

        elif operation == "toml_to_json":
            data = _simple_toml_parse(input_text)
            return {"success": True, "result": json.dumps(data, indent=2, ensure_ascii=False)}

        else:
            return {"success": False, "error": f"Unknown operation: '{operation}'. Available: json_to_yaml, yaml_to_json, csv_to_json, json_to_csv, markdown_to_html, toml_to_json"}

    except json.JSONDecodeError as e:
        return {"success": False, "error": f"Invalid JSON: {e}"}
    except Exception as e:
        return {"success": False, "error": f"Conversion error: {e}"}


def _dict_to_yaml(data: Any, indent: int = 0) -> str:
    """Simple dict/list to YAML-like string (no external deps)."""
    prefix = "  " * indent
    if isinstance(data, dict):
        lines = []
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                lines.append(f"{prefix}{k}:")
                lines.append(_dict_to_yaml(v, indent + 1))
            else:
                lines.append(f"{prefix}{k}: {_yaml_value(v)}")
        return "\n".join(lines)
    elif isinstance(data, list):
        lines = []
        for item in data:
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}-")
                lines.append(_dict_to_yaml(item, indent + 1))
            else:
                lines.append(f"{prefix}- {_yaml_value(item)}")
        return "\n".join(lines)
    return f"{prefix}{_yaml_value(data)}"


def _yaml_value(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        if any(c in v for c in ":#{}[]|>&*!%@`"):
            return f'"{v}"'
        return v
    return str(v)


def _simple_yaml_parse(text: str) -> dict:
    """Very basic YAML parser for simple key: value structures."""
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            val = val.strip()
            if val.lower() == "true":
                result[key.strip()] = True
            elif val.lower() == "false":
                result[key.strip()] = False
            elif val.lower() == "null":
                result[key.strip()] = None
            else:
                try:
                    result[key.strip()] = int(val)
                except ValueError:
                    try:
                        result[key.strip()] = float(val)
                    except ValueError:
                        result[key.strip()] = val.strip("'\"")
    return result


def _simple_toml_parse(text: str) -> dict:
    """Very basic TOML parser for simple structures."""
    result = {}
    current_section = result
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            parts = section.split(".")
            current_section = result
            for part in parts:
                if part not in current_section:
                    current_section[part] = {}
                current_section = current_section[part]
        elif "=" in line:
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            if val.startswith('"') and val.endswith('"'):
                current_section[key] = val[1:-1]
            elif val.lower() == "true":
                current_section[key] = True
            elif val.lower() == "false":
                current_section[key] = False
            else:
                try:
                    current_section[key] = int(val)
                except ValueError:
                    try:
                        current_section[key] = float(val)
                    except ValueError:
                        current_section[key] = val
    return result


def _simple_md_to_html(md: str) -> str:
    """Basic markdown to HTML conversion."""
    html = md
    # Headers
    html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
    html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
    html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)
    # Bold/italic
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
    # Code
    html = re.sub(r'`(.+?)`', r'<code>\1</code>', html)
    # Links
    html = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', html)
    # Paragraphs
    html = re.sub(r'\n\n', r'</p><p>', html)
    return f"<p>{html}</p>"


# ---------------------------------------------------------------------------
# Number Base Conversion
# ---------------------------------------------------------------------------

def number_convert(value: str, from_base: str, to_base: str) -> dict[str, Any]:
    """Number base conversion.

    Bases: bin (binary), oct (octal), dec (decimal), hex (hexadecimal)
    """
    base_map = {"bin": 2, "binary": 2, "oct": 8, "octal": 8, "dec": 10, "decimal": 10, "hex": 16, "hexadecimal": 16}

    from_b = base_map.get(from_base.lower().strip())
    to_b = base_map.get(to_base.lower().strip())

    if from_b is None:
        return {"success": False, "error": f"Unknown base: '{from_base}'. Use: bin, oct, dec, hex"}
    if to_b is None:
        return {"success": False, "error": f"Unknown base: '{to_base}'. Use: bin, oct, dec, hex"}

    # Clean input
    clean = value.strip().lower()
    for prefix in ("0x", "0b", "0o"):
        if clean.startswith(prefix):
            clean = clean[2:]
            break

    try:
        decimal_val = int(clean, from_b)
    except ValueError:
        return {"success": False, "error": f"'{value}' is not a valid base-{from_b} number"}

    # Convert to target
    if to_b == 2:
        result = bin(decimal_val)
    elif to_b == 8:
        result = oct(decimal_val)
    elif to_b == 16:
        result = hex(decimal_val)
    else:
        result = str(decimal_val)

    return {"success": True, "result": f"{value} (base {from_b}) = {result} (base {to_b})"}
