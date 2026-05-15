"""
code_analysis_tools.py – Code analysis and inspection tools.

Covers: line counting, TODO/FIXME finding, dependency analysis, duplicate detection,
complexity estimation, symbol extraction, import analysis, dead code detection.
"""
from __future__ import annotations

import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


# Common code file extensions
_CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h", ".hpp",
    ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".scala", ".lua",
    ".r", ".m", ".mm", ".dart", ".vue", ".svelte", ".html", ".css", ".scss",
    ".sass", ".less", ".sql", ".sh", ".bash", ".ps1", ".bat", ".cmd",
}


def count_lines(path: str, include_blank: bool = True, by_extension: bool = False) -> dict[str, Any]:
    """Count lines of code in a file or directory.
    
    Returns total lines, code lines, blank lines, comment lines.
    If by_extension=True, breaks down by file type.
    """
    target = Path(path)
    if not target.exists():
        return {"success": False, "error": f"Path not found: {path}"}
    
    stats = {"total": 0, "code": 0, "blank": 0, "comment": 0, "files": 0}
    by_ext: dict[str, dict[str, int]] = {}
    
    files = [target] if target.is_file() else _collect_code_files(target)
    
    for f in files:
        ext = f.suffix.lower()
        if ext not in _CODE_EXTENSIONS and target.is_dir():
            continue
        
        try:
            lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue
        
        stats["files"] += 1
        file_stats = {"total": 0, "code": 0, "blank": 0, "comment": 0}
        
        comment_chars = _get_comment_chars(ext)
        in_block_comment = False
        
        for line in lines:
            stripped = line.strip()
            file_stats["total"] += 1
            
            if not stripped:
                file_stats["blank"] += 1
            elif in_block_comment:
                file_stats["comment"] += 1
                if "*/" in stripped or '"""' in stripped or "'''" in stripped:
                    in_block_comment = False
            elif stripped.startswith(("/*", '"""', "'''")):
                file_stats["comment"] += 1
                if not (stripped.endswith("*/") or stripped.count('"""') >= 2 or stripped.count("'''") >= 2):
                    in_block_comment = True
            elif any(stripped.startswith(c) for c in comment_chars):
                file_stats["comment"] += 1
            else:
                file_stats["code"] += 1
        
        for k in ("total", "code", "blank", "comment"):
            stats[k] += file_stats[k]
        
        if by_extension:
            if ext not in by_ext:
                by_ext[ext] = {"total": 0, "code": 0, "files": 0}
            by_ext[ext]["total"] += file_stats["total"]
            by_ext[ext]["code"] += file_stats["code"]
            by_ext[ext]["files"] += 1
    
    result_lines = [
        f"Files: {stats['files']}",
        f"Total lines: {stats['total']}",
        f"Code lines: {stats['code']}",
        f"Blank lines: {stats['blank']}",
        f"Comment lines: {stats['comment']}",
    ]
    
    if by_extension and by_ext:
        result_lines.append("\nBy extension:")
        for ext, es in sorted(by_ext.items(), key=lambda x: x[1]["code"], reverse=True):
            result_lines.append(f"  {ext}: {es['code']} code lines ({es['files']} files)")
    
    return {"success": True, "result": "\n".join(result_lines)}


def find_todos(path: str, include_fixme: bool = True) -> dict[str, Any]:
    """Find TODO, FIXME, HACK, XXX comments in code files."""
    target = Path(path)
    if not target.exists():
        return {"success": False, "error": f"Path not found: {path}"}
    
    patterns = [r"\bTODO\b", r"\bHACK\b", r"\bXXX\b"]
    if include_fixme:
        patterns.append(r"\bFIXME\b")
    
    combined = re.compile("|".join(patterns), re.IGNORECASE)
    
    files = [target] if target.is_file() else _collect_code_files(target)
    findings: list[str] = []
    
    for f in files:
        try:
            lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue
        
        for i, line in enumerate(lines, 1):
            if combined.search(line):
                rel = f.relative_to(target) if target.is_dir() else f.name
                findings.append(f"  {rel}:{i}: {line.strip()}")
    
    if not findings:
        return {"success": True, "result": "No TODOs/FIXMEs found"}
    
    return {"success": True, "result": f"Found {len(findings)} items:\n" + "\n".join(findings[:100])}


