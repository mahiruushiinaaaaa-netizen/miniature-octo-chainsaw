import importlib
try:
    importlib.import_module('mini_ai.agents.agent')
    print('IMPORT OK')
except Exception as e:
    import traceback
    traceback.print_exc()
    print('IMPORT FAILED')
