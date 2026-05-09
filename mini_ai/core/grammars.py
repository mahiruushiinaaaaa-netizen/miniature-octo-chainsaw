"""
grammars.py – GBNF grammars for constraining model output to valid JSON.
Highly effective for small models like Qwen2.5 3B.
"""

# A flexible JSON grammar that ensures the model outputs an object with a "plan" and an "action" key.
# Mandatory plan + enforced action names
JSON_ACTION_GRAMMAR = r'''
root   ::= object
object ::= "{" space "\"plan\"" space ":" space string "," space "\"action\"" space ":" space tool_name ( "," space string space ":" space value )* space "}"
tool_name ::= "\"answer\"" | "\"write_files\"" | "\"edit_blocks\"" | "\"read_files\"" | "\"workspace_map\"" | "\"run_cmd\"" | "\"workspace_index\"" | "\"workspace_scan\"" | "\"list_dir\"" | "\"make_dir\"" | "\"delete_path\"" | "\"move_path\"" | "\"copy_path\"" | "\"search_files\"" | "\"web_search\"" | "\"read_url\"" | "\"search_docs\"" | "\"write_task_note\"" | "\"run_python\"" | "\"play_media\"" | "\"laravel_create_project\"" | "\"laravel_install_breeze\"" | "\"laravel_migrate\""
value  ::= object | array | string | number | ("true" | "false" | "null")
array  ::= "[" space ( value ( "," space value )* )? space "]"
string ::= "\"" ( [^"\\\x00-\x1F] | "\\" ( ["\\/bfnrt] | "u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] ) )* "\""
number ::= "-"? ([0-9] | [1-9] [0-9]*) ("." [0-9]+)? ([eE] [+-]? [0-9]+)?
space  ::= [ \t\n\r]*
'''

# Mandatory plan + enforced action names (Thinking variant)
THINK_JSON_GRAMMAR = r'''
root    ::= (think space)? object
think   ::= "<think>" [^<]* "</think>"
object  ::= "{" space "\"plan\"" space ":" space string "," space "\"action\"" space ":" space tool_name ( "," space string space ":" space value )* space "}"
tool_name ::= "\"answer\"" | "\"write_files\"" | "\"edit_blocks\"" | "\"read_files\"" | "\"workspace_map\"" | "\"run_cmd\"" | "\"workspace_index\"" | "\"workspace_scan\"" | "\"list_dir\"" | "\"make_dir\"" | "\"delete_path\"" | "\"move_path\"" | "\"copy_path\"" | "\"search_files\"" | "\"web_search\"" | "\"read_url\"" | "\"search_docs\"" | "\"write_task_note\"" | "\"run_python\"" | "\"play_media\""
value   ::= object | array | string | number | ("true" | "false" | "null")
array   ::= "[" space ( value ( "," space value )* )? space "]"
string  ::= "\"" ( [^"\\\x00-\x1F] | "\\" ( ["\\/bfnrt] | "u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] ) )* "\""
number  ::= "-"? ([0-9] | [1-9] [0-9]*) ("." [0-9]+)? ([eE] [+-]? [0-9]+)?
space   ::= [ \t\n\r]*
'''
