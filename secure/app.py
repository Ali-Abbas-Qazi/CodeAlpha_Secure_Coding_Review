"""
CampusNotes - a small note-sharing web app for students (SECURE VERSION)
--------------------------------------------------------------------------
Same features as the vulnerable version, with every finding from the
code review fixed. Each fix is tagged with its finding ID (e.g. [V-01]).

Run:  python3 app.py   ->  http://127.0.0.1:5000
Demo accounts: admin / admin123   alice / alice2024   bob / qwerty
"""
import ipaddress
import json
import os
import secrets
import sqlite3
# subprocess is only used below with a fixed argument list and a validated IP
import subprocess  # nosec B404

from flask import (Flask, abort, g, redirect, render_template_string, request,
                   send_from_directory, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
# [V-04] secret key comes from the environment, never from source code
app.secret_key = os.environ.get("CAMPUSNOTES_SECRET") or secrets.token_hex(32)
# [V-10] hardened session cookie
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=os.environ.get("HTTPS") == "1")
DB_PATH = "campusnotes.db"
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")


# ----------------------------------------------------------------- database
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_):
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript("""
        DROP TABLE IF EXISTS users; DROP TABLE IF EXISTS notes;
        CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT UNIQUE,
                            password TEXT, role TEXT);
        CREATE TABLE notes (id INTEGER PRIMARY KEY, owner_id INTEGER,
                            title TEXT, body TEXT);
    """)
    users = [("admin", "admin123", "admin"), ("alice", "alice2024", "student"),
             ("bob", "qwerty", "student")]
    for u, p, r in users:
        # [V-05] salted, slow hash (scrypt/PBKDF2) instead of MD5
        db.execute("INSERT INTO users (username, password, role) VALUES (?,?,?)",
                   (u, generate_password_hash(p), r))
    notes = [(1, "Server credentials", "Lab DB root password: Adm1n!Lab"),
             (2, "Exam prep", "Revise subnetting and OSI layers."),
             (3, "Group project", "Meeting on Friday at 3pm.")]
    db.executemany("INSERT INTO notes (owner_id, title, body) VALUES (?,?,?)", notes)
    db.commit()
    db.close()
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    with open(os.path.join(UPLOAD_DIR, "syllabus.txt"), "w") as f:
        f.write("CS-301 Secure Software Development - Week 1: Threat modelling\n")


# ------------------------------------------------------------ CSRF [V-09]
def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


@app.before_request
def check_csrf():
    if request.method == "POST":
        sent = request.form.get("csrf", "")
        if not sent or not secrets.compare_digest(sent, session.get("csrf", "")):
            abort(400, "Invalid or missing CSRF token")


@app.after_request
def security_headers(resp):
    resp.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


# ---------------------------------------------------------------- templates
BASE = """<!doctype html><title>CampusNotes</title>
<style>body{font-family:sans-serif;max-width:760px;margin:30px auto;padding:0 16px}
input,textarea{display:block;margin:6px 0 12px;padding:8px;width:100%}
.note{border:1px solid #ccc;padding:10px;margin:10px 0;border-radius:6px}</style>
<h1>CampusNotes</h1>
{% if session.get('user') %}<p>Logged in as <b>{{ session['user'] }}</b> |
<a href="/">My notes</a> | <a href="/search">Search</a> | <a href="/tools">Tools</a> |
<a href="/logout">Logout</a></p>{% endif %}
{{ content|safe }}"""  # content is already rendered and auto-escaped by page()


def page(content, **ctx):
    inner = render_template_string(content, csrf=csrf_token(), **ctx)
    return render_template_string(BASE, content=inner)


def login_required():
    if "uid" not in session:
        abort(redirect(url_for("login")))


