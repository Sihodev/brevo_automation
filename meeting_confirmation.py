#!/usr/bin/env python3
"""
Simple Meeting Confirmation Handler
Sends confirmation messages when meetings are booked via Brevo webhooks
"""

from flask import Flask, request, jsonify
import requests
import logging
import json
from datetime import datetime, timedelta
import hashlib
import threading
import time
import os

# Import configuration

AISENSY_URL = "https://backend.aisensy.com/campaign/t2/api/v2"
AISENSY_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjY4Y2FhNjRhOTQyMjZkMGMzMGJlZGYxNyIsIm5hbWUiOiJTSUhPIFJlc2VhcmNoIDcwNzkiLCJhcHBOYW1lIjoiQWlTZW5zeSIsImNsaWVudElkIjoiNjhjYWE2NGE5NDIyNmQwYzMwYmVkZjEyIiwiYWN0aXZlUGxhbiI6IlBST19RVUFSVEVSTFkiLCJpYXQiOjE3NTg4OTEyOTV9.8xemmqyOMd63--d2XTewXwEwfxleFnhLjPFhUK61_2o"

# Set campaign name - try from config first, then fallback
MEETING_CONFIRMATION_CAMPAIGN = "1on1 Booked"
MEETING_REMINDER_CAMPAIGN = "1hour Reminder 1on1"

