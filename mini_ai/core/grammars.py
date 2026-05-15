"""
grammars.py – GBNF grammars for constraining model output to valid JSON.
Highly effective for small models like Qwen2.5 3B.

Grammars:
  - MINIMAL_JSON_GRAMMAR: Simplified action-only format (no "plan" field) for micro-prompts
  - JSON_ACTION_GRAMMAR: Single action with mandatory plan + enforced tool names
  - THINK_JSON_GRAMMAR: Single action with optional <think> block prefix
  - MULTI_ACTION_GRAMMAR: Supports both single-action and multi-action (batch) formats
    with optional depends_on dependency declarations between actions
"""

# Minimal JSON grammar for micro-prompt system. No "plan" field required.
# Forces output to: {"action": tool_name, ...optional params}
MINIMAL_JSON_GRAMMAR = r'''
root   ::= object
object ::= "{" space "\"action\"" space ":" space tool_name ( "," space string space ":" space value )* space "}"
tool_name ::= "\"run_cmd\"" | "\"write_files\"" | "\"read_files\"" | "\"list_dir\"" | "\"web_search\"" | "\"read_url\"" | "\"answer\"" | "\"make_dir\"" | "\"delete_path\"" | "\"move_path\"" | "\"copy_path\"" | "\"search_files\"" | "\"python_execute\"" | "\"javascript_execute\"" | "\"edit_blocks\"" | "\"workspace_map\"" | "\"workspace_scan\"" | "\"workspace_index\"" | "\"open_browser\"" | "\"play_media\"" | "\"stop_media\"" | "\"json_query\"" | "\"csv_query\"" | "\"text_transform\"" | "\"system_info\"" | "\"http_request\"" | "\"sqlite_query\"" | "\"archive\"" | "\"clipboard\"" | "\"env_var\"" | "\"process_manage\"" | "\"diff_files\"" | "\"screenshot\"" | "\"timer\"" | "\"file_info\"" | "\"scaffold\"" | "\"calculate\"" | "\"datetime_util\"" | "\"regex_tool\"" | "\"batch_read_files\"" | "\"batch_write_files\"" | "\"git_op\"" | "\"docker_op\"" | "\"package_op\"" | "\"code_analyze\"" | "\"test_op\"" | "\"convert\"" | "\"format_convert\"" | "\"number_convert\"" | "\"net_op\"" | "\"project_init\"" | "\"project_info\"" | "\"dependency_tree\"" | "\"project_health\"" | "\"file_op_ext\"" | "\"text_op\"" | "\"json_format\"" | "\"template_render\"" | "\"markdown_op\"" | "\"crypto_op\""
value  ::= object | array | string | number | ("true" | "false" | "null")
array  ::= "[" space ( value ( "," space value )* )? space "]"
string ::= "\"" ( [^"\\\x00-\x1F] | "\\" ( ["\\/bfnrt] | "u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] ) )* "\""
number ::= "-"? ([0-9] | [1-9] [0-9]*) ("." [0-9]+)? ([eE] [+-]? [0-9]+)?
space  ::= [ \t\n\r]*
'''

# A flexible JSON grammar that ensures the model outputs an object with a "plan" and an "action" key.
# Mandatory plan + enforced action names
JSON_ACTION_GRAMMAR = r'''
root   ::= object
object ::= "{" space "\"plan\"" space ":" space string "," space "\"action\"" space ":" space tool_name ( "," space string space ":" space value )* space "}"
tool_name ::= "\"answer\"" | "\"write_files\"" | "\"edit_blocks\"" | "\"read_files\"" | "\"workspace_map\"" | "\"run_cmd\"" | "\"workspace_index\"" | "\"workspace_scan\"" | "\"list_dir\"" | "\"make_dir\"" | "\"delete_path\"" | "\"move_path\"" | "\"copy_path\"" | "\"search_files\"" | "\"web_search\"" | "\"read_url\"" | "\"search_docs\"" | "\"write_task_note\"" | "\"python_execute\"" | "\"javascript_execute\"" | "\"play_media\"" | "\"stop_media\"" | "\"open_browser\"" | "\"json_query\"" | "\"csv_query\"" | "\"text_transform\"" | "\"system_info\"" | "\"http_request\"" | "\"sqlite_query\"" | "\"archive\"" | "\"clipboard\"" | "\"env_var\"" | "\"process_manage\"" | "\"diff_files\"" | "\"screenshot\"" | "\"timer\"" | "\"file_info\"" | "\"scaffold\"" | "\"calculate\"" | "\"datetime_util\"" | "\"regex_tool\"" | "\"batch_read_files\"" | "\"batch_write_files\"" | "\"laravel_create_project\"" | "\"laravel_install_breeze\"" | "\"laravel_migrate\"" | "\"git_op\"" | "\"docker_op\"" | "\"package_op\"" | "\"code_analyze\"" | "\"test_op\"" | "\"convert\"" | "\"format_convert\"" | "\"number_convert\"" | "\"net_op\"" | "\"project_init\"" | "\"project_info\"" | "\"dependency_tree\"" | "\"project_health\"" | "\"file_op_ext\"" | "\"text_op\"" | "\"json_format\"" | "\"template_render\"" | "\"markdown_op\"" | "\"crypto_op\""
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
tool_name ::= "\"answer\"" | "\"write_files\"" | "\"edit_blocks\"" | "\"read_files\"" | "\"workspace_map\"" | "\"run_cmd\"" | "\"workspace_index\"" | "\"workspace_scan\"" | "\"list_dir\"" | "\"make_dir\"" | "\"delete_path\"" | "\"move_path\"" | "\"copy_path\"" | "\"search_files\"" | "\"web_search\"" | "\"read_url\"" | "\"search_docs\"" | "\"write_task_note\"" | "\"python_execute\"" | "\"javascript_execute\"" | "\"play_media\"" | "\"stop_media\"" | "\"open_browser\"" | "\"json_query\"" | "\"csv_query\"" | "\"text_transform\"" | "\"system_info\"" | "\"http_request\"" | "\"sqlite_query\"" | "\"archive\"" | "\"clipboard\"" | "\"env_var\"" | "\"process_manage\"" | "\"diff_files\"" | "\"screenshot\"" | "\"timer\"" | "\"file_info\"" | "\"scaffold\"" | "\"calculate\"" | "\"datetime_util\"" | "\"regex_tool\"" | "\"batch_read_files\"" | "\"batch_write_files\"" | "\"laravel_create_project\"" | "\"laravel_install_breeze\"" | "\"laravel_migrate\"" | "\"git_op\"" | "\"docker_op\"" | "\"package_op\"" | "\"code_analyze\"" | "\"test_op\"" | "\"convert\"" | "\"format_convert\"" | "\"number_convert\"" | "\"net_op\"" | "\"project_init\"" | "\"project_info\"" | "\"dependency_tree\"" | "\"project_health\"" | "\"file_op_ext\"" | "\"text_op\"" | "\"json_format\"" | "\"template_render\"" | "\"markdown_op\"" | "\"crypto_op\""
value   ::= object | array | string | number | ("true" | "false" | "null")
array   ::= "[" space ( value ( "," space value )* )? space "]"
string  ::= "\"" ( [^"\\\x00-\x1F] | "\\" ( ["\\/bfnrt] | "u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] ) )* "\""
number  ::= "-"? ([0-9] | [1-9] [0-9]*) ("." [0-9]+)? ([eE] [+-]? [0-9]+)?
space   ::= [ \t\n\r]*
'''

