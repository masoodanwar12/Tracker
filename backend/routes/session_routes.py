# routes/session_routes.py — check-in, check-out, pause, resume, attendance history
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify
from database import get_conn
from auth import login_required

sessions_bp = Blueprint("sessions", __name__)

AUTO_OFFLINE_AFTER_SECONDS = 25  # ~2-3 missed heartbeats (heartbeat fires every 10s) before treating as offline


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _parse_iso(ts):
    # Stored timestamps end in "Z"; Python's fromisoformat wants "+00:00" instead.
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def auto_close_stale_sessions(conn):
    """Any session whose last heartbeat (or check-in, if no heartbeat ever arrived)
    is older than AUTO_OFFLINE_AFTER_SECONDS gets marked ended. This covers the case
    where someone closes the tab/browser without clicking Check Out — without this,
    they'd show as 'active' forever."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=AUTO_OFFLINE_AFTER_SECONDS)
    rows = conn.execute(
        "SELECT id, check_in, last_heartbeat_at FROM sessions WHERE status != 'ended'"
    ).fetchall()
    for row in rows:
        reference = row["last_heartbeat_at"] or row["check_in"]
        try:
            if _parse_iso(reference) < cutoff:
                conn.execute(
                    "UPDATE sessions SET status = 'ended', check_out = ? WHERE id = ?",
                    (row["last_heartbeat_at"] or now_iso(), row["id"]),
                )
        except (ValueError, TypeError):
            continue  # malformed timestamp from old data — skip rather than crash
    conn.commit()


@sessions_bp.post("/api/sessions/check-in")
@login_required
def check_in(user):
    if user.get("role") == "owner":
        return jsonify({"error": "Owner accounts can't check in — sign in as an employee account to track time."}), 403
    body = request.get_json(silent=True) or {}
    conn = get_conn()
    try:
        # Prevent double check-in
        existing = conn.execute(
            "SELECT id FROM sessions WHERE user_id = ? AND status != 'ended'",
            (user["id"],)
        ).fetchone()
        if existing:
            return jsonify({"error": "You already have an active session", "session_id": existing["id"]}), 409

        ts = now_iso()
        cur = conn.execute(
            "INSERT INTO sessions (user_id, project, notes, check_in, status, last_heartbeat_at) VALUES (?, ?, ?, ?, 'active', ?)",
            (user["id"], body.get("project"), body.get("notes"), ts, ts),
        )
        session_id = cur.lastrowid
        conn.execute(
            "INSERT INTO activity_events (session_id, event_type, occurred_at) VALUES (?, 'work_start', ?)",
            (session_id, ts),
        )
        conn.commit()
        return jsonify({"session_id": session_id, "check_in": ts, "status": "active"}), 201
    finally:
        conn.close()


@sessions_bp.post("/api/sessions/<int:session_id>/pause")
@login_required
def pause_session(user, session_id):
    body = request.get_json(silent=True) or {}
    reason = body.get("reason", "manual")  # "manual" or "idle"
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id, status FROM sessions WHERE id = ? AND user_id = ?", (session_id, user["id"])
        ).fetchone()
        if not row:
            return jsonify({"error": "Session not found"}), 404
        if row["status"] == "paused":
            return jsonify({"status": "paused"})  # already paused, no-op
        ts = now_iso()
        conn.execute("UPDATE sessions SET status = 'paused', last_heartbeat_at = ? WHERE id = ?", (ts, session_id))
        conn.execute(
            "INSERT INTO activity_events (session_id, event_type, occurred_at) VALUES (?, ?, ?)",
            (session_id, "pause_idle" if reason == "idle" else "pause_start", ts),
        )
        conn.commit()
        return jsonify({"status": "paused", "paused_at": ts, "reason": reason})
    finally:
        conn.close()


@sessions_bp.post("/api/sessions/<int:session_id>/resume")
@login_required
def resume_session(user, session_id):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id FROM sessions WHERE id = ? AND user_id = ?", (session_id, user["id"])
        ).fetchone()
        if not row:
            return jsonify({"error": "Session not found"}), 404
        ts = now_iso()
        conn.execute("UPDATE sessions SET status = 'active', last_heartbeat_at = ? WHERE id = ?", (ts, session_id))
        conn.execute(
            "INSERT INTO activity_events (session_id, event_type, occurred_at) VALUES (?, 'resume', ?)",
            (session_id, ts),
        )
        conn.commit()
        return jsonify({"status": "active", "resumed_at": ts})
    finally:
        conn.close()


@sessions_bp.post("/api/sessions/<int:session_id>/check-out")
@login_required
def check_out(user, session_id):
    body = request.get_json(silent=True) or {}
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id FROM sessions WHERE id = ? AND user_id = ?", (session_id, user["id"])
        ).fetchone()
        if not row:
            return jsonify({"error": "Session not found"}), 404
        ts = now_iso()
        conn.execute(
            """UPDATE sessions
               SET status = 'ended', check_out = ?,
                   total_work_seconds = ?, total_idle_seconds = ?
               WHERE id = ?""",
            (ts, body.get("total_work_seconds", 0), body.get("total_idle_seconds", 0), session_id),
        )
        conn.commit()
        return jsonify({"status": "ended", "check_out": ts})
    finally:
        conn.close()


@sessions_bp.post("/api/sessions/<int:session_id>/heartbeat")
@login_required
def heartbeat(user, session_id):
    """Called periodically by the employee's browser while checked in, so the
    owner dashboard can show live activity % without waiting for check-out."""
    body = request.get_json(silent=True) or {}
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id FROM sessions WHERE id = ? AND user_id = ?", (session_id, user["id"])
        ).fetchone()
        if not row:
            return jsonify({"error": "Session not found"}), 404
        conn.execute(
            "UPDATE sessions SET total_work_seconds = ?, total_idle_seconds = ?, last_heartbeat_at = ? WHERE id = ?",
            (body.get("total_work_seconds", 0), body.get("total_idle_seconds", 0), now_iso(), session_id),
        )
        conn.commit()
        return jsonify({"ok": True})
    finally:
        conn.close()


@sessions_bp.get("/api/sessions/active")
@login_required
def get_active(user):
    conn = get_conn()
    try:
        auto_close_stale_sessions(conn)
        row = conn.execute(
            "SELECT * FROM sessions WHERE user_id = ? AND status != 'ended' ORDER BY id DESC LIMIT 1",
            (user["id"],)
        ).fetchone()
        return jsonify(dict(row) if row else None)
    finally:
        conn.close()


@sessions_bp.get("/api/sessions")
@login_required
def list_sessions(user):
    limit = int(request.args.get("limit", 30))
    conn = get_conn()
    try:
        auto_close_stale_sessions(conn)
        rows = conn.execute(
            "SELECT * FROM sessions WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user["id"], limit)
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()


def _group_sessions_by_day(rows):
    """Turns a flat list of session rows into one summary entry per calendar day:
    how many times they checked in that day, and total active/idle seconds across
    all of that day's sessions combined."""
    days = {}
    for r in rows:
        day = r["check_in"][:10]  # "2026-06-21T10:00:00.000Z" -> "2026-06-21"
        if day not in days:
            days[day] = {
                "date": day,
                "session_count": 0,
                "total_work_seconds": 0,
                "total_idle_seconds": 0,
                "sessions": [],
            }
        days[day]["session_count"] += 1
        days[day]["total_work_seconds"] += r["total_work_seconds"] or 0
        days[day]["total_idle_seconds"] += r["total_idle_seconds"] or 0
        days[day]["sessions"].append(dict(r))
    # Most recent day first; sessions within a day most recent first too.
    ordered = sorted(days.values(), key=lambda d: d["date"], reverse=True)
    for d in ordered:
        d["sessions"].sort(key=lambda s: s["check_in"], reverse=True)
    return ordered