# JSON file for storing reminders
REMINDERS_JSON_FILE = "meeting_reminders.json"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('meeting_confirmation.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize reminders JSON file
def init_reminders_file():
    """Initialize JSON file for storing reminder schedules"""
    if not os.path.exists(REMINDERS_JSON_FILE):
        with open(REMINDERS_JSON_FILE, 'w') as f:
            json.dump([], f)
        logger.info(f"Created reminders file: {REMINDERS_JSON_FILE}")

# Initialize reminders file
init_reminders_file()

# Reminder scheduler class
class ReminderScheduler:
    def __init__(self):
        self.is_running = False
        self.scheduler_thread = None
        logger.info("Reminder Scheduler initialized")
    
    def start_scheduler(self):
        """Start the reminder scheduler in background"""
        if not self.is_running:
            self.is_running = True
            self.scheduler_thread = threading.Thread(target=self._reminder_loop)
            self.scheduler_thread.daemon = True
            self.scheduler_thread.start()
            logger.info("Reminder scheduler started")
    
    def stop_scheduler(self):
        """Stop the reminder scheduler"""
        self.is_running = False
        logger.info("Reminder scheduler stopped")
    
    def _reminder_loop(self):
        """Main loop for checking and sending reminders"""
        logger.info("Reminder scheduler loop started")
        
        while self.is_running:
            try:
                self._check_and_send_reminders()
                time.sleep(60)  # Check every minute
            except Exception as e:
                logger.error(f"Error in reminder loop: {str(e)}")
                time.sleep(60)
        
        logger.info("Reminder scheduler loop stopped")
    
    def _check_and_send_reminders(self):
        """Check for reminders that need to be sent"""
        try:
            # Load reminders from JSON file
            reminders = self._load_reminders()
            
            if not reminders:
                return
            
            current_time = datetime.now()
            reminders_to_send = []
            
            # Find reminders that should be sent now (1 hour 20 minutes before meeting)
            for reminder in reminders:
                if reminder.get('reminder_sent', False):
                    continue
                
                meeting_datetime_str = reminder.get('meeting_datetime')
                if not meeting_datetime_str:
                    continue
                
                try:
                    meeting_datetime = datetime.fromisoformat(meeting_datetime_str)
                    reminder_time = meeting_datetime - timedelta(hours=1, minutes=00)
                    
                    # Check if it's time to send reminder (within 30-minute window for overdue reminders)
                    time_diff = abs((current_time - reminder_time).total_seconds())
                    
                    # Send reminder if:
                    # 1. Within 1 minute of reminder time (normal case), OR
                    # 2. Past reminder time but within 30 minutes (overdue case)
                    if time_diff <= 60 or (current_time >= reminder_time and time_diff <= 1800):
                        reminders_to_send.append(reminder)
                        if time_diff > 60:
                            logger.info(f"Sending overdue reminder for {reminder.get('name', 'Unknown')} - {time_diff/60:.1f} minutes past reminder time")
                        
                except Exception as e:
                    logger.error(f"Error parsing meeting datetime {meeting_datetime_str}: {str(e)}")
                    continue
            
            # Send reminders
            for reminder in reminders_to_send:
                success = self._send_reminder_message(
                    reminder['phone'],
                    reminder['name'],
                    datetime.fromisoformat(reminder['meeting_datetime']),
                    reminder['meeting_link']
                )
                
                if success:
                    # Mark as sent
                    reminder['reminder_sent'] = True
                    reminder['reminder_sent_at'] = current_time.isoformat()
                    logger.info(f"Reminder sent successfully for {reminder['name']} ({reminder['phone']})")
                else:
                    logger.error(f"Failed to send reminder for {reminder['name']} ({reminder['phone']})")
            
            # Save updated reminders back to JSON file
            if reminders_to_send:
                self._save_reminders(reminders)
            
        except Exception as e:
            logger.error(f"Error checking reminders: {str(e)}")
    
    def _send_reminder_message(self, phone: str, name: str, meeting_datetime: datetime, meeting_link: str) -> bool:
        """Send reminder message via AISensy"""
        try:
            if not phone:
                logger.error("No phone number provided for reminder")
                return False
            
            # Ensure phone number has + prefix
            if not phone.startswith('+'):
                phone = '+' + phone
            
            # Format meeting time
            date = meeting_datetime.strftime("%Y-%m-%d")
            time = meeting_datetime.strftime("%I:%M %p")
            
            # Create payload for AISensy
            payload = {
                "apiKey": AISENSY_API_KEY,
                "campaignName": MEETING_REMINDER_CAMPAIGN,
                "destination": phone,
                "userName": "Skand",
                "templateParams": [name, time, meeting_link]  # Only Name, Time, and Link for reminder
            }
            
            logger.info(f"Sending meeting reminder to {phone} for {name}")
            logger.info(f"Meeting details: Date: {date}, Time: {time}, Link: {meeting_link}")
            
            # Send reminder message
            response = requests.post(AISENSY_URL, json=payload, timeout=30)
            
            if response.status_code == 200:
                logger.info(f"Meeting reminder sent successfully to {phone}")
                return True
            else:
                logger.error(f"Failed to send reminder to {phone}. Status: {response.status_code}, Response: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Error sending reminder to {phone}: {str(e)}")
            return False
    
    def schedule_reminder(self, webhook_id: str, phone: str, name: str, meeting_datetime: datetime, meeting_link: str) -> bool:
        """Schedule a reminder for a meeting"""
        try:
            reminders = self._load_reminders()
            
            # Check if reminder already exists for this webhook
            for reminder in reminders:
                if reminder.get('webhook_id') == webhook_id:
                    logger.info(f"Reminder already exists for webhook {webhook_id}")
                    return True
            
            # Create new reminder
            new_reminder = {
                "webhook_id": webhook_id,
                "phone": phone,
                "name": name,
                "meeting_datetime": meeting_datetime.isoformat(),
                "meeting_link": meeting_link,
                "reminder_sent": False,
                "created_at": datetime.now().isoformat()
            }
            
            reminders.append(new_reminder)
            self._save_reminders(reminders)
            
            logger.info(f"Reminder scheduled for {name} ({phone}) at {meeting_datetime}")
            return True
            
        except Exception as e:
            logger.error(f"Error scheduling reminder: {str(e)}")
            return False
    
    def _load_reminders(self):
        """Load reminders from JSON file"""
        try:
            if not os.path.exists(REMINDERS_JSON_FILE):
                return []
            
            with open(REMINDERS_JSON_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading reminders: {str(e)}")
            return []
    
    def _save_reminders(self, reminders):
        """Save reminders to JSON file"""
        try:
            with open(REMINDERS_JSON_FILE, 'w') as f:
                json.dump(reminders, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving reminders: {str(e)}")

# Initialize reminder scheduler
reminder_scheduler = ReminderScheduler()

app = Flask(__name__)

class MeetingConfirmation:
    def __init__(self):
        """Initialize the Meeting Confirmation Handler"""
        self.processed_webhooks = set()
        logger.info("Meeting Confirmation Handler initialized")
    
    def send_confirmation_message(self, phone: str, name: str, date: str, time: str, meeting_link: str) -> bool:
        """Send meeting confirmation message via AISensy API"""
        try:
            if not phone:
                logger.error("No phone number provided for meeting confirmation")
                return False
            
            # Ensure phone number has + prefix
            if not phone.startswith('+'):
                phone = '+' + phone
                logger.info(f"Fixed phone format: {phone}")
            
            # Create payload for AISensy
            payload = {
                "apiKey": AISENSY_API_KEY,
                "campaignName": MEETING_CONFIRMATION_CAMPAIGN,
                "destination": phone,
                "userName": "Skand",
                "templateParams": [name, date, time, meeting_link]
            }
            
            logger.info(f"Sending meeting confirmation to {phone} for {name}")
            logger.info(f"Meeting details: Date: {date}, Time: {time}, Link: {meeting_link}")
            
            # Send confirmation message
            response = requests.post(AISENSY_URL, json=payload, timeout=30)
            
            logger.info(f"AISensy response status: {response.status_code}")
            logger.info(f"AISensy response: {response.text}")
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"Meeting confirmation sent successfully to {phone}")
                return True
            else:
                try:
                    error_data = response.json()
                    error_message = error_data.get('errorMessage', 'Unknown error')
                    logger.error(f"Failed to send meeting confirmation to {phone}. Status: {response.status_code}, Error: {error_message}")
                    
                    # Special handling for WABA verification error
                    if 'WABA is not verified' in error_message:
                        logger.error("WABA (WhatsApp Business Account) is not verified with AISensy. Please verify your account in AISensy dashboard.")
                        logger.error("Contact AISensy support or check your account verification status.")
                    
                except json.JSONDecodeError:
                    logger.error(f"Failed to send meeting confirmation to {phone}. Status: {response.status_code}, Response: {response.text}")
                
                return False
                
        except Exception as e:
            logger.error(f"Error sending meeting confirmation to {phone}: {str(e)}")
            return False
    


    def extract_webhook_data(self, webhook_data: dict) -> dict:
        """Extract meeting data from Brevo webhook - supports multiple formats"""
        try:
            logger.info("=" * 60)
            logger.info("EXTRACTING WEBHOOK DATA")
            logger.info("=" * 60)
            
            # Check webhook format
            has_attributes = "attributes" in webhook_data
            has_params = "params" in webhook_data
            has_meeting_start = "meeting_start_timestamp" in webhook_data
            has_event_participants = "event_participants" in webhook_data
            
            logger.info(f"Webhook format detection:")
            logger.info(f"- Has attributes: {has_attributes}")
            logger.info(f"- Has params: {has_params}")
            logger.info(f"- Has meeting_start_timestamp: {has_meeting_start}")
            logger.info(f"- Has event_participants: {has_event_participants}")
            
            if has_meeting_start and has_event_participants:
                # Meeting data at root level (new format)
                logger.info("Detected ROOT LEVEL webhook format")
                return self._extract_root_level_webhook_data(webhook_data)
            elif has_attributes and has_params:
                # Direct webhook format (same as brevo.py)
                logger.info("Detected DIRECT webhook format (same as brevo.py)")
                return self._extract_direct_webhook_data(webhook_data)
            else:
                logger.error("❌ Invalid webhook format - missing required sections")
                logger.error("Required: Either 'attributes' and 'params' sections OR meeting data at root level")
                return {}
                
        except Exception as e:
            logger.error(f"❌ Error extracting webhook data: {str(e)}", exc_info=True)
            return {}

    def _extract_direct_webhook_data(self, webhook_data: dict) -> dict:
        """Extract data from direct webhook format (same as brevo.py)"""
        logger.info("Extracting from DIRECT webhook format (same as brevo.py)")
        
        # Phone number from attributes (root level)
        attributes = webhook_data.get("attributes", {})
        logger.info(f"Attributes section: {attributes}")
        phone = attributes.get("SMS") or attributes.get("WHATSAPP")
        logger.info(f"Extracted phone: {phone} (from WHATSAPP: {attributes.get('WHATSAPP')}, SMS: {attributes.get('SMS')})")
        
        # Meeting URL from params
        params = webhook_data.get("params", {})
        logger.info(f"Params section: {params}")
        meeting_link = params.get("meeting_url")
        meeting_name = params.get("meeting_name", "Meeting")
        logger.info(f"Extracted meeting_link: {meeting_link}")
        logger.info(f"Extracted meeting_name: {meeting_name}")
        
        # Name from event participants
        event_participants = params.get("event_participants", [])
        logger.info(f"Event participants: {event_participants}")
        if event_participants:
            first_participant = event_participants[0]
            first_name = first_participant.get("FIRSTNAME", "")
            last_name = first_participant.get("LASTNAME", "")
            name = f"{first_name} {last_name}".strip() if first_name or last_name else "User"
            logger.info(f"Extracted name from participants: {name} (first: {first_name}, last: {last_name})")
        else:
            name = "User"
            logger.info("No event participants found, using default name: User")
        
        # Date and time from meeting timestamp
        meeting_start = params.get("meeting_start_timestamp")
        logger.info(f"Meeting start timestamp: {meeting_start}")
        date = None
        time = None
        meeting_datetime = None
        if meeting_start:
            try:
                # Parse the UTC timestamp and convert to Indian timezone (IST)
                meeting_dt = datetime.fromisoformat(meeting_start.replace('Z', '+00:00'))
                # Convert UTC to IST (UTC+5:30)
                ist_offset = timedelta(hours=5, minutes=30)
                meeting_dt_ist = meeting_dt + ist_offset
                
                # Convert to timezone-naive datetime for comparison
                meeting_dt_ist = meeting_dt_ist.replace(tzinfo=None)
                
                date = meeting_dt_ist.strftime("%Y-%m-%d")
                time = meeting_dt_ist.strftime("%I:%M %p")
                meeting_datetime = meeting_dt_ist
                
                logger.info(f"✅ Successfully parsed timestamp: {meeting_start} -> UTC: {meeting_dt} -> IST: {meeting_dt_ist} -> Date: {date}, Time: {time}")
            except Exception as e:
                logger.error(f"❌ Could not parse meeting timestamp '{meeting_start}': {e}")
        else:
            logger.warning("❌ No meeting_start_timestamp found in params")
        
        return self._create_extraction_result(name, phone, date, time, meeting_link, meeting_name, meeting_datetime)

    def _extract_root_level_webhook_data(self, webhook_data: dict) -> dict:
        """Extract data from root level webhook format (meeting data at root level)"""
        logger.info("Extracting from ROOT LEVEL webhook format")
        
        # Meeting data is at root level
        meeting_link = webhook_data.get("meeting_address") or webhook_data.get("meeting_location", "")
        meeting_name = webhook_data.get("meeting_name", "Meeting")
        meeting_start = webhook_data.get("meeting_start_timestamp")
        
        logger.info(f"Meeting data from root level:")
        logger.info(f"- meeting_link: {meeting_link}")
        logger.info(f"- meeting_name: {meeting_name}")
        logger.info(f"- meeting_start: {meeting_start}")
        
        # Name from event participants
        event_participants = webhook_data.get("event_participants", [])
        logger.info(f"Event participants: {event_participants}")
        
        if event_participants:
            first_participant = event_participants[0]
            first_name = first_participant.get("FIRSTNAME", "")
            last_name = first_participant.get("LASTNAME", "")
            name = f"{first_name} {last_name}".strip() if first_name or last_name else "User"
            email = first_participant.get("EMAIL", "")
            logger.info(f"Extracted name from participants: {name} (first: {first_name}, last: {last_name}, email: {email})")
        else:
            name = "User"
            email = ""
            logger.info("No event participants found, using default name: User")
        
        # Phone number - not available in this webhook format
        phone = None
        logger.warning("Root level webhook - phone number not available in this format")
        logger.info(f"Email available: {email} (could be used to fetch phone from database if needed)")
        
        # Parse meeting timestamp (same as brevo.py logic)
        date = None
        time = None
        meeting_datetime = None
        if meeting_start:
            try:
                # Parse the UTC timestamp and convert to Indian timezone (IST)
                meeting_dt = datetime.fromisoformat(meeting_start.replace('Z', '+00:00'))
                # Convert UTC to IST (UTC+5:30)
                ist_offset = timedelta(hours=5, minutes=30)
                meeting_dt_ist = meeting_dt + ist_offset
                
                # Convert to timezone-naive datetime for comparison
                meeting_dt_ist = meeting_dt_ist.replace(tzinfo=None)
                
                date = meeting_dt_ist.strftime("%Y-%m-%d")
                time = meeting_dt_ist.strftime("%I:%M %p")
                meeting_datetime = meeting_dt_ist
                
                logger.info(f"✅ Successfully parsed timestamp: {meeting_start} -> UTC: {meeting_dt} -> IST: {meeting_dt_ist} -> Date: {date}, Time: {time}")
            except Exception as e:
                logger.error(f"❌ Could not parse meeting timestamp '{meeting_start}': {e}")
        else:
            logger.warning("❌ No meeting_start_timestamp found")
        
        # Set defaults for missing data (same as brevo.py logic)
        if not meeting_link:
            meeting_link = "https://meet.google.com/meeting"
            logger.warning("No meeting link found, using default")
        if not meeting_name:
            meeting_name = "One-on-One Meeting"
            logger.warning("No meeting name found, using default")
        
        logger.info("✅ Extracted data from root level webhook format")
        
        return self._create_extraction_result(name, phone, date, time, meeting_link, meeting_name, meeting_datetime)

    def _create_extraction_result(self, name, phone, date, time, meeting_link, meeting_name, meeting_datetime):
        """Create the final extraction result with logging"""
        logger.info("=" * 60)
        logger.info("EXTRACTION SUMMARY:")
        logger.info(f"- Name: {name}")
        logger.info(f"- Phone: {phone}")
        logger.info(f"- Date: {date}")
        logger.info(f"- Time: {time}")
        logger.info(f"- Meeting Link: {meeting_link}")
        logger.info(f"- Meeting Name: {meeting_name}")
        logger.info("=" * 60)
        
        # Set defaults for missing data
        if not meeting_link:
            meeting_link = "https://meet.google.com/meeting"
            logger.warning("No meeting link found, using default")
        if not meeting_name:
            meeting_name = "One-on-One Meeting"
            logger.warning("No meeting name found, using default")
        
        return {
            "phone": phone,
            "name": name,
            "date": date,
            "time": time,
            "meeting_link": meeting_link,
            "meeting_name": meeting_name,
            "meeting_datetime": meeting_datetime
        }
    
    def process_webhook(self, webhook_data: dict) -> dict:
        """Process meeting booking webhook and send confirmation"""
        try:
            logger.info("Processing meeting booking webhook")
            
            # Create unique webhook ID to prevent duplicates
            webhook_id = hashlib.md5(json.dumps(webhook_data, sort_keys=True).encode()).hexdigest()
            
            # Check if this webhook was already processed
            if webhook_id in self.processed_webhooks:
                logger.warning(f"Duplicate webhook detected, skipping: {webhook_id}")
                return {"status": "already_processed", "message": "Webhook already processed"}
            
            # Mark this webhook as processed
            self.processed_webhooks.add(webhook_id)
            
            # Extract meeting data
            meeting_data = self.extract_webhook_data(webhook_data)
            
            if not meeting_data:
                return {"status": "error", "message": "Failed to extract meeting data"}
            
            phone = meeting_data["phone"]
            name = meeting_data["name"]
            date = meeting_data["date"]
            time = meeting_data["time"]
            meeting_link = meeting_data["meeting_link"]
            meeting_datetime = meeting_data.get("meeting_datetime")
            
            logger.info(f"Extracted meeting data - Name: {name}, Phone: {phone}, Date: {date}, Time: {time}")
            
            # Validate required fields
            if not phone:
                error_msg = "Missing required field: phone number"
                logger.error(error_msg)
                return {"status": "error", "message": error_msg}
            
            # Send meeting confirmation message
            confirmation_sent = self.send_confirmation_message(phone, name, date, time, meeting_link)
            
            # Schedule reminder if meeting datetime is available
            reminder_scheduled = False
            if meeting_datetime:
                reminder_scheduled = reminder_scheduler.schedule_reminder(
                    webhook_id, phone, name, meeting_datetime, meeting_link
                )
                if reminder_scheduled:
                    logger.info(f"Reminder scheduled for {name} at {meeting_datetime}")
                else:
                    logger.warning(f"Failed to schedule reminder for {name}")
            
            result = {
                "status": "success" if confirmation_sent else "failed",
                "webhook_id": webhook_id,
                "confirmation_sent": confirmation_sent,
                "reminder_scheduled": reminder_scheduled,
                "meeting_data": {
                    "name": name,
                    "phone": phone,
                    "date": date,
                    "time": time,
                    "meeting_link": meeting_link,
                    "meeting_datetime": meeting_datetime.isoformat() if meeting_datetime else None
                }
            }
            
            logger.info(f"Meeting confirmation webhook processed: {result['status']}")
            return result
            
        except Exception as e:
            error_msg = f"Error processing webhook: {str(e)}"
            logger.error(error_msg)
            return {"status": "error", "message": error_msg}

# Initialize the meeting confirmation handler
confirmation_handler = MeetingConfirmation()

# Flask API endpoints
@app.route('/', methods=['POST'])
@app.route('/webhook', methods=['POST'])
@app.route('/confirmation/webhook', methods=['POST'])
def handle_confirmation_webhook():
    """Handle incoming meeting booking webhooks from Brevo"""
    logger.info(f"Received meeting confirmation webhook - Method: {request.method}")
    logger.info(f"Request headers: {dict(request.headers)}")
    
    try:
        webhook_data = request.get_json()
        if not webhook_data:
            logger.error("No JSON data received in webhook")
            return jsonify({"status": "error", "message": "No JSON data received"}), 400
        
        # Detailed webhook data logging
        logger.info("=" * 80)
        logger.info("WEBHOOK DATA RECEIVED:")
        logger.info("=" * 80)
        logger.info(f"Full webhook data: {json.dumps(webhook_data, indent=2)}")
        logger.info("=" * 80)
        
        # Log specific sections
        logger.info("WEBHOOK STRUCTURE ANALYSIS:")
        logger.info(f"- Top level keys: {list(webhook_data.keys())}")
        
        # Check for all possible webhook formats
        if "attributes" in webhook_data:
            logger.info(f"- Attributes: {webhook_data['attributes']}")
        else:
            logger.warning("- No 'attributes' section found")
            
        if "params" in webhook_data:
            logger.info(f"- Params: {webhook_data['params']}")
        else:
            logger.warning("- No 'params' section found")
            
        # Check for root level meeting data
        if "meeting_start_timestamp" in webhook_data:
            logger.info(f"- Meeting Start Timestamp: {webhook_data['meeting_start_timestamp']}")
        else:
            logger.warning("- No 'meeting_start_timestamp' found")
            
        if "event_participants" in webhook_data:
            logger.info(f"- Event Participants: {webhook_data['event_participants']}")
        else:
            logger.warning("- No 'event_participants' found")
            
        if "meeting_name" in webhook_data:
            logger.info(f"- Meeting Name: {webhook_data['meeting_name']}")
        else:
            logger.warning("- No 'meeting_name' found")
            
        if "meeting_address" in webhook_data:
            logger.info(f"- Meeting Address: {webhook_data['meeting_address']}")
        else:
            logger.warning("- No 'meeting_address' found")
            
        if "meeting_location" in webhook_data:
            logger.info(f"- Meeting Location: {webhook_data['meeting_location']}")
        else:
            logger.warning("- No 'meeting_location' found")
            
        # Check for other common fields
        if "account_email" in webhook_data:
            logger.info(f"- Account Email: {webhook_data['account_email']}")
        if "currency" in webhook_data:
            logger.info(f"- Currency: {webhook_data['currency']}")
        if "price" in webhook_data:
            logger.info(f"- Price: {webhook_data['price']}")
        if "meeting_notes" in webhook_data:
            logger.info(f"- Meeting Notes: {webhook_data['meeting_notes']}")
        if "questions_and_answers" in webhook_data:
            logger.info(f"- Questions & Answers: {webhook_data['questions_and_answers']}")
            
        logger.info("=" * 80)
        
        # Process the webhook
        result = confirmation_handler.process_webhook(webhook_data)
        
        logger.info(f"Webhook processing result: {result}")
        
        if result["status"] == "error":
            return jsonify(result), 400
        elif result["status"] == "already_processed":
            return jsonify(result), 200
        elif result["status"] == "failed":
            return jsonify(result), 500
        else:
            return jsonify(result), 200
            
    except Exception as e:
        logger.error(f"Error in confirmation webhook endpoint: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": "Internal server error"}), 500

@app.route('/', methods=['GET'])
def root_info():
    """Root endpoint with service information"""
    return jsonify({
        "service": "meeting_confirmation",
        "status": "running",
        "endpoints": {
            "webhook": "POST / or POST /webhook or POST /confirmation/webhook",
            "health": "GET /confirmation/health",
            "test": "POST /confirmation/test",
            "test_webhook": "POST /confirmation/test-webhook",
            "debug_webhook": "POST /confirmation/debug-webhook",
            "print_webhook": "POST /confirmation/print-webhook",
            "stats": "GET /confirmation/stats",
            "reminder_start": "POST /reminder/start",
            "reminder_stop": "POST /reminder/stop",
            "reminder_status": "GET /reminder/status",
            "reminder_test": "POST /reminder/test",
            "reminder_list": "GET /reminder/list"
        },
        "timestamp": datetime.now().isoformat()
    })

@app.route('/confirmation/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "meeting_confirmation",
        "processed_webhooks": len(confirmation_handler.processed_webhooks)
    })

