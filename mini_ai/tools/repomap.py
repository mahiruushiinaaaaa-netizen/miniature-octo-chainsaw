import ast
import math
import re
from collections import Counter
from pathlib import Path
from typing import List, Optional

from mini_ai.core.logger import get_logger

logger = get_logger("repomap")

def get_python_signatures(content: str) -> List[str]:
    signatures = []
    try:
        tree = ast.parse(content)
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                signatures.append(f"class {node.name}:")
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        signatures.append(f"    def {item.name}(...):")
            elif isinstance(node, ast.FunctionDef):
                signatures.append(f"def {node.name}(...):")
    except SyntaxError:
        pass
    return signatures

def get_js_signatures(content: str) -> List[str]:
    signatures = []
    class_pattern = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+(\w+)", re.MULTILINE)
    func_pattern = re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)", re.MULTILINE)
    const_func_pattern = re.compile(r"^\s*(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)\s*=>|function)", re.MULTILINE)
    
    for match in class_pattern.finditer(content):
        signatures.append(f"class {match.group(1)} {{ ... }}")
    for match in func_pattern.finditer(content):
        signatures.append(f"function {match.group(1)}(...)")
    for match in const_func_pattern.finditer(content):
        signatures.append(f"const {match.group(1)} = (...) => {{}}")
        
    return signatures

def generate_repo_map(root_path: str, max_files: int = 150) -> str:
    root = Path(root_path)
    if not root.exists() or not root.is_dir():
        return ""
        
    output = ["REPOSITORY MAP:"]
    count = 0
    
    for file_path in sorted(root.rglob("*")):
        if count >= max_files:
            break
        if not file_path.is_file():
            continue
        if any(p.startswith(".") or p in {"node_modules", "__pycache__", "venv", "dist", "build"} for p in file_path.parts):
            continue
            
        ext = file_path.suffix.lower()
        if ext not in {".py", ".js", ".ts", ".jsx", ".tsx"}:
            continue
            
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            if ext == ".py":
                sigs = get_python_signatures(content)
            else:
                sigs = get_js_signatures(content)
                
            if sigs:
                rel_path = file_path.relative_to(root)
                output.append(f"\n{rel_path}:")
                output.extend(["  " + s for s in sigs])
                count += 1
        except Exception:
            continue
            
    if count == 0:
        return ""
        
    return "\n".join(output)


# --- Enhanced Repo Map v2 ---

FILE_ROLES = {"entry_point", "utility", "model", "controller", "test", "config", "unknown"}

# Patterns for role classification
_ENTRY_POINT_PATTERNS = re.compile(
    r"(^|/)(?:main|app|index|run|server|cli|launch|start|manage)\.", re.IGNORECASE
)
_TEST_PATTERNS = re.compile(
    r"(^|/)(test_|spec_|tests/|spec/|__tests__/|\.test\.|\.spec\.)", re.IGNORECASE
)
_CONFIG_PATTERNS = re.compile(
    r"(^|/)(config|settings|\.env|setup\.cfg|pyproject|package\.json|tsconfig|"
    r"webpack|vite\.config|babel\.config|jest\.config|\.eslintrc)", re.IGNORECASE
)
_MODEL_PATTERNS = re.compile(
    r"(^|/)(models?/|schemas?/|entities/|types/)", re.IGNORECASE
)
_CONTROLLER_PATTERNS = re.compile(
    r"(^|/)(controllers?/|routes?/|views?/|handlers?/|api/|endpoints?/)", re.IGNORECASE
)


def classify_file_role(path: str, signatures: List[str]) -> str:
    """Assign a role from the closed set based on path patterns and signatures.

    Args:
        path: Relative file path (forward slashes).
        signatures: List of extracted function/class signatures.

    Returns:
        One of: entry_point, utility, model, controller, test, config, unknown.
    """
    # Normalize path separators
    normalized = path.replace("\\", "/")

    # Check patterns in priority order
    if _TEST_PATTERNS.search(normalized):
        return "test"

    if _CONFIG_PATTERNS.search(normalized):
        return "config"

    if _ENTRY_POINT_PATTERNS.search(normalized):
        return "entry_point"

    if _CONTROLLER_PATTERNS.search(normalized):
        return "controller"

    if _MODEL_PATTERNS.search(normalized):
        return "model"

    # Signature-based heuristics
    sig_text = " ".join(signatures).lower()
    if any(kw in sig_text for kw in ("class ", "dataclass", "basemodel", "schema")):
        if any(kw in sig_text for kw in ("route", "handler", "view", "endpoint", "controller")):
            return "controller"
        if any(kw in sig_text for kw in ("model", "schema", "entity", "field")):
            return "model"

    # Check for __main__ guard in signatures or if it has a main() function
    if any("def main" in s or "__main__" in s for s in signatures):
        return "entry_point"

    # Files with mostly helper/utility functions
    if signatures and all("def " in s or "function " in s or "const " in s for s in signatures):
        return "utility"

    if signatures:
        return "utility"

    return "unknown"


