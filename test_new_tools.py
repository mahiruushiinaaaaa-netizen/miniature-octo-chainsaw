"""Quick functional test of new tools."""
from mini_ai.tools.data_tools import calculate, datetime_util, regex_tool, text_transform, csv_query
from mini_ai.tools.system_tools import system_info, env_var, file_info, clipboard_op
from mini_ai.tools.network_tools import sqlite_query
from mini_ai.tools.archive_tools import scaffold
import tempfile, os

print("=== Testing calculate ===")
r = calculate("2**10 + sqrt(144)")
print(f"  2^10 + sqrt(144) = {r['result']}")
assert r["success"] and r["result"] == "1036.0"

print("=== Testing datetime_util ===")
r = datetime_util("now")
assert r["success"]
print(f"  Now: {r['result'][:40]}...")

print("=== Testing regex_tool ===")
r = regex_tool("findall", r"\d+", text="abc123def456ghi789")
assert r["success"] and r["count"] == 3
print(f"  Found {r['count']} numbers")

print("=== Testing text_transform ===")
r = text_transform("Hello World", "hash", "sha256")
assert r["success"] and "sha256:" in r["result"]
print(f"  Hash: {r['result'][:50]}...")

r = text_transform("Hello World", "base64_encode")
assert r["success"] and r["result"] == "SGVsbG8gV29ybGQ="
print(f"  Base64: {r['result']}")

print("=== Testing system_info ===")
r = system_info("cpu")
assert r["success"]
print(f"  CPU info retrieved ({len(r['result'])} chars)")

print("=== Testing env_var ===")
r = env_var("set", "TEST_MINI_AI", "hello123")
assert r["success"]
r = env_var("get", "TEST_MINI_AI")
assert r["success"] and "hello123" in r["result"]
env_var("unset", "TEST_MINI_AI")
print(f"  Set/Get/Unset: OK")

print("=== Testing file_info ===")
r = file_info(__file__, "full")
assert r["success"]
print(f"  File info: OK")

print("=== Testing sqlite_query ===")
db_path = os.path.join(tempfile.gettempdir(), "test_mini_ai.db")
r = sqlite_query(db_path, "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT)")
assert r["success"]
r = sqlite_query(db_path, "INSERT INTO users (name) VALUES (?)", ["Alice"])
assert r["success"]
r = sqlite_query(db_path, "SELECT * FROM users")
assert r["success"] and "Alice" in r["result"]
os.remove(db_path)
print(f"  SQLite CRUD: OK")

print("=== Testing scaffold ===")
r = scaffold("python_class", "MyService")
assert r["success"] and "class MyService" in r["result"]
r = scaffold("dockerfile", "myapp", {"language": "python"})
assert r["success"] and "FROM python" in r["result"]
r = scaffold("react_component", "UserCard")
assert r["success"] and "UserCard" in r["result"]
print(f"  Scaffold (python_class, dockerfile, react_component): OK")

print("\n✓ ALL NEW TOOLS WORKING CORRECTLY")
