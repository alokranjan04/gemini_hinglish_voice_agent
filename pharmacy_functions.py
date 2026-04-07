import os
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
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


def check_available_slots(preferred_day: str):
    """Check available appointment slots for a given day."""
    day = preferred_day.strip().capitalize()
    if day == "Sunday":
        return {"error": "Clinic is closed on Sundays. Monday se Saturday tak available hain."}
    slots = AVAILABLE_SLOTS.get(day)
    if not slots:
        return {"error": f"'{preferred_day}' ek valid weekday nahi hai. Please Monday to Saturday mein se choose karein."}
    
    # Filter out already booked slots for that day
    booked = [
        a["preferred_time"]
        for a in APPOINTMENTS_DB["appointments"].values()
        if a["preferred_day"].capitalize() == day and a["status"] == "confirmed"
    ]
    available = [s for s in slots if s not in booked]
    
    if not available:
        return {"message": f"{day} ko koi slot available nahi hai. Kisi aur din try karein.", "available_slots": []}
    
    slots_str = ", ".join(available)
    return {
        "day": day,
        "available_slots": available,
        "message": f"{day} ko ye slots available hain: {slots_str}. Aap inmein se koi select kar sakte hain."
    }


def book_appointment(patient_name: str, patient_age: str, parent_name: str,
                     contact_number: str, preferred_day: str, preferred_time: str,
                     reason: str):
    """Book an appointment at Neha Child Care clinic."""
    day = preferred_day.strip().capitalize()

    if day == "Sunday":
        return {"error": "Sunday ko clinic band hai. Koi aur din select karein."}

    if day not in AVAILABLE_SLOTS:
        return {"error": f"'{preferred_day}' valid nahi hai. Monday to Saturday mein se choose karein."}

    if preferred_time not in AVAILABLE_SLOTS.get(day, []):
        return {"error": f"{preferred_time} is din ke liye valid slot nahi hai.",
                "available_slots": AVAILABLE_SLOTS.get(day, [])}

    # Check if slot is already taken
    for appt in APPOINTMENTS_DB["appointments"].values():
        if (appt["preferred_day"].capitalize() == day and
                appt["preferred_time"] == preferred_time and
                appt["status"] == "confirmed"):
            return {"error": f"{day} {preferred_time} ka slot already booked hai. Koi aur time choose karein.",
                    "available_slots": [s for s in AVAILABLE_SLOTS[day] if s != preferred_time]}

    appt_id = APPOINTMENTS_DB["next_id"]
    APPOINTMENTS_DB["next_id"] += 1

    appointment = {
        "id": appt_id,
        "patient_name": patient_name,
        "patient_age": patient_age,
        "parent_name": parent_name,
        "contact_number": contact_number,
        "preferred_day": day,
        "preferred_time": preferred_time,
        "reason": reason,
        "status": "confirmed",
        "clinic": "Neha Child Care"
    }
    APPOINTMENTS_DB["appointments"][appt_id] = appointment

    print(f"DEBUG: Appointment object created with ID {appt_id}. Starting integrations...")

    # --- NEW: Google Calendar and Email Integration ---
    calendar_status = "Not attempted"
    email_status = "Not attempted"

    try:
        # 1. Create Calendar Event
        print(f"DEBUG: Attempting to create Google Calendar event for {patient_name}...")
        event_result = create_google_calendar_event(appointment)
        if "id" in event_result:
            calendar_status = "Success"
            print(f"SUCCESS: Calendar event created: {event_result.get('htmlLink')}")
        else:
            calendar_status = f"Failed: {event_result.get('error')}"
            print(f"FAILURE: Calendar event failed: {calendar_status}")
    except Exception as e:
        calendar_status = f"Error: {str(e)}"
        print(f"CRITICAL ERROR in Calendar Integration: {e}")

    try:
        # 2. Send Email to Doctor
        print(f"DEBUG: Sending confirmation email to doctor...")
        email_result = send_confirmation_email(appointment)
        if email_result.get("success"):
            email_status = "Success"
            print("SUCCESS: Confirmation email sent to doctor.")
        else:
            email_status = f"Failed: {email_result.get('error')}"
            print(f"FAILURE: Email failed: {email_status}")
    except Exception as e:
        email_status = f"Error: {str(e)}"
        print(f"CRITICAL ERROR in Email Integration: {e}")

    try:
        # 3. Update Google Sheets Instantly (Final Success Pillar)
        print(f"DEBUG: Updating Google Sheets log for {patient_name}...")
        sheet_result = update_booking_sheet(
            name=patient_name,
            patient_name=patient_name,
            problems=reason,
            parents_name=parent_name,
            is_booked=True,
            booking_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        if sheet_result.get("success"):
            print("SUCCESS: Google Sheets log updated.")
        else:
            print(f"FAILURE: Google Sheets failed: {sheet_result.get('error')}")
    except Exception as e:
        print(f"CRITICAL ERROR in Google Sheets Integration: {e}")

    return {
        "appointment_id": appt_id,
        "message": f"Appointment successfully book ho gayi! Appointment ID hai {appt_id}.",
        "patient_name": patient_name,
        "parent_name": parent_name,
        "day": day,
        "time": preferred_time,
        "clinic": "Neha Child Care",
        "calendar_status": calendar_status,
        "email_status": email_status,
        "reminder": "Please apna appointment ID yaad rakhein. 15 minute pehle clinic aa jayein."
    }


def get_appointment_datetime(day_name: str, time_str: str):
    """Helper to convert 'Monday' and '11:00 AM' to a datetime object for the NEXT occurrence."""
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    try:
        target_day = days.index(day_name.capitalize())
    except:
        # Fallback if AI passes something else
        target_day = datetime.now().weekday()
    
    now = datetime.now()
    current_day = now.weekday()
    
    days_ahead = target_day - current_day
    
    # If the day is today, check if the time has passed
    if days_ahead < 0:
        days_ahead += 7
    elif days_ahead == 0:
        # Check if the requested time is still in the future for today
        try:
            time_obj = datetime.strptime(time_str, "%I:%M %p")
            if now.hour > time_obj.hour or (now.hour == time_obj.hour and now.minute >= time_obj.minute):
                days_ahead = 7 # Push to next week
            else:
                days_ahead = 0 # It's for today!
        except:
            days_ahead = 7

    target_date = now + timedelta(days=days_ahead)
    
    # Parse time (e.g., "11:00 AM")
    try:
        time_obj = datetime.strptime(time_str, "%I:%M %p")
    except:
        time_obj = datetime.now().replace(hour=11, minute=0)

    final_dt = target_date.replace(hour=time_obj.hour, minute=time_obj.minute, second=0, microsecond=0)
    return final_dt


def create_google_calendar_event(appt):
    """Create an event in Google Calendar using a Service Account JSON file."""
    try:
        # Path to Service Account JSON
        creds_file = 'google-credentials.json'
        if not os.path.exists(creds_file):
            return {"error": "google-credentials.json file missing"}
        
        # Load and clean JSON manually for maximum Windows reliability
        with open(creds_file, 'r') as f:
            creds_data = json.load(f)
        
        # Scrub the private key
        key = creds_data.get("private_key", "")
        if "\\n" in key:
            key = key.replace("\\n", "\n")
        creds_data["private_key"] = key.strip()

        scopes = ['https://www.googleapis.com/auth/calendar']
        creds = service_account.Credentials.from_service_account_info(creds_data, scopes=scopes)
        service = build('calendar', 'v3', credentials=creds)

        start_dt = get_appointment_datetime(appt["preferred_day"], appt["preferred_time"])
        end_dt = start_dt + timedelta(minutes=30)

        event = {
            'summary': f'Appointment: {appt["patient_name"]} ({appt["clinic"]})',
            'location': 'Neha Child Care Clinic',
            'description': f'Patient: {appt["patient_name"]}\nAge: {appt["patient_age"]}\nParent: {appt["parent_name"]}\nContact: {appt["contact_number"]}\nReason: {appt["reason"]}',
            'start': {
                'dateTime': start_dt.isoformat(),
                'timeZone': 'Asia/Kolkata',
            },
            'end': {
                'dateTime': end_dt.isoformat(),
                'timeZone': 'Asia/Kolkata',
            },
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'email', 'minutes': 24 * 60},
                    {'method': 'popup', 'minutes': 30},
                ],
            },
        }

        calendar_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")
        event = service.events().insert(calendarId=calendar_id, body=event).execute()
        print(f"Event created: {event.get('htmlLink')}")
        return event

    except Exception as e:
        print(f"Error creating calendar event: {e}")
        return {"error": str(e)}


