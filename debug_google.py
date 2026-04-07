import json
import base64
import os

def hex_diagnose():
    try:
        with open('google-credentials.json', 'r') as f:
            info = json.load(f)
        
        raw_key = info.get("private_key", "")
        print(f"--- Hex Diagnosis ---")

        # Extract base64 part
        clean_b64 = raw_key.replace("-----BEGIN PRIVATE KEY-----", "").replace("-----END PRIVATE KEY-----", "")
        clean_b64 = "".join(clean_b64.split())
        
        decoded = base64.b64decode(clean_b64)
        print(f"Decoded size: {len(decoded)} bytes")
        
        # Print first 16 bytes and last 16 bytes in HEX
        print(f"First 16 bytes (HEX): {decoded[:16].hex(' ')}")
        print(f"Last 16 bytes (HEX):  {decoded[-16:].hex(' ')}")
        
        # Check for specific ASN.1 markers
        if decoded.startswith(b'\x30\x82'):
            print("Marker found: ASN.1 Sequence (Correct for Private Key)")
        else:
            print("Marker MISSING: ASN.1 Sequence (Key is likely corrupted)")

    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    hex_diagnose()
