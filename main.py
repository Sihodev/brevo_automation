#!/usr/bin/env python3
"""
Background Reminder Scheduler Service
Runs separately from webhook service to send reminders
"""

import json
import time
import logging
import requests
from datetime import datetime, timedelta
import os
import signal
import sys

# Import configuration
AISENSY_URL = "https://backend.aisensy.com/campaign/t2/api/v2"
AISENSY_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjY4Y2FhNjRhOTQyMjZkMGMzMGJlZGYxNyIsIm5hbWUiOiJTSUhPIFJlc2VhcmNoIDcwNzkiLCJhcHBOYW1lIjoiQWlTZW5zeSIsImNsaWVudElkIjoiNjhjYWE2NGE5NDIyNmQwYzMwYmVkZjEyIiwiYWN0aXZlUGxhbiI6IlBST19RVUFSVEVSTFkiLCJpYXQiOjE3NTg4OTEyOTV9.8xemmqyOMd63--d2XTewXwEwfxleFnhLjPFhUK61_2o"

MEETING_REMINDER_CAMPAIGN = "1hour Reminder 1on1"
REMINDERS_JSON_FILE = "meeting_reminders.json"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('reminder_scheduler.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class ReminderScheduler:
    def __init__(self):
        self.is_running = False
        logger.info("Reminder Scheduler initialized")
    
    def start_scheduler(self):
        """Start the reminder scheduler"""
        self.is_running = True
        logger.info("Reminder scheduler started")
        
        while self.is_running:
            try:
                self._check_and_send_reminders()
                time.sleep(60)  # Check every minute
            except Exception as e:
                logger.error(f"Error in reminder loop: {str(e)}")
                time.sleep(60)
    
    def stop_scheduler(self):
        """Stop the reminder scheduler"""
        self.is_running = False
        logger.info("Reminder scheduler stopped")
    
    def _check_and_send_reminders(self):
        """Check for reminders that need to be sent"""
        try:
            # Load reminders from JSON file
            reminders = self._load_reminders()
            
            if not reminders:
                return
            
            current_time = datetime.now()
            reminders_to_send = []
            
            # Find reminders that should be sent now
            for reminder in reminders:
                if reminder.get('reminder_sent', False):
                    continue
                
                meeting_datetime_str = reminder.get('meeting_datetime')
                if not meeting_datetime_str:
                    continue
                
                try:
                    meeting_datetime = datetime.fromisoformat(meeting_datetime_str)
                    reminder_time = meeting_datetime - timedelta(hours=1, minutes=0)
                    
                    # Check if it's time to send reminder
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
            time = meeting_datetime.strftime("%I:%M %p")
            
            # Create payload for AISensy
            payload = {
                "apiKey": AISENSY_API_KEY,
                "campaignName": MEETING_REMINDER_CAMPAIGN,
                "destination": phone,
                "userName": "Skand",
                "templateParams": [name, time, meeting_link]  # Only Name, Time, and Link
            }
            
            logger.info(f"Sending meeting reminder to {phone} for {name}")
            logger.info(f"Meeting details: Time: {time}, Link: {meeting_link}")
            
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

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    scheduler.stop_scheduler()
    logger.info("Shutdown complete")
    sys.exit(0)

if __name__ == '__main__':
    logger.info("Starting Reminder Scheduler Service...")
    logger.info(f"Reminder Campaign: {MEETING_REMINDER_CAMPAIGN}")
    logger.info(f"AISensy URL: {AISENSY_URL}")
    
    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    scheduler = ReminderScheduler()
    
    try:
        scheduler.start_scheduler()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
        scheduler.stop_scheduler()
    except Exception as e:
        logger.error(f"Fatal error in reminder scheduler: {str(e)}")
        scheduler.stop_scheduler()
        raise
