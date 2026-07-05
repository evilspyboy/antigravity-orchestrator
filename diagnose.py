import os
import sys
import subprocess
import json
import re
import socket

def check_port(host, port):
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except Exception:
        return False

def get_running_servers():
    try:
        ps_cmd = "Get-CimInstance Win32_Process -Filter 'Name = ''language_server_windows_x64.exe''' | Select-Object ProcessId, CommandLine | ConvertTo-Json -Compress"
        res = subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True, timeout=15)
        stdout = res.stdout.strip()
        if not stdout:
            return []
        parsed = json.loads(stdout)
        process_list = parsed if isinstance(parsed, list) else [parsed]
        results = []
        for p in process_list:
            proc_id = p.get("ProcessId")
            cmdline = p.get("CommandLine", "")
            csrf_match = re.search(r'--csrf_token\s+([\w-]+)', cmdline)
            csrf_token = csrf_match.group(1) if csrf_match else "NONE"
            
            # Get listening ports
            netstat_cmd = f'(netstat -ano) | Where-Object {{ $_ -match \'\\s+LISTENING\\s+{proc_id}\\s*$\' }} | ForEach-Object {{ $parts = $_.Trim() -split \'\\s+\'; if ($parts.Length -ge 2) {{ $addr = $parts[1]; $addr.Substring($addr.LastIndexOf(\':\') + 1) }} }} | Select-Object -Unique | ConvertTo-Json -Compress'
            res_ns = subprocess.run(["powershell", "-Command", netstat_cmd], capture_output=True, text=True, timeout=15)
            ns_stdout = res_ns.stdout.strip()
            ports = []
            if ns_stdout:
                try:
                    parsed_ports = json.loads(ns_stdout)
                    ports = parsed_ports if isinstance(parsed_ports, list) else [parsed_ports]
                except Exception:
                    try:
                        ports = [int(ns_stdout)]
                    except Exception:
                        pass
            results.append({
                "pid": proc_id,
                "cmdline": cmdline[:150] + "...",
                "csrf_token": csrf_token,
                "ports": ports
            })
        return results
    except Exception as e:
        return f"Error getting servers: {e}"

def main():
    print("=== AGENT SESSION DIAGNOSTICS ===")
    
    # Resolve Conversation ID
    conv_id = ""
    if len(sys.argv) > 1:
        conv_id = sys.argv[1]
    
    if not conv_id:
        conv_id = os.environ.get('ANTIGRAVITY_CONVERSATION_ID', '')
        
    if not conv_id:
        cwd = os.getcwd().replace('\\', '/')
        m_conv = re.search(r'/brain/([\w-]+)', cwd)
        if m_conv:
            conv_id = m_conv.group(1)
            
    print(f"Conversation ID: {conv_id or 'UNKNOWN'}")
    print(f"Active Workspace Path: {os.getcwd()}")
    print("\n--- ENVIRONMENT VARIABLES ---")
    print(f"ANTIGRAVITY_LS_ADDRESS: {os.environ.get('ANTIGRAVITY_LS_ADDRESS')}")
    print(f"ANTIGRAVITY_CSRF_TOKEN: {os.environ.get('ANTIGRAVITY_CSRF_TOKEN')}")
    print(f"VSCODE_IPC_HOOK: {os.environ.get('VSCODE_IPC_HOOK')}")
    print(f"VSCODE_PID: {os.environ.get('VSCODE_PID')}")
    
    # Try connecting to the current LS address
    ls_addr = os.environ.get('ANTIGRAVITY_LS_ADDRESS')
    if ls_addr:
        m = re.search(r'localhost:(\d+)|127\.0\.0\.1:(\d+)', ls_addr)
        if m:
            port = int(m.group(1) or m.group(2))
            connected = check_port('localhost', port)
            print(f"Connection test to ANTIGRAVITY_LS_ADDRESS (port {port}): {'SUCCESS' if connected else 'FAILED'}")
            
    print("\n--- RUNNING LANGUAGE SERVERS ---")
    servers = get_running_servers()
    if isinstance(servers, list):
        for s in servers:
            print(f"PID {s['pid']}:")
            print(f"  Command: {s['cmdline']}")
            print(f"  CSRF Token: {s['csrf_token']}")
            print(f"  Listening Ports: {s['ports']}")
            for p in s['ports']:
                connected = check_port('localhost', p)
                print(f"    Port {p} connection: {'SUCCESS' if connected else 'FAILED'}")
    else:
        print(servers)
        
    print("\n--- RECENT MESSAGE FILES ---")
    if conv_id:
        home_dir = os.path.expanduser('~')
        messages_dir = os.path.join(home_dir, '.gemini', 'antigravity-ide', 'brain', conv_id, '.system_generated', 'messages')
        messages_dir = os.path.normpath(messages_dir)
        print(f"Expected Messages Dir: {messages_dir}")
        if os.path.exists(messages_dir):
            files = [os.path.join(messages_dir, f) for f in os.listdir(messages_dir) if f.endswith('.json')]
            files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
            print(f"Total message files found: {len(files)}")
            for f in files[:3]:
                print(f"File: {os.path.basename(f)} (mtime: {os.path.getmtime(f)})")
                try:
                    with open(f, 'r') as file_h:
                        content = json.load(file_h)
                        print(f"  Sender: {content.get('sender')}")
                        print(f"  Recipient: {content.get('recipient')}")
                        print(f"  Content: {content.get('content')[:100]}...")
                except Exception as fe:
                    print(f"  Error reading file: {fe}")
        else:
            print("Messages directory does not exist.")
    else:
        print("Could not resolve Conversation ID to locate messages folder.")

if __name__ == '__main__':
    main()
