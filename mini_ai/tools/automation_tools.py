"""
automation_tools.py - YouTube downloader, PDF summarizer, image resizer,
auto-backup, daily digest, project stats, dependency auditor, docker helper,
auto-commit, and cron scheduler.

Pure-Python implementations with optional dependency fallbacks.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# YouTube Downloader
# ---------------------------------------------------------------------------

def youtube_download(url: str, output_dir: str = "", format: str = "mp4",
                    quality: str = "best") -> dict[str, Any]:
    """Download YouTube video/audio using yt-dlp.

    Args:
        url: YouTube URL or search query
        output_dir: Output directory (default: ~/Downloads)
        format: 'mp4', 'mp3', 'webm', 'audio'
        quality: 'best', '720', '480', '360', 'worst'
    """
    if not url:
        return {"success": False, "error": "No URL provided"}

    # Check for yt-dlp
    ytdlp = shutil.which("yt-dlp")
    if not ytdlp:
        return {"success": False, "error": "yt-dlp not installed. Install with: pip install yt-dlp"}

    # Resolve output directory
    if not output_dir:
        output_dir = str(Path.home() / "Downloads")
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # Build command
    cmd = [ytdlp, "--no-playlist", "--no-warnings"]

    if format in ("mp3", "audio"):
        cmd += ["-x", "--audio-format", "mp3", "--audio-quality", "0"]
    elif format == "webm":
        cmd += ["-f", "bestvideo[ext=webm]+bestaudio[ext=webm]/best[ext=webm]"]
    else:
        quality_map = {"best": "bestvideo+bestaudio/best",
                       "720": "bestvideo[height<=720]+bestaudio/best[height<=720]",
                       "480": "bestvideo[height<=480]+bestaudio/best[height<=480]",
                       "360": "bestvideo[height<=360]+bestaudio/best[height<=360]",
                       "worst": "worstvideo+worstaudio/worst"}
        fmt_str = quality_map.get(quality, quality_map["best"])
        cmd += ["-f", fmt_str]

    cmd += ["-o", str(out_path / "%(title)s.%(ext)s"), url]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        output = (result.stdout + result.stderr).strip()
        if result.returncode == 0:
            # Extract filename from output
            dest_match = re.search(r'\[download\] Destination: (.+)', output)
            merge_match = re.search(r'\[Merger\] Merging formats into "(.+)"', output)
            already_match = re.search(r'\[download\] (.+) has already been downloaded', output)
            filename = (merge_match or dest_match or already_match)
            fname = filename.group(1) if filename else "unknown"
            return {"success": True, "result": f"Downloaded: {fname}"}
        return {"success": False, "error": output[:500]}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Download timed out (5 min limit)"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# PDF Summarizer
# ---------------------------------------------------------------------------

def pdf_summarize(file_path: str, max_pages: int = 20,
                  mode: str = "extract") -> dict[str, Any]:
    """Extract text from PDF and provide summary/stats.

    Args:
        file_path: Path to PDF file
        max_pages: Maximum pages to process
        mode: 'extract' (full text), 'summary' (key stats), 'outline' (headings)
    """
    path = Path(file_path)
    if not path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}
    if not path.suffix.lower() == ".pdf":
        return {"success": False, "error": "Not a PDF file"}

    # Try PyPDF2 first, then pdfplumber, then fallback
    text = ""
    page_count = 0

    try:
        import PyPDF2
        with open(path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            page_count = len(reader.pages)
            pages_to_read = min(page_count, max_pages)
            for i in range(pages_to_read):
                page_text = reader.pages[i].extract_text() or ""
                text += f"\n--- Page {i+1} ---\n{page_text}"
    except ImportError:
        try:
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                page_count = len(pdf.pages)
                pages_to_read = min(page_count, max_pages)
                for i in range(pages_to_read):
                    page_text = pdf.pages[i].extract_text() or ""
                    text += f"\n--- Page {i+1} ---\n{page_text}"
        except ImportError:
            return {"success": False,
                    "error": "No PDF library available. Install: pip install PyPDF2 or pip install pdfplumber"}

    if not text.strip():
        return {"success": False, "error": "Could not extract text (may be scanned/image PDF)"}

    mode = mode.lower().strip()

    if mode == "extract":
        # Return full text (truncated)
        if len(text) > 8000:
            text = text[:8000] + f"\n\n...[truncated, {len(text)} chars total]"
        return {"success": True, "result": text}

    elif mode == "summary":
        words = text.split()
        sentences = re.split(r'[.!?]+', text)
        paragraphs = [p for p in text.split("\n\n") if p.strip()]
        summary = (
            f"PDF: {path.name}\n"
            f"Pages: {page_count} (read {min(page_count, max_pages)})\n"
            f"Words: ~{len(words):,}\n"
            f"Sentences: ~{len(sentences):,}\n"
            f"Paragraphs: ~{len(paragraphs):,}\n"
            f"Characters: {len(text):,}\n"
            f"\nFirst 500 chars:\n{text[:500]}"
        )
        return {"success": True, "result": summary}

    elif mode == "outline":
        # Extract lines that look like headings (short, capitalized, etc.)
        lines = text.splitlines()
        headings = []
        for line in lines:
            line = line.strip()
            if not line or len(line) > 100:
                continue
            if (line.isupper() or
                re.match(r'^\d+[\.\)]\s+', line) or
                re.match(r'^(Chapter|Section|Part)\s+', line, re.I) or
                (len(line) < 60 and line[0].isupper() and not line.endswith(('.', ',', ';')))):
                headings.append(line)
        if not headings:
            return {"success": True, "result": "No clear headings detected in PDF"}
        return {"success": True, "result": "\n".join(headings[:50])}

    return {"success": False, "error": f"Unknown mode: {mode}. Use: extract, summary, outline"}


# ---------------------------------------------------------------------------
# Image Resizer
# ---------------------------------------------------------------------------

def image_resize(file_path: str, width: int = 0, height: int = 0,
                 scale: float = 0.0, output: str = "",
                 quality: int = 85) -> dict[str, Any]:
    """Resize an image file.

    Args:
        file_path: Path to image
        width: Target width (0 = auto from height)
        height: Target height (0 = auto from width)
        scale: Scale factor (e.g. 0.5 for half size)
        output: Output path (default: adds _resized suffix)
        quality: JPEG quality 1-100
    """
    path = Path(file_path)
    if not path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    valid_exts = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tiff"}
    if path.suffix.lower() not in valid_exts:
        return {"success": False, "error": f"Unsupported format: {path.suffix}"}

    try:
        from PIL import Image
    except ImportError:
        return {"success": False, "error": "Pillow not installed. Install with: pip install Pillow"}

    try:
        img = Image.open(path)
        orig_w, orig_h = img.size

        if scale > 0:
            new_w = int(orig_w * scale)
            new_h = int(orig_h * scale)
        elif width and height:
            new_w, new_h = width, height
        elif width:
            ratio = width / orig_w
            new_w = width
            new_h = int(orig_h * ratio)
        elif height:
            ratio = height / orig_h
            new_w = int(orig_w * ratio)
            new_h = height
        else:
            return {"success": False, "error": "Specify width, height, or scale"}

        resized = img.resize((new_w, new_h), Image.LANCZOS)

        if not output:
            output = str(path.parent / f"{path.stem}_resized{path.suffix}")

        out_path = Path(output)
        save_kwargs = {}
        if out_path.suffix.lower() in (".jpg", ".jpeg"):
            save_kwargs["quality"] = quality
            save_kwargs["optimize"] = True
        elif out_path.suffix.lower() == ".png":
            save_kwargs["optimize"] = True

        resized.save(out_path, **save_kwargs)

        result_size = out_path.stat().st_size
        return {"success": True, "result": (
            f"Resized: {orig_w}x{orig_h} → {new_w}x{new_h}\n"
            f"Saved: {out_path}\n"
            f"Size: {result_size / 1024:.1f} KB"
        )}
    except Exception as e:
        return {"success": False, "error": f"Resize failed: {e}"}


# ---------------------------------------------------------------------------
# Auto-Backup
# ---------------------------------------------------------------------------

def auto_backup(path: str, destination: str = "", mode: str = "snapshot",
                max_backups: int = 10) -> dict[str, Any]:
    """Create automatic backups of files or directories.

    Args:
        path: File or directory to backup
        destination: Backup destination (default: .backups/ in same parent)
        mode: 'snapshot' (timestamped copy), 'incremental' (only changed), 'list' (show backups)
        max_backups: Maximum number of backups to keep (oldest pruned)
    """
    source = Path(path)
    if mode != "list" and not source.exists():
        return {"success": False, "error": f"Source not found: {path}"}

    if not destination:
        destination = str(source.parent / ".backups")
    backup_dir = Path(destination)
    backup_dir.mkdir(parents=True, exist_ok=True)

    mode = mode.lower().strip()

    if mode == "list":
        backups = sorted(backup_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        if not backups:
            return {"success": True, "result": "No backups found"}
        lines = [f"Backups in {backup_dir}:"]
        for b in backups[:20]:
            mtime = datetime.fromtimestamp(b.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            size = b.stat().st_size if b.is_file() else sum(f.stat().st_size for f in b.rglob("*") if f.is_file())
            lines.append(f"  {b.name} ({size/1024:.1f} KB) - {mtime}")
        return {"success": True, "result": "\n".join(lines)}

    elif mode == "snapshot":
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if source.is_file():
            backup_name = f"{source.stem}_{timestamp}{source.suffix}"
            dest = backup_dir / backup_name
            shutil.copy2(source, dest)
        else:
            backup_name = f"{source.name}_{timestamp}"
            dest = backup_dir / backup_name
            shutil.copytree(source, dest, dirs_exist_ok=True)

        # Prune old backups
        _prune_backups(backup_dir, source.name, max_backups)

        return {"success": True, "result": f"Backup created: {dest}"}

    elif mode == "incremental":
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{source.name}_inc_{timestamp}"
        dest = backup_dir / backup_name
        dest.mkdir(parents=True, exist_ok=True)

        copied = 0
        if source.is_file():
            shutil.copy2(source, dest / source.name)
            copied = 1
        else:
            for f in source.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(source)
                    backup_file = dest / rel
                    # Check if file changed (compare hash)
                    existing_backups = list(backup_dir.glob(f"*/{rel}"))
                    if existing_backups:
                        latest = max(existing_backups, key=lambda p: p.stat().st_mtime)
                        if _file_hash(f) == _file_hash(latest):
                            continue
                    backup_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, backup_file)
                    copied += 1

        if copied == 0:
            shutil.rmtree(dest, ignore_errors=True)
            return {"success": True, "result": "No changes detected, no backup needed"}

        _prune_backups(backup_dir, source.name, max_backups)
        return {"success": True, "result": f"Incremental backup: {copied} files → {dest}"}

    return {"success": False, "error": f"Unknown mode: {mode}. Use: snapshot, incremental, list"}


def _file_hash(path: Path) -> str:
    """Quick MD5 hash of a file."""
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
    except Exception:
        return ""
    return h.hexdigest()


def _prune_backups(backup_dir: Path, prefix: str, max_keep: int) -> None:
    """Remove oldest backups exceeding max_keep."""
    items = sorted(
        [p for p in backup_dir.iterdir() if p.name.startswith(prefix.split(".")[0])],
        key=lambda p: p.stat().st_mtime
    )
    while len(items) > max_keep:
        old = items.pop(0)
        if old.is_file():
            old.unlink()
        else:
            shutil.rmtree(old, ignore_errors=True)


# ---------------------------------------------------------------------------
# Daily Digest
# ---------------------------------------------------------------------------

def daily_digest(path: str = "", scope: str = "today") -> dict[str, Any]:
    """Generate a daily digest of activity: git commits, file changes, notes.

    Args:
        path: Project path (default: current directory)
        scope: 'today', 'yesterday', 'week'
    """
    project = Path(path) if path else Path.cwd()
    if not project.exists():
        project = Path.cwd()

    scope = scope.lower().strip()
    now = datetime.now()

    if scope == "yesterday":
        since = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0)
        until = now.replace(hour=0, minute=0, second=0)
    elif scope == "week":
        since = (now - timedelta(days=7)).replace(hour=0, minute=0, second=0)
        until = now
    else:  # today
        since = now.replace(hour=0, minute=0, second=0)
        until = now

    digest_parts = [f"📋 Daily Digest ({scope.title()}) - {now.strftime('%B %d, %Y')}"]
    digest_parts.append("=" * 50)

    # Git activity
    if shutil.which("git") and (project / ".git").exists():
        since_str = since.strftime("%Y-%m-%d %H:%M")
        try:
            result = subprocess.run(
                ["git", "log", f"--since={since_str}", "--oneline", "--no-merges"],
                cwd=str(project), capture_output=True, text=True, timeout=10
            )
            commits = result.stdout.strip().splitlines()
            if commits:
                digest_parts.append(f"\n🔀 Git Commits ({len(commits)}):")
                for c in commits[:15]:
                    digest_parts.append(f"  • {c}")
        except Exception:
            pass

        # Files changed
        try:
            result = subprocess.run(
                ["git", "diff", "--stat", f"--since={since_str}", "HEAD"],
                cwd=str(project), capture_output=True, text=True, timeout=10
            )
            if result.stdout.strip():
                digest_parts.append(f"\n📁 Files Changed:")
                digest_parts.append(f"  {result.stdout.strip().splitlines()[-1] if result.stdout.strip() else 'none'}")
        except Exception:
            pass

    # Recently modified files
    recent_files = []
    try:
        for f in project.rglob("*"):
            if f.is_file() and not any(p in str(f) for p in [".git", "__pycache__", "node_modules", ".venv"]):
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                if since <= mtime <= until:
                    recent_files.append((f, mtime))
    except Exception:
        pass

    if recent_files:
        recent_files.sort(key=lambda x: x[1], reverse=True)
        digest_parts.append(f"\n📝 Recently Modified ({len(recent_files)} files):")
        for f, mt in recent_files[:10]:
            try:
                rel = f.relative_to(project)
            except ValueError:
                rel = f.name
            digest_parts.append(f"  • {rel} ({mt.strftime('%H:%M')})")

    # Notes from today
    notes_dir = Path.home() / ".mini_ai" / "notes"
    if notes_dir.exists():
        today_notes = []
        for note_file in notes_dir.glob("*.md"):
            try:
                mtime = datetime.fromtimestamp(note_file.stat().st_mtime)
                if since <= mtime <= until:
                    today_notes.append(note_file.stem)
            except Exception:
                pass
        if today_notes:
            digest_parts.append(f"\n📌 Notes ({len(today_notes)}):")
            for n in today_notes[:5]:
                digest_parts.append(f"  • {n}")

    if len(digest_parts) <= 2:
        digest_parts.append("\n(No activity detected for this period)")

    return {"success": True, "result": "\n".join(digest_parts)}


# ---------------------------------------------------------------------------
# Project Stats
# ---------------------------------------------------------------------------

def project_stats(path: str = "") -> dict[str, Any]:
    """Analyze project statistics: LOC, file types, size, complexity.

    Args:
        path: Project root path
    """
    project = Path(path) if path else Path.cwd()
    if not project.exists():
        return {"success": False, "error": f"Path not found: {path}"}

    skip_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv",
                 ".tox", "dist", "build", ".eggs", ".hypothesis", ".mypy_cache"}

    stats = {
        "total_files": 0,
        "total_dirs": 0,
        "total_size": 0,
        "by_extension": {},
        "largest_files": [],
        "loc_by_type": {},
    }

    code_extensions = {".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp",
                       ".h", ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt",
                       ".dart", ".vue", ".svelte", ".html", ".css", ".scss", ".sql"}

    try:
        for item in project.rglob("*"):
            # Skip excluded directories
            if any(skip in item.parts for skip in skip_dirs):
                continue

            if item.is_dir():
                stats["total_dirs"] += 1
                continue

            if item.is_file():
                stats["total_files"] += 1
                size = item.stat().st_size
                stats["total_size"] += size
                ext = item.suffix.lower() or "(no ext)"

                if ext not in stats["by_extension"]:
                    stats["by_extension"][ext] = {"count": 0, "size": 0}
                stats["by_extension"][ext]["count"] += 1
                stats["by_extension"][ext]["size"] += size

                stats["largest_files"].append((str(item.relative_to(project)), size))

                # Count lines for code files
                if ext in code_extensions:
                    try:
                        lines = item.read_text(encoding="utf-8", errors="ignore").splitlines()
                        code_lines = len([l for l in lines if l.strip() and not l.strip().startswith(("#", "//", "/*", "*"))])
                        if ext not in stats["loc_by_type"]:
                            stats["loc_by_type"][ext] = {"files": 0, "lines": 0, "code_lines": 0}
                        stats["loc_by_type"][ext]["files"] += 1
                        stats["loc_by_type"][ext]["lines"] += len(lines)
                        stats["loc_by_type"][ext]["code_lines"] += code_lines
                    except Exception:
                        pass
    except Exception as e:
        return {"success": False, "error": f"Scan error: {e}"}

    # Format output
    lines = [f"📊 Project Stats: {project.name}", "=" * 50]
    lines.append(f"Files: {stats['total_files']:,}  |  Dirs: {stats['total_dirs']:,}  |  Size: {stats['total_size']/1024/1024:.1f} MB")

    # Top extensions
    sorted_exts = sorted(stats["by_extension"].items(), key=lambda x: x[1]["count"], reverse=True)
    lines.append(f"\n📁 File Types (top 10):")
    for ext, info in sorted_exts[:10]:
        lines.append(f"  {ext:12s} {info['count']:5d} files  ({info['size']/1024:.0f} KB)")

    # LOC stats
    if stats["loc_by_type"]:
        total_loc = sum(v["code_lines"] for v in stats["loc_by_type"].values())
        total_lines = sum(v["lines"] for v in stats["loc_by_type"].values())
        lines.append(f"\n💻 Code Stats:")
        lines.append(f"  Total lines: {total_lines:,}  |  Code lines: {total_loc:,}")
        sorted_loc = sorted(stats["loc_by_type"].items(), key=lambda x: x[1]["code_lines"], reverse=True)
        for ext, info in sorted_loc[:8]:
            lines.append(f"  {ext:8s} {info['files']:4d} files  {info['code_lines']:6,} LOC")

    # Largest files
    stats["largest_files"].sort(key=lambda x: x[1], reverse=True)
    lines.append(f"\n📦 Largest Files:")
    for fname, size in stats["largest_files"][:5]:
        lines.append(f"  {fname} ({size/1024:.1f} KB)")

    return {"success": True, "result": "\n".join(lines)}


# ---------------------------------------------------------------------------
# Dependency Auditor
# ---------------------------------------------------------------------------

def dependency_audit(path: str = "", fix: bool = False) -> dict[str, Any]:
    """Audit project dependencies for issues, outdated packages, vulnerabilities.

    Args:
        path: Project root path
        fix: Whether to attempt auto-fix (update lockfiles)
    """
    project = Path(path) if path else Path.cwd()
    if not project.exists():
        return {"success": False, "error": f"Path not found: {path}"}

    results = []
    issues = 0

    # Python: requirements.txt / pyproject.toml
    req_file = project / "requirements.txt"
    pyproject = project / "pyproject.toml"

    if req_file.exists():
        results.append("🐍 Python Dependencies (requirements.txt):")
        try:
            deps = [l.strip() for l in req_file.read_text().splitlines()
                    if l.strip() and not l.startswith("#")]
            results.append(f"  Packages: {len(deps)}")

            # Check for unpinned deps
            unpinned = [d for d in deps if "==" not in d and ">=" not in d and not d.startswith("-")]
            if unpinned:
                issues += len(unpinned)
                results.append(f"  ⚠️  Unpinned ({len(unpinned)}): {', '.join(unpinned[:5])}")

            # Try pip audit if available
            if shutil.which("pip"):
                try:
                    audit_result = subprocess.run(
                        ["pip", "audit", "--format", "json"],
                        cwd=str(project), capture_output=True, text=True, timeout=30
                    )
                    if audit_result.returncode == 0:
                        results.append("  ✅ No known vulnerabilities")
                    else:
                        vulns = audit_result.stdout.strip()
                        if vulns:
                            results.append(f"  🚨 Vulnerabilities found: {vulns[:200]}")
                            issues += 1
                except Exception:
                    pass

            # Check for outdated
            if shutil.which("pip") and not fix:
                try:
                    outdated = subprocess.run(
                        ["pip", "list", "--outdated", "--format", "json"],
                        capture_output=True, text=True, timeout=30
                    )
                    if outdated.returncode == 0:
                        pkgs = json.loads(outdated.stdout)
                        if pkgs:
                            results.append(f"  📦 Outdated ({len(pkgs)}):")
                            for p in pkgs[:5]:
                                results.append(f"    {p['name']}: {p['version']} → {p['latest_version']}")
                            issues += len(pkgs)
                except Exception:
                    pass
        except Exception as e:
            results.append(f"  Error reading: {e}")

    # Node.js: package.json
    pkg_json = project / "package.json"
    if pkg_json.exists():
        results.append("\n📦 Node.js Dependencies (package.json):")
        try:
            pkg = json.loads(pkg_json.read_text())
            deps_count = len(pkg.get("dependencies", {}))
            dev_count = len(pkg.get("devDependencies", {}))
            results.append(f"  Dependencies: {deps_count}  |  DevDependencies: {dev_count}")

            # Check for ^ or ~ (loose versioning)
            all_deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            loose = [k for k, v in all_deps.items() if isinstance(v, str) and (v.startswith("^") or v.startswith("~"))]
            if loose:
                results.append(f"  ⚠️  Loose versions ({len(loose)}): {', '.join(loose[:5])}")

            # npm audit
            if shutil.which("npm"):
                try:
                    audit = subprocess.run(
                        ["npm", "audit", "--json"],
                        cwd=str(project), capture_output=True, text=True, timeout=30
                    )
                    audit_data = json.loads(audit.stdout) if audit.stdout else {}
                    vuln_count = audit_data.get("metadata", {}).get("vulnerabilities", {})
                    total_vulns = sum(vuln_count.values()) if isinstance(vuln_count, dict) else 0
                    if total_vulns:
                        results.append(f"  🚨 Vulnerabilities: {total_vulns} ({vuln_count})")
                        issues += total_vulns
                    else:
                        results.append("  ✅ No known vulnerabilities")
                except Exception:
                    pass
        except Exception as e:
            results.append(f"  Error: {e}")

    # Cargo.toml (Rust)
    cargo = project / "Cargo.toml"
    if cargo.exists():
        results.append("\n🦀 Rust Dependencies (Cargo.toml):")
        try:
            content = cargo.read_text()
            dep_lines = re.findall(r'^(\w[\w-]*)\s*=', content, re.MULTILINE)
            results.append(f"  Packages: ~{len(dep_lines)}")
            if shutil.which("cargo"):
                try:
                    audit = subprocess.run(
                        ["cargo", "audit"], cwd=str(project),
                        capture_output=True, text=True, timeout=30
                    )
                    if "0 vulnerabilities" in audit.stdout:
                        results.append("  ✅ No known vulnerabilities")
                    elif audit.stdout.strip():
                        results.append(f"  🚨 {audit.stdout.strip()[:200]}")
                        issues += 1
                except Exception:
                    pass
        except Exception:
            pass

    if not results:
        return {"success": True, "result": "No dependency files found (requirements.txt, package.json, Cargo.toml)"}

    # Summary
    results.insert(0, f"🔍 Dependency Audit - {project.name}")
    results.insert(1, "=" * 50)
    results.append(f"\n{'⚠️' if issues else '✅'} Total issues: {issues}")

    return {"success": True, "result": "\n".join(results)}


# ---------------------------------------------------------------------------
# Docker Helper
# ---------------------------------------------------------------------------

def docker_helper(operation: str, target: str = "",
                  options: str = "") -> dict[str, Any]:
    """Enhanced Docker helper with compose, build, and management.

    Operations:
    - compose_up: Start docker-compose services
    - compose_down: Stop docker-compose services
    - compose_logs: View compose logs
    - compose_status: Show compose service status
    - build: Build image from Dockerfile
    - prune: Clean unused images/containers/volumes
    - stats: Show resource usage of running containers
    - inspect: Inspect container/image details
    - exec: Execute command in running container (target=container, options=command)
    - generate: Generate Dockerfile for a project type (target=type like python/node/go)
    """
    if not shutil.which("docker"):
        return {"success": False, "error": "Docker not installed or not in PATH"}

    operation = operation.lower().strip()

    if operation == "compose_up":
        compose_file = target or "docker-compose.yml"
        cmd = ["docker", "compose", "-f", compose_file, "up", "-d"]
        if options:
            cmd.extend(options.split())
        return _run_docker_cmd(cmd)

    elif operation == "compose_down":
        compose_file = target or "docker-compose.yml"
        cmd = ["docker", "compose", "-f", compose_file, "down"]
        if "volumes" in options or "-v" in options:
            cmd.append("-v")
        return _run_docker_cmd(cmd)

    elif operation == "compose_logs":
        compose_file = target or "docker-compose.yml"
        cmd = ["docker", "compose", "-f", compose_file, "logs", "--tail", "50"]
        return _run_docker_cmd(cmd)

    elif operation == "compose_status":
        compose_file = target or "docker-compose.yml"
        cmd = ["docker", "compose", "-f", compose_file, "ps"]
        return _run_docker_cmd(cmd)

    elif operation == "build":
        tag = target or "myapp:latest"
        cmd = ["docker", "build", "-t", tag, "."]
        if options:
            cmd = ["docker", "build", "-t", tag] + options.split() + ["."]
        return _run_docker_cmd(cmd, timeout=300)

    elif operation == "prune":
        results = []
        # Prune containers
        r1 = subprocess.run(["docker", "container", "prune", "-f"],
                           capture_output=True, text=True, timeout=30)
        results.append(f"Containers: {r1.stdout.strip()}")
        # Prune images
        r2 = subprocess.run(["docker", "image", "prune", "-f"],
                           capture_output=True, text=True, timeout=30)
        results.append(f"Images: {r2.stdout.strip()}")
        if "all" in options:
            r3 = subprocess.run(["docker", "volume", "prune", "-f"],
                               capture_output=True, text=True, timeout=30)
            results.append(f"Volumes: {r3.stdout.strip()}")
        return {"success": True, "result": "\n".join(results)}

    elif operation == "stats":
        cmd = ["docker", "stats", "--no-stream", "--format",
               "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}"]
        return _run_docker_cmd(cmd)

    elif operation == "inspect":
        if not target:
            return {"success": False, "error": "Specify container/image name to inspect"}
        cmd = ["docker", "inspect", "--format", "{{json .}}", target]
        result = _run_docker_cmd(cmd)
        if result["success"]:
            try:
                data = json.loads(result["result"])
                # Extract key info
                summary = {
                    "Id": data.get("Id", "")[:12],
                    "Created": data.get("Created", ""),
                    "State": data.get("State", {}),
                    "Image": data.get("Config", {}).get("Image", ""),
                    "Ports": data.get("NetworkSettings", {}).get("Ports", {}),
                }
                result["result"] = json.dumps(summary, indent=2)
            except Exception:
                pass
        return result

    elif operation == "exec":
        if not target:
            return {"success": False, "error": "Specify container name"}
        command = options or "sh"
        cmd = ["docker", "exec", target] + command.split()
        return _run_docker_cmd(cmd)

    elif operation == "generate":
        dockerfile = _generate_dockerfile(target or "python")
        return {"success": True, "result": dockerfile}

    return {"success": False, "error": f"Unknown operation: {operation}"}


def _run_docker_cmd(cmd: list[str], timeout: int = 60) -> dict[str, Any]:
    """Run a docker command and return result."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        output = (result.stdout + result.stderr).strip()
        if len(output) > 3000:
            output = output[:3000] + "\n...[truncated]"
        if result.returncode == 0:
            return {"success": True, "result": output or "(no output)"}
        return {"success": False, "error": output or f"Exit code: {result.returncode}"}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Command timed out ({timeout}s)"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _generate_dockerfile(project_type: str) -> str:
    """Generate a Dockerfile template for common project types."""
    templates = {
        "python": (
            "FROM python:3.11-slim\n"
            "WORKDIR /app\n"
            "COPY requirements.txt .\n"
            "RUN pip install --no-cache-dir -r requirements.txt\n"
            "COPY . .\n"
            "EXPOSE 8000\n"
            "CMD [\"python\", \"main.py\"]\n"
        ),
        "node": (
            "FROM node:20-alpine\n"
            "WORKDIR /app\n"
            "COPY package*.json ./\n"
            "RUN npm ci --only=production\n"
            "COPY . .\n"
            "EXPOSE 3000\n"
            "CMD [\"node\", \"index.js\"]\n"
        ),
        "go": (
            "FROM golang:1.22-alpine AS builder\n"
            "WORKDIR /app\n"
            "COPY go.* ./\n"
            "RUN go mod download\n"
            "COPY . .\n"
            "RUN CGO_ENABLED=0 go build -o /app/main .\n\n"
            "FROM alpine:latest\n"
            "COPY --from=builder /app/main /main\n"
            "EXPOSE 8080\n"
            "CMD [\"/main\"]\n"
        ),
        "rust": (
            "FROM rust:1.75 AS builder\n"
            "WORKDIR /app\n"
            "COPY Cargo.* ./\n"
            "RUN mkdir src && echo 'fn main(){}' > src/main.rs && cargo build --release && rm -rf src\n"
            "COPY . .\n"
            "RUN cargo build --release\n\n"
            "FROM debian:bookworm-slim\n"
            "COPY --from=builder /app/target/release/app /usr/local/bin/app\n"
            "CMD [\"app\"]\n"
        ),
    }
    return templates.get(project_type, templates["python"])


