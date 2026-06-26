# auth.py — password hashing (werkzeug) and JWT tokens (PyJWT)
import os
import jwt
from datetime import datetime, timezone, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from flask import request, jsonify
from database import get_conn

SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-in-production")
ALGORITHM = "HS256"
TOKEN_EXPIRY_DAYS = 7


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return check_password_hash(hashed, password)


def create_token(user_id: int, role: str, email: str) -> str:
    payload = {
        "id": user_id,
        "role": role,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(days=TOKEN_EXPIRY_DAYS),
    }
    return jwt.encode(payload, SECRET, algorithm=ALGORITHM)


def decode_token(token: str):
    try:
        return jwt.decode(token, SECRET, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def get_current_user():
    """Extract the JWT payload from the Authorization header, then confirm that user
    still exists in the DB. A token can decode successfully but point at a user_id
    that no longer exists (e.g. the database was reset/replaced while a browser still
    had an old token saved) — without this check, that leads to a confusing
    FOREIGN KEY constraint crash deeper in the request instead of a clean 401."""
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    payload = decode_token(header[7:])
    if not payload:
        return None
    conn = get_conn()
    try:
        row = conn.execute("SELECT id FROM users WHERE id = ?", (payload["id"],)).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return payload


def login_required(f):
    """Decorator: rejects requests without a valid JWT for a user that still exists."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({"error": "Authentication required", "code": "INVALID_SESSION"}), 401
        return f(*args, user=user, **kwargs)
    return wrapper


def owner_required(f):
    """Decorator: rejects requests from non-owners."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({"error": "Authentication required", "code": "INVALID_SESSION"}), 401
        if user["role"] != "owner":
            return jsonify({"error": "Owner access required"}), 403
        return f(*args, user=user, **kwargs)
    return wrapper
