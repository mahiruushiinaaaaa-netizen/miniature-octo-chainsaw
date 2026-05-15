# Implementation Plan: Tool Expansion (100+ Tasks)

## Overview

Add 64 new tools across 11 modules, register them in schemas/executor/grammars, reaching 104+ total tools covering 127+ distinct task types. Each task creates one tool module, registers it fully, and verifies syntax.

## Tasks

- [ ] 1. Git Operations Module
  - [ ] 1.1 Create `mini_ai/tools/git_ops.py` with `git_op()` function
    - Implement operations: branch (list/create/delete/switch), stash (save/pop/list/drop), log (last N), blame, cherry_pick, rebase, tag (list/create/delete), remote (list/add/remove), status, diff_staged, merge, reset (soft/mixed/hard)
    - Use subprocess with 30s timeout, check `git` availability
    - Handle non-git-repo errors gracefully
    - Resolve path via parameter, default to "."
  - [ ] 1.2 Register `git_op` in schemas.py, executor.py registry + wrapper, all 4 grammars

- [ ] 2. Docker Operations Module
  - [ ] 2.1 Create `mini_ai/tools/docker_ops.py` with `docker_op()` function
    - Implement operations: ps, images, run, stop, rm, logs, build, compose_up, compose_down, exec, pull, inspect
    - Check docker/docker-compose availability, return install hint on missing
    - Truncate logs output to 3000 chars
  - [ ] 2.2 Register `docker_op` in schemas.py, executor.py registry + wrapper, all 4 grammars

- [ ] 3. Package Management Module
  - [ ] 3.1 Create `mini_ai/tools/package_ops.py` with `package_op()` function
    - Support managers: npm, pip, cargo, composer, go, yarn, pnpm
    - Implement operations: install, uninstall, list, outdated, update, search, init
    - Auto-detect available package manager, suggest install if missing
    - Handle permission errors (suggest --user for pip, sudo for global)
  - [ ] 3.2 Register `package_op` in schemas.py, executor.py registry + wrapper, all 4 grammars

- [ ] 4. Code Analysis Module
  - [ ] 4.1 Create `mini_ai/tools/code_ops.py` with `code_analyze()` function
    - Implement operations: complexity (count branches/loops per function), dead_code (find unused imports/functions via AST), dependencies (list imports), lint (delegate to ruff/eslint/phpstan), format (delegate to black/prettier), metrics (LOC/functions/classes), imports (import graph), todos (find TODO/FIXME/HACK)
    - Pure Python AST analysis for complexity/dead_code/metrics/imports/todos
    - Delegate to external tools for lint/format with availability check
  - [ ] 4.2 Register `code_analyze` in schemas.py, executor.py registry + wrapper, all 4 grammars

- [ ] 5. Test Operations Module
  - [ ] 5.1 Create `mini_ai/tools/test_ops.py` with `test_op()` function
    - Implement operations: run (auto-detect pytest/jest/phpunit/cargo test), coverage, list (find test files), failed (re-run failed)
    - Auto-detect test framework from config files (pyproject.toml, package.json, phpunit.xml, Cargo.toml)
    - Parse test output for pass/fail counts
  - [ ] 5.2 Register `test_op` in schemas.py, executor.py registry + wrapper, all 4 grammars

- [ ] 6. Conversion Module
  - [ ] 6.1 Create `mini_ai/tools/convert_ops.py` with `convert()`, `format_convert()`, `number_convert()`
    - `convert`: length, weight, temperature, speed, data_size, time, area, volume with comprehensive unit tables
    - `format_convert`: json↔yaml, csv↔json, xml→json, markdown→html, toml→json (pure Python, no deps)
    - `number_convert`: binary, octal, decimal, hex conversions
  - [ ] 6.2 Register `convert`, `format_convert`, `number_convert` in schemas.py, executor.py, all 4 grammars