# ---------------------------------------------------------------------------
# Auto-Commit
# ---------------------------------------------------------------------------

def auto_commit(path: str = "", message: str = "",
                mode: str = "smart") -> dict[str, Any]:
    """Automatically commit changes with smart commit messages.

    Args:
        path: Repository path
        message: Custom commit message (if empty, auto-generates)
        mode: 'smart' (auto-message), 'all' (stage all + commit), 'staged' (commit staged only)
    """
    if not shutil.which("git"):
        return {"success": False, "error": "git not installed"}

    repo = Path(path) if path else Path.cwd()
    if not (repo / ".git").exists():
        return {"success": False, "error": f"Not a git repository: {repo}"}

    mode = mode.lower().strip()

    # Check for changes
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo), capture_output=True, text=True, timeout=10
    )
    changes = status.stdout.strip()
    if not changes:
        return {"success": True, "result": "No changes to commit"}

    # Stage files if mode is 'all' or 'smart'
    if mode in ("all", "smart"):
        subprocess.run(["git", "add", "-A"], cwd=str(repo), capture_output=True, timeout=10)

    # Generate commit message if not provided
    if not message:
        message = _generate_commit_message(repo)

    # Commit
    result = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=str(repo), capture_output=True, text=True, timeout=15
    )
    output = (result.stdout + result.stderr).strip()

    if result.returncode == 0:
        return {"success": True, "result": f"Committed: {message}\n{output}"}
    return {"success": False, "error": output}


