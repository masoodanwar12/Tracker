# routes/auth_routes.py — /api/auth/register and /api/auth/login
from flask import Blueprint, request, jsonify
from database import get_conn
from auth import hash_password, verify_password, create_token

auth_bp = Blueprint("auth", __name__)


@auth_bp.post("/api/auth/register")
def register():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    role = "owner" if body.get("role") == "owner" else "employee"
    designation = (body.get("designation") or "").strip() or None

    if not name or not email or not password:
        return jsonify({"error": "name, email, and password are required"}), 400

    conn = get_conn()
    try:
        existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            return jsonify({"error": "An account with this email already exists"}), 409

        cur = conn.execute(
            "INSERT INTO users (name, email, password, role, designation) VALUES (?, ?, ?, ?, ?)",
            (name, email, hash_password(password), role, designation),
        )
        conn.commit()
        user_id = cur.lastrowid
        token = create_token(user_id, role, email)
        return jsonify({
            "token": token,
            "user": {"id": user_id, "name": name, "email": email, "role": role, "designation": designation},
        }), 201
    finally:
        conn.close()


@auth_bp.post("/api/auth/login")
def login():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400

    conn = get_conn()
    try:
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not user or not verify_password(password, user["password"]):
            return jsonify({"error": "Invalid email or password"}), 401

        token = create_token(user["id"], user["role"], user["email"])
        return jsonify({
            "token": token,
            "user": {
                "id": user["id"], "name": user["name"], "email": user["email"],
                "role": user["role"], "designation": user["designation"],
            },
        })
    finally:
        conn.close()