def find_duplicates(path: str, min_lines: int = 5) -> dict[str, Any]:
    """Find duplicate code blocks (potential copy-paste)."""
    target = Path(path)
    if not target.exists():
        return {"success": False, "error": f"Path not found: {path}"}
    
    files = [target] if target.is_file() else _collect_code_files(target)
    
    # Hash blocks of min_lines consecutive non-blank lines
    block_hashes: dict[str, list[tuple[str, int]]] = defaultdict(list)
    
    for f in files:
        try:
            lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue
        
        # Sliding window of non-blank lines
        non_blank = [(i, l.strip()) for i, l in enumerate(lines, 1) if l.strip()]
        
        for idx in range(len(non_blank) - min_lines + 1):
            block = "\n".join(l for _, l in non_blank[idx:idx + min_lines])
            rel = str(f.relative_to(target)) if target.is_dir() else f.name
            block_hashes[block].append((rel, non_blank[idx][0]))
    
    # Find duplicates
    duplicates = [(block, locs) for block, locs in block_hashes.items() if len(locs) > 1]
    duplicates.sort(key=lambda x: len(x[1]), reverse=True)
    
    if not duplicates:
        return {"success": True, "result": "No duplicate code blocks found"}
    
    result_lines = [f"Found {len(duplicates)} duplicate blocks:"]
    for block, locs in duplicates[:20]:
        preview = block.split("\n")[0][:60]
        locations = ", ".join(f"{f}:{ln}" for f, ln in locs[:5])
        result_lines.append(f"  [{len(locs)}x] \"{preview}...\" at {locations}")
    
    return {"success": True, "result": "\n".join(result_lines)}


def analyze_imports(path: str) -> dict[str, Any]:
    """Analyze imports/dependencies in a file or project."""
    target = Path(path)
    if not target.exists():
        return {"success": False, "error": f"Path not found: {path}"}
    
    files = [target] if target.is_file() else _collect_code_files(target)
    
    imports: dict[str, list[str]] = defaultdict(list)
    stdlib_imports: set[str] = set()
    third_party: set[str] = set()
    local_imports: set[str] = set()
    
    for f in files:
        ext = f.suffix.lower()
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        
        rel = str(f.relative_to(target)) if target.is_dir() else f.name
        
        if ext == ".py":
            for m in re.finditer(r"^(?:from\s+([\w.]+)\s+)?import\s+([\w., ]+)", content, re.MULTILINE):
                module = m.group(1) or m.group(2).split(",")[0].strip()
                imports[module].append(rel)
                if module.startswith("."):
                    local_imports.add(module)
                else:
                    top = module.split(".")[0]
                    third_party.add(top)
        elif ext in (".js", ".ts", ".jsx", ".tsx"):
            for m in re.finditer(r"(?:import|require)\s*\(?['\"]([^'\"]+)['\"]", content):
                module = m.group(1)
                imports[module].append(rel)
                if module.startswith("."):
                    local_imports.add(module)
                else:
                    third_party.add(module.split("/")[0])
        elif ext == ".go":
            for m in re.finditer(r'"([^"]+)"', content):
                module = m.group(1)
                if "/" in module:
                    imports[module].append(rel)
                    third_party.add(module.split("/")[0])
    
    # Build summary
    result_lines = [
        f"Files analyzed: {len(files)}",
        f"Unique imports: {len(imports)}",
        f"Third-party packages: {len(third_party)}",
        f"Local/relative imports: {len(local_imports)}",
    ]
    
    if third_party:
        result_lines.append("\nThird-party dependencies:")
        for pkg in sorted(third_party)[:30]:
            result_lines.append(f"  - {pkg}")
    
    # Most imported modules
    top_imports = sorted(imports.items(), key=lambda x: len(x[1]), reverse=True)[:15]
    if top_imports:
        result_lines.append("\nMost imported:")
        for mod, files_list in top_imports:
            result_lines.append(f"  {mod} ({len(files_list)} files)")
    
    return {"success": True, "result": "\n".join(result_lines)}


def find_symbols(path: str, symbol_type: str = "all") -> dict[str, Any]:
    """Extract function/class/variable definitions from code.
    
    symbol_type: all, functions, classes, variables, exports
    """
    target = Path(path)
    if not target.exists():
        return {"success": False, "error": f"Path not found: {path}"}
    
    files = [target] if target.is_file() else _collect_code_files(target)
    symbols: list[str] = []
    
    for f in files:
        ext = f.suffix.lower()
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        
        rel = str(f.relative_to(target)) if target.is_dir() else f.name
        file_symbols = _extract_symbols(content, ext, symbol_type)
        
        for sym in file_symbols:
            symbols.append(f"  {rel}: {sym}")
    
    if not symbols:
        return {"success": True, "result": "No symbols found"}
    
    return {"success": True, "result": f"Found {len(symbols)} symbols:\n" + "\n".join(symbols[:100])}


