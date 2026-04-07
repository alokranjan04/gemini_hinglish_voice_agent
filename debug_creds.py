import os
import json
from dotenv import load_dotenv

load_dotenv()

def debug_google_creds():
    print("--- 🕵️‍♂️ CREDENTIAL DIAGNOSTIC ---")
    creds_json = os.getenv("GOOGLE_CREDENTIALS")
    
    if not creds_json:
        print("❌ ERROR: GOOGLE_CREDENTIALS not found in .env")
        return

    # Check for wrapping quotes
    if (creds_json.startswith("'") and creds_json.endswith("'")) or (creds_json.startswith('"') and creds_json.endswith('"')):
        print("⚠️ NOTICE: Credentials have extra wrapping quotes. Removing them...")
        creds_json = creds_json[1:-1]

    try:
        data = json.loads(creds_json)
        print("✅ JSON: Successfully parsed.")
        
        pk = data.get("private_key", "")
        print(f"📏 KEY LENGTH: {len(pk)} chars")
        
        if "-----BEGIN PRIVATE KEY-----" in pk:
            print("✅ HEADER: Found.")
        else:
            print("❌ HEADER: Missing!")
            
        if "\\n" in pk:
            print("⚠️ ISSUE: Literal '\\n' strings found instead of actual newlines.")
        
        if "\n" in pk:
            print("✅ NEWLINES: Actual newlines detected.")
            
    except Exception as e:
        print(f"❌ JSON ERROR: {e}")
        print(f"First 50 chars of string: {creds_json[:50]}...")

if __name__ == "__main__":
    debug_google_creds()