def _generate_commit_message(repo: Path) -> str:
    """Generate a descriptive commit message from staged changes."""
    try:
        # Get diff stats
        diff = subprocess.run(
            ["git", "diff", "--cached", "--stat"],
            cwd=str(repo), capture_output=True, text=True, timeout=10
        )
        stat_lines = diff.stdout.strip().splitlines()

        # Get changed file names
        names = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=str(repo), capture_output=True, text=True, timeout=10
        )
        files = names.stdout.strip().splitlines()

        if not files:
            return "chore: update files"

        # Determine type from files
        extensions = set(Path(f).suffix for f in files)
        dirs = set(Path(f).parts[0] if len(Path(f).parts) > 1 else "" for f in files)

        # Smart prefix
        if all(f.endswith((".md", ".txt", ".rst")) for f in files):
            prefix = "docs"
        elif any("test" in f.lower() for f in files):
            prefix = "test"
        elif any(f in ("package.json", "requirements.txt", "Cargo.toml", "go.mod") for f in files):
            prefix = "deps"
        elif any(d in dirs for d in ("config", "configs", ".github")):
            prefix = "chore"
        elif len(files) == 1:
            prefix = "update"
        else:
            prefix = "feat"

        # Smart description
        if len(files) == 1:
            desc = f"update {files[0]}"
        elif len(files) <= 3:
            desc = f"update {', '.join(Path(f).name for f in files)}"
        else:
            desc = f"update {len(files)} files in {', '.join(d for d in dirs if d)[:50]}"

        return f"{prefix}: {desc}"
    except Exception:
        return f"chore: update {datetime.now().strftime('%Y-%m-%d %H:%M')}"


