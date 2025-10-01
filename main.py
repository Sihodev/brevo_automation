#!/usr/bin/env python3
"""
Main entry point for Brevo Meeting Confirmation Service
Handles meeting confirmations and reminders via AISensy API
"""

import sys
import os
import signal
import logging
from datetime import datetime

# Add current directory to Python path to import meeting_confirmation
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from meeting_confirmation import app, reminder_scheduler, logger

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    reminder_scheduler.stop_scheduler()
    logger.info("Shutdown complete")
    sys.exit(0)

def main():
    """Main function to start the meeting confirmation service"""
    try:
        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        logger.info("=" * 60)
        logger.info("STARTING BREVO MEETING CONFIRMATION SERVICE")
        logger.info("=" * 60)
        logger.info(f"Service started at: {datetime.now().isoformat()}")
        logger.info(f"Python version: {sys.version}")
        logger.info(f"Working directory: {os.getcwd()}")
        logger.info("=" * 60)
        
        # Start the reminder scheduler
        logger.info("Starting reminder scheduler...")
        reminder_scheduler.start_scheduler()
        logger.info("Reminder scheduler started successfully")
        
        # Start the Flask application
        logger.info("Starting Flask application...")
        logger.info("Service endpoints available at:")
        logger.info("  - Webhook: POST http://localhost:8002/")
        logger.info("  - Health: GET http://localhost:8002/confirmation/health")
        logger.info("  - Test: POST http://localhost:8002/confirmation/test")
        logger.info("  - Stats: GET http://localhost:8002/confirmation/stats")
        logger.info("  - Reminder status: GET http://localhost:8002/reminder/status")
        logger.info("=" * 60)
        
        # Run the Flask app
        app.run(
            host='0.0.0.0',
            port=8002,
            debug=True,
            use_reloader=False  # Disable reloader to prevent duplicate scheduler threads
        )
        
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
        reminder_scheduler.stop_scheduler()
    except Exception as e:
        logger.error(f"Fatal error in main service: {str(e)}", exc_info=True)
        reminder_scheduler.stop_scheduler()
        raise
    finally:
        logger.info("Service shutdown complete")

if __name__ == '__main__':
    main()
