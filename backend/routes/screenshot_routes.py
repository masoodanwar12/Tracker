# routes/screenshot_routes.py — upload, serve, and list screenshots
import os
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from database import get_conn
from auth import login_required, owner_required

screenshots_bp = Blueprint("screenshots", __name__)

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads", "screenshots")
ALLOWED_MIMES = {"image/png", "image/jpeg", "image/webp"}
MAX_SIZE_BYTES = 8 * 1024 * 1024  # 8 MB

os.makedirs(UPLOAD_DIR, exist_ok=True)


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ── upload (called by the desktop agent every 10 minutes) ──────────────────
@screenshots_bp.post("/api/screenshots/upload")
@login_required
def upload_screenshot(user):
    if "screenshot" not in request.files:
        return jsonify({"error": "No screenshot file received"}), 400

    file = request.files["screenshot"]
    session_id = request.form.get("session_id")
    active_window_title = request.form.get("active_window_title", "Unknown")
    capture_type = request.form.get("capture_type", "auto")

    if not session_id:
        return jsonify({"error": "session_id is required"}), 400
    if file.mimetype not in ALLOWED_MIMES:
        return jsonify({"error": "Only PNG, JPEG, or WebP images are accepted"}), 400

    # Read into memory to check size before saving
    data = file.read()
    if len(data) > MAX_SIZE_BYTES:
        return jsonify({"error": "Screenshot exceeds 8 MB limit"}), 400

    ts = now_iso()
    ext = ".png" if "png" in file.mimetype else (".jpg" if "jpeg" in file.mimetype else ".webp")
    file_name = f"user{user['id']}_{int(datetime.now(timezone.utc).timestamp() * 1000)}{ext}"
    save_path = os.path.join(UPLOAD_DIR, file_name)

    with open(save_path, "wb") as f:
        f.write(data)

    conn = get_conn()
    try:
        cur = conn.execute(
            """INSERT INTO screenshots
               (session_id, user_id, file_name, captured_at, active_window_title, capture_type)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (int(session_id), user["id"], file_name, ts, active_window_title, capture_type),
        )
        conn.commit()
        return jsonify({
            "id": cur.lastrowid,
            "captured_at": ts,
            "active_window_title": active_window_title,
            "capture_type": capture_type,
            "url": f"/api/screenshots/file/{file_name}",
        }), 201
    finally:
        conn.close()


# ── serve the actual image file ────────────────────────────────────────────
@screenshots_bp.get("/api/screenshots/file/<path:filename>")
def serve_file(filename):
    # Basic path traversal protection
    safe = secure_filename(filename)
    if safe != filename:
        return jsonify({"error": "Invalid filename"}), 400
    return send_from_directory(UPLOAD_DIR, safe)


# ── employee views their own screenshots ───────────────────────────────────
@screenshots_bp.get("/api/screenshots/mine")
@login_required
def my_screenshots(user):
    limit = int(request.args.get("limit", 50))
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT id, session_id, captured_at, active_window_title, capture_type, file_name
               FROM screenshots WHERE user_id = ?
               ORDER BY captured_at DESC LIMIT ?""",
            (user["id"], limit),
        ).fetchall()
        return jsonify([{**dict(r), "url": f"/api/screenshots/file/{r['file_name']}"} for r in rows])
    finally:
        conn.close()


# ── screenshots for one session (employee's own) ───────────────────────────
@screenshots_bp.get("/api/screenshots/session/<int:session_id>")
@login_required
def session_screenshots(user, session_id):
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT id, captured_at, active_window_title, capture_type, file_name
               FROM screenshots WHERE session_id = ? AND user_id = ?
               ORDER BY captured_at ASC""",
            (session_id, user["id"]),
        ).fetchall()
        return jsonify([{**dict(r), "url": f"/api/screenshots/file/{r['file_name']}"} for r in rows])
    finally:
        conn.close()


# ── owner views a specific employee's screenshots ──────────────────────────
@screenshots_bp.get("/api/screenshots/employee/<int:employee_id>")
@owner_required
def employee_screenshots(user, employee_id):
    limit = int(request.args.get("limit", 50))
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT s.id, s.session_id, s.captured_at, s.active_window_title,
                      s.capture_type, s.file_name, s.viewed_by_owner,
                      u.name AS employee_name
               FROM screenshots s JOIN users u ON u.id = s.user_id
               WHERE s.user_id = ?
               ORDER BY s.captured_at DESC LIMIT ?""",
            (employee_id, limit),
        ).fetchall()
        return jsonify([{**dict(r), "url": f"/api/screenshots/file/{r['file_name']}"} for r in rows])
    finally:
        conn.close()


# ── owner marks a screenshot as reviewed ──────────────────────────────────
@screenshots_bp.patch("/api/screenshots/<int:screenshot_id>/mark-viewed")
@owner_required
def mark_viewed(user, screenshot_id):
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE screenshots SET viewed_by_owner = 1 WHERE id = ?", (screenshot_id,)
        )
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


# ── delete a screenshot: employee can delete their own, owner can delete any ──
@screenshots_bp.delete("/api/screenshots/<int:screenshot_id>")
@login_required
def delete_screenshot(user, screenshot_id):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id, user_id, file_name FROM screenshots WHERE id = ?", (screenshot_id,)
        ).fetchone()
        if not row:
            return jsonify({"error": "Screenshot not found"}), 404
        if user["role"] != "owner" and row["user_id"] != user["id"]:
            return jsonify({"error": "You can only delete your own screenshots"}), 403

        conn.execute("DELETE FROM screenshots WHERE id = ?", (screenshot_id,))
        conn.commit()

        # Best-effort file cleanup — DB row is gone either way, a leftover file isn't critical.
        try:
            file_path = os.path.join(UPLOAD_DIR, secure_filename(row["file_name"]))
            if os.path.exists(file_path):
                os.remove(file_path)
        except OSError:
            pass

        return jsonify({"ok": True})
    finally:
        conn.close()