# ---------------------------------------------------------------------------
# Cron Scheduler
# ---------------------------------------------------------------------------

def cron_scheduler(operation: str, name: str = "", schedule: str = "",
                   command: str = "", path: str = "") -> dict[str, Any]:
    """Manage scheduled tasks (cron-like) stored in ~/.mini_ai/cron.json.

    Operations:
    - add: Add a new scheduled task
    - remove: Remove a task by name
    - list: List all scheduled tasks
    - run: Manually run a task by name
    - check: Check which tasks are due
    - clear: Remove all tasks

    Schedule format: 'every Xm/Xh/Xd' or 'daily HH:MM' or 'hourly'
    """
    cron_file = Path.home() / ".mini_ai" / "cron.json"
    cron_file.parent.mkdir(parents=True, exist_ok=True)

    # Load existing tasks
    tasks = []
    if cron_file.exists():
        try:
            tasks = json.loads(cron_file.read_text())
        except Exception:
            tasks = []

    operation = operation.lower().strip()

    if operation == "list":
        if not tasks:
            return {"success": True, "result": "No scheduled tasks"}
        lines = ["📅 Scheduled Tasks:"]
        for t in tasks:
            last_run = t.get("last_run", "never")
            lines.append(f"  • {t['name']} [{t['schedule']}] → {t['command'][:50]}")
            lines.append(f"    Last run: {last_run}")
        return {"success": True, "result": "\n".join(lines)}

    elif operation == "add":
        if not name or not schedule or not command:
            return {"success": False, "error": "Required: name, schedule, command"}
        # Validate schedule
        if not _parse_schedule(schedule):
            return {"success": False, "error": f"Invalid schedule: {schedule}. Use: 'every 5m', 'every 2h', 'daily 09:00', 'hourly'"}
        # Check for duplicate
        if any(t["name"] == name for t in tasks):
            return {"success": False, "error": f"Task '{name}' already exists. Remove it first."}
        tasks.append({
            "name": name,
            "schedule": schedule,
            "command": command,
            "path": path or str(Path.cwd()),
            "created": datetime.now().isoformat(),
            "last_run": None,
        })
        cron_file.write_text(json.dumps(tasks, indent=2))
        return {"success": True, "result": f"Added task: {name} [{schedule}] → {command}"}

    elif operation == "remove":
        if not name:
            return {"success": False, "error": "Specify task name to remove"}
        original_len = len(tasks)
        tasks = [t for t in tasks if t["name"] != name]
        if len(tasks) == original_len:
            return {"success": False, "error": f"Task '{name}' not found"}
        cron_file.write_text(json.dumps(tasks, indent=2))
        return {"success": True, "result": f"Removed task: {name}"}

    elif operation == "run":
        if not name:
            return {"success": False, "error": "Specify task name to run"}
        task = next((t for t in tasks if t["name"] == name), None)
        if not task:
            return {"success": False, "error": f"Task '{name}' not found"}
        # Execute the command
        try:
            result = subprocess.run(
                task["command"], shell=True,
                cwd=task.get("path", "."),
                capture_output=True, text=True, timeout=60
            )
            output = (result.stdout + result.stderr).strip()
            # Update last_run
            task["last_run"] = datetime.now().isoformat()
            cron_file.write_text(json.dumps(tasks, indent=2))
            if result.returncode == 0:
                return {"success": True, "result": f"Task '{name}' completed:\n{output[:1000]}"}
            return {"success": False, "error": f"Task '{name}' failed (exit {result.returncode}):\n{output[:500]}"}
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"Task '{name}' timed out (60s)"}
        except Exception as e:
            return {"success": False, "error": f"Task '{name}' error: {e}"}

    elif operation == "check":
        now = datetime.now()
        due_tasks = []
        for task in tasks:
            if _is_task_due(task, now):
                due_tasks.append(task["name"])
        if due_tasks:
            return {"success": True, "result": f"Due tasks: {', '.join(due_tasks)}"}
        return {"success": True, "result": "No tasks are currently due"}

    elif operation == "clear":
        cron_file.write_text("[]")
        return {"success": True, "result": "All scheduled tasks cleared"}

    return {"success": False, "error": f"Unknown operation: {operation}"}