def send_confirmation_email(appt):
    """Send HTML confirmation email to the doctor."""
    try:
        gmail_user = os.getenv("GMAIL_USER")
        gmail_password = os.getenv("GMAIL_APP_PASSWORD")
        doctor_email = os.getenv("DOCTOR_EMAIL", gmail_user)

        if not gmail_user or not gmail_password:
            return {"error": "Email credentials missing in .env"}

        msg = MIMEMultipart()
        msg['From'] = f"Clinic Assistant <{gmail_user}>"
        msg['To'] = doctor_email
        msg['Subject'] = f"New Appointment: {appt['patient_name']} for {appt['preferred_day']}"

        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 10px;">
                <h2 style="color: #007bff; border-bottom: 2px solid #007bff; padding-bottom: 10px;">New Appointment Request</h2>
                <p>Hello Doctor, you have a new appointment scheduled:</p>
                
                <table style="width: 100%; border-collapse: collapse;">
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Patient Name:</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee;">{appt['patient_name']}</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Age:</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee;">{appt['patient_age']}</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Parent Name:</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee;">{appt['parent_name']}</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Contact:</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee;">{appt['contact_number']}</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Day & Time:</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee;">{appt['preferred_day']} at {appt['preferred_time']}</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><strong>Reason:</strong></td><td style="padding: 8px; border-bottom: 1px solid #eee;">{appt['reason']}</td></tr>
                </table>
                
                <p style="margin-top: 20px; font-size: 12px; color: #777;">This is an automated notification from your Voice AI Assistant.</p>
            </div>
        </body>
        </html>
        """
        
        msg.attach(MIMEText(html, 'html'))

        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(gmail_user, gmail_password)
        server.send_message(msg)
        server.quit()

        return {"success": True}

    except Exception as e:
        print(f"Error sending email: {e}")
        return {"error": str(e)}


def send_call_summary_email(summary: str, transcript: str):
    """Send post-call analytic report to the doctor."""
    try:
        gmail_user = os.getenv("GMAIL_USER")
        gmail_password = os.getenv("GMAIL_APP_PASSWORD")
        doctor_email = os.getenv("DOCTOR_EMAIL", gmail_user)

        if not gmail_user or not gmail_password:
            return {"error": "Email credentials missing in .env"}

        msg = MIMEMultipart()
        msg['From'] = f"Clinic Voice AI <{gmail_user}>"
        msg['To'] = doctor_email
        msg['Subject'] = f"Call Summary: Neha Child Care Agent - {datetime.now().strftime('%d %b %I:%M %p')}"

        # Format transcript with line breaks
        formatted_transcript = transcript.replace("\n", "<br>")

        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 650px; margin: 0 auto; padding: 25px; border: 1px solid #eee; border-radius: 12px; box-shadow: 0 4px 10px rgba(0,0,0,0.05);">
                <h2 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px;">Post-Call Analytics Report</h2>
                
                <section style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin-bottom: 20px;">
                    <h3 style="color: #3498db; margin-top: 0;">AI Summary</h3>
                    <p style="font-size: 15px; color: #444;">{summary}</p>
                </section>

                <section>
                    <h3 style="color: #3498db;">Full Transcript</h3>
                    <div style="background: #ffffff; border-left: 4px solid #3498db; padding: 10px 15px; font-size: 14px; color: #666; max-height: 400px; overflow-y: auto;">
                        {formatted_transcript}
                    </div>
                </section>
                
                <p style="margin-top: 30px; font-size: 11px; color: #999; text-align: center;">
                    Generated by Gemini 3.1 Multimodal Live API • Neha Child Care Clinic
                </p>
            </div>
        </body>
        </html>
        """
        
        msg.attach(MIMEText(html, 'html'))

        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(gmail_user, gmail_password)
        server.send_message(msg)
        server.quit()

        print(f"Post-call summary sent to {doctor_email}")
        return {"success": True}

    except Exception as e:
        print(f"Error sending summary email: {e}")
        return {"error": str(e)}


