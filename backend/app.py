# app.py — WorkPulse Python backend entry point
import os
from flask import Flask, jsonify, send_from_directory

from database import init_db
from routes.auth_routes import auth_bp
from routes.session_routes import sessions_bp
from routes.screenshot_routes import screenshots_bp
from routes.owner_routes import owner_bp

WEB_DASHBOARD_DIR = os.path.join(os.path.dirname(__file__), "..", "web-dashboard")

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB max request body


# ── CORS for local development ─────────────────────────────────────────────
@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response

@app.route("/api/<path:path>", methods=["OPTIONS"])
@app.route("/api/", methods=["OPTIONS"])
def options_handler(path=""):
    return "", 204


# ── Register all route blueprints ──────────────────────────────────────────
app.register_blueprint(auth_bp)
app.register_blueprint(sessions_bp)
app.register_blueprint(screenshots_bp)
app.register_blueprint(owner_bp)


# ── Health check ───────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    from datetime import datetime, timezone
    return jsonify({"status": "ok", "time": datetime.now(timezone.utc).isoformat()})


# ── Serve the web dashboard (static HTML/JS/CSS) ───────────────────────────
@app.get("/")
@app.get("/<path:path>")
def serve_dashboard(path=""):
    # Only serve if the web-dashboard directory exists
    if not os.path.isdir(WEB_DASHBOARD_DIR):
        return jsonify({"error": "Web dashboard not found"}), 404
    target = os.path.join(WEB_DASHBOARD_DIR, path)
    # Fall back to index.html for any non-asset path (SPA routing)
    if not path or not os.path.isfile(target):
        return send_from_directory(WEB_DASHBOARD_DIR, "index.html")
    return send_from_directory(WEB_DASHBOARD_DIR, path)


# ── Init DB and start ──────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 4000))
    print(f"WorkPulse backend (Python/Flask) running on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