def _bm25_score(term_freq: int, doc_len: int, avg_doc_len: float, n_docs: int, doc_freq: int) -> float:
    """Compute BM25 score for a single term in a document.

    Uses standard BM25 parameters k1=1.5, b=0.75.
    """
    k1 = 1.5
    b = 0.75
    if doc_freq == 0 or n_docs == 0:
        return 0.0
    idf = math.log((n_docs - doc_freq + 0.5) / (doc_freq + 0.5) + 1.0)
    tf_norm = (term_freq * (k1 + 1)) / (term_freq + k1 * (1 - b + b * (doc_len / avg_doc_len)))
    return idf * tf_norm


def _compute_file_bm25(
    file_path: str,
    signatures: List[str],
    goal_terms: List[str],
    all_doc_terms: List[List[str]],
    avg_doc_len: float,
    n_docs: int,
    term_doc_freq: Counter,
) -> float:
    """Compute BM25 relevance score for a file against goal terms."""
    # Build document from path + signatures
    doc_tokens = _tokenize_for_bm25(file_path, signatures)
    doc_len = len(doc_tokens)
    if doc_len == 0 or not goal_terms:
        return 0.0

    token_freq = Counter(doc_tokens)
    score = 0.0
    for term in goal_terms:
        tf = token_freq.get(term, 0)
        df = term_doc_freq.get(term, 0)
        score += _bm25_score(tf, doc_len, avg_doc_len, n_docs, df)
    return score


def _tokenize_for_bm25(file_path: str, signatures: List[str]) -> List[str]:
    """Tokenize a file path and its signatures into lowercase terms."""
    text = file_path.replace("/", " ").replace("\\", " ").replace("_", " ").replace(".", " ")
    text += " " + " ".join(signatures)
    # Split on non-alphanumeric, lowercase
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return tokens


