import os
import json
import smtplib
import traceback
import audioop
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

# In-memory storage
APPOINTMENTS_DB = {"appointments": {}, "next_id": 1}

# Available slots (day: [time slots])
AVAILABLE_SLOTS = {
    "Monday":    ["10:00 AM", "11:00 AM", "12:00 PM", "5:00 PM", "6:00 PM"],
    "Tuesday":   ["10:00 AM", "11:00 AM", "12:00 PM", "5:00 PM", "6:00 PM"],
    "Wednesday": ["10:00 AM", "11:00 AM", "12:00 PM", "5:00 PM", "6:00 PM"],
    "Thursday":  ["10:00 AM", "11:00 AM", "12:00 PM", "5:00 PM", "6:00 PM"],
    "Friday":    ["10:00 AM", "11:00 AM", "12:00 PM", "5:00 PM", "6:00 PM"],
    "Saturday":  ["9:00 AM", "10:00 AM", "11:00 AM", "12:00 PM"],
}

def get_google_creds():
    """Load Google service account credentials. Tries env var first, then credentials file."""
    # Try loading from google-credentials.json file first (most reliable)
    creds_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "google-credentials.json")
    if os.path.exists(creds_file):
        try:
            with open(creds_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"WARNING: Could not load google-credentials.json: {e}")

    # Fall back to GOOGLE_CREDENTIALS env var
    creds_json = os.getenv("GOOGLE_CREDENTIALS", "").strip()
    if not creds_json:
        return None

    try:
        if (creds_json.startswith("'") and creds_json.endswith("'")) or (creds_json.startswith('"') and creds_json.endswith('"')):
            creds_json = creds_json[1:-1]

        data = json.loads(creds_json)

        pk = data.get("private_key", "")
        if pk:
            pk = pk.replace("\\n", "\n")
            pk = pk.replace("\\\\n", "\n")
            data["private_key"] = pk.strip()

        return data
    except Exception as e:
        print(f"WARNING: Credential Parse Error: {e}")
        return None

def generate_ics(appt):
    """Generate a standard iCalendar (.ics) string."""
    start_dt = get_appointment_datetime(appt["preferred_day"], appt["preferred_time"])
    end_dt = start_dt + timedelta(minutes=30)
    
    dtstamp = datetime.now().strftime("%Y%m%dT%H%M%SZ")
    dtstart = start_dt.strftime("%Y%m%dT%H%M%S")
    dtend = end_dt.strftime("%Y%m%dT%H%M%S")
    
    ics = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Neha Child Care//Clinic Assistant//EN",
        "METHOD:REQUEST",
        "BEGIN:VEVENT",
        f"UID:{appt['id']}@nehachildcare.com",
        f"DTSTAMP:{dtstamp}",
        f"DTSTART;TZID=Asia/Kolkata:{dtstart}",
        f"DTEND;TZID=Asia/Kolkata:{dtend}",
        f"SUMMARY:Appointment: {appt['patient_name']}",
        f"DESCRIPTION:Parent: {appt['parent_name']}\\nReason: {appt['reason']}\\nContact: {appt['contact_number']}",
        "LOCATION:Neha Child Care Clinic",
        "STATUS:CONFIRMED",
        "SEQUENCE:0",
        "BEGIN:VALARM",
        "TRIGGER:-PT30M",
        "ACTION:DISPLAY",
        "DESCRIPTION:Reminder",
        "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR"
    ]
    return "\n".join(ics)

def get_appointment_datetime(day_name, time_str):
    """Convert 'Monday' and '10:00 AM' to a datetime object for the upcoming week."""
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    target_day = days.index(day_name.capitalize())
    
    current_dt = datetime.now()
    current_day = current_dt.weekday()
    
    days_ahead = target_day - current_day
    if days_ahead <= 0: days_ahead += 7
    
    target_date = current_dt + timedelta(days=days_ahead)
    time_dt = datetime.strptime(time_str, "%I:%M %p")
    
    return target_date.replace(hour=time_dt.hour, minute=time_dt.minute, second=0, microsecond=0)

def update_booking_sheet(patient_name, problems, parents_name, contact_number, booking_time):
    """Append a new row to the Google Sheets booking log with detailed error reporting."""
    try:
        creds_data = get_google_creds()
        if not creds_data: return {"error": "Credentials missing"}
        
        scopes = ['https://www.googleapis.com/auth/spreadsheets']
        creds = service_account.Credentials.from_service_account_info(creds_data, scopes=scopes)
        service = build('sheets', 'v4', credentials=creds)
        
        spreadsheet_id = "1T5FLtmFUu0-VWpa8KT_c3BP8BcDKjZuco3tHDeDRbyo"
        range_name = "Sheet1!A2" 
        
        values = [[
            patient_name,
            problems,
            parents_name,
            contact_number,
            "Yes",
            booking_time
        ]]
        
        result = service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={'values': values}
        ).execute()
        
        return {"success": True, "updated": result.get('updates', {}).get('updatedCells')}
    except Exception as e:
        print(f"SHEETS ERROR: {e}")
        return {"error": str(e)}

