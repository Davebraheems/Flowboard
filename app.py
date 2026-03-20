from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import os, json, requests
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "flowboard-super-secret-2025")

TURSO_URL   = os.environ.get("TURSO_URL",   "libsql://flowboard-davebraheems.aws-us-east-1.turso.io")
TURSO_TOKEN = os.environ.get("TURSO_TOKEN", "")

# Convert libsql:// to https:// for HTTP API
def get_http_url():
    return TURSO_URL.replace("libsql://", "https://")

def turso_execute(sql, params=None):
    """Execute a single statement and return rows."""
    url = f"{get_http_url()}/v2/pipeline"
    headers = {
        "Authorization": f"Bearer {TURSO_TOKEN}",
        "Content-Type": "application/json"
    }
    stmt = {"type": "execute", "stmt": {"sql": sql}}
    if params:
        stmt["stmt"]["args"] = [{"type": _turso_type(p), "value": str(p) if p is not None else None} for p in params]

    payload = {"requests": [stmt, {"type": "close"}]}
    resp = requests.post(url, headers=headers, json=payload)
    resp.raise_for_status()
    data = resp.json()
    result = data["results"][0]
    if result["type"] == "error":
        raise Exception(result["error"]["message"])
    rs = result["response"]["result"]
    cols = [c["name"] for c in rs["cols"]]
    rows = []
    for row in rs["rows"]:
        d = {}
        for i, col in enumerate(cols):
            cell = row[i]
            d[col] = cell["value"] if cell["type"] != "null" else None
        rows.append(d)
    return rows

def turso_run(sql, params=None):
    """Execute a statement without caring about return value."""
    turso_execute(sql, params)

def turso_batch(statements):
    """Run multiple statements in one request."""
    url = f"{get_http_url()}/v2/pipeline"
    headers = {
        "Authorization": f"Bearer {TURSO_TOKEN}",
        "Content-Type": "application/json"
    }
    reqs = []
    for sql, params in statements:
        stmt = {"type": "execute", "stmt": {"sql": sql}}
        if params:
            stmt["stmt"]["args"] = [{"type": _turso_type(p), "value": str(p) if p is not None else None} for p in params]
        reqs.append(stmt)
    reqs.append({"type": "close"})
    payload = {"requests": reqs}
    resp = requests.post(url, headers=headers, json=payload)
    resp.raise_for_status()
    return resp.json()

def _turso_type(v):
    if v is None: return "null"
    if isinstance(v, int): return "integer"
    if isinstance(v, float): return "float"
    return "text"

def turso_one(sql, params=None):
    rows = turso_execute(sql, params)
    return rows[0] if rows else None

def turso_lastid(table, where_col, where_val):
    row = turso_one(f"SELECT id FROM {table} WHERE {where_col}=? ORDER BY id DESC LIMIT 1", (where_val,))
    return row["id"] if row else None

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def init_db():
    statements = [
        ("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now')))", None),
        ("CREATE TABLE IF NOT EXISTS boards (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, name TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now')))", None),
        ("CREATE TABLE IF NOT EXISTS columns (id INTEGER PRIMARY KEY AUTOINCREMENT, board_id INTEGER NOT NULL, name TEXT NOT NULL, color TEXT DEFAULT '#6366f1', position INTEGER DEFAULT 0)", None),
        ("CREATE TABLE IF NOT EXISTS cards (id INTEGER PRIMARY KEY AUTOINCREMENT, column_id INTEGER NOT NULL, title TEXT NOT NULL, description TEXT DEFAULT '', priority TEXT DEFAULT 'medium', due_date TEXT DEFAULT '', tags TEXT DEFAULT '[]', position INTEGER DEFAULT 0, created_at TEXT DEFAULT (datetime('now')))", None),
        ("CREATE TABLE IF NOT EXISTS writing_sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, content TEXT NOT NULL, word_count INTEGER DEFAULT 0, char_count INTEGER DEFAULT 0, duration_seconds INTEGER DEFAULT 0, grace_period INTEGER DEFAULT 5, created_at TEXT DEFAULT (datetime('now')))", None),
    ]
    turso_batch(statements)

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
            existing = turso_one("SELECT id FROM users WHERE email=? OR username=?", (email, username))
            if existing:
                error = "Email or username already taken."
            else:
                pw_hash = generate_password_hash(password)
                turso_run("INSERT INTO users (username, email, password_hash) VALUES (?,?,?)", (username, email, pw_hash))
                user = turso_one("SELECT id FROM users WHERE email=?", (email,))
                user_id = user["id"]
                turso_run("INSERT INTO boards (user_id, name) VALUES (?,?)", (user_id, "My First Board"))
                bid = turso_lastid("boards", "user_id", user_id)
                for n, col, p in [("To Do","#6366f1",0),("In Progress","#f59e0b",1),("Done","#10b981",2)]:
                    turso_run("INSERT INTO columns (board_id,name,color,position) VALUES (?,?,?,?)", (bid,n,col,p))
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
        user = turso_one("SELECT * FROM users WHERE email=?", (email,))
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
    boards = turso_execute("SELECT * FROM boards WHERE user_id=? ORDER BY id", (session["user_id"],))
    return render_template("index.html", boards=boards, username=session.get("username"))