def _parse_schedule(schedule: str) -> bool:
    """Validate a schedule string."""
    schedule = schedule.lower().strip()
    if schedule == "hourly":
        return True
    if schedule.startswith("daily "):
        time_part = schedule[6:].strip()
        return bool(re.match(r'^\d{1,2}:\d{2}$', time_part))
    if schedule.startswith("every "):
        interval = schedule[6:].strip()
        return bool(re.match(r'^\d+[mhd]$', interval))
    return False


def _is_task_due(task: dict, now: datetime) -> bool:
    """Check if a task is due to run."""
    schedule = task["schedule"].lower().strip()
    last_run_str = task.get("last_run")

    if not last_run_str:
        return True  # Never run before

    try:
        last_run = datetime.fromisoformat(last_run_str)
    except Exception:
        return True

    if schedule == "hourly":
        return (now - last_run).total_seconds() >= 3600

    if schedule.startswith("daily "):
        return (now - last_run).total_seconds() >= 86400

    if schedule.startswith("every "):
        interval = schedule[6:].strip()
        match = re.match(r'^(\d+)([mhd])$', interval)
        if match:
            num = int(match.group(1))
            unit = match.group(2)
            seconds = {"m": 60, "h": 3600, "d": 86400}[unit] * num
            return (now - last_run).total_seconds() >= seconds

    return False
