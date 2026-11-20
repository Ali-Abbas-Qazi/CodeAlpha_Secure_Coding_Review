"""
CampusNotes - a small note-sharing web app for students (VULNERABLE VERSION)
------------------------------------------------------------------------------
This version contains deliberate security flaws for a secure code review.
DO NOT deploy it. Run it only on localhost inside a lab VM.

Run:  python3 app.py   ->  http://127.0.0.1:5000
Demo accounts: admin / admin123   alice / alice2024   bob / qwerty
"""
import base64
import hashlib
import os
import pickle
import sqlite3

from flask import (Flask, g, redirect, render_template_string, request,
                   send_file, session, url_for)

app = Flask(__name__)
app.secret_key = "campusnotes-secret-123"          # hardcoded secret key
DB_PATH = "campusnotes.db"
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")


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
        db.execute("INSERT INTO users (username, password, role) VALUES (?,?,?)",
                   (u, hashlib.md5(p.encode()).hexdigest(), r))   # weak hash
    notes = [(1, "Server credentials", "Lab DB root password: Adm1n!Lab"),
             (2, "Exam prep", "Revise subnetting and OSI layers."),
             (3, "Group project", "Meeting on Friday at 3pm.")]
    db.executemany("INSERT INTO notes (owner_id, title, body) VALUES (?,?,?)", notes)
    db.commit()
    db.close()
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    with open(os.path.join(UPLOAD_DIR, "syllabus.txt"), "w") as f:
        f.write("CS-301 Secure Software Development - Week 1: Threat modelling\n")


# ---------------------------------------------------------------- templates
BASE = """<!doctype html><title>CampusNotes</title>
<style>body{font-family:sans-serif;max-width:760px;margin:30px auto;padding:0 16px}
input,textarea{display:block;margin:6px 0 12px;padding:8px;width:100%}
.note{border:1px solid #ccc;padding:10px;margin:10px 0;border-radius:6px}</style>
<h1>CampusNotes</h1>
{% if session.get('user') %}<p>Logged in as <b>{{ session['user'] }}</b> |
<a href="/">My notes</a> | <a href="/search">Search</a> | <a href="/tools">Tools</a> |
<a href="/logout">Logout</a></p>{% endif %}
{{ content|safe }}"""


def page(content, **ctx):
    inner = render_template_string(content, **ctx)
    return render_template_string(BASE, content=inner)


# ------------------------------------------------------------------- routes
@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        username = request.form["username"]
        password = hashlib.md5(request.form["password"].encode()).hexdigest()
        query = (f"SELECT * FROM users WHERE username = '{username}' "
                 f"AND password = '{password}'")                     # SQL injection
        user = get_db().execute(query).fetchone()
        if user:
            session["user"] = user["username"]
            session["uid"] = user["id"]
            session["role"] = user["role"]
            return redirect(url_for("index"))
        error = f"Login failed for user {username}"
    return page("""<h2>Login</h2><p style="color:red">{{ error }}</p>
        <form method="post"><input name="username" placeholder="Username">
        <input name="password" type="password" placeholder="Password">
        <button>Login</button></form>""", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def index():
    if "uid" not in session:
        return redirect(url_for("login"))
    notes = get_db().execute("SELECT * FROM notes WHERE owner_id = ?",
                             (session["uid"],)).fetchall()
    theme = "light"
    if request.cookies.get("prefs"):
        prefs = pickle.loads(base64.b64decode(request.cookies["prefs"]))  # insecure deserialisation
        theme = prefs.get("theme", "light")
    return page("""<h2>My notes</h2><p>Theme: {{ theme }}</p>
        {% for n in notes %}<div class="note"><a href="/note/{{ n['id'] }}">{{ n['title'] }}</a></div>{% endfor %}
        <h3>New note</h3><form method="post" action="/add">
        <input name="title" placeholder="Title"><textarea name="body" placeholder="Note"></textarea>
        <button>Save</button></form>
        <p><a href="/download?file=syllabus.txt">Download course syllabus</a></p>""",
                notes=notes, theme=theme)


@app.route("/add", methods=["POST"])                                # no CSRF protection
def add():
    if "uid" not in session:
        return redirect(url_for("login"))
    db = get_db()
    db.execute("INSERT INTO notes (owner_id, title, body) VALUES (?,?,?)",
               (session["uid"], request.form["title"], request.form["body"]))
    db.commit()
    return redirect(url_for("index"))


@app.route("/note/<int:note_id>")
def view_note(note_id):
    if "uid" not in session:
        return redirect(url_for("login"))
    note = get_db().execute("SELECT * FROM notes WHERE id = ?",
                            (note_id,)).fetchone()                   # no ownership check (IDOR)
    if not note:
        return page("<p>Note not found</p>"), 404
    return page("""<div class="note"><h2>{{ n['title'] }}</h2>
        <div>{{ n['body']|safe }}</div></div>""", n=note)            # stored XSS


@app.route("/search")
def search():
    if "uid" not in session:
        return redirect(url_for("login"))
    q = request.args.get("q", "")
    rows = []
    if q:
        rows = get_db().execute(
            "SELECT id, title FROM notes WHERE owner_id = %d AND title LIKE '%%%s%%'"
            % (session["uid"], q)).fetchall()                        # SQL injection
    return page("""<h2>Search my notes</h2><form><input name="q" value="{{ q }}">
        <button>Search</button></form>
        {% for r in rows %}<div class="note">{{ r[0] }} - {{ r[1] }}</div>{% endfor %}""",
                q=q, rows=rows)


@app.route("/download")
def download():
    filename = request.args.get("file", "")
    return send_file(os.path.join(UPLOAD_DIR, filename))             # path traversal


@app.route("/tools", methods=["GET", "POST"])
def tools():
    if "uid" not in session:
        return redirect(url_for("login"))
    output = ""
    if request.method == "POST":
        host = request.form["host"]
        output = os.popen("ping -c 2 " + host).read()                # command injection
    return page("""<h2>Network tools</h2><p>Check if a campus server is online.</p>
        <form method="post"><input name="host" placeholder="e.g. 127.0.0.1">
        <button>Ping</button></form><pre>{{ output }}</pre>""", output=output)


if __name__ == "__main__":
    if not os.path.exists(DB_PATH):
        init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)                   # debug mode on, all interfaces