def update_booking_sheet(name, patient_name, problems, parents_name, is_booked, booking_time):
    """Append a new row to the Google Sheets booking log."""
    try:
        creds_file = 'google-credentials.json'
        if not os.path.exists(creds_file):
            return {"error": "google-credentials.json file missing"}
        
        with open(creds_file, 'r') as f:
            creds_data = json.load(f)
        
        key = creds_data.get("private_key", "").replace("\\n", "\n").strip()
        creds_data["private_key"] = key
        
        scopes = ['https://www.googleapis.com/auth/spreadsheets']
        creds = service_account.Credentials.from_service_account_info(creds_data, scopes=scopes)
        service = build('sheets', 'v4', credentials=creds)
        
        spreadsheet_id = "1T5FLtmFUu0-VWpa8KT_c3BP8BcDKjZuco3tHDeDRbyo"
        range_name = "Sheet1!A2" # Appends to the next available row
        
        values = [[
            name or "Unknown",
            patient_name or "N/A",
            problems or "N/A",
            parents_name or "N/A",
            "Yes" if is_booked else "No",
            booking_time or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ]]
        
        body = {'values': values}
        result = service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption="RAW",
            body=body
        ).execute()
        
        print(f"Google Sheets updated: {result.get('updates').get('updatedCells')} cells updated.")
        return {"success": True}

    except Exception as e:
        print(f"Error updating Google Sheets: {e}")
        return {"error": str(e)}