# Multi-action grammar supporting both single-action and batch formats.
# Backward compatible: accepts {"plan": ..., "action": ...} (single)
# and also {"plan": ..., "actions": [...]} (batch with optional depends_on).
MULTI_ACTION_GRAMMAR = r'''
root    ::= (think space)? (single_action | multi_action)
think   ::= "<think>" [^<]* "</think>"
single_action ::= "{" space "\"plan\"" space ":" space string "," space "\"action\"" space ":" space tool_name ( "," space string space ":" space value )* space "}"
multi_action  ::= "{" space "\"plan\"" space ":" space string "," space "\"actions\"" space ":" space action_array space "}"
action_array  ::= "[" space action_obj ("," space action_obj)* space "]"
action_obj    ::= "{" space "\"action\"" space ":" space tool_name ( "," space action_field )* space "}"
action_field  ::= depends_on_field | generic_field
depends_on_field ::= "\"depends_on\"" space ":" space int_array
generic_field ::= string space ":" space value
int_array     ::= "[" space ( number ( "," space number )* )? space "]"
tool_name ::= "\"answer\"" | "\"write_files\"" | "\"edit_blocks\"" | "\"read_files\"" | "\"workspace_map\"" | "\"run_cmd\"" | "\"workspace_index\"" | "\"workspace_scan\"" | "\"list_dir\"" | "\"make_dir\"" | "\"delete_path\"" | "\"move_path\"" | "\"copy_path\"" | "\"search_files\"" | "\"web_search\"" | "\"read_url\"" | "\"search_docs\"" | "\"write_task_note\"" | "\"python_execute\"" | "\"javascript_execute\"" | "\"play_media\"" | "\"stop_media\"" | "\"open_browser\"" | "\"json_query\"" | "\"csv_query\"" | "\"text_transform\"" | "\"system_info\"" | "\"http_request\"" | "\"sqlite_query\"" | "\"archive\"" | "\"clipboard\"" | "\"env_var\"" | "\"process_manage\"" | "\"diff_files\"" | "\"screenshot\"" | "\"timer\"" | "\"file_info\"" | "\"scaffold\"" | "\"calculate\"" | "\"datetime_util\"" | "\"regex_tool\"" | "\"batch_read_files\"" | "\"batch_write_files\"" | "\"laravel_create_project\"" | "\"laravel_install_breeze\"" | "\"laravel_migrate\"" | "\"git_op\"" | "\"docker_op\"" | "\"package_op\"" | "\"code_analyze\"" | "\"test_op\"" | "\"convert\"" | "\"format_convert\"" | "\"number_convert\"" | "\"net_op\"" | "\"project_init\"" | "\"project_info\"" | "\"dependency_tree\"" | "\"project_health\"" | "\"file_op_ext\"" | "\"text_op\"" | "\"json_format\"" | "\"template_render\"" | "\"markdown_op\"" | "\"crypto_op\""
value   ::= object | array | string | number | ("true" | "false" | "null")
object  ::= "{" space ( string space ":" space value ( "," space string space ":" space value )* )? space "}"
array   ::= "[" space ( value ( "," space value )* )? space "]"
string  ::= "\"" ( [^"\\\x00-\x1F] | "\\" ( ["\\/bfnrt] | "u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] ) )* "\""
number  ::= "-"? ([0-9] | [1-9] [0-9]*) ("." [0-9]+)? ([eE] [+-]? [0-9]+)?
space   ::= [ \t\n\r]*
'''
