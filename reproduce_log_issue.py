import subprocess
import time
import urllib.request
import os
import signal
import sys

def run_server(port, unbuffered=False):
    cmd = ["python"]
    if unbuffered:
        cmd.append("-u")
    cmd.extend(["-m", "http.server", str(port)])
    
    log_file = f"test_log_{port}.log"
    with open(log_file, "w") as f:
        # Simulate what shell redirection does roughly
        p = subprocess.Popen(cmd, stderr=f, stdout=f)
    return p, log_file

def check_logs(log_file):
    if not os.path.exists(log_file):
        return f"File {log_file} does not exist"
    
    with open(log_file, "r") as f:
        content = f.read()
    return content

def main():
    print("Starting buffered server on 8083...")
    p1, log1 = run_server(8083, unbuffered=False)
    
    print("Starting unbuffered server on 8084...")
    p2, log2 = run_server(8084, unbuffered=True)
    
    try:
        time.sleep(2)
        print("Making requests...")
        try:
            with urllib.request.urlopen("http://localhost:8083", timeout=1) as response:
                pass
        except Exception as e: 
            pass
        
        try:
            with urllib.request.urlopen("http://localhost:8084", timeout=1) as response:
                pass
        except Exception as e:
            pass
        
        time.sleep(2)
        
        print("\nChecking logs:")
        content1 = check_logs(log1)
        print(f"Buffered (8083) Log Content Length: {len(content1)}")
        
        content2 = check_logs(log2)
        print(f"Unbuffered (8084) Log Content Length: {len(content2)}")
        
        if len(content1) == 0 and len(content2) > 0:
            print("\nSUCCESS: Verified that unbuffered mode writes logs immediately while buffered mode does not.")
        else:
            print(f"\nINCONCLUSIVE: Buffered len={len(content1)}, Unbuffered len={len(content2)}")
            
    finally:
        os.kill(p1.pid, signal.SIGTERM)
        os.kill(p2.pid, signal.SIGTERM)

if __name__ == "__main__":
    main()