- [ ] 7. Network Operations Module
  - [ ] 7.1 Create `mini_ai/tools/net_ops.py` with `net_op()` function
    - Implement operations: ping (subprocess), dns (socket.getaddrinfo), port_check (socket connect), download (urllib with progress), whois (subprocess or socket), traceroute (subprocess)
    - Platform-aware: use `ping -n` on Windows, `ping -c` on Unix
    - Download with size limit (100MB max), progress reporting
  - [ ] 7.2 Register `net_op` in schemas.py, executor.py registry + wrapper, all 4 grammars

- [ ] 8. Project Operations Module
  - [ ] 8.1 Create `mini_ai/tools/project_ops.py` with `project_init()`, `project_info()`, `dependency_tree()`, `project_health()`
    - `project_init`: templates for python_package, node_app, react_app, django_app, flask_app, fastapi_app, express_app, cli_tool, library
    - `project_info`: detect language, framework, entry points, config files
    - `dependency_tree`: parse requirements.txt/package.json/Cargo.toml
    - `project_health`: check for outdated deps, missing README, no tests, no gitignore
  - [ ] 8.2 Register all 4 tools in schemas.py, executor.py registry + wrappers, all 4 grammars

- [ ] 9. Advanced File Operations Module
  - [ ] 9.1 Create `mini_ai/tools/file_ops_ext.py` with `file_op_ext()` function
    - Implement operations: find_duplicates (hash-based), bulk_rename (regex pattern), tree (visual directory tree), disk_usage (recursive size), find_large (top N largest files), compare_dirs (diff two directories)
    - Use hashlib for duplicate detection, pathlib for traversal
    - Limit traversal depth to prevent hanging on huge trees
  - [ ] 9.2 Register `file_op_ext` in schemas.py, executor.py registry + wrapper, all 4 grammars

- [ ] 10. Text Operations Module
  - [ ] 10.1 Create `mini_ai/tools/text_ops.py` with `text_op()`, `json_format()`, `template_render()`, `markdown_op()`
    - `text_op`: sort_lines, deduplicate, column extract, word wrap
    - `json_format`: pretty, compact, validate, merge, diff
    - `template_render`: simple {{variable}} substitution
    - `markdown_op`: generate TOC, extract links, extract headings, to_html (basic)
  - [ ] 10.2 Register all 4 tools in schemas.py, executor.py registry + wrappers, all 4 grammars

- [ ] 11. Crypto Operations Module
  - [ ] 11.1 Create `mini_ai/tools/crypto_ops.py` with `crypto_op()` function
    - Implement operations: hash (md5/sha1/sha256/sha512 of text or file), hmac_sign, hmac_verify, random (string/bytes/hex), uuid (v4), password (configurable length/complexity), encode (base32/base64/hex), decode
    - All stdlib: hashlib, hmac, secrets, uuid, base64
    - No actual encryption (avoid security liability) — focus on hashing, signing, random generation
  - [ ] 11.2 Register `crypto_op` in schemas.py, executor.py registry + wrapper, all 4 grammars

- [ ] 12. Grammar & Schema Bulk Registration
  - [ ] 12.1 Update all 4 grammars in `grammars.py` with the 19 new tool names
    - Add to MINIMAL_JSON_GRAMMAR, JSON_ACTION_GRAMMAR, THINK_JSON_GRAMMAR, MULTI_ACTION_GRAMMAR
  - [ ] 12.2 Verify syntax: run `python -c "import ast; ast.parse(open('mini_ai/core/grammars.py').read())"` 

- [ ] 13. Final Verification
  - [ ] 13.1 Run syntax check on all new tool modules
  - [ ] 13.2 Verify executor imports don't crash: `python -c "from mini_ai.core.executor import ToolExecutor"`
  - [ ] 13.3 Update TASKS.md and README.md with new tool list

## Notes

- Each task creates a self-contained module that can be tested independently
- Compound tools (one function with `operation` param) keep grammar size manageable
- All implementations use Python stdlib only — no pip install required
- Tools that delegate to external commands (git, docker, npm) check availability first
- Output truncated to 3000 chars to prevent context overflow
- 30s default timeout on all subprocess calls
