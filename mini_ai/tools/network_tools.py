"""
network_tools.py – HTTP request tool and SQLite database tool.

Provides API interaction and local database capabilities without
requiring external dependencies beyond Python stdlib.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# HTTP Request Tool
# ---------------------------------------------------------------------------

def http_request(
    method: str,
    url: str,
    headers: dict[str, str] | None = None,
    body: str | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    """Make an HTTP request to an API endpoint.
    
    Supports GET, POST, PUT, PATCH, DELETE, HEAD methods.
    Returns status code, headers, and response body.
    """
    method = method.upper().strip()
    if method not in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
        return {"success": False, "error": f"Unsupported method: {method}"}
    
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    
    # Build request
    req_headers = {
        "User-Agent": "MiniAI/1.0",
        "Accept": "application/json, text/plain, */*",
    }
    if headers:
        req_headers.update(headers)
    
    # Auto-set content-type for body
    if body and "Content-Type" not in req_headers and "content-type" not in req_headers:
        try:
            json.loads(body)
            req_headers["Content-Type"] = "application/json"
        except (json.JSONDecodeError, TypeError):
            req_headers["Content-Type"] = "text/plain"
    
    data = body.encode("utf-8") if body else None
    
    try:
        # SSL context
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            ctx = ssl.create_default_context()
        
        req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
        handler = urllib.request.HTTPSHandler(context=ctx)
        opener = urllib.request.build_opener(handler)
        
        with opener.open(req, timeout=timeout) as resp:
            status = resp.status
            resp_headers = dict(resp.headers)
            resp_body = resp.read().decode("utf-8", errors="replace")
            
            # Try to pretty-print JSON responses
            content_type = resp_headers.get("Content-Type", "")
            if "json" in content_type:
                try:
                    parsed = json.loads(resp_body)
                    resp_body = json.dumps(parsed, indent=2, ensure_ascii=False)
                except json.JSONDecodeError:
                    pass
            
            # Truncate very large responses
            if len(resp_body) > 10000:
                resp_body = resp_body[:10000] + "\n...[truncated]"
            
            result_lines = [
                f"HTTP {status} {method} {url}",
                f"Content-Type: {content_type}",
                f"Content-Length: {resp_headers.get('Content-Length', 'unknown')}",
                "",
                resp_body,
            ]
            
            return {
                "success": True,
                "result": "\n".join(result_lines),
                "status": status,
                "headers": resp_headers,
            }
    
    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode("utf-8", errors="replace")[:2000]
        except Exception:
            pass
        return {
            "success": False,
            "error": f"HTTP {e.code}: {e.reason}\n{error_body}",
            "status": e.code,
        }
    except urllib.error.URLError as e:
        return {"success": False, "error": f"Connection error: {e.reason}"}
    except Exception as e:
        return {"success": False, "error": f"Request failed: {e}"}


# ---------------------------------------------------------------------------
# SQLite Database Tool
# ---------------------------------------------------------------------------

# Safety: max rows returned, max query time
_MAX_ROWS = 100
_MAX_QUERY_TIME = 10  # seconds

# Blocked operations for safety
_BLOCKED_PATTERNS = [
    r"ATTACH\s+DATABASE",
    r"LOAD_EXTENSION",
    r"PRAGMA\s+(?!table_info|database_list|index_list)",
]


def sqlite_query(
    database: str,
    query: str,
    params: list | None = None,
) -> dict[str, Any]:
    """Execute SQL queries on SQLite databases.
    
    Supports SELECT, INSERT, UPDATE, DELETE, CREATE TABLE, and schema inspection.
    Uses parameterized queries for safety.
    """
    # Safety checks
    query_upper = query.strip().upper()
    for pattern in _BLOCKED_PATTERNS:
        if re.search(pattern, query_upper):
            return {"success": False, "error": f"Blocked operation for safety"}
    
    db_path = Path(database)
    
    # Auto-create parent directory for new databases
    if not db_path.exists():
        db_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        conn = sqlite3.connect(str(db_path), timeout=_MAX_QUERY_TIME)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Execute with parameters if provided
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        
        # Determine query type
        is_select = query_upper.startswith(("SELECT", "PRAGMA", "EXPLAIN"))
        
        if is_select:
            rows = cursor.fetchmany(_MAX_ROWS)
            if not rows:
                conn.close()
                return {"success": True, "result": "Query returned 0 rows"}
            
            # Get column names
            columns = [desc[0] for desc in cursor.description]
            
            # Format as table
            result_rows = []
            for row in rows:
                result_rows.append(dict(row))
            
            # Build readable output
            output = _format_sql_results(columns, result_rows)
            
            total = cursor.fetchone()
            has_more = total is not None
            
            conn.close()
            return {
                "success": True,
                "result": output,
                "columns": columns,
                "row_count": len(result_rows),
                "has_more": has_more,
            }
        else:
            # DML/DDL statement
            affected = cursor.rowcount
            conn.commit()
            conn.close()
            
            action = query_upper.split()[0] if query_upper else "UNKNOWN"
            return {
                "success": True,
                "result": f"{action} executed successfully. Rows affected: {affected}",
                "rows_affected": affected,
            }
    
    except sqlite3.Error as e:
        return {"success": False, "error": f"SQLite error: {e}"}
    except Exception as e:
        return {"success": False, "error": f"Database error: {e}"}


def _format_sql_results(columns: list[str], rows: list[dict]) -> str:
    """Format SQL results as a readable table."""
    if not rows:
        return "(no results)"
    
    # Calculate column widths
    col_widths = {}
    for col in columns:
        max_val = max(len(str(row.get(col, ""))[:40]) for row in rows)
        col_widths[col] = min(max(len(col), max_val), 40)
    
    # Header
    header = " | ".join(col.ljust(col_widths[col])[:40] for col in columns)
    sep = "-+-".join("-" * col_widths[col] for col in columns)
    
    lines = [header, sep]
    for row in rows:
        line = " | ".join(str(row.get(col, "")).ljust(col_widths[col])[:40] for col in columns)
        lines.append(line)
    
    lines.append(f"\n({len(rows)} row{'s' if len(rows) != 1 else ''})")
    return "\n".join(lines)
