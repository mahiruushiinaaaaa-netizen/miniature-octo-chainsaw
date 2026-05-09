import re
import difflib
from pathlib import Path
from typing import Optional

# Matchers for the blocks
HEAD = r"<{7}\s*SEARCH\s*"
DIVIDER = r"={7}\s*"
UPDATED = r">{7}\s*REPLACE\s*"

# Complete regex pattern to match a full SEARCH/REPLACE block
BLOCK_PATTERN = re.compile(
    r"(?P<filename>[^\n]+)\n"  # Filename on the line before
    r"```[a-zA-Z0-9]*\n"       # Optional language tag in markdown
    r"(?P<search>" + HEAD + r"\n.*?)"
    r"(?P<divider>" + DIVIDER + r"\n)"
    r"(?P<replace>.*?" + UPDATED + r"\n)"
    r"```",                    # End of markdown block
    re.DOTALL | re.IGNORECASE
)

def find_blocks(text: str) -> list[dict]:
    """Find all search/replace blocks in the text."""
    blocks = []
    
    # We use a simple line-based state machine because regex can be brittle with markdown blocks
    lines = text.splitlines(keepends=True)
    
    state = "OUTSIDE"
    current_file = ""
    search_lines = []
    replace_lines = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        if state == "OUTSIDE":
            # Look for <<<<<<< SEARCH
            if "<<<<<<< SEARCH" in line:
                # The filename should be right above the markdown fence
                # So we look back 1 or 2 lines for something that looks like a filename
                # If we can't find it, we'll try to find it earlier
                file_cand = ""
                for j in range(i - 1, max(-1, i - 4), -1):
                    cand = lines[j].strip()
                    if cand and not cand.startswith("```"):
                        file_cand = cand
                        break
                
                current_file = file_cand.strip("`* ")
                state = "IN_SEARCH"
                search_lines = []
                replace_lines = []
        elif state == "IN_SEARCH":
            if "=======" in line:
                state = "IN_REPLACE"
            else:
                search_lines.append(line)
        elif state == "IN_REPLACE":
            if ">>>>>>> REPLACE" in line:
                blocks.append({
                    "file": current_file,
                    "search": "".join(search_lines),
                    "replace": "".join(replace_lines)
                })
                state = "OUTSIDE"
            else:
                replace_lines.append(line)
                
        i += 1
        
    return blocks

def normalize(text: str) -> list[str]:
    """Normalize text for comparison: strip whitespace, remove empty lines."""
    return [l.strip() for l in text.strip().splitlines() if l.strip()]

def try_dotdotdots(whole: str, search: str, replace: str) -> Optional[str]:
    """
    Handle SEARCH/REPLACE blocks that use '...' to elide code.
    Example:
    <<<<<<< SEARCH
    func_start()
    ...
    func_end()
    =======
    func_start()
    ...
    new_code()
    func_end()
    >>>>>>> REPLACE
    """
    dots_re = re.compile(r"(^\s*\.\.\.\n)", re.MULTILINE | re.DOTALL)
    
    search_pieces = re.split(dots_re, search)
    replace_pieces = re.split(dots_re, replace)
    
    if len(search_pieces) != len(replace_pieces):
        return None # Unpaired dots
        
    if len(search_pieces) == 1:
        return None # No dots
        
    # All dots must match exactly in both search and replace
    for i in range(1, len(search_pieces), 2):
        if search_pieces[i] != replace_pieces[i]:
            return None

    # Filter out the '...' pieces
    search_parts = [search_pieces[i] for i in range(0, len(search_pieces), 2)]
    replace_parts = [replace_pieces[i] for i in range(0, len(replace_pieces), 2)]
    
    current_content = whole
    for s_part, r_part in zip(search_parts, replace_parts):
        if not s_part and not r_part:
            continue
        if not s_part and r_part:
            # Append to end
            if not current_content.endswith("\n"):
                current_content += "\n"
            current_content += r_part
            continue
            
        if current_content.count(s_part) != 1:
            return None # Ambiguous or missing match
            
        current_content = current_content.replace(s_part, r_part, 1)
        
    return current_content

def apply_edit_block(original_content: str, search_text: str, replace_text: str) -> tuple[bool, str]:
    """Applies a search/replace block to the original content with fuzzy matching and elision support."""
    
    if not search_text.strip() and original_content.strip() == "":
        # New file creation
        return True, replace_text
        
    # 1. Exact Match
    if search_text in original_content:
        return True, original_content.replace(search_text, replace_text, 1)
        
    # 2. Dot-Dot-Dot (Elision) Support
    dot_result = try_dotdotdots(original_content, search_text, replace_text)
    if dot_result is not None:
        return True, dot_result

    # 3. Match ignoring leading whitespace and line endings
    search_norm = normalize(search_text)
    orig_lines = original_content.splitlines(keepends=True)
    
    if not search_norm:
        return False, original_content
        
    for i in range(len(orig_lines) - len(search_norm) + 1):
        chunk = orig_lines[i:i + len(search_norm)]
        chunk_norm = normalize("".join(chunk))
        
        if chunk_norm == search_norm:
            # We found a match! apply indentation from original to replace text
            leading_ws = len(orig_lines[i]) - len(orig_lines[i].lstrip())
            indent = orig_lines[i][:leading_ws]
            
            rep_lines = replace_text.splitlines(keepends=True)
            indented_rep = []
            
            # Find min indentation of replace block to offset correctly
            rep_min_indent = min([len(l) - len(l.lstrip()) for l in rep_lines if l.strip()] or [0])
            
            for line in rep_lines:
                if line.strip():
                    stripped = line[rep_min_indent:]
                    indented_rep.append(indent + stripped)
                else:
                    indented_rep.append(line)
                    
            res = "".join(orig_lines[:i]) + "".join(indented_rep) + "".join(orig_lines[i + len(search_norm):])
            return True, res
            
    # 4. Fuzzy matching via difflib SequenceMatcher
    best_ratio = 0
    best_idx = -1
    best_len = 0
    
    search_str = "".join(search_norm)
    for length in range(max(1, len(search_norm) - 2), len(search_norm) + 3):
        for i in range(len(orig_lines) - length + 1):
            chunk = orig_lines[i:i + length]
            chunk_str = "".join(normalize("".join(chunk)))
            ratio = difflib.SequenceMatcher(None, search_str, chunk_str).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_idx = i
                best_len = length
                
    if best_ratio > 0.85:
        res = "".join(orig_lines[:best_idx]) + replace_text + "".join(orig_lines[best_idx + best_len:])
        return True, res

    return False, original_content