# ------------------------------------------------------------------- routes
@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        # [V-01] parameterised query: input is data, never SQL
        user = get_db().execute("SELECT * FROM users WHERE username = ?",
                                (username,)).fetchone()
        if user and check_password_hash(user["password"], password):
            session.clear()                       # new session on login
            session["user"] = user["username"]
            session["uid"] = user["id"]
            session["role"] = user["role"]
            return redirect(url_for("index"))
        error = "Invalid username or password"   # generic message
    return page("""<h2>Login</h2><p style="color:red">{{ error }}</p>
        <form method="post"><input type="hidden" name="csrf" value="{{ csrf }}">
        <input name="username" placeholder="Username">
        <input name="password" type="password" placeholder="Password">
        <button>Login</button></form>""", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def index():
    login_required()
    notes = get_db().execute("SELECT * FROM notes WHERE owner_id = ?",
                             (session["uid"],)).fetchall()
    # [V-07] JSON instead of pickle: data can't execute code
    theme = "light"
    try:
        prefs = json.loads(request.cookies.get("prefs", "{}"))
        if prefs.get("theme") in ("light", "dark"):
            theme = prefs["theme"]
    except (ValueError, AttributeError):
        pass
    return page("""<h2>My notes</h2><p>Theme: {{ theme }}</p>
        {% for n in notes %}<div class="note"><a href="/note/{{ n['id'] }}">{{ n['title'] }}</a></div>{% endfor %}
        <h3>New note</h3><form method="post" action="/add">
        <input type="hidden" name="csrf" value="{{ csrf }}">
        <input name="title" placeholder="Title" maxlength="100">
        <textarea name="body" placeholder="Note" maxlength="5000"></textarea>
        <button>Save</button></form>
        <p><a href="/download?file=syllabus.txt">Download course syllabus</a></p>""",
                notes=notes, theme=theme)


@app.route("/add", methods=["POST"])
def add():
    login_required()
    title = request.form.get("title", "").strip()[:100]
    body = request.form.get("body", "").strip()[:5000]
    if title:
        db = get_db()
        db.execute("INSERT INTO notes (owner_id, title, body) VALUES (?,?,?)",
                   (session["uid"], title, body))
        db.commit()
    return redirect(url_for("index"))


@app.route("/note/<int:note_id>")
def view_note(note_id):
    login_required()
    # [V-08] only return the note if it belongs to the logged-in user
    note = get_db().execute("SELECT * FROM notes WHERE id = ? AND owner_id = ?",
                            (note_id, session["uid"])).fetchone()
    if not note:
        return page("<p>Note not found</p>"), 404
    # [V-03] no |safe filter: Jinja escapes the body, so HTML is shown as text
    return page("""<div class="note"><h2>{{ n['title'] }}</h2>
        <div style="white-space:pre-wrap">{{ n['body'] }}</div></div>""", n=note)


@app.route("/search")
def search():
    login_required()
    q = request.args.get("q", "")[:100]
    rows = []
    if q:
        # [V-02] parameterised LIKE query
        rows = get_db().execute(
            "SELECT id, title FROM notes WHERE owner_id = ? AND title LIKE ?",
            (session["uid"], f"%{q}%")).fetchall()
    return page("""<h2>Search my notes</h2><form><input name="q" value="{{ q }}">
        <button>Search</button></form>
        {% for r in rows %}<div class="note">{{ r[0] }} - {{ r[1] }}</div>{% endfor %}""",
                q=q, rows=rows)


@app.route("/download")
def download():
    login_required()
    # [V-06] send_from_directory refuses any path that leaves UPLOAD_DIR
    filename = request.args.get("file", "")
    return send_from_directory(UPLOAD_DIR, filename, as_attachment=True)


@app.route("/tools", methods=["GET", "POST"])
def tools():
    login_required()
    output = ""
    if request.method == "POST":
        # [V-11] validate input as an IP address, then run without a shell
        try:
            host = str(ipaddress.ip_address(request.form.get("host", "").strip()))
            # fixed argument list, no shell, host already validated as an IP address
            result = subprocess.run(["ping", "-c", "2", host],  # nosec B603 B607
                                    capture_output=True, text=True, timeout=10)
            output = result.stdout or result.stderr
        except ValueError:
            output = "Please enter a valid IPv4 or IPv6 address."
        except subprocess.TimeoutExpired:
            output = "Ping timed out."
    return page("""<h2>Network tools</h2><p>Check if a campus server is online.</p>
        <form method="post"><input type="hidden" name="csrf" value="{{ csrf }}">
        <input name="host" placeholder="e.g. 127.0.0.1">
        <button>Ping</button></form><pre>{{ output }}</pre>""", output=output)


if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        init_db()
    # [V-12] debug off and bound to localhost only
    app.run(host="127.0.0.1", port=5000, debug=False)
