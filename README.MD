# WorkPulse

A lightweight employee time-tracking and monitoring web app built with Python (Flask), vanilla HTML/CSS/JS, and SQLite.

## Features

- Employee check-in / check-out with project tagging and notes
- Heartbeat-based auto-offline - marks employees offline if the tab is closed without checking out
- Screenshot capture - periodic and manual screenshots stored per session
- Owner dashboard - real-time view of all employee statuses, attendance history, and screenshot gallery
- JWT authentication - role-based access (owner vs employee)
- Activity tracking - work vs idle time logged per session
- Single-file frontend - no build step required

## Tech Stack

| Layer    | Technology                     |
|----------|--------------------------------|
| Backend  | Python 3, Flask                |
| Auth     | PyJWT + Werkzeug password hash |
| Database | SQLite (WAL mode)              |
| Frontend | Vanilla HTML / CSS / JS        |

## Getting Started

cd backend
pip install -r requirements.txt
python app.py

Server runs at http://localhost:4000

## API Endpoints

| Method | Route | Description |
|--------|-------|-------------|
| POST | /api/auth/register | Register employee or owner |
| POST | /api/auth/login | Login, returns JWT |
| POST | /api/sessions/check-in | Employee check-in |
| POST | /api/sessions/check-out | Employee check-out |
| POST | /api/sessions/heartbeat | Keep session alive |
| GET | /api/owner/employees | All employees + live status |
| GET | /api/owner/screenshots | Screenshot gallery |

## License

MIT