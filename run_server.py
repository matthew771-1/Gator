#!/usr/bin/env python3
"""
Simple script to run the Gator backend server
"""

import uvicorn
import sys
import os

if __name__ == "__main__":
    print("=" * 60)
    print("🐊 Gator OSINT Backend Server")
    print("=" * 60)
    print("\nStarting server...")
    print("Frontend will be available at: http://localhost:8000")
    print("API docs will be available at: http://localhost:8000/docs")
    print("\nPress Ctrl+C to stop the server\n")
    
    try:
        uvicorn.run(
            "backend_api:app",
            host="0.0.0.0",
            port=8000,
            reload=True,  # Auto-reload on code changes
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\n\nServer stopped.")
        sys.exit(0)