@sessions_bp.get("/api/sessions/daily-summary")
@login_required
def daily_summary(user):
    """Same data as /api/sessions, but grouped into one row per day — how many
    times checked in, and total active/idle time across all of that day's
    sessions — instead of one row per individual session."""
    limit_days = int(request.args.get("days", 30))
    conn = get_conn()
    try:
        auto_close_stale_sessions(conn)
        rows = conn.execute(
            "SELECT * FROM sessions WHERE user_id = ? ORDER BY id DESC LIMIT 500",
            (user["id"],)
        ).fetchall()
        grouped = _group_sessions_by_day(rows)
        return jsonify(grouped[:limit_days])
    finally:
        conn.close()


@sessions_bp.delete("/api/sessions/<int:session_id>")
@login_required
def delete_session(user, session_id):
    """Employee can delete their own session; owner can delete any session.
    Deletes the session's screenshots (DB rows + files) and activity log too,
    since they're meaningless without the session they belong to."""
    conn = get_conn()
    try:
        row = conn.execute("SELECT id, user_id FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not row:
            return jsonify({"error": "Session not found"}), 404
        if user["role"] != "owner" and row["user_id"] != user["id"]:
            return jsonify({"error": "You can only delete your own sessions"}), 403

        shots = conn.execute(
            "SELECT file_name FROM screenshots WHERE session_id = ?", (session_id,)
        ).fetchall()

        conn.execute("DELETE FROM screenshots WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM activity_events WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()

        import os
        from werkzeug.utils import secure_filename
        upload_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads", "screenshots")
        for s in shots:
            try:
                p = os.path.join(upload_dir, secure_filename(s["file_name"]))
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass

        return jsonify({"ok": True})
    finally:
        conn.close()
