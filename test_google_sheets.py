import os
import json
from datetime import datetime
from google.oauth2 import service_account
from googleapiclient.discovery import build

def test_sheets():
    print("--- GOOGLE SHEETS DIAGNOSTIC ---")
    creds_file = 'google-credentials.json'
    spreadsheet_id = "1NWx5XXBokgbqS_Rou0VGu78B4e8OdntXNZvYCGYiZcU"
    
    if not os.path.exists(creds_file):
        print("ERROR: 'google-credentials.json' file is MISSING!")
        return

    try:
        with open(creds_file, 'r') as f:
            creds_data = json.load(f)
        
        email = creds_data.get("client_email")
        print(f"1. Checking Service Account Email: {email}")
        print(f"   IMPORTANT: Make sure YOUR SHEET is shared with this email as EDITOR.")
        
        # Robust Normalize & Rebuild (Matches pharmacy_functions.py logic)
        pk = creds_data.get("private_key", "")
        if pk:
            # Clean quotes and resolve escape sequences
            pk = pk.strip().strip("'").strip('"')
            pk = pk.replace("\\n", "\n").replace("\\\\n", "\n")
            
            # Extract the body (everything between headers)
            body = pk.replace("-----BEGIN PRIVATE KEY-----", "").replace("-----END PRIVATE KEY-----", "")
            # Remove all whitespace, newlines, and non-base64 noise
            body = "".join(body.split())
            
            # Re-wrap to 64 character lines (Standard RSA Format)
            wrapped_body = "\n".join(body[i:i+64] for i in range(0, len(body), 64))
            
            # Final reconstruction
            final_pk = f"-----BEGIN PRIVATE KEY-----\n{wrapped_body}\n-----END PRIVATE KEY-----\n"
            creds_data["private_key"] = final_pk
        
        scopes = ['https://www.googleapis.com/auth/spreadsheets']
        creds = service_account.Credentials.from_service_account_info(creds_data, scopes=scopes)
        service = build('sheets', 'v4', credentials=creds)
        
        # Test 1: Get Metadata (Checks if API is enabled and if ID is valid)
        print("2. Attempting to connect to spreadsheet...")
        sheet_metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        sheets = sheet_metadata.get('sheets', '')
        sheet_names = [s.get("properties", {}).get("title") for s in sheets]
        print(f"   SUCCESS! Connected to spreadsheet. Found tabs: {sheet_names}")
        
        # Test 2: Try to write
        target_tab = "Sheet1"
        if target_tab not in sheet_names:
            print(f"   WARNING: 'Sheet1' not found. Using '{sheet_names[0]}' instead.")
            target_tab = sheet_names[0]
            
        print(f"3. Attempting to write a test row to '{target_tab}'...")
        range_name = f"{target_tab}!A2"
        values = [["DIAGNOSTIC TEST", "PASSED", "Connection Healthy", "-", "-", datetime.now().strftime("%Y-%m-%d %H:%M:%S")]]
        body = {'values': values}
        
        result = service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption="RAW",
            body=body
        ).execute()
        
        print(f"   SUCCESS! {result.get('updates').get('updatedCells')} cells updated.")
        print("\n*** ALL TESTS PASSED! Priya can now update your logs. ***")
        
    except Exception as e:
        print(f"\n!!! FAILED !!!")
        print(f"Error Details: {str(e)}")
        if "403" in str(e):
            print("REASON: Permission Denied. You MUST share the sheet with the email in Step 1.")
        elif "sheets.googleapis.com" in str(e):
            print("REASON: Google Sheets API is DISABLED. Enable it in Google Cloud Console.")
        elif "404" in str(e):
            print("REASON: Spreadsheet ID is WRONG. Please check your .env or script.")

if __name__ == "__main__":
    test_sheets()