@app.route('/confirmation/test', methods=['POST'])
def test_confirmation():
    """Test endpoint for sending meeting confirmation messages"""
    try:
        data = request.get_json()
        phone = data.get('phone')
        name = data.get('name', 'Test User')
        date = data.get('date')
        time = data.get('time')
        meeting_link = data.get('meeting_link', 'https://example.com/meeting')
        
        if not phone:
            return jsonify({"status": "error", "message": "Phone number is required"}), 400
        
        # If no date/time provided, use a sample meeting time instead of current time
        if not date:
            # Use tomorrow's date as a sample
            tomorrow = datetime.now() + timedelta(days=1)
            date = tomorrow.strftime('%Y-%m-%d')
        if not time:
            # Use a sample time
            time = "02:00 PM"
        
        success = confirmation_handler.send_confirmation_message(phone, name, date, time, meeting_link)
        
        return jsonify({
            "status": "success" if success else "failed",
            "message": "Test confirmation message sent" if success else "Failed to send test message",
            "test_data": {
                "phone": phone,
                "name": name,
                "date": date,
                "time": time,
                "meeting_link": meeting_link
            }
        })
        
    except Exception as e:
        logger.error(f"Error in test endpoint: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/confirmation/stats', methods=['GET'])
def get_stats():
    """Get statistics about processed webhooks"""
    return jsonify({
        "status": "success",
        "total_processed_webhooks": len(confirmation_handler.processed_webhooks),
        "service_uptime": datetime.now().isoformat()
    })

@app.route('/confirmation/test-webhook', methods=['POST'])
def test_webhook_parsing():
    """Test endpoint for testing webhook data parsing with sample data"""
    try:
        # Test with root level webhook format (the format you provided)
        sample_webhook_data = {
            "account_email": "john@example.com",
            "currency": "EUR",
            "event_participants": [
                {
                    "EMAIL": "john@example.com",
                    "FIRSTNAME": "john",
                    "LASTNAME": "doe"
                }
            ],
            "meeting_address": "12345 CityAB",
            "meeting_end_timestamp": "2025-06-10T07:09:01.696Z",
            "meeting_location": "MeetingpointA",
            "meeting_name": "Testmeeting",
            "meeting_notes": "Meeting-notes",
            "meeting_start_timestamp": "2025-06-10T07:09:01.696Z",
            "price": 123,
            "questions_and_answers": [
                {
                    "answer": "Answer to the question",
                    "question": "What is the question?"
                }
            ]
        }
        
        # Test the extraction
        extracted_data = confirmation_handler.extract_webhook_data(sample_webhook_data)
        
        return jsonify({
            "status": "success",
            "message": "Webhook parsing test completed using root level format",
            "sample_webhook": sample_webhook_data,
            "extracted_data": extracted_data,
            "expected_meeting_time": "2025-06-10 12:39 PM IST (from 2025-06-10T07:09:01.696Z UTC)",
            "format_note": "Root level webhook format - meeting data at root level, no phone number available"
        })
        
    except Exception as e:
        logger.error(f"Error in webhook parsing test: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/confirmation/debug-webhook', methods=['POST'])
def debug_webhook():
    """Debug endpoint to test any webhook data format"""
    try:
        webhook_data = request.get_json()
        if not webhook_data:
            return jsonify({"status": "error", "message": "No JSON data provided"}), 400
        
        logger.info("=" * 80)
        logger.info("DEBUG WEBHOOK ENDPOINT CALLED")
        logger.info("=" * 80)
        
        # Test the extraction
        extracted_data = confirmation_handler.extract_webhook_data(webhook_data)
        
        return jsonify({
            "status": "success",
            "message": "Debug webhook parsing completed",
            "input_webhook": webhook_data,
            "extracted_data": extracted_data,
            "debug_info": {
                "has_attributes": "attributes" in webhook_data,
                "has_params": "params" in webhook_data,
                "has_meeting_start": "meeting_start_timestamp" in webhook_data,
                "has_event_participants": "event_participants" in webhook_data,
                "top_level_keys": list(webhook_data.keys()),
                "supported_formats": [
                    "Root level format: meeting data at root level with 'meeting_start_timestamp' and 'event_participants'",
                    "Direct format: 'attributes' and 'params' sections (same as brevo.py)"
                ]
            }
        })
        
    except Exception as e:
        logger.error(f"Error in debug webhook: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/confirmation/print-webhook', methods=['POST'])
def print_webhook_details():
    """Simple endpoint to print webhook details without processing"""
    try:
        webhook_data = request.get_json()
        if not webhook_data:
            return jsonify({"status": "error", "message": "No JSON data provided"}), 400
        
        logger.info("=" * 100)
        logger.info("PRINT WEBHOOK DETAILS ENDPOINT CALLED")
        logger.info("=" * 100)
        
        # Print all webhook details
        logger.info("COMPLETE WEBHOOK DATA:")
        logger.info(json.dumps(webhook_data, indent=2))
        
        logger.info("=" * 100)
        logger.info("FIELD-BY-FIELD ANALYSIS:")
        logger.info("=" * 100)
        
        for key, value in webhook_data.items():
            logger.info(f"Field: '{key}' = {value} (Type: {type(value).__name__})")
        
        logger.info("=" * 100)
        
        return jsonify({
            "status": "success",
            "message": "Webhook details printed to logs",
            "webhook_data": webhook_data,
            "field_count": len(webhook_data),
            "fields": list(webhook_data.keys())
        })
        
    except Exception as e:
        logger.error(f"Error in print webhook: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

# Add reminder API endpoints
@app.route('/reminder/start', methods=['POST'])
def start_reminder_scheduler():
    """Start the reminder scheduler"""
    try:
        reminder_scheduler.start_scheduler()
        return jsonify({
            "status": "success",
            "message": "Reminder scheduler started successfully"
        })
    except Exception as e:
        logger.error(f"Error starting reminder scheduler: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/reminder/stop', methods=['POST'])
def stop_reminder_scheduler():
    """Stop the reminder scheduler"""
    try:
        reminder_scheduler.stop_scheduler()
        return jsonify({
            "status": "success",
            "message": "Reminder scheduler stopped successfully"
        })
    except Exception as e:
        logger.error(f"Error stopping reminder scheduler: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/reminder/status', methods=['GET'])
def get_reminder_status():
    """Get reminder scheduler status and pending reminders"""
    try:
        reminders = reminder_scheduler._load_reminders()
        
        # Count pending and sent reminders
        pending_count = sum(1 for r in reminders if not r.get('reminder_sent', False))
        sent_count = sum(1 for r in reminders if r.get('reminder_sent', False))
        
        # Get next few pending reminders
        pending_reminders = [r for r in reminders if not r.get('reminder_sent', False)]
        pending_reminders.sort(key=lambda x: x.get('meeting_datetime', ''))
        next_reminders = pending_reminders[:5]
        
        return jsonify({
            "status": "success",
            "scheduler_running": reminder_scheduler.is_running,
            "pending_reminders": pending_count,
            "sent_reminders": sent_count,
            "next_reminders": [
                {
                    "name": r.get('name', 'Unknown'),
                    "phone": r.get('phone', 'Unknown'),
                    "meeting_datetime": r.get('meeting_datetime', 'Unknown'),
                    "meeting_link": r.get('meeting_link', 'Unknown'),
                    "created_at": r.get('created_at', 'Unknown')
                } for r in next_reminders
            ]
        })
        
    except Exception as e:
        logger.error(f"Error getting reminder status: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/reminder/test', methods=['POST'])
def test_reminder():
    """Test endpoint for sending reminder messages"""
    try:
        data = request.get_json()
        phone = data.get('phone')
        name = data.get('name', 'Test User')
        meeting_datetime_str = data.get('meeting_datetime')
        meeting_link = data.get('meeting_link', 'https://example.com/meeting')
        
        if not phone:
            return jsonify({"status": "error", "message": "Phone number is required"}), 400
        
        if not meeting_datetime_str:
            # Use a sample meeting time 2 hours from now
            meeting_datetime = datetime.now() + timedelta(hours=2)
        else:
            meeting_datetime = datetime.fromisoformat(meeting_datetime_str)
        
        # Send test reminder
        success = reminder_scheduler._send_reminder_message(phone, name, meeting_datetime, meeting_link)
        
        return jsonify({
            "status": "success" if success else "failed",
            "message": "Test reminder message sent" if success else "Failed to send test reminder",
            "test_data": {
                "phone": phone,
                "name": name,
                "meeting_datetime": meeting_datetime.isoformat(),
                "meeting_link": meeting_link
            }
        })
        
    except Exception as e:
        logger.error(f"Error in test reminder endpoint: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/reminder/list', methods=['GET'])
def list_all_reminders():
    """List all reminders (both pending and sent)"""
    try:
        reminders = reminder_scheduler._load_reminders()
        
        return jsonify({
            "status": "success",
            "total_reminders": len(reminders),
            "reminders": reminders
        })
        
    except Exception as e:
        logger.error(f"Error listing reminders: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    logger.info("Starting Meeting Confirmation Service...")
    logger.info(f"Campaign Name: {MEETING_CONFIRMATION_CAMPAIGN}")
    logger.info(f"Reminder Campaign: {MEETING_REMINDER_CAMPAIGN}")
    logger.info(f"AISensy URL: {AISENSY_URL}")
    
    # Start reminder scheduler
    reminder_scheduler.start_scheduler()
    
    try:
        app.run(host='0.0.0.0', port=8002, debug=True)
    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down...")
        reminder_scheduler.stop_scheduler()
    except Exception as e:
        logger.error(f"Fatal error in meeting confirmation service: {str(e)}")
        reminder_scheduler.stop_scheduler()
        raise
