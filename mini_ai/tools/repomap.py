import ast
import re
from pathlib import Path
from typing import List

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
