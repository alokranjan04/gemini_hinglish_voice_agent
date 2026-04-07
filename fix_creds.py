import shutil
import os
import glob

def fix():
    # Try to find the JSON file in Downloads
    downloads = os.path.join(os.environ['USERPROFILE'], 'Downloads')
    pattern = os.path.join(downloads, 'ai-voice-agent-c2a2b-*.json')
    files = glob.glob(pattern)

    if files:
        # Sort by modification time to get the newest one
        files.sort(key=os.path.getmtime, reverse=True)
        source = files[0]
        target = 'google-credentials.json'
        
        # Copy the file
        shutil.copy(source, target)
        print(f"SUCCESS: Copied {source}")
        print(f"Target: {os.path.abspath(target)}")
    else:
        print(f"ERROR: No matching file found in {downloads}")
        print(f"Please make sure the file 'ai-voice-agent-c2a2b-...' is in your Downloads folder.")

if __name__ == "__main__":
    fix()
