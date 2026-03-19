from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import os, json
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import psycopg2
import psycopg2.extras

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "flowboard-secret-key-change-in-production")

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:[081190se154Qu#]@db.lcickgqwboffvhlugvmu.supabase.co:5432/postgres")

def db():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
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
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS boards (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS columns (
            id SERIAL PRIMARY KEY,
            board_id INTEGER NOT NULL REFERENCES boards(id),
            name TEXT NOT NULL,
            color TEXT DEFAULT '#6366f1',
            position INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS cards (
            id SERIAL PRIMARY KEY,
            column_id INTEGER NOT NULL REFERENCES columns(id),
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            priority TEXT DEFAULT 'medium',
            due_date TEXT DEFAULT '',
            tags TEXT DEFAULT '[]',
            position INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS writing_sessions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            content TEXT NOT NULL,
            word_count INTEGER DEFAULT 0,
            char_count INTEGER DEFAULT 0,
            duration_seconds INTEGER DEFAULT 0,
            grace_period INTEGER DEFAULT 5,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    conn.commit()
    conn.close()

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
            c = conn.cursor()
            c.execute("SELECT id FROM users WHERE email=%s OR username=%s", (email, username))
            existing = c.fetchone()
            if existing:
                error = "Email or username already taken."
                conn.close()
            else:
                pw_hash = generate_password_hash(password)
                c.execute("INSERT INTO users (username, email, password_hash) VALUES (%s,%s,%s) RETURNING id", (username, email, pw_hash))
                user_id = c.fetchone()["id"]
                c.execute("INSERT INTO boards (user_id, name) VALUES (%s,%s) RETURNING id", (user_id, "My First Board"))
                bid = c.fetchone()["id"]
                cols = [("To Do","#6366f1",0),("In Progress","#f59e0b",1),("Done","#10b981",2)]
                for n, col, p in cols:
                    c.execute("INSERT INTO columns (board_id,name,color,position) VALUES (%s,%s,%s,%s)", (bid,n,col,p))
                conn.commit()
                conn.close()
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
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE email=%s", (email,))
        user = c.fetchone()
        conn.close()
        if not user or not check_password_hash(user["password_hash"], password):
            error = "Invalid email or password."
        else:
            session["user_id"]  = user["id"]
            session["username"] = user["username"]
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
    c = conn.cursor()
    c.execute("SELECT * FROM boards WHERE user_id=%s ORDER BY id", (session["user_id"],))
    boards = c.fetchall()
    conn.close()
    return render_template("index.html", boards=boards, username=session.get("username"))

@app.route("/board/<int:board_id>")
@login_required
def board(board_id):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT * FROM boards WHERE id=%s AND user_id=%s", (board_id, session["user_id"]))
    board = c.fetchone()
    if not board:
        conn.close()
        return redirect(url_for("index"))
    c.execute("SELECT * FROM columns WHERE board_id=%s ORDER BY position", (board_id,))
    cols = c.fetchall()
    data = []
    for col in cols:
        c.execute("SELECT * FROM cards WHERE column_id=%s ORDER BY position", (col["id"],))
        cards = c.fetchall()
        data.append({"col": col, "cards": [dict(card) | {"tags": json.loads(card["tags"])} for card in cards]})
    conn.close()
    today = datetime.now().strftime("%Y-%m-%d")
    return render_template("board.html", board=board, data=data, today=today, username=session.get("username"))

# ── Board API ─────────────────────────────────────────────
@app.route("/api/boards", methods=["POST"])
@login_required
def create_board():
    name = request.json.get("name", "New Board")
    conn = db()
    c = conn.cursor()
    c.execute("INSERT INTO boards (user_id, name) VALUES (%s,%s) RETURNING id", (session["user_id"], name))
    bid = c.fetchone()["id"]
    defaults = [("Backlog","#64748b",0),("To Do","#6366f1",1),("In Progress","#f59e0b",2),("Done","#10b981",3)]
    for n, col, p in defaults:
        c.execute("INSERT INTO columns (board_id,name,color,position) VALUES (%s,%s,%s,%s)", (bid,n,col,p))
    conn.commit()
    conn.close()
    return jsonify({"id": bid, "name": name})

@app.route("/api/boards/<int:board_id>", methods=["DELETE"])
@login_required
def delete_board(board_id):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT id FROM boards WHERE id=%s AND user_id=%s", (board_id, session["user_id"]))
    if not c.fetchone():
        conn.close()
        return jsonify({"error": "Not found"}), 404
    c.execute("DELETE FROM cards WHERE column_id IN (SELECT id FROM columns WHERE board_id=%s)", (board_id,))
    c.execute("DELETE FROM columns WHERE board_id=%s", (board_id,))
    c.execute("DELETE FROM boards WHERE id=%s", (board_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

# ── Column API ────────────────────────────────────────────
@app.route("/api/columns", methods=["POST"])
@login_required
def create_column():
    d = request.json
    conn = db()
    c = conn.cursor()
    c.execute("SELECT COALESCE(MAX(position)+1,0) FROM columns WHERE board_id=%s", (d["board_id"],))
    pos = c.fetchone()["coalesce"]
    c.execute("INSERT INTO columns (board_id,name,color,position) VALUES (%s,%s,%s,%s) RETURNING id",
              (d["board_id"], d.get("name","New Column"), d.get("color","#6366f1"), pos))
    col_id = c.fetchone()["id"]
    conn.commit()
    conn.close()
    return jsonify({"id": col_id, "name": d.get("name"), "color": d.get("color","#6366f1"), "position": pos})

@app.route("/api/columns/<int:col_id>", methods=["PATCH","DELETE"])
@login_required
def column_ops(col_id):
    conn = db()
    c = conn.cursor()
    if request.method == "DELETE":
        c.execute("DELETE FROM cards WHERE column_id=%s", (col_id,))
        c.execute("DELETE FROM columns WHERE id=%s", (col_id,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})
    d = request.json
    if "name"  in d: c.execute("UPDATE columns SET name=%s  WHERE id=%s", (d["name"],  col_id))
    if "color" in d: c.execute("UPDATE columns SET color=%s WHERE id=%s", (d["color"], col_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

# ── Card API ──────────────────────────────────────────────
@app.route("/api/cards", methods=["POST"])
@login_required
def create_card():
    d = request.json
    conn = db()
    c = conn.cursor()
    c.execute("SELECT COALESCE(MAX(position)+1,0) FROM cards WHERE column_id=%s", (d["column_id"],))
    pos = c.fetchone()["coalesce"]
    tags = json.dumps(d.get("tags", []))
    c.execute("INSERT INTO cards (column_id,title,description,priority,due_date,tags,position) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
              (d["column_id"], d.get("title","New Task"), d.get("description",""), d.get("priority","medium"), d.get("due_date",""), tags, pos))
    card_id = c.fetchone()["id"]
    conn.commit()
    conn.close()
    return jsonify({"id": card_id, "position": pos})

@app.route("/api/cards/<int:card_id>", methods=["PATCH","DELETE"])
@login_required
def card_ops(card_id):
    conn = db()
    c = conn.cursor()
    if request.method == "DELETE":
        c.execute("DELETE FROM cards WHERE id=%s", (card_id,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})
    d = request.json
    for f in ["title","description","priority","due_date","column_id","position"]:
        if f in d: c.execute(f"UPDATE cards SET {f}=%s WHERE id=%s", (d[f], card_id))
    if "tags" in d: c.execute("UPDATE cards SET tags=%s WHERE id=%s", (json.dumps(d["tags"]), card_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/cards/move", methods=["POST"])
@login_required
def move_card():
    d = request.json
    card_id, new_col, new_pos = d["card_id"], d["column_id"], d["position"]
    conn = db()
    c = conn.cursor()
    c.execute("SELECT column_id, position FROM cards WHERE id=%s", (card_id,))
    old = c.fetchone()
    c.execute("UPDATE cards SET position=position+1 WHERE column_id=%s AND position>=%s", (new_col, new_pos))
    c.execute("UPDATE cards SET column_id=%s, position=%s WHERE id=%s", (new_col, new_pos, card_id))
    c.execute("""UPDATE cards SET position=(
                    SELECT COUNT(*) FROM cards c2
                    WHERE c2.column_id=cards.column_id AND c2.position<cards.position
                 ) WHERE column_id=%s""", (old["column_id"],))
    conn.commit()
    conn.close()
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
    c = conn.cursor()
    c.execute("SELECT * FROM writing_sessions WHERE user_id=%s ORDER BY created_at DESC", (session["user_id"],))
    rows = c.fetchall()
    conn.close()
    return render_template("sessions.html", sessions=rows, username=session.get("username"))

@app.route("/sessions/<int:session_id>")
@login_required
def session_detail(session_id):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT * FROM writing_sessions WHERE id=%s AND user_id=%s", (session_id, session["user_id"]))
    s = c.fetchone()
    conn.close()
    if not s:
        return redirect(url_for("sessions_page"))
    return render_template("session_detail.html", session=s, username=session.get("username"))

@app.route("/api/sessions", methods=["POST"])
@login_required
def save_session():
    d = request.json
    content = d.get("content", "").strip()
    if not content:
        return jsonify({"error": "No content"}), 400
    conn = db()
    c = conn.cursor()
    c.execute("""INSERT INTO writing_sessions (user_id, content, word_count, char_count, duration_seconds, grace_period)
                 VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
              (session["user_id"], content, d.get("word_count",0), d.get("char_count",0), d.get("duration_seconds",0), d.get("grace_period",5)))
    sid = c.fetchone()["id"]
    conn.commit()
    conn.close()
    return jsonify({"id": sid, "ok": True})

@app.route("/api/sessions/<int:session_id>", methods=["DELETE"])
@login_required
def delete_session(session_id):
    conn = db()
    c = conn.cursor()
    c.execute("DELETE FROM writing_sessions WHERE id=%s AND user_id=%s", (session_id, session["user_id"]))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

init_db()

if __name__ == "__main__":
    app.run(debug=True, port=5051)
