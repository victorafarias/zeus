import asyncio
import sys
import os
from unittest.mock import MagicMock

# Adjust path to import backend modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

# MOCK dependencies before import
sys.modules['fastapi'] = MagicMock()
sys.modules['config'] = MagicMock()
sys.modules['agent.tools.base'] = MagicMock()

# Define BaseTool mock since it's used as base class
class BaseTool:
    def _success(self, msg): return f"SUCCESS: {msg}"
    def _error(self, msg): return f"ERROR: {msg}"

# Inject BaseTool into base module
sys.modules['agent.tools.base'].BaseTool = BaseTool
sys.modules['agent.tools.base'].ToolParameter = MagicMock()

# Mock settings
mock_settings = MagicMock()
mock_settings.max_execution_time = 30
sys.modules['config'].get_settings.return_value = mock_settings
sys.modules['config'].get_logger.return_value = MagicMock()

# Now import the tool
# We need to manually load it because the import system might struggle with partial mocks
# But since file is local, we can just load the module spec or trying import if structure allows.
# Given the directory structure, 'agent.tools.shell_executor' 
# c:\Users\Administrator\zeus\backend\agent\tools\shell_executor.py

try:
    from agent.tools.shell_executor import ShellExecutorTool
except ImportError:
    # Fallback for direct import if package structure is complex
    import importlib.util
    spec = importlib.util.spec_from_file_location("ShellExecutorTool", 
        os.path.join(os.path.dirname(__file__), 'agent', 'tools', 'shell_executor.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules["ShellExecutorTool"] = module
    spec.loader.exec_module(module)
    ShellExecutorTool = module.ShellExecutorTool

async def main():
    print("--- Verifying Fix for Shell Executor Hang ---")
    
    tool = ShellExecutorTool()
    
    # Simulate a background command
    command = "nohup python3 --version > version.log 2>&1 &"
    
    try:
        print(f"Executing: {command}")
        result = await asyncio.wait_for(tool.execute(command, working_dir="."), timeout=5.0)
        print(f"Result: {result}")
        
        if "Timeout ao ler saída" in str(result) or "Processo iniciado" in str(result):
             print("SUCCESS: Execution handled correctly (either finished or timed out gracefully).")
        else:
             print("WARNING: Result was unexpected but did not hang.")

    except asyncio.TimeoutError:
        print("FAIL: Execution timed out! The fix is NOT working.")
    except Exception as ex:
        print(f"Exception during test: {ex}")

if __name__ == "__main__":
    asyncio.run(main())