def generate_repo_map_v2(
    root: str,
    goal: str = "",
    dep_graph: "Optional[object]" = None,
    max_tokens: int = 400,
) -> str:
    """Generate a goal-focused repo map with import edges and role annotations.

    Args:
        root: Root directory path.
        goal: Current user goal for relevance filtering.
        dep_graph: Optional DependencyGraph instance for import edges and hop filtering.
        max_tokens: Maximum token budget (1 token ≈ 4 chars). Default 400.

    Returns:
        Formatted repo map string within token budget.
    """
    from mini_ai.core.workspace_index import score_file, keywords_from_goal

    max_chars = max_tokens * 4  # 400 tokens = 1600 chars
    root_path = Path(root)
    if not root_path.exists() or not root_path.is_dir():
        return ""

    # Collect all parseable files with signatures
    file_entries: List[dict] = []  # {path, signatures, role, has_syntax_error}

    for file_path in sorted(root_path.rglob("*")):
        if not file_path.is_file():
            continue
        if any(
            p.startswith(".") or p in {"node_modules", "__pycache__", "venv", "dist", "build", ".git"}
            for p in file_path.parts
        ):
            continue

        ext = file_path.suffix.lower()
        if ext not in {".py", ".js", ".ts", ".jsx", ".tsx"}:
            continue

        rel_path = str(file_path.relative_to(root_path)).replace("\\", "/")
        has_syntax_error = False
        sigs: List[str] = []

        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            if ext == ".py":
                sigs = get_python_signatures(content)
                # Check if syntax error occurred (get_python_signatures returns [] on SyntaxError)
                if not sigs:
                    try:
                        ast.parse(content)
                    except SyntaxError:
                        has_syntax_error = True
            else:
                sigs = get_js_signatures(content)
        except Exception:
            has_syntax_error = True

        role = classify_file_role(rel_path, sigs)
        file_entries.append({
            "path": rel_path,
            "signatures": sigs,
            "role": role,
            "has_syntax_error": has_syntax_error,
        })

    if not file_entries:
        return ""

    # Score files for relevance
    goal_keywords = keywords_from_goal(goal) if goal else []
    scored_entries: List[tuple] = []  # (score, entry)

    for entry in file_entries:
        if goal:
            s = score_file(
                entry["path"],
                goal,
                [],  # stack not critical for relative scoring
                tokens=[],
                suffix=Path(entry["path"]).suffix.lower(),
                size=0,
                mtime=0.0,
            )
        else:
            s = 0
        scored_entries.append((s, entry))

    scored_entries.sort(key=lambda x: x[0], reverse=True)

    # Determine which files to include based on dependency hops
    highest_score = scored_entries[0][0] if scored_entries else 0
    relevance_threshold = 5

    included_paths: set = set()

    if dep_graph is not None and highest_score > relevance_threshold:
        # Filter to files within 2 dependency hops of highest-relevance file
        best_file = scored_entries[0][1]["path"]
        included_paths = dep_graph.files_within_hops(best_file, max_hops=2)
    elif dep_graph is not None:
        # Fallback: entry_point files + 1 hop
        entry_points = [e["path"] for _, e in scored_entries if e["role"] == "entry_point"]
        for ep in entry_points:
            included_paths.update(dep_graph.files_within_hops(ep, max_hops=1))
        # If no entry points found, include all files
        if not included_paths:
            included_paths = {e["path"] for _, e in scored_entries}
    else:
        # No dep_graph: include all files
        included_paths = {e["path"] for _, e in scored_entries}

    # Filter scored entries to included paths
    filtered_entries = [(s, e) for s, e in scored_entries if e["path"] in included_paths]

    # If no entries after filtering, fall back to all
    if not filtered_entries:
        filtered_entries = scored_entries

    # Build import edges map from dep_graph
    import_edges: dict = {}  # path -> list of imported paths
    if dep_graph is not None and hasattr(dep_graph, "_imports"):
        import_edges = {k: list(v) for k, v in dep_graph._imports.items()}

    # BM25 filtering if output would exceed budget
    # First, build the full map and check size
    all_doc_terms: List[List[str]] = []
    for _, entry in filtered_entries:
        all_doc_terms.append(_tokenize_for_bm25(entry["path"], entry["signatures"]))

    avg_doc_len = sum(len(d) for d in all_doc_terms) / max(len(all_doc_terms), 1)
    n_docs = len(all_doc_terms)

    # Compute term document frequency
    term_doc_freq: Counter = Counter()
    for doc_tokens in all_doc_terms:
        unique_terms = set(doc_tokens)
        for term in unique_terms:
            term_doc_freq[term] += 1

    # Compute BM25 scores for each file
    bm25_scores: List[tuple] = []  # (bm25_score, relevance_score, entry)
    for i, (rel_score, entry) in enumerate(filtered_entries):
        if goal_keywords:
            bm25 = _compute_file_bm25(
                entry["path"],
                entry["signatures"],
                goal_keywords,
                all_doc_terms,
                avg_doc_len,
                n_docs,
                term_doc_freq,
            )
        else:
            bm25 = float(rel_score)  # Use relevance score as fallback
        bm25_scores.append((bm25, rel_score, entry))

    # Sort by BM25 score descending
    bm25_scores.sort(key=lambda x: (x[0], x[1]), reverse=True)

    # Build output, applying BM25 threshold and char budget
    output_lines: List[str] = ["REPO MAP v2:"]
    current_chars = len(output_lines[0])

    for bm25, rel_score, entry in bm25_scores:
        # Apply BM25 threshold of 1.5 only when we need to trim
        # (always include if we're under budget, filter above 1.5 when over)
        file_lines = _format_file_entry(entry, import_edges)
        file_text = "\n".join(file_lines)
        candidate_chars = current_chars + len(file_text) + 1  # +1 for newline

        if candidate_chars > max_chars:
            # Over budget: only include if BM25 > 1.5
            if goal_keywords and bm25 <= 1.5:
                continue
            # Even with high BM25, stop if we'd exceed budget
            if candidate_chars > max_chars:
                break

        output_lines.extend(file_lines)
        current_chars += len(file_text) + 1

    # Final enforcement: truncate to max_chars
    result = "\n".join(output_lines)
    if len(result) > max_chars:
        result = result[:max_chars].rsplit("\n", 1)[0]

    if result == "REPO MAP v2:":
        return ""

    return result


def _format_file_entry(entry: dict, import_edges: dict) -> List[str]:
    """Format a single file entry with role annotation and import edges."""
    path = entry["path"]
    role = entry["role"]
    has_syntax_error = entry["has_syntax_error"]
    signatures = entry["signatures"]

    lines: List[str] = []

    # File header with role
    role_tag = f"[{role}]"
    if has_syntax_error:
        role_tag += " [syntax-error]"
    lines.append(f"\n{path} {role_tag}:")

    # Import edges
    edges = import_edges.get(path, [])
    if edges:
        edge_strs = [e.rsplit("/", 1)[-1] for e in edges[:5]]  # Show basename, max 5
        lines.append(f"  → imports: {', '.join(edge_strs)}")

    # Signatures (limit to keep output compact)
    for sig in signatures[:8]:
        lines.append(f"  {sig}")

    return lines