@app.route("/board/<int:board_id>")
@login_required
def board(board_id):
    board = turso_one("SELECT * FROM boards WHERE id=? AND user_id=?", (board_id, session["user_id"]))
    if not board:
        return redirect(url_for("index"))
    cols = turso_execute("SELECT * FROM columns WHERE board_id=? ORDER BY position", (board_id,))
    data = []
    for col in cols:
        cards = turso_execute("SELECT * FROM cards WHERE column_id=? ORDER BY position", (col["id"],))
        for card in cards:
            card["tags"] = json.loads(card["tags"] or "[]")
        data.append({"col": col, "cards": cards})
    today = datetime.now().strftime("%Y-%m-%d")
    return render_template("board.html", board=board, data=data, today=today, username=session.get("username"))

# ── Board API ─────────────────────────────────────────────
@app.route("/api/boards", methods=["POST"])
@login_required
def create_board():
    name = request.json.get("name", "New Board")
    turso_run("INSERT INTO boards (user_id, name) VALUES (?,?)", (session["user_id"], name))
    bid = turso_lastid("boards", "user_id", session["user_id"])
    for n, col, p in [("Backlog","#64748b",0),("To Do","#6366f1",1),("In Progress","#f59e0b",2),("Done","#10b981",3)]:
        turso_run("INSERT INTO columns (board_id,name,color,position) VALUES (?,?,?,?)", (bid,n,col,p))
    return jsonify({"id": bid, "name": name})

@app.route("/api/boards/<int:board_id>", methods=["DELETE"])
@login_required
def delete_board(board_id):
    board = turso_one("SELECT id FROM boards WHERE id=? AND user_id=?", (board_id, session["user_id"]))
    if not board:
        return jsonify({"error": "Not found"}), 404
    turso_run("DELETE FROM cards WHERE column_id IN (SELECT id FROM columns WHERE board_id=?)", (board_id,))
    turso_run("DELETE FROM columns WHERE board_id=?", (board_id,))
    turso_run("DELETE FROM boards WHERE id=?", (board_id,))
    return jsonify({"ok": True})

# ── Column API ────────────────────────────────────────────
@app.route("/api/columns", methods=["POST"])
@login_required
def create_column():
    d = request.json
    row = turso_one("SELECT COALESCE(MAX(position)+1,0) as pos FROM columns WHERE board_id=?", (d["board_id"],))
    pos = row["pos"] if row else 0
    turso_run("INSERT INTO columns (board_id,name,color,position) VALUES (?,?,?,?)", (d["board_id"], d.get("name","New Column"), d.get("color","#6366f1"), pos))
    col = turso_lastid("columns", "board_id", d["board_id"])
    return jsonify({"id": col, "name": d.get("name"), "color": d.get("color","#6366f1"), "position": pos})

@app.route("/api/columns/<int:col_id>", methods=["PATCH","DELETE"])
@login_required
def column_ops(col_id):
    if request.method == "DELETE":
        turso_run("DELETE FROM cards WHERE column_id=?", (col_id,))
        turso_run("DELETE FROM columns WHERE id=?", (col_id,))
        return jsonify({"ok": True})
    d = request.json
    if "name"  in d: turso_run("UPDATE columns SET name=?  WHERE id=?", (d["name"],  col_id))
    if "color" in d: turso_run("UPDATE columns SET color=? WHERE id=?", (d["color"], col_id))
    return jsonify({"ok": True})