def code_complexity(path: str) -> dict[str, Any]:
    """Estimate cyclomatic complexity of functions in a file."""
    target = Path(path)
    if not target.exists():
        return {"success": False, "error": f"Path not found: {path}"}
    
    if target.is_dir():
        return {"success": False, "error": "Please specify a single file for complexity analysis"}
    
    try:
        content = f.read_text(encoding="utf-8", errors="ignore") if (f := target) else ""
        content = target.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return {"success": False, "error": str(e)}
    
    ext = target.suffix.lower()
    
    # Count decision points per function
    decision_keywords = {
        ".py": [r"\bif\b", r"\belif\b", r"\bfor\b", r"\bwhile\b", r"\band\b", r"\bor\b", r"\bexcept\b"],
        ".js": [r"\bif\b", r"\belse\s+if\b", r"\bfor\b", r"\bwhile\b", r"\b&&\b", r"\b\|\|\b", r"\bcatch\b", r"\bcase\b"],
        ".ts": [r"\bif\b", r"\belse\s+if\b", r"\bfor\b", r"\bwhile\b", r"\b&&\b", r"\b\|\|\b", r"\bcatch\b", r"\bcase\b"],
    }
    
    keywords = decision_keywords.get(ext, decision_keywords.get(".js", []))
    
    # Find functions and their complexity
    if ext == ".py":
        func_pattern = re.compile(r"^([ \t]*)(?:def|async\s+def)\s+(\w+)", re.MULTILINE)
    else:
        func_pattern = re.compile(r"(?:function|const|let|var)\s+(\w+)|(\w+)\s*(?:=\s*)?(?:\([^)]*\)\s*(?:=>|{))", re.MULTILINE)
    
    lines = content.splitlines()
    functions: list[tuple[str, int]] = []
    
    if ext == ".py":
        # Python: use indentation to find function boundaries
        matches = list(func_pattern.finditer(content))
        for i, m in enumerate(matches):
            func_name = m.group(2)
            start_line = content[:m.start()].count("\n")
            indent = len(m.group(1))
            
            # Find end of function
            end_line = len(lines)
            for j in range(start_line + 1, len(lines)):
                stripped = lines[j]
                if stripped.strip() and not stripped.startswith(" " * (indent + 1)) and not stripped.strip().startswith("#"):
                    if not stripped[indent:indent+1] == " ":
                        end_line = j
                        break
            
            func_body = "\n".join(lines[start_line:end_line])
            complexity = 1  # Base complexity
            for kw in keywords:
                complexity += len(re.findall(kw, func_body))
            
            functions.append((func_name, complexity))
    else:
        # Simple heuristic for other languages
        total_complexity = 1
        for kw in keywords:
            total_complexity += len(re.findall(kw, content))
        functions.append(("(file)", total_complexity))
    
    # Sort by complexity
    functions.sort(key=lambda x: x[1], reverse=True)
    
    result_lines = ["Cyclomatic Complexity:"]
    for name, cx in functions[:30]:
        level = "LOW" if cx <= 5 else "MEDIUM" if cx <= 10 else "HIGH" if cx <= 20 else "VERY HIGH"
        result_lines.append(f"  {name}: {cx} ({level})")
    
    avg = sum(c for _, c in functions) / max(len(functions), 1)
    result_lines.append(f"\nAverage: {avg:.1f} | Functions: {len(functions)}")
    
    return {"success": True, "result": "\n".join(result_lines)}


