from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import os, json
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import libsql_experimental as libsql

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "flowboard-secret-key-change-in-production")

TURSO_URL   = os.environ.get("TURSO_URL",   "libsql://flowboard-davebraheems.aws-us-east-1.turso.io")
TURSO_TOKEN = os.environ.get("TURSO_TOKEN", "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicnciLCJpYXQiOjE3NzQwMDgxMzYsImlkIjoiMDE5ZDBiMWMtODIwMS03YzBmLThkNjktYjAxMWY4ZDAxOTJkIiwicmlkIjoiMjIxOTJiYmYtNzM4My00Njk3LWEwY2MtMGU0ODljOTA0NGZmIn0.lso9hRgcpulKQA7Uvg9prk4byrncUjYky5IWrCqJUGF5slqKgETxM72D80o17P0k7gb8zFOxhcAT9JZZLAEiDA")

def db():
    conn = libsql.connect(database=TURSO_URL, auth_token=TURSO_TOKEN)
    return conn

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def init_db():
    conn = db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS boards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS columns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            board_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            color TEXT DEFAULT '#6366f1',
            position INTEGER DEFAULT 0,
            FOREIGN KEY(board_id) REFERENCES boards(id)
        );
        CREATE TABLE IF NOT EXISTS cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            column_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            priority TEXT DEFAULT 'medium',
            due_date TEXT DEFAULT '',
            tags TEXT DEFAULT '[]',
            position INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(column_id) REFERENCES columns(id)
        );
        CREATE TABLE IF NOT EXISTS writing_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            content TEXT NOT NULL,
            word_count INTEGER DEFAULT 0,
            char_count INTEGER DEFAULT 0,
            duration_seconds INTEGER DEFAULT 0,
            grace_period INTEGER DEFAULT 5,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
    """)
    conn.commit()

# ── Auth ──────────────────────────────────────────────────
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if "user_id" in session:
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm  = request.form.get("confirm", "")
        if not username or not email or not password:
            error = "All fields are required."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        elif password != confirm:
            error = "Passwords do not match."
        else:
            conn = db()
            existing = conn.execute("SELECT id FROM users WHERE email=? OR username=?", (email, username)).fetchone()
            if existing:
                error = "Email or username already taken."
            else:
                pw_hash = generate_password_hash(password)
                conn.execute("INSERT INTO users (username, email, password_hash) VALUES (?,?,?)", (username, email, pw_hash))
                conn.commit()
                user = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
                user_id = user[0]
                conn.execute("INSERT INTO boards (user_id, name) VALUES (?,?)", (user_id, "My First Board"))
                conn.commit()
                board = conn.execute("SELECT id FROM boards WHERE user_id=? ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
                bid = board[0]
                cols = [("To Do","#6366f1",0),("In Progress","#f59e0b",1),("Done","#10b981",2)]
                for n, col, p in cols:
                    conn.execute("INSERT INTO columns (board_id,name,color,position) VALUES (?,?,?,?)", (bid,n,col,p))
                conn.commit()
                session["user_id"]  = user_id
                session["username"] = username
                return redirect(url_for("index"))
    return render_template("signup.html", error=error)

@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        conn = db()
        user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if not user or not check_password_hash(user[3], password):
            error = "Invalid email or password."
        else:
            session["user_id"]  = user[0]
            session["username"] = user[1]
            return redirect(url_for("index"))
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ── Pages ─────────────────────────────────────────────────
@app.route("/")
@login_required
def index():
    conn = db()
    boards = conn.execute("SELECT * FROM boards WHERE user_id=? ORDER BY id", (session["user_id"],)).fetchall()
    return render_template("index.html", boards=boards, username=session.get("username"))

@app.route("/board/<int:board_id>")
@login_required
def board(board_id):
    conn = db()
    board = conn.execute("SELECT * FROM boards WHERE id=? AND user_id=?", (board_id, session["user_id"])).fetchone()
    if not board:
        return redirect(url_for("index"))
    cols = conn.execute("SELECT * FROM columns WHERE board_id=? ORDER BY position", (board_id,)).fetchall()
    data = []
    for col in cols:
        cards = conn.execute("SELECT * FROM cards WHERE column_id=? ORDER BY position", (col[0],)).fetchall()
        card_list = []
        for card in cards:
            card_dict = {
                "id": card[0], "column_id": card[1], "title": card[2],
                "description": card[3], "priority": card[4], "due_date": card[5],
                "tags": json.loads(card[6]), "position": card[7], "created_at": card[8]
            }
            card_list.append(card_dict)
        col_dict = {"id": col[0], "board_id": col[1], "name": col[2], "color": col[3], "position": col[4]}
        data.append({"col": col_dict, "cards": card_list})
    today = datetime.now().strftime("%Y-%m-%d")
    return render_template("board.html", board=board, data=data, today=today, username=session.get("username"))

# ── Board API ─────────────────────────────────────────────
@app.route("/api/boards", methods=["POST"])
@login_required
def create_board():
    name = request.json.get("name", "New Board")
    conn = db()
    conn.execute("INSERT INTO boards (user_id, name) VALUES (?,?)", (session["user_id"], name))
    conn.commit()
    board = conn.execute("SELECT id FROM boards WHERE user_id=? ORDER BY id DESC LIMIT 1", (session["user_id"],)).fetchone()
    bid = board[0]
    defaults = [("Backlog","#64748b",0),("To Do","#6366f1",1),("In Progress","#f59e0b",2),("Done","#10b981",3)]
    for n, col, p in defaults:
        conn.execute("INSERT INTO columns (board_id,name,color,position) VALUES (?,?,?,?)", (bid,n,col,p))
    conn.commit()
    return jsonify({"id": bid, "name": name})

@app.route("/api/boards/<int:board_id>", methods=["DELETE"])
@login_required
def delete_board(board_id):
    conn = db()
    board = conn.execute("SELECT id FROM boards WHERE id=? AND user_id=?", (board_id, session["user_id"])).fetchone()
    if not board:
        return jsonify({"error": "Not found"}), 404
    conn.execute("DELETE FROM cards WHERE column_id IN (SELECT id FROM columns WHERE board_id=?)", (board_id,))
    conn.execute("DELETE FROM columns WHERE board_id=?", (board_id,))
    conn.execute("DELETE FROM boards WHERE id=?", (board_id,))
    conn.commit()
    return jsonify({"ok": True})

# ── Column API ────────────────────────────────────────────
@app.route("/api/columns", methods=["POST"])
@login_required
def create_column():
    d = request.json
    conn = db()
    pos = conn.execute("SELECT COALESCE(MAX(position)+1,0) FROM columns WHERE board_id=?", (d["board_id"],)).fetchone()[0]
    conn.execute("INSERT INTO columns (board_id,name,color,position) VALUES (?,?,?,?)", (d["board_id"], d.get("name","New Column"), d.get("color","#6366f1"), pos))
    conn.commit()
    col = conn.execute("SELECT id FROM columns WHERE board_id=? ORDER BY id DESC LIMIT 1", (d["board_id"],)).fetchone()
    return jsonify({"id": col[0], "name": d.get("name"), "color": d.get("color","#6366f1"), "position": pos})

@app.route("/api/columns/<int:col_id>", methods=["PATCH","DELETE"])
@login_required
def column_ops(col_id):
    conn = db()
    if request.method == "DELETE":
        conn.execute("DELETE FROM cards WHERE column_id=?", (col_id,))
        conn.execute("DELETE FROM columns WHERE id=?", (col_id,))
        conn.commit()
        return jsonify({"ok": True})
    d = request.json
    if "name"  in d: conn.execute("UPDATE columns SET name=?  WHERE id=?", (d["name"],  col_id))
    if "color" in d: conn.execute("UPDATE columns SET color=? WHERE id=?", (d["color"], col_id))
    conn.commit()
    return jsonify({"ok": True})

# ── Card API ──────────────────────────────────────────────
@app.route("/api/cards", methods=["POST"])
@login_required
def create_card():
    d = request.json
    conn = db()
    pos = conn.execute("SELECT COALESCE(MAX(position)+1,0) FROM cards WHERE column_id=?", (d["column_id"],)).fetchone()[0]
    tags = json.dumps(d.get("tags", []))
    conn.execute("INSERT INTO cards (column_id,title,description,priority,due_date,tags,position) VALUES (?,?,?,?,?,?,?)",
                 (d["column_id"], d.get("title","New Task"), d.get("description",""), d.get("priority","medium"), d.get("due_date",""), tags, pos))
    conn.commit()
    card = conn.execute("SELECT id FROM cards WHERE column_id=? ORDER BY id DESC LIMIT 1", (d["column_id"],)).fetchone()
    return jsonify({"id": card[0], "position": pos})

@app.route("/api/cards/<int:card_id>", methods=["PATCH","DELETE"])
@login_required
def card_ops(card_id):
    conn = db()
    if request.method == "DELETE":
        conn.execute("DELETE FROM cards WHERE id=?", (card_id,))
        conn.commit()
        return jsonify({"ok": True})
    d = request.json
    for f in ["title","description","priority","due_date","column_id","position"]:
        if f in d: conn.execute(f"UPDATE cards SET {f}=? WHERE id=?", (d[f], card_id))
    if "tags" in d: conn.execute("UPDATE cards SET tags=? WHERE id=?", (json.dumps(d["tags"]), card_id))
    conn.commit()
    return jsonify({"ok": True})

@app.route("/api/cards/move", methods=["POST"])
@login_required
def move_card():
    d = request.json
    card_id, new_col, new_pos = d["card_id"], d["column_id"], d["position"]
    conn = db()
    old = conn.execute("SELECT column_id FROM cards WHERE id=?", (card_id,)).fetchone()
    conn.execute("UPDATE cards SET position=position+1 WHERE column_id=? AND position>=?", (new_col, new_pos))
    conn.execute("UPDATE cards SET column_id=?, position=? WHERE id=?", (new_col, new_pos, card_id))
    conn.execute("""UPDATE cards SET position=(
                    SELECT COUNT(*) FROM cards c2
                    WHERE c2.column_id=cards.column_id AND c2.position<cards.position
                 ) WHERE column_id=?""", (old[0],))
    conn.commit()
    return jsonify({"ok": True})

# ── Write or Die ──────────────────────────────────────────
@app.route("/write")
@login_required
def write():
    return render_template("write.html", username=session.get("username"))

@app.route("/sessions")
@login_required
def sessions_page():
    conn = db()
    rows = conn.execute("SELECT * FROM writing_sessions WHERE user_id=? ORDER BY created_at DESC", (session["user_id"],)).fetchall()
    sessions_list = []
    for r in rows:
        sessions_list.append({
            "id": r[0], "user_id": r[1], "content": r[2],
            "word_count": r[3], "char_count": r[4],
            "duration_seconds": r[5], "grace_period": r[6], "created_at": r[7]
        })
    return render_template("sessions.html", sessions=sessions_list, username=session.get("username"))

@app.route("/sessions/<int:session_id>")
@login_required
def session_detail(session_id):
    conn = db()
    r = conn.execute("SELECT * FROM writing_sessions WHERE id=? AND user_id=?", (session_id, session["user_id"])).fetchone()
    if not r:
        return redirect(url_for("sessions_page"))
    s = {
        "id": r[0], "user_id": r[1], "content": r[2],
        "word_count": r[3], "char_count": r[4],
        "duration_seconds": r[5], "grace_period": r[6], "created_at": r[7]
    }
    return render_template("session_detail.html", session=s, username=session.get("username"))

@app.route("/api/sessions", methods=["POST"])
@login_required
def save_session():
    d = request.json
    content = d.get("content", "").strip()
    if not content:
        return jsonify({"error": "No content"}), 400
    conn = db()
    conn.execute("""INSERT INTO writing_sessions (user_id, content, word_count, char_count, duration_seconds, grace_period)
                    VALUES (?,?,?,?,?,?)""",
                 (session["user_id"], content, d.get("word_count",0), d.get("char_count",0), d.get("duration_seconds",0), d.get("grace_period",5)))
    conn.commit()
    s = conn.execute("SELECT id FROM writing_sessions WHERE user_id=? ORDER BY id DESC LIMIT 1", (session["user_id"],)).fetchone()
    return jsonify({"id": s[0], "ok": True})

@app.route("/api/sessions/<int:session_id>", methods=["DELETE"])
@login_required
def delete_session(session_id):
    conn = db()
    conn.execute("DELETE FROM writing_sessions WHERE id=? AND user_id=?", (session_id, session["user_id"]))
    conn.commit()
    return jsonify({"ok": True})

init_db()

if __name__ == "__main__":
    app.run(debug=True, port=5051)