def create_google_calendar_event(appt):
    """Invite the doctor via Service Account to ensure calendar visibility."""
    try:
        creds_data = get_google_creds()
        if not creds_data: return {"error": "Credentials missing"}
        
        scopes = ['https://www.googleapis.com/auth/calendar']
        creds = service_account.Credentials.from_service_account_info(creds_data, scopes=scopes)
        service = build('calendar', 'v3', credentials=creds)
        
        start_dt = get_appointment_datetime(appt["preferred_day"], appt["preferred_time"])
        end_dt = start_dt + timedelta(minutes=30)
        
        event = {
            'summary': f'Appointment: {appt["patient_name"]}',
            'description': f'Parent: {appt["parent_name"]}\nContact: {appt["contact_number"]}\nReason: {appt["reason"]}',
            'start': {'dateTime': start_dt.isoformat(), 'timeZone': 'Asia/Kolkata'},
            'end': {'dateTime': end_dt.isoformat(), 'timeZone': 'Asia/Kolkata'},
        }

        calendar_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")
        event_result = service.events().insert(calendarId=calendar_id, body=event).execute()
        return event_result
    except Exception as e:
        print(f"CALENDAR ERROR: {e}")
        return {"error": str(e)}

def book_appointment(patient_name, patient_age, parent_name, contact_number, preferred_day, preferred_time, reason):
    """Master booking function for Neha Child Care with honest reporting."""
    print(f"\n[DIGITAL_LOG]: Processing booking for {patient_name}...")
    
    appt_id = APPOINTMENTS_DB["next_id"]
    APPOINTMENTS_DB["next_id"] += 1
    
    appt = {
        "id": appt_id, "patient_name": patient_name, "patient_age": patient_age,
        "parent_name": parent_name, "contact_number": contact_number,
        "preferred_day": preferred_day, "preferred_time": preferred_time,
        "reason": reason, "clinic": "Neha Child Care"
    }
    
    # 🏃 1. Update Sheets
    sheet_res = update_booking_sheet(patient_name, reason, parent_name, contact_number, datetime.now().strftime("%Y-%m-%d %H:%M"))
    
    # 🏃 2. Update Calendar
    cal_res = create_google_calendar_event(appt)
    
    # 🏃 3. Send Email with ICS Attachment
    email_res = send_confirmation_email_with_ics(appt)
    
    # Check for underlying failures
    if "error" in sheet_res or "error" in cal_res:
        return {
            "success": False,
            "message": f"BOOKING_PARTIAL_FAILURE: Shets/Calendar update handle nahi paya. Check terminal.",
            "sheets_status": sheet_res.get("error", "OK"),
            "calendar_status": cal_res.get("error", "OK")
        }
    
    return {
        "success": True,
        "message": f"Appointment successfully booked and synced! ID: {appt_id}.",
        "details": appt
    }

def send_confirmation_email_with_ics(appt):
    """Send appointment email with an attached .ics file."""
    try:
        gmail_user = os.getenv("GMAIL_USER")
        gmail_password = os.getenv("GMAIL_APP_PASSWORD")
        doctor_email = os.getenv("DOCTOR_EMAIL")
        
        msg = MIMEMultipart()
        msg['From'] = f"Clinic Assistant <{gmail_user}>"
        msg['To'] = doctor_email
        msg['Subject'] = f"Appointment Booked: {appt['patient_name']}"
        
        body = f"Appointment confirmed for {appt['patient_name']} on {appt['preferred_day']} at {appt['preferred_time']}."
        msg.attach(MIMEText(body, 'plain'))
        
        # Add ICS Attachment
        ics_content = generate_ics(appt)
        part = MIMEBase('text', 'calendar', method='REQUEST', name='invite.ics')
        part.set_payload(ics_content)
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', 'attachment; filename="invite.ics"')
        msg.attach(part)
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(gmail_user, gmail_password)
        server.send_message(msg)
        server.quit()
        return {"success": True}
    except Exception as e:
        print(f"EMAIL ERROR: {e}")
        return {"error": str(e)}

def send_call_summary_email(summary, transcript):
    """Standard call summary email."""
    try:
        gmail_user = os.getenv("GMAIL_USER")
        gmail_password = os.getenv("GMAIL_APP_PASSWORD")
        doctor_email = os.getenv("DOCTOR_EMAIL")
        
        msg = MIMEMultipart()
        msg['From'] = f"Priya Assistant <{gmail_user}>"
        msg['To'] = doctor_email
        msg['Subject'] = f"Call Summary: Neha Child Care"
        
        body = f"Summary: {summary}\n\nTranscript:\n{transcript}"
        msg.attach(MIMEText(body, 'plain'))
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(gmail_user, gmail_password)
        server.send_message(msg)
        server.quit()
        return {"success": True}
    except Exception as e:
        return {"error": str(e)}

