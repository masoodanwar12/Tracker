# routes/owner_routes.py — owner-only endpoints for the web dashboard
from flask import Blueprint, request, jsonify
from database import get_conn
from auth import owner_required
from datetime import datetime, timezone
from routes.session_routes import auto_close_stale_sessions

owner_bp = Blueprint("owner", __name__)


def today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


@owner_bp.get("/api/owner/employees")
@owner_required
def list_employees(user):
    """All employees with their current session status."""
    conn = get_conn()
    try:
        auto_close_stale_sessions(conn)
        employees = conn.execute(
            "SELECT id, name, email, designation FROM users WHERE role = 'employee' ORDER BY name"
        ).fetchall()

        result = []
        for emp in employees:
            session = conn.execute(
                """SELECT id, status, check_in, project, total_work_seconds, total_idle_seconds
                   FROM sessions
                   WHERE user_id = ? AND status != 'ended'
                   ORDER BY id DESC LIMIT 1""",
                (emp["id"],),
            ).fetchone()
            result.append({
                "id": emp["id"],
                "name": emp["name"],
                "email": emp["email"],
                "designation": emp["designation"],
                "session_status": session["status"] if session else "offline",
                "session_id": session["id"] if session else None,
                "check_in": session["check_in"] if session else None,
                "project": session["project"] if session else None,
                "total_work_seconds": session["total_work_seconds"] if session else 0,
                "total_idle_seconds": session["total_idle_seconds"] if session else 0,
            })
        return jsonify(result)
    finally:
        conn.close()


@owner_bp.get("/api/owner/employee/<int:employee_id>/sessions")
@owner_required
def employee_sessions(user, employee_id):
    """Attendance history for a specific employee."""
    limit = int(request.args.get("limit", 30))
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM sessions WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (employee_id, limit),
        ).fetchall()
        return jsonify([dict(r) for r in rows])
    finally:
        conn.close()


@owner_bp.get("/api/owner/employee/<int:employee_id>/sessions/daily-summary")
@owner_required
def employee_daily_summary(user, employee_id):
    """Same as employee_sessions but grouped into one row per day — total
    check-ins and total active/idle time for that day, instead of one row
    per individual session."""
    from routes.session_routes import _group_sessions_by_day
    limit_days = int(request.args.get("days", 30))
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM sessions WHERE user_id = ? ORDER BY id DESC LIMIT 500",
            (employee_id,),
        ).fetchall()
        grouped = _group_sessions_by_day(rows)
        return jsonify(grouped[:limit_days])
    finally:
        conn.close()


@owner_bp.get("/api/owner/stats")
@owner_required
def team_stats(user):
    """Quick numbers for the dashboard header cards."""
    conn = get_conn()
    try:
        t = today()
        active_now = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE status != 'ended' AND date(check_in) = ?", (t,)
        ).fetchone()[0]
        total_employees = conn.execute(
            "SELECT COUNT(*) FROM users WHERE role = 'employee'"
        ).fetchone()[0]
        screenshots_today = conn.execute(
            "SELECT COUNT(*) FROM screenshots WHERE date(captured_at) = ?", (t,)
        ).fetchone()[0]
        return jsonify({
            "active_now": active_now,
            "total_employees": total_employees,
            "screenshots_today": screenshots_today,
        })
    finally:
        conn.close()


@owner_bp.delete("/api/owner/employee/<int:employee_id>")
@owner_required
def delete_employee(user, employee_id):
    """Permanently removes an employee account and everything tied to it:
    their sessions, screenshots (DB rows + actual files), and activity log."""
    conn = get_conn()
    try:
        target = conn.execute(
            "SELECT id, role FROM users WHERE id = ?", (employee_id,)
        ).fetchone()
        if not target:
            return jsonify({"error": "Employee not found"}), 404
        if target["role"] != "employee":
            return jsonify({"error": "Can only delete employee accounts this way"}), 400

        shots = conn.execute(
            "SELECT file_name FROM screenshots WHERE user_id = ?", (employee_id,)
        ).fetchall()

        session_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM sessions WHERE user_id = ?", (employee_id,)
        ).fetchall()]

        if session_ids:
            placeholders = ",".join("?" * len(session_ids))
            conn.execute(f"DELETE FROM activity_events WHERE session_id IN ({placeholders})", session_ids)

        conn.execute("DELETE FROM screenshots WHERE user_id = ?", (employee_id,))
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (employee_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (employee_id,))
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
