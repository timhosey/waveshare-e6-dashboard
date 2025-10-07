#!/usr/bin/env python3
"""
view_archives.py
- Browse and view archived dashboard snapshots
- Simple command-line interface for archive management
"""

import os
import sys
import json
from datetime import datetime
from pathlib import Path
import argparse

ARCHIVE_DIR = Path("archive")

def list_archives():
    """List all available archives."""
    if not ARCHIVE_DIR.exists():
        print("No archives found. Run archive_dashboards.py first.")
        return
    
    print("📁 Available Archives:")
    print("=" * 50)
    
    dates = []
    for item in ARCHIVE_DIR.iterdir():
        if item.is_dir() and item.name.count('-') == 2:  # YYYY-MM-DD format
            dates.append(item.name)
    
    dates.sort(reverse=True)  # Most recent first
    
    for date_str in dates:
        date_dir = ARCHIVE_DIR / date_str
        png_files = list(date_dir.glob("*.png"))
        metadata_files = list(date_dir.glob("*_metadata.json"))
        
        print(f"📅 {date_str} ({len(png_files)} snapshots)")
        
        if metadata_files:
            try:
                with open(metadata_files[0], 'r') as f:
                    metadata = json.load(f)
                    successful = metadata.get("summary", {}).get("successful", 0)
                    failed = metadata.get("summary", {}).get("failed", 0)
                    print(f"   ✅ {successful} successful, ❌ {failed} failed")
            except Exception:
                pass
        
        # List individual dashboards
        for png_file in sorted(png_files):
            dashboard_name = png_file.stem.split('_')[-1].replace('dash_', '').replace('dash', '')
            print(f"   📊 {dashboard_name}")
    
    print(f"\nTotal: {len(dates)} archive days")

def show_archive_summary():
    """Show archive summary."""
    summary_path = ARCHIVE_DIR / "archive_summary.json"
    if not summary_path.exists():
        print("No archive summary found. Run archive_dashboards.py first.")
        return
    
    with open(summary_path, 'r') as f:
        summary = json.load(f)
    
    print("📊 Archive Summary:")
    print("=" * 30)
    print(f"Total snapshots: {summary.get('total_archives', 0)}")
    print(f"Total size: {summary.get('total_size_bytes', 0) / 1024 / 1024:.1f} MB")
    
    date_range = summary.get('date_range', {})
    if date_range.get('oldest'):
        print(f"Date range: {date_range['oldest']} to {date_range['newest']}")

def view_date_archives(date_str):
    """View archives for a specific date."""
    date_dir = ARCHIVE_DIR / date_str
    if not date_dir.exists():
        print(f"No archives found for date: {date_str}")
        return
    
    print(f"📅 Archives for {date_str}:")
    print("=" * 40)
    
    # Show metadata if available
    metadata_files = list(date_dir.glob("*_metadata.json"))
    if metadata_files:
        with open(metadata_files[0], 'r') as f:
            metadata = json.load(f)
        
        print(f"Created: {metadata.get('created_at', 'Unknown')}")
        summary = metadata.get('summary', {})
        print(f"Dashboards: {summary.get('successful', 0)}/{summary.get('total_dashboards', 0)}")
        
        # Show dashboard details
        dashboards = metadata.get('dashboards', {})
        for name, info in dashboards.items():
            size_kb = info.get('size_bytes', 0) / 1024
            print(f"  📊 {name}: {info.get('archive_file', 'Unknown')} ({size_kb:.1f} KB)")
    
    # List PNG files
    png_files = sorted(date_dir.glob("*.png"))
    print(f"\n📁 Files ({len(png_files)} total):")
    for png_file in png_files:
        size_kb = png_file.stat().st_size / 1024
        print(f"  🖼️  {png_file.name} ({size_kb:.1f} KB)")

def main():
    parser = argparse.ArgumentParser(description="View dashboard archives")
    parser.add_argument("--date", help="View archives for specific date (YYYY-MM-DD)")
    parser.add_argument("--summary", action="store_true", help="Show archive summary")
    parser.add_argument("--list", action="store_true", help="List all archives")
    
    args = parser.parse_args()
    
    if args.summary:
        show_archive_summary()
    elif args.date:
        view_date_archives(args.date)
    else:
        list_archives()

if __name__ == "__main__":
    main()
