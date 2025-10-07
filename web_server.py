#!/usr/bin/env python3
"""
web_server.py
- Web interface for dashboard browsing and management
- Allows manual navigation through all dashboards
- Browse archives and view historical snapshots
- Configuration and status monitoring
"""

import os
import sys
import json
import time
import threading
from datetime import datetime
from pathlib import Path
import logging

from flask import Flask, render_template_string, jsonify, send_file, request, redirect, url_for

# Import dashboard modules
try:
    from dash_comic import compose_dashboard_no_display as compose_comic_web
    from dash_weather import compose_weather_dashboard_no_display as compose_weather_web
    from dash_motivation import compose_motivation_dashboard_no_display as compose_motivation_web
    from dash_recipe import compose_recipe_dashboard_no_display as compose_recipe_web
    DASHBOARDS_AVAILABLE = True
except ImportError as e:
    logging.warning("Dashboard modules not available: %s", e)
    DASHBOARDS_AVAILABLE = False

# Import archive system
try:
    from archive_scheduler import archive_scheduler
    from view_archives import list_archives, show_archive_summary, view_date_archives
    ARCHIVE_AVAILABLE = True
except ImportError:
    ARCHIVE_AVAILABLE = False

# Configuration
WEB_PORT = int(os.environ.get("WEB_PORT", "5000"))
WEB_HOST = os.environ.get("WEB_HOST", "0.0.0.0")
DEBUG_MODE = os.environ.get("WEB_DEBUG", "false").lower() == "true"

# Cache for dashboard images
IMAGE_CACHE_DIR = Path("web_cache")
IMAGE_CACHE_DIR.mkdir(exist_ok=True, mode=0o755)

app = Flask(__name__)
app.logger.setLevel(logging.INFO)

