import subprocess
import os
import json

def test_send():
    # Resolve the path dynamically without hardcoding the username 'andre'
    local_app_data = os.environ.get('LOCALAPPDATA', '')
    exe = os.path.join(
        local_app_data, 
        'Programs', 
        'Antigravity IDE', 
        'resources', 
        'app', 
        'extensions', 
        'antigravity', 
        'bin', 
        'language_server_windows_x64.exe'
    )
    
    # Parse the active conversation ID dynamically from the environment metadata
    conv_id = None
    metadata_str = os.environ.get('ANTIGRAVITY_SOURCE_METADATA')
    if metadata_str:
        try:
            metadata = json.loads(metadata_str)
            conv_id = metadata.get('tool', {}).get('conversationId')
        except Exception as e:
            print("Error parsing metadata:", e)
            
    if not conv_id:
        print("Could not find conversation ID in environment.")
        return
        
    print(f"Detected conversation ID: {conv_id}")
    print(f"Using language server binary: {exe}")
    
    # Prefix with [System Message] as requested to verify the visual indicator
    cmd = [exe, "agentapi", "send-message", conv_id, "[System Message] - [SELF TEST] Checking routing"]
    print('Running cmd:', cmd)
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print('Success:\n', res.stdout)
    except subprocess.CalledProcessError as e:
        print('Error:\nstdout:', e.stdout, '\nstderr:', e.stderr)

if __name__ == '__main__':
    test_send()
