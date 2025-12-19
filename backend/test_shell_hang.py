import asyncio
import sys
import os

# Mocking the logger and settings for standalone run
class MockLogger:
    def info(self, msg, **kwargs):
        print(f"INFO: {msg} {kwargs}")
    def warning(self, msg, **kwargs):
        print(f"WARN: {msg} {kwargs}")
    def error(self, msg, **kwargs):
        print(f"ERROR: {msg} {kwargs}")

class MockSettings:
    max_execution_time = 30

logger = MockLogger()
settings = MockSettings()

# Copied simplified ShellExecutorTool logic
class ShellExecutorTool:
    async def execute(self, command, working_dir="/app/data", timeout=30):
        print(f"Executing: {command}")
        
        is_background = (
            command.strip().endswith('&') or
            'nohup' in command.lower() or
            command.strip().endswith('&>')
        )
        
        if is_background:
            cmd_to_run = command.strip()
            if not cmd_to_run.endswith('&'):
                cmd_to_run = cmd_to_run + ' &'
            
            print(f"Running background command: {cmd_to_run}")
            
            # Using basic asyncio subprocess as in the tool
            process = await asyncio.create_subprocess_shell(
                cmd_to_run,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir
            )
            
            print("Process started. Waiting 0.5s...")
            await asyncio.sleep(0.5)
            
            if process.returncode is None:
                print(f"Process still running (PID: {process.pid}). Success.")
                return f"Processo iniciado em background (PID: {process.pid})"
            else:
                print(f"Process finished with code {process.returncode}. Reading output...")
                stdout, stderr = await process.communicate()
                print(f"STDOUT: {stdout}")
                print(f"STDERR: {stderr}")
                return "Finished"

async def main():
    # Attempting to reproduce the hang
    # We need a directory that exists. Using standard temp or current dir.
    # The original command had /app/data/outputs. We'll use .
    
    # Simulating the exact command from the log
    # Note: 'python3 -u -m http.server' is a long running process.
    # The 'e' at the end is the suspicious part.
    command = "nohup python3 -u -m http.server 8091 > http_8091.log 2>&1 & e"
    
    tool = ShellExecutorTool()
    
    print("--- Starting Execution ---")
    try:
        # We need to wrap this in wait_for to detect hang in the test itself
        result = await asyncio.wait_for(tool.execute(command, working_dir="."), timeout=5.0)
        print(f"Result: {result}")
    except asyncio.TimeoutError:
        print("!!! HANG DETECTED !!! Execution timed out after 5s")
    except Exception as ex:
        print(f"Exception: {ex}")

if __name__ == "__main__":
    asyncio.run(main())
