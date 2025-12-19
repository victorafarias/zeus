import asyncio
import sys

async def run_test():
    print("Starting subprocess...")
    # Command that mimics the user's scenario:
    # A bash script that starts a background process that keeps running (sleep 10)
    # redirecting output to file, but we want to see if it holds pipes open.
    # echo $$ prints bash PID.
    cmd = "bash -lc 'nohup sleep 10 > /tmp/sleep.log 2>&1 & echo $!'"
    
    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    stdout_buffer = []
    
    async def read_stream(stream, buffer):
        while True:
            line = await stream.readline()
            if not line:
                break
            buffer.append(line.decode())
            print(f"Read: {line.decode().strip()}")

    tasks = [
        asyncio.create_task(read_stream(process.stdout, stdout_buffer)),
        asyncio.create_task(read_stream(process.stderr, []))
    ]

    print("Waiting for process...")
    await process.wait()
    print(f"Process exited with {process.returncode}")
    
    print("Waiting for streams...")
    # This is where I expect it to hang if FDs are leaked
    try:
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=2.0)
        print("Streams finished normally")
    except asyncio.TimeoutError:
        print("TIMEOUT waiting for streams! (Reproduction successful)")

if __name__ == "__main__":
    asyncio.run(run_test())
