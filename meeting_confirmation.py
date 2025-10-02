#!/usr/bin/env python3
"""
Webhook Service for Brevo Meeting Confirmations
Handles webhook processing and sends confirmation messages
Reminder scheduling is handled by separate reminder_scheduler.py
"""

from flask import Flask, request, jsonify
import requests
import logging
import json
from datetime import datetime, timedelta
import hashlib
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

# Reminder scheduling is now handled by separate reminder_scheduler.py

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
    
    def _schedule_reminder(self, webhook_id: str, phone: str, name: str, meeting_datetime: datetime, meeting_link: str) -> bool:
        """Schedule a reminder by writing to JSON file (for background scheduler to pick up)"""
        try:
            # Load existing reminders
            reminders = []
            if os.path.exists(REMINDERS_JSON_FILE):
                with open(REMINDERS_JSON_FILE, 'r') as f:
                    reminders = json.load(f)
            
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
            
            # Save reminders back to JSON file
            with open(REMINDERS_JSON_FILE, 'w') as f:
                json.dump(reminders, f, indent=2)
            
            logger.info(f"Reminder scheduled for {name} ({phone}) at {meeting_datetime}")
            return True
            
        except Exception as e:
            logger.error(f"Error scheduling reminder: {str(e)}")
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
            
            # Schedule reminder by writing to JSON file (for background scheduler to pick up)
            reminder_scheduled = False
            if meeting_datetime:
                reminder_scheduled = self._schedule_reminder(
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
        "service": "webhook_service",
        "status": "running",
        "endpoints": {
            "webhook": "POST / or POST /webhook or POST /confirmation/webhook",
            "health": "GET /confirmation/health",
            "test": "POST /confirmation/test",
            "test_webhook": "POST /confirmation/test-webhook",
            "debug_webhook": "POST /confirmation/debug-webhook",
            "print_webhook": "POST /confirmation/print-webhook",
            "stats": "GET /confirmation/stats"
        },
        "note": "Reminder scheduling handled by separate reminder_scheduler.py",
        "timestamp": datetime.now().isoformat()
    })

@app.route('/confirmation/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "webhook_service",
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

# Reminder endpoints removed - handled by separate reminder_scheduler.py

if __name__ == '__main__':
    logger.info("Starting Webhook Service...")
    logger.info(f"Campaign Name: {MEETING_CONFIRMATION_CAMPAIGN}")
    logger.info(f"AISensy URL: {AISENSY_URL}")
    logger.info("Reminder scheduling handled by separate reminder_scheduler.py")
    
    try:
        app.run(host='0.0.0.0', port=8002, debug=False)
    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down...")
    except Exception as e:
        logger.error(f"Fatal error in webhook service: {str(e)}")
        raise
