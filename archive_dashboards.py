#!/usr/bin/env python3
"""
archive_dashboards.py
- Generates daily snapshots of all dashboards
- Archives images with timestamps and metadata
- Can be run manually or via cron job
- Organizes files by date for easy browsing
"""

import os
import sys
import time
import json
import logging
import subprocess
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

# Archive retention (days)
RETENTION_DAYS = 90

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

def generate_dashboard_snapshot(script_name: str) -> Path | None:
    """Generate a snapshot of a single dashboard."""
    try:
        logging.info("Generating snapshot for %s...", script_name)
        
        # Run the dashboard script
        result = subprocess.run(
            [sys.executable, script_name],
            capture_output=True,
            text=True,
            timeout=60  # 60 second timeout
        )
        
        if result.returncode != 0:
            logging.error("Failed to generate %s: %s", script_name, result.stderr)
            return None
        
        # Look for the generated preview image
        script_base = script_name.replace("dash_", "out_").replace(".py", ".png")
        preview_path = Path(script_base)
        
        if preview_path.exists():
            logging.info("Generated snapshot: %s", preview_path)
            return preview_path
        else:
            logging.warning("No preview image found for %s", script_name)
            return None
            
    except subprocess.TimeoutExpired:
        logging.error("Timeout generating %s", script_name)
        return None
    except Exception as e:
        logging.error("Error generating %s: %s", script_name, e)
        return None

def create_daily_archive():
    """Create a complete daily archive of all dashboards."""
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    timestamp_str = now.strftime("%Y%m%d_%H%M%S")
    
    # Create date directory
    date_dir = ARCHIVE_DIR / date_str
    date_dir.mkdir(exist_ok=True)
    
    logging.info("Creating daily archive for %s", date_str)
    
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
            logging.warning("Dashboard script not found: %s", script_name)
            archive_data["summary"]["failed"] += 1
            continue
        
        # Generate snapshot
        snapshot_path = generate_dashboard_snapshot(script_name)
        
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
            logging.info("Archived %s -> %s", script_name, archive_filename)
            
        else:
            archive_data["summary"]["failed"] += 1
            logging.error("Failed to generate snapshot for %s", script_name)
    
    # Save metadata
    metadata_path = date_dir / f"{timestamp_str}_metadata.json"
    with open(metadata_path, 'w') as f:
        json.dump(archive_data, f, indent=2)
    
    logging.info("Daily archive complete: %d successful, %d failed", 
                archive_data["summary"]["successful"], 
                archive_data["summary"]["failed"])
    
    return date_dir

def cleanup_old_archives():
    """Remove archives older than retention period."""
    cutoff_date = datetime.now() - timedelta(days=RETENTION_DAYS)
    cutoff_str = cutoff_date.strftime("%Y-%m-%d")
    
    logging.info("Cleaning up archives older than %s", cutoff_str)
    
    removed_count = 0
    for item in ARCHIVE_DIR.iterdir():
        if item.is_dir() and item.name < cutoff_str:
            logging.info("Removing old archive: %s", item.name)
            shutil.rmtree(item)
            removed_count += 1
    
    if removed_count > 0:
        logging.info("Removed %d old archive directories", removed_count)
    else:
        logging.info("No old archives to remove")

def generate_archive_summary():
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
    
    logging.info("Archive summary: %d snapshots, %.1f MB total", 
                summary["total_archives"], 
                summary["total_size_bytes"] / 1024 / 1024)
    
    return summary

def main():
    """Main archive process."""
    if "--cleanup-only" in sys.argv:
        cleanup_old_archives()
        return
    
    if "--summary-only" in sys.argv:
        generate_archive_summary()
        return
    
    # Create daily archive
    archive_dir = create_daily_archive()
    
    # Cleanup old archives
    cleanup_old_archives()
    
    # Generate summary
    generate_archive_summary()
    
    logging.info("Archive process complete!")

if __name__ == "__main__":
    main()