def check_available_slots(preferred_day):
    day = preferred_day.strip().capitalize()
    slots = AVAILABLE_SLOTS.get(day, [])
    return {"day": day, "available_slots": slots}

def _get_sheets_service():
    creds_data = get_google_creds()
    if not creds_data: return None, None
    creds = service_account.Credentials.from_service_account_info(
        creds_data, scopes=['https://www.googleapis.com/auth/spreadsheets'])
    return build('sheets', 'v4', credentials=creds), "1T5FLtmFUu0-VWpa8KT_c3BP8BcDKjZuco3tHDeDRbyo"

def _get_calendar_service():
    creds_data = get_google_creds()
    if not creds_data: return None
    creds = service_account.Credentials.from_service_account_info(
        creds_data, scopes=['https://www.googleapis.com/auth/calendar'])
    return build('calendar', 'v3', credentials=creds)

def _find_sheet_rows(patient_name, contact_number):
    """Return list of (row_index, row_data) matching patient_name or contact_number."""
    service, spreadsheet_id = _get_sheets_service()
    if not service: return []
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range="Sheet1!A:F").execute()
    rows = result.get('values', [])
    matches = []
    for i, row in enumerate(rows[1:], start=2):  # skip header
        name_match = len(row) > 0 and patient_name.lower() in row[0].lower()
        phone_match = len(row) > 3 and contact_number and row[3] == str(contact_number)
        if name_match or phone_match:
            matches.append((i, row))
    return matches

def _delete_calendar_events(patient_name):
    """Delete all upcoming calendar events matching patient name."""
    service = _get_calendar_service()
    if not service: return 0
    calendar_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")
    now = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    events = service.events().list(
        calendarId=calendar_id, q=f"Appointment: {patient_name}",
        timeMin=now, maxResults=10, singleEvents=True).execute()
    deleted = 0
    for event in events.get('items', []):
        if f"Appointment: {patient_name}" in event.get('summary', ''):
            service.events().delete(calendarId=calendar_id, eventId=event['id']).execute()
            deleted += 1
    return deleted

def cancel_appointment(patient_name, contact_number):
    """Cancel an existing appointment by patient name."""
    print(f"\n[DIGITAL_LOG]: Cancelling appointment for {patient_name}...")
    try:
        service, spreadsheet_id = _get_sheets_service()
        rows = _find_sheet_rows(patient_name, contact_number)
        if not rows:
            return {"success": False, "message": f"Koi appointment nahi mili '{patient_name}' ke liye. Kya naam sahi hai?"}

        # Mark as Cancelled in sheet
        for row_idx, _ in rows:
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f"Sheet1!E{row_idx}",
                valueInputOption="RAW",
                body={'values': [["Cancelled"]]}
            ).execute()

        # Delete from calendar
        deleted = _delete_calendar_events(patient_name)
        print(f"[DIGITAL_LOG]: Cancelled {len(rows)} sheet rows, {deleted} calendar events.")
        return {"success": True, "message": f"{patient_name} ki appointment cancel ho gayi hai."}
    except Exception as e:
        print(f"CANCEL ERROR: {e}")
        return {"error": str(e)}

def reschedule_appointment(patient_name, contact_number, new_day, new_time):
    """Reschedule an existing appointment to a new day and time."""
    print(f"\n[DIGITAL_LOG]: Rescheduling appointment for {patient_name} to {new_day} {new_time}...")
    try:
        # Get old appointment details from sheet
        rows = _find_sheet_rows(patient_name, contact_number)
        if not rows:
            return {"success": False, "message": f"Koi appointment nahi mili '{patient_name}' ke liye."}

        _, old_row = rows[0]
        reason = old_row[1] if len(old_row) > 1 else "Reschedule"

        # Cancel old
        cancel_appointment(patient_name, contact_number)

        # Book new
        result = book_appointment(
            patient_name=patient_name,
            patient_age="",
            parent_name=patient_name,
            contact_number=contact_number,
            preferred_day=new_day,
            preferred_time=new_time,
            reason=reason
        )
        if result.get("success"):
            return {"success": True, "message": f"{patient_name} ki appointment reschedule ho gayi! {new_day} ko {new_time} baje."}
        return result
    except Exception as e:
        print(f"RESCHEDULE ERROR: {e}")
        return {"error": str(e)}

FUNCTION_MAP = {
    "check_available_slots": check_available_slots,
    "book_appointment": book_appointment,
    "cancel_appointment": cancel_appointment,
    "reschedule_appointment": reschedule_appointment
}
