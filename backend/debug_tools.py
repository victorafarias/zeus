
import sys
import os

# Add the current directory to sys.path to allow imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from agent.tools import TOOLS
    from agent.tools.base import ToolParameter
except ImportError as e:
    print(f"Import Error: {e}")
    sys.exit(1)

print(f"Checking {len(TOOLS)} tools...")

for tool in TOOLS:
    print(f"Checking tool: {tool.name}")
    if not hasattr(tool, 'parameters'):
        print(f"ERROR: Tool {tool.name} has no parameters attribute")
        continue
        
    for i, param in enumerate(tool.parameters):
        if not isinstance(param, ToolParameter):
            print(f"ERROR: Tool '{tool.name}' parameter #{i} is not a ToolParameter instance. It is: {type(param)} - {param}")
        else:
            # print(f"  Param: {param.name} (OK)")
            pass

print("Check complete.")