def project_stats(path: str) -> dict[str, Any]:
    """Get comprehensive project statistics."""
    target = Path(path)
    if not target.exists():
        return {"success": False, "error": f"Path not found: {path}"}
    
    if not target.is_dir():
        return {"success": False, "error": "Path must be a directory"}
    
    ext_counts: Counter = Counter()
    total_size = 0
    total_files = 0
    largest_files: list[tuple[str, int]] = []
    
    for f in target.rglob("*"):
        if f.is_file():
            # Skip hidden/vendor dirs
            parts = f.relative_to(target).parts
            if any(p.startswith(".") or p in ("node_modules", "vendor", "__pycache__", "dist", "build", ".git") for p in parts):
                continue
            
            total_files += 1
            size = f.stat().st_size
            total_size += size
            ext_counts[f.suffix.lower() or "(no ext)"] += 1
            largest_files.append((str(f.relative_to(target)), size))
    
    largest_files.sort(key=lambda x: x[1], reverse=True)
    
    result_lines = [
        f"Project: {target.name}",
        f"Total files: {total_files}",
        f"Total size: {_human_size(total_size)}",
        f"\nFile types (top 15):",
    ]
    
    for ext, count in ext_counts.most_common(15):
        result_lines.append(f"  {ext}: {count} files")
    
    if largest_files:
        result_lines.append(f"\nLargest files:")
        for name, size in largest_files[:10]:
            result_lines.append(f"  {name}: {_human_size(size)}")
    
    return {"success": True, "result": "\n".join(result_lines)}


# --- Helpers ---

def _collect_code_files(directory: Path, max_files: int = 500) -> list[Path]:
    """Collect code files from a directory, skipping vendor/hidden dirs."""
    files = []
    skip_dirs = {".git", "node_modules", "vendor", "__pycache__", "dist", "build", ".venv", "venv", ".tox"}
    
    for f in directory.rglob("*"):
        if len(files) >= max_files:
            break
        if f.is_file() and f.suffix.lower() in _CODE_EXTENSIONS:
            if not any(p in skip_dirs for p in f.relative_to(directory).parts):
                files.append(f)
    return files


def _get_comment_chars(ext: str) -> list[str]:
    """Get single-line comment characters for a file extension."""
    mapping = {
        ".py": ["#"],
        ".rb": ["#"],
        ".sh": ["#"],
        ".bash": ["#"],
        ".r": ["#"],
        ".js": ["//"],
        ".ts": ["//"],
        ".jsx": ["//"],
        ".tsx": ["//"],
        ".java": ["//"],
        ".c": ["//"],
        ".cpp": ["//"],
        ".cs": ["//"],
        ".go": ["//"],
        ".rs": ["//"],
        ".swift": ["//"],
        ".kt": ["//"],
        ".dart": ["//"],
        ".php": ["//", "#"],
        ".lua": ["--"],
        ".sql": ["--"],
        ".html": ["<!--"],
        ".css": ["/*"],
    }
    return mapping.get(ext, ["//", "#"])


def _extract_symbols(content: str, ext: str, symbol_type: str) -> list[str]:
    """Extract symbols from code content."""
    symbols = []
    
    if ext == ".py":
        if symbol_type in ("all", "functions"):
            for m in re.finditer(r"^(?:[ \t]*)(?:async\s+)?def\s+(\w+)", content, re.MULTILINE):
                symbols.append(f"func {m.group(1)}")
        if symbol_type in ("all", "classes"):
            for m in re.finditer(r"^class\s+(\w+)", content, re.MULTILINE):
                symbols.append(f"class {m.group(1)}")
    elif ext in (".js", ".ts", ".jsx", ".tsx"):
        if symbol_type in ("all", "functions"):
            for m in re.finditer(r"(?:function|const|let|var)\s+(\w+)\s*(?:=\s*(?:async\s*)?\(|[\(])", content):
                symbols.append(f"func {m.group(1)}")
        if symbol_type in ("all", "classes"):
            for m in re.finditer(r"class\s+(\w+)", content):
                symbols.append(f"class {m.group(1)}")
        if symbol_type in ("all", "exports"):
            for m in re.finditer(r"export\s+(?:default\s+)?(?:function|class|const|let|var)\s+(\w+)", content):
                symbols.append(f"export {m.group(1)}")
    elif ext in (".java", ".cs", ".kt"):
        if symbol_type in ("all", "classes"):
            for m in re.finditer(r"(?:public|private|protected)?\s*(?:abstract|static)?\s*class\s+(\w+)", content):
                symbols.append(f"class {m.group(1)}")
        if symbol_type in ("all", "functions"):
            for m in re.finditer(r"(?:public|private|protected)\s+\w+\s+(\w+)\s*\(", content):
                symbols.append(f"method {m.group(1)}")
    
    return symbols


def _human_size(size: int) -> str:
    """Convert bytes to human-readable size."""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