# ── Card API ──────────────────────────────────────────────
@app.route("/api/cards", methods=["POST"])
@login_required
def create_card():
    d = request.json
    row = turso_one("SELECT COALESCE(MAX(position)+1,0) as pos FROM cards WHERE column_id=?", (d["column_id"],))
    pos = row["pos"] if row else 0
    tags = json.dumps(d.get("tags", []))
    turso_run("INSERT INTO cards (column_id,title,description,priority,due_date,tags,position) VALUES (?,?,?,?,?,?,?)",
              (d["column_id"], d.get("title","New Task"), d.get("description",""), d.get("priority","medium"), d.get("due_date",""), tags, pos))
    card = turso_lastid("cards", "column_id", d["column_id"])
    return jsonify({"id": card, "position": pos})

@app.route("/api/cards/<int:card_id>", methods=["PATCH","DELETE"])
@login_required
def card_ops(card_id):
    if request.method == "DELETE":
        turso_run("DELETE FROM cards WHERE id=?", (card_id,))
        return jsonify({"ok": True})
    d = request.json
    for f in ["title","description","priority","due_date","column_id","position"]:
        if f in d: turso_run(f"UPDATE cards SET {f}=? WHERE id=?", (d[f], card_id))
    if "tags" in d: turso_run("UPDATE cards SET tags=? WHERE id=?", (json.dumps(d["tags"]), card_id))
    return jsonify({"ok": True})

@app.route("/api/cards/move", methods=["POST"])
@login_required
def move_card():
    d = request.json
    card_id, new_col, new_pos = d["card_id"], d["column_id"], d["position"]
    old = turso_one("SELECT column_id FROM cards WHERE id=?", (card_id,))
    turso_run("UPDATE cards SET position=position+1 WHERE column_id=? AND position>=?", (new_col, new_pos))
    turso_run("UPDATE cards SET column_id=?, position=? WHERE id=?", (new_col, new_pos, card_id))
    turso_run("""UPDATE cards SET position=(
                    SELECT COUNT(*) FROM cards c2
                    WHERE c2.column_id=cards.column_id AND c2.position<cards.position
                 ) WHERE column_id=?""", (old["column_id"],))
    return jsonify({"ok": True})

# ── Write or Die ──────────────────────────────────────────
@app.route("/write")
@login_required
def write():
    return render_template("write.html", username=session.get("username"))

@app.route("/sessions")
@login_required
def sessions_page():
    rows = turso_execute("SELECT * FROM writing_sessions WHERE user_id=? ORDER BY created_at DESC", (session["user_id"],))
    for r in rows:
        r["word_count"]       = int(r.get("word_count") or 0)
        r["char_count"]       = int(r.get("char_count") or 0)
        r["duration_seconds"] = int(r.get("duration_seconds") or 0)
        r["grace_period"]     = int(r.get("grace_period") or 5)
    return render_template("sessions.html", sessions=rows, username=session.get("username"))

@app.route("/sessions/<int:session_id>")
@login_required
def session_detail(session_id):
    s = turso_one("SELECT * FROM writing_sessions WHERE id=? AND user_id=?", (session_id, session["user_id"]))
    if not s:
        return redirect(url_for("sessions_page"))
    s["word_count"]       = int(s.get("word_count") or 0)
    s["char_count"]       = int(s.get("char_count") or 0)
    s["duration_seconds"] = int(s.get("duration_seconds") or 0)
    s["grace_period"]     = int(s.get("grace_period") or 5)
    return render_template("session_detail.html", session=s, username=session.get("username"))

@app.route("/api/sessions", methods=["POST"])
@login_required
def save_session():
    d = request.json
    content = d.get("content", "").strip()
    if not content:
        return jsonify({"error": "No content"}), 400
    turso_run("INSERT INTO writing_sessions (user_id,content,word_count,char_count,duration_seconds,grace_period) VALUES (?,?,?,?,?,?)",
              (session["user_id"], content, d.get("word_count",0), d.get("char_count",0), d.get("duration_seconds",0), d.get("grace_period",5)))
    s = turso_lastid("writing_sessions", "user_id", session["user_id"])
    return jsonify({"id": s, "ok": True})

@app.route("/api/sessions/<int:session_id>", methods=["DELETE"])
@login_required
def delete_session(session_id):
    turso_run("DELETE FROM writing_sessions WHERE id=? AND user_id=?", (session_id, session["user_id"]))
    return jsonify({"ok": True})

init_db()

if __name__ == "__main__":
    app.run(debug=True, port=5051)