# HTML Template
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sakura Dashboard Web Interface</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 0;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            color: #333;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            overflow: hidden;
        }
        .header {
            background: linear-gradient(135deg, #ff6b6b, #feca57);
            color: white;
            padding: 30px;
            text-align: center;
        }
        .header h1 {
            margin: 0;
            font-size: 2.5em;
            font-weight: 300;
        }
        .header p {
            margin: 10px 0 0 0;
            opacity: 0.9;
        }
        .nav {
            display: flex;
            justify-content: center;
            gap: 15px;
            padding: 20px;
            background: #f8f9fa;
            border-bottom: 1px solid #e9ecef;
        }
        .nav button {
            padding: 12px 24px;
            border: none;
            border-radius: 25px;
            background: #007bff;
            color: white;
            font-size: 16px;
            cursor: pointer;
            transition: all 0.3s ease;
            font-weight: 500;
        }
        .nav button:hover {
            background: #0056b3;
            transform: translateY(-2px);
        }
        .nav button.active {
            background: #28a745;
        }
        .content {
            padding: 30px;
        }
        .dashboard-container {
            text-align: center;
            background: #f8f9fa;
            border-radius: 15px;
            padding: 30px;
            margin: 20px 0;
        }
        .dashboard-image {
            max-width: 100%;
            height: auto;
            border-radius: 10px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
            margin: 20px 0;
        }
        .status {
            background: #e8f5e8;
            border: 1px solid #c3e6c3;
            border-radius: 10px;
            padding: 20px;
            margin: 20px 0;
        }
        .status h3 {
            margin-top: 0;
            color: #155724;
        }
        .archive-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
            gap: 20px;
            margin: 20px 0;
        }
        .archive-item {
            background: white;
            border-radius: 10px;
            padding: 15px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
            text-align: center;
            cursor: pointer;
            transition: transform 0.3s ease;
        }
        .archive-item:hover {
            transform: translateY(-5px);
        }
        .loading {
            text-align: center;
            padding: 40px;
            color: #666;
        }
        .error {
            background: #f8d7da;
            color: #721c24;
            padding: 20px;
            border-radius: 10px;
            margin: 20px 0;
        }
        .footer {
            text-align: center;
            padding: 20px;
            background: #f8f9fa;
            color: #666;
            border-top: 1px solid #e9ecef;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🌸 Sakura Dashboard Web Interface</h1>
            <p>Browse your e-ink dashboards from anywhere!</p>
        </div>
        
        <div class="nav">
            <button onclick="loadDashboard('comic')">📚 Comic</button>
            <button onclick="loadDashboard('weather')">🌤️ Weather</button>
            <button onclick="loadDashboard('motivation')">📅 Motivation</button>
            <button onclick="loadDashboard('recipe')">🍳 Recipe</button>
            <button onclick="loadArchives()">📁 Archives</button>
            <button onclick="loadStatus()">📊 Status</button>
        </div>
        
        <div class="content" id="content">
            <div class="loading">
                <h3>🌸 Welcome to Sakura Dashboard!</h3>
                <p>Click a dashboard above to get started.</p>
            </div>
        </div>
        
        <div class="footer">
            <p>🕐 Last updated: <span id="lastUpdate"></span></p>
        </div>
    </div>

    <script>
        let currentDashboard = null;
        
        function updateLastUpdate() {
            document.getElementById('lastUpdate').textContent = new Date().toLocaleString();
        }
        
        function setActiveButton(name) {
            document.querySelectorAll('.nav button').forEach(btn => {
                btn.classList.remove('active');
                if (btn.textContent.toLowerCase().includes(name.toLowerCase())) {
                    btn.classList.add('active');
                }
            });
        }
        
        async function loadDashboard(name) {
            currentDashboard = name;
            setActiveButton(name);
            
            document.getElementById('content').innerHTML = `
                <div class="loading">
                    <h3>Loading ${name} dashboard...</h3>
                    <p>Generating fresh content...</p>
                </div>
            `;
            
            try {
                const response = await fetch(`/api/dashboard/${name}`);
                const data = await response.json();
                
                if (data.success) {
                    document.getElementById('content').innerHTML = `
                        <div class="dashboard-container">
                            <h2>📚 ${data.name} Dashboard</h2>
                            <p><strong>Generated:</strong> ${new Date(data.generated_at).toLocaleString()}</p>
                            <img src="/api/image/${name}" alt="${name} dashboard" class="dashboard-image">
                            <p><em>🌸 Fresh ${name} content generated just for you!</em></p>
                        </div>
                    `;
                } else {
                    document.getElementById('content').innerHTML = `
                        <div class="error">
                            <h3>❌ Error loading ${name} dashboard</h3>
                            <p>${data.error}</p>
                        </div>
                    `;
                }
            } catch (error) {
                document.getElementById('content').innerHTML = `
                    <div class="error">
                        <h3>❌ Network Error</h3>
                        <p>Failed to load dashboard: ${error.message}</p>
                    </div>
                `;
            }
            
            updateLastUpdate();
        }
        
        async function loadArchives() {
            setActiveButton('archives');
            
            document.getElementById('content').innerHTML = `
                <div class="loading">
                    <h3>Loading archives...</h3>
                </div>
            `;
            
            try {
                const response = await fetch('/api/archives');
                const data = await response.json();
                
                if (data.success) {
                    let html = '<h2>📁 Dashboard Archives</h2>';
                    
                    if (data.archives.length === 0) {
                        html += '<p>No archives found yet. Archives are created daily at 1:00 AM.</p>';
                    } else {
                        html += '<div class="archive-grid">';
                        data.archives.forEach(archive => {
                            html += `
                                <div class="archive-item" onclick="viewArchive('${archive.date}')">
                                    <h4>📅 ${archive.date}</h4>
                                    <p>${archive.count} snapshots</p>
                                    <small>${archive.successful}/${archive.total} successful</small>
                                </div>
                            `;
                        });
                        html += '</div>';
                    }
                    
                    document.getElementById('content').innerHTML = html;
                } else {
                    document.getElementById('content').innerHTML = `
                        <div class="error">
                            <h3>❌ Error loading archives</h3>
                            <p>${data.error}</p>
                        </div>
                    `;
                }
            } catch (error) {
                document.getElementById('content').innerHTML = `
                    <div class="error">
                        <h3>❌ Network Error</h3>
                        <p>Failed to load archives: ${error.message}</p>
                    </div>
                `;
            }
            
            updateLastUpdate();
        }
        
        async function viewArchive(date) {
            try {
                const response = await fetch(`/api/archive/${date}`);
                const data = await response.json();
                
                if (data.success) {
                    let html = `<h2>📅 Archives for ${date}</h2>`;
                    html += `<p><a href="javascript:loadArchives()">← Back to Archives</a></p>`;
                    
                    data.dashboards.forEach(dashboard => {
                        html += `
                            <div class="dashboard-container">
                                <h3>📊 ${dashboard.name}</h3>
                                <p>Generated: ${new Date(dashboard.generated_at).toLocaleString()}</p>
                                <img src="/api/archive-image/${date}/${dashboard.name}" alt="${dashboard.name}" class="dashboard-image">
                            </div>
                        `;
                    });
                    
                    document.getElementById('content').innerHTML = html;
                }
            } catch (error) {
                document.getElementById('content').innerHTML = `
                    <div class="error">
                        <h3>❌ Error loading archive</h3>
                        <p>${error.message}</p>
                    </div>
                `;
            }
        }
        
        async function loadStatus() {
            setActiveButton('status');
            
            document.getElementById('content').innerHTML = `
                <div class="loading">
                    <h3>Loading status...</h3>
                </div>
            `;
            
            try {
                const response = await fetch('/api/status');
                const data = await response.json();
                
                let html = `
                    <h2>📊 System Status</h2>
                    <div class="status">
                        <h3>🌸 Dashboard Service</h3>
                        <p><strong>Status:</strong> ${data.service_running ? '✅ Running' : '❌ Stopped'}</p>
                        <p><strong>Uptime:</strong> ${data.uptime || 'Unknown'}</p>
                        <p><strong>Current Dashboard:</strong> ${data.current_dashboard || 'None'}</p>
                        <p><strong>Rotation Interval:</strong> ${data.rotation_interval || 'Unknown'}</p>
                    </div>
                    
                    <div class="status">
                        <h3>📁 Archive System</h3>
                        <p><strong>Status:</strong> ${data.archive_available ? '✅ Available' : '❌ Not Available'}</p>
                        <p><strong>Total Archives:</strong> ${data.total_archives || 0}</p>
                        <p><strong>Archive Size:</strong> ${data.archive_size || '0 MB'}</p>
                        <p><strong>Next Archive:</strong> ${data.next_archive || 'Unknown'}</p>
                    </div>
                    
                    <div class="status">
                        <h3>🌐 Web Interface</h3>
                        <p><strong>Server:</strong> ✅ Running</p>
                        <p><strong>Port:</strong> ${data.web_port || WEB_PORT}</p>
                        <p><strong>Last Update:</strong> ${new Date().toLocaleString()}</p>
                    </div>
                `;
                
                document.getElementById('content').innerHTML = html;
            } catch (error) {
                document.getElementById('content').innerHTML = `
                    <div class="error">
                        <h3>❌ Error loading status</h3>
                        <p>${error.message}</p>
                    </div>
                `;
            }
            
            updateLastUpdate();
        }
        
        // Initialize
        updateLastUpdate();
        setInterval(updateLastUpdate, 1000);
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/dashboard/<dashboard_name>')
def get_dashboard(dashboard_name):
    """Generate and return dashboard data."""
    try:
        if not DASHBOARDS_AVAILABLE:
            return jsonify({"success": False, "error": "Dashboard modules not available"})
        
        # Generate the dashboard image (web-only versions to avoid affecting e-ink display)
        if dashboard_name == 'comic':
            dashboard_func = compose_comic_web
            name = "Comic"
        elif dashboard_name == 'weather':
            dashboard_func = compose_weather_web
            name = "Weather"
        elif dashboard_name == 'motivation':
            dashboard_func = compose_motivation_web
            name = "Motivation"
        elif dashboard_name == 'recipe':
            dashboard_func = compose_recipe_web
            name = "Recipe"
        else:
            return jsonify({"success": False, "error": f"Unknown dashboard: {dashboard_name}"})
        
        # Generate the dashboard (web-only, no e-ink display update)
        img = dashboard_func()
        
        # Save to cache
        cache_path = IMAGE_CACHE_DIR / f"{dashboard_name}.png"
        try:
            img.save(cache_path)
        except PermissionError:
            app.logger.warning("Permission denied saving cache to %s, trying alternative location", cache_path)
            # Try saving to a temp location in the current directory
            cache_path = Path(f"web_cache_{dashboard_name}.png")
            img.save(cache_path)
        except Exception as e:
            app.logger.error("Failed to save cache: %s", e)
            # Continue without caching
        
        return jsonify({
            "success": True,
            "name": name,
            "generated_at": datetime.now().isoformat(),
            "cache_path": str(cache_path)
        })
        
    except Exception as e:
        app.logger.error("Error generating dashboard %s: %s", dashboard_name, e)
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/image/<dashboard_name>')
def get_dashboard_image(dashboard_name):
    """Serve dashboard image."""
    # Try primary cache location first
    cache_path = IMAGE_CACHE_DIR / f"{dashboard_name}.png"
    if cache_path.exists():
        return send_file(cache_path, mimetype='image/png')
    
    # Try fallback cache location
    fallback_path = Path(f"web_cache_{dashboard_name}.png")
    if fallback_path.exists():
        return send_file(fallback_path, mimetype='image/png')
    
    # Generate if not cached
    get_dashboard(dashboard_name)
    
    # Check both locations after generation
    if cache_path.exists():
        return send_file(cache_path, mimetype='image/png')
    elif fallback_path.exists():
        return send_file(fallback_path, mimetype='image/png')
    else:
        return "Image not found", 404

@app.route('/api/archives')
def get_archives():
    """Get list of available archives."""
    try:
        if not ARCHIVE_AVAILABLE:
            return jsonify({"success": False, "error": "Archive system not available"})
        
        # This would need to be implemented to return archive list
        # For now, return empty list
        return jsonify({
            "success": True,
            "archives": []
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/archive/<date>')
def get_archive_date(date):
    """Get archives for a specific date."""
    try:
        if not ARCHIVE_AVAILABLE:
            return jsonify({"success": False, "error": "Archive system not available"})
        
        # This would need to be implemented
        return jsonify({"success": False, "error": "Archive viewing not yet implemented"})
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/status')
def get_status():
    """Get system status."""
    try:
        return jsonify({
            "success": True,
            "service_running": True,  # Would need to check actual service status
            "uptime": "Unknown",
            "current_dashboard": "Unknown",
            "rotation_interval": "120s",
            "archive_available": ARCHIVE_AVAILABLE,
            "total_archives": 0,
            "archive_size": "0 MB",
            "next_archive": "1:00 AM daily",
            "web_port": WEB_PORT
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

def ensure_cache_directory():
    """Ensure the cache directory exists with proper permissions."""
    try:
        IMAGE_CACHE_DIR.mkdir(exist_ok=True, mode=0o755)
        app.logger.info("Cache directory ready: %s", IMAGE_CACHE_DIR)
    except Exception as e:
        app.logger.error("Failed to create cache directory: %s", e)

def start_web_server():
    """Start the web server in a separate thread."""
    ensure_cache_directory()
    app.logger.info("Starting web server on %s:%d", WEB_HOST, WEB_PORT)
    app.run(host=WEB_HOST, port=WEB_PORT, debug=DEBUG_MODE, use_reloader=False, threaded=True)

if __name__ == "__main__":
    start_web_server()
