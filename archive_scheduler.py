#!/usr/bin/env python3
"""
archive_scheduler.py
- Built-in archiving system that runs within the main dashboard service
- No cron dependencies - everything self-contained
- Runs as a background thread alongside the dashboard rotator
"""

import os
import sys
import time
import json
import logging
import subprocess
import threading
from datetime import datetime, timedelta
from pathlib import Path
import shutil

# Configuration
ARCHIVE_DIR = Path("archive")
ARCHIVE_DIR.mkdir(exist_ok=True)

# Dashboard scripts to archive
DASHBOARD_SCRIPTS = [
    "dash_comic.py",
    "dash_weather.py", 
    "dash_motivation.py",
    "dash_recipe.py"
]

# Archive settings
ARCHIVE_HOUR = 1  # 1 AM
ARCHIVE_RETENTION_DAYS = int(os.environ.get("ARCHIVE_RETENTION_DAYS", "90"))

class ArchiveScheduler:
    def __init__(self):
        self.running = False
        self.thread = None
        self.log = logging.getLogger("archive_scheduler")
        
    def start(self):
        """Start the archive scheduler in a background thread."""
        if self.running:
            self.log.warning("Archive scheduler already running")
            return
            
        self.running = True
        self.thread = threading.Thread(target=self._archive_loop, daemon=True)
        self.thread.start()
        self.log.info("Archive scheduler started (daily at %d:00 AM)", ARCHIVE_HOUR)
    
    def stop(self):
        """Stop the archive scheduler."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        self.log.info("Archive scheduler stopped")
    
    def _archive_loop(self):
        """Main archive loop - runs continuously in background."""
        self.log.info("Archive scheduler loop started")
        
        while self.running:
            try:
                now = datetime.now()
                
                # Check if it's time to archive (1 AM)
                if now.hour == ARCHIVE_HOUR and now.minute == 0:
                    self.log.info("Archive time reached - generating daily snapshots")
                    self._create_daily_archive()
                    
                    # Sleep for a minute to avoid running multiple times in the same hour
                    time.sleep(60)
                
                # Check for cleanup every 6 hours
                elif now.hour % 6 == 0 and now.minute == 0:
                    self.log.info("Running archive cleanup")
                    self._cleanup_old_archives()
                    time.sleep(60)
                
                else:
                    # Sleep for 30 seconds and check again
                    time.sleep(30)
                    
            except Exception as e:
                self.log.error("Error in archive loop: %s", e)
                time.sleep(60)  # Wait a minute before retrying
    
    def _generate_dashboard_snapshot(self, script_name: str) -> Path | None:
        """Generate a snapshot of a single dashboard."""
        try:
            self.log.debug("Generating snapshot for %s", script_name)
            
            # Run the dashboard script
            result = subprocess.run(
                [sys.executable, script_name],
                capture_output=True,
                text=True,
                timeout=60  # 60 second timeout
            )
            
            if result.returncode != 0:
                self.log.error("Failed to generate %s: %s", script_name, result.stderr)
                return None
            
            # Look for the generated preview image
            script_base = script_name.replace("dash_", "out_").replace(".py", ".png")
            preview_path = Path(script_base)
            
            if preview_path.exists():
                self.log.debug("Generated snapshot: %s", preview_path)
                return preview_path
            else:
                self.log.warning("No preview image found for %s", script_name)
                return None
                
        except subprocess.TimeoutExpired:
            self.log.error("Timeout generating %s", script_name)
            return None
        except Exception as e:
            self.log.error("Error generating %s: %s", script_name, e)
            return None
    
    def _create_daily_archive(self):
        """Create a complete daily archive of all dashboards."""
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        timestamp_str = now.strftime("%Y%m%d_%H%M%S")
        
        # Create date directory
        date_dir = ARCHIVE_DIR / date_str
        date_dir.mkdir(exist_ok=True)
        
        self.log.info("Creating daily archive for %s", date_str)
        
        archive_data = {
            "date": date_str,
            "timestamp": timestamp_str,
            "created_at": now.isoformat(),
            "dashboards": {},
            "summary": {
                "total_dashboards": len(DASHBOARD_SCRIPTS),
                "successful": 0,
                "failed": 0
            }
        }
        
        # Generate snapshots for each dashboard
        for script_name in DASHBOARD_SCRIPTS:
            script_path = Path(script_name)
            if not script_path.exists():
                self.log.warning("Dashboard script not found: %s", script_name)
                archive_data["summary"]["failed"] += 1
                continue
            
            # Generate snapshot
            snapshot_path = self._generate_dashboard_snapshot(script_name)
            
            if snapshot_path and snapshot_path.exists():
                # Copy to archive with timestamp
                archive_filename = f"{timestamp_str}_{script_name.replace('.py', '.png')}"
                archive_path = date_dir / archive_filename
                
                shutil.copy2(snapshot_path, archive_path)
                
                # Clean up original preview
                snapshot_path.unlink()
                
                # Record in metadata
                dashboard_name = script_name.replace("dash_", "").replace(".py", "")
                archive_data["dashboards"][dashboard_name] = {
                    "script": script_name,
                    "archive_file": archive_filename,
                    "size_bytes": archive_path.stat().st_size,
                    "generated_at": now.isoformat()
                }
                
                archive_data["summary"]["successful"] += 1
                self.log.info("Archived %s -> %s", script_name, archive_filename)
                
            else:
                archive_data["summary"]["failed"] += 1
                self.log.error("Failed to generate snapshot for %s", script_name)
        
        # Save metadata
        metadata_path = date_dir / f"{timestamp_str}_metadata.json"
        with open(metadata_path, 'w') as f:
            json.dump(archive_data, f, indent=2)
        
        self.log.info("Daily archive complete: %d successful, %d failed", 
                    archive_data["summary"]["successful"], 
                    archive_data["summary"]["failed"])
        
        # Generate summary
        self._generate_archive_summary()
    
    def _cleanup_old_archives(self):
        """Remove archives older than retention period."""
        cutoff_date = datetime.now() - timedelta(days=ARCHIVE_RETENTION_DAYS)
        cutoff_str = cutoff_date.strftime("%Y-%m-%d")
        
        self.log.info("Cleaning up archives older than %s", cutoff_str)
        
        removed_count = 0
        for item in ARCHIVE_DIR.iterdir():
            if item.is_dir() and item.name < cutoff_str:
                self.log.info("Removing old archive: %s", item.name)
                shutil.rmtree(item)
                removed_count += 1
        
        if removed_count > 0:
            self.log.info("Removed %d old archive directories", removed_count)
    
    def _generate_archive_summary(self):
        """Generate a summary of all archives."""
        summary = {
            "generated_at": datetime.now().isoformat(),
            "total_archives": 0,
            "total_size_bytes": 0,
            "date_range": {"oldest": None, "newest": None},
            "dashboards": {}
        }
        
        dates = []
        for item in ARCHIVE_DIR.iterdir():
            if item.is_dir() and item.name.count('-') == 2:  # YYYY-MM-DD format
                dates.append(item.name)
                
                # Calculate size
                dir_size = sum(f.stat().st_size for f in item.rglob('*') if f.is_file())
                summary["total_size_bytes"] += dir_size
                
                # Count files
                png_count = len(list(item.glob("*.png")))
                summary["total_archives"] += png_count
        
        if dates:
            dates.sort()
            summary["date_range"]["oldest"] = dates[0]
            summary["date_range"]["newest"] = dates[-1]
        
        # Save summary
        summary_path = ARCHIVE_DIR / "archive_summary.json"
        with open(summary_path, 'w') as f:
            json.dump(summary, f, indent=2)
        
        self.log.info("Archive summary: %d snapshots, %.1f MB total", 
                    summary["total_archives"], 
                    summary["total_size_bytes"] / 1024 / 1024)

# Global instance
archive_scheduler = ArchiveScheduler()