def check_appointment(appointment_id: int):
    """Check details of an existing appointment."""
    appt = APPOINTMENTS_DB["appointments"].get(int(appointment_id))
    if appt:
        return {
            "appointment_id": appt["id"],
            "patient_name": appt["patient_name"],
            "patient_age": appt["patient_age"],
            "parent_name": appt["parent_name"],
            "contact_number": appt["contact_number"],
            "day": appt["preferred_day"],
            "time": appt["preferred_time"],
            "reason": appt["reason"],
            "status": appt["status"],
            "clinic": "Neha Child Care"
        }
    return {"error": f"Appointment ID {appointment_id} nahi mila. Please sahi ID check karein."}


def cancel_appointment(appointment_id: int):
    """Cancel an existing appointment."""
    appt = APPOINTMENTS_DB["appointments"].get(int(appointment_id))
    if not appt:
        return {"error": f"Appointment ID {appointment_id} nahi mila."}
    if appt["status"] == "cancelled":
        return {"message": f"Appointment {appointment_id} pehle se hi cancel hai."}

    APPOINTMENTS_DB["appointments"][int(appointment_id)]["status"] = "cancelled"
    return {
        "message": f"Appointment {appointment_id} successfully cancel ho gayi.",
        "patient_name": appt["patient_name"],
        "day": appt["preferred_day"],
        "time": appt["preferred_time"]
    }


# Function mapping
FUNCTION_MAP = {
    "check_available_slots": check_available_slots,
    "book_appointment": book_appointment,
    "check_appointment": check_appointment,
    "cancel_appointment": cancel_appointment,
}
