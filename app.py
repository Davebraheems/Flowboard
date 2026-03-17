from flask import Flask, render_template, request, jsonify
import sqlite3, os, json
from datetime import datetime

app = Flask(__name__)
DB = "/tmp/kanban.db" if os.environ.get("VERCEL") else os.path.join(os.path.dirname(__file__), "kanban.db")

def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS boards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
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
    """)
    # Seed demo board
    c.execute("SELECT COUNT(*) FROM boards")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO boards (name) VALUES ('My Project')")
        bid = c.lastrowid
        cols = [
            (bid, 'Backlog',     '#64748b', 0),
            (bid, 'To Do',       '#6366f1', 1),
            (bid, 'In Progress', '#f59e0b', 2),
            (bid, 'Review',      '#8b5cf6', 3),
            (bid, 'Done',        '#10b981', 4),
        ]
        c.executemany("INSERT INTO columns (board_id, name, color, position) VALUES (?,?,?,?)", cols)
        col_ids = [c.lastrowid - 4 + i for i in range(5)]
        cards = [
            (col_ids[0], 'Research competitor apps',      'Look at 5 main competitors and note key features', 'low',    '',           '["research"]',  0),
            (col_ids[0], 'Set up CI/CD pipeline',         'GitHub Actions for automated testing & deploy',    'medium', '2025-04-20', '["devops"]',    1),
            (col_ids[1], 'Design system tokens',          'Define colors, spacing, and typography tokens',    'high',   '2025-04-10', '["design"]',    0),
            (col_ids[1], 'User authentication flow',      'Login, signup, password reset pages',              'high',   '2025-04-08', '["backend","auth"]', 1),
            (col_ids[1], 'Write API documentation',       'Document all REST endpoints with examples',        'medium', '2025-04-15', '["docs"]',      2),
            (col_ids[2], 'Kanban board drag-and-drop',    'Implement card dragging between columns',          'high',   '2025-04-05', '["frontend"]',  0),
            (col_ids[2], 'Database schema design',        'ERD for users, projects, tasks, and comments',     'medium', '2025-04-07', '["backend"]',   1),
            (col_ids[3], 'Homepage redesign',             'New hero section and feature highlights',          'medium', '2025-04-03', '["design","frontend"]', 0),
            (col_ids[4], 'Project scaffolding',           'Flask app, folder structure, requirements.txt',    'low',    '',           '["backend"]',   0),
            (col_ids[4], 'Wireframes v1',                 'Low-fidelity wireframes for 5 core screens',       'low',    '',           '["design"]',    1),
        ]
        c.executemany("INSERT INTO cards (column_id, title, description, priority, due_date, tags, position) VALUES (?,?,?,?,?,?,?)", cards)
    conn.commit()
    conn.close()

@app.route("/")
def index():
    conn = db()
    boards = conn.execute("SELECT * FROM boards ORDER BY id").fetchall()
    conn.close()
    return render_template("index.html", boards=boards)

@app.route("/board/<int:board_id>")
def board(board_id):
    conn = db()
    board = conn.execute("SELECT * FROM boards WHERE id=?", (board_id,)).fetchone()
    cols = conn.execute("SELECT * FROM columns WHERE board_id=? ORDER BY position", (board_id,)).fetchall()
    data = []
    for col in cols:
        cards = conn.execute("SELECT * FROM cards WHERE column_id=? ORDER BY position", (col['id'],)).fetchall()
        data.append({'col': col, 'cards': [dict(c) | {'tags': json.loads(c['tags'])} for c in cards]})
    conn.close()
    today = datetime.now().strftime('%Y-%m-%d')
    return render_template("board.html", board=board, data=data, today=today)

# --- API ---

@app.route("/api/boards", methods=["POST"])
def create_board():
    name = request.json.get("name", "New Board")
    conn = db()
    c = conn.cursor()
    c.execute("INSERT INTO boards (name) VALUES (?)", (name,))
    bid = c.lastrowid
    defaults = [('Backlog','#64748b',0),('To Do','#6366f1',1),('In Progress','#f59e0b',2),('Done','#10b981',3)]
    c.executemany("INSERT INTO columns (board_id,name,color,position) VALUES (?,?,?,?)", [(bid,n,col,p) for n,col,p in defaults])
    conn.commit()
    conn.close()
    return jsonify({"id": bid, "name": name})

@app.route("/api/boards/<int:board_id>", methods=["DELETE"])
def delete_board(board_id):
    conn = db()
    conn.execute("DELETE FROM cards WHERE column_id IN (SELECT id FROM columns WHERE board_id=?)", (board_id,))
    conn.execute("DELETE FROM columns WHERE board_id=?", (board_id,))
    conn.execute("DELETE FROM boards WHERE id=?", (board_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/columns", methods=["POST"])
def create_column():
    d = request.json
    conn = db()
    c = conn.cursor()
    pos = conn.execute("SELECT COALESCE(MAX(position)+1,0) FROM columns WHERE board_id=?", (d['board_id'],)).fetchone()[0]
    c.execute("INSERT INTO columns (board_id,name,color,position) VALUES (?,?,?,?)", (d['board_id'], d.get('name','New Column'), d.get('color','#6366f1'), pos))
    col_id = c.lastrowid
    conn.commit()
    conn.close()
    return jsonify({"id": col_id, "name": d.get('name'), "color": d.get('color','#6366f1'), "position": pos})

@app.route("/api/columns/<int:col_id>", methods=["PATCH","DELETE"])
def column_ops(col_id):
    conn = db()
    if request.method == "DELETE":
        conn.execute("DELETE FROM cards WHERE column_id=?", (col_id,))
        conn.execute("DELETE FROM columns WHERE id=?", (col_id,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})
    d = request.json
    if 'name' in d: conn.execute("UPDATE columns SET name=? WHERE id=?", (d['name'], col_id))
    if 'color' in d: conn.execute("UPDATE columns SET color=? WHERE id=?", (d['color'], col_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/cards", methods=["POST"])
def create_card():
    d = request.json
    conn = db()
    c = conn.cursor()
    pos = conn.execute("SELECT COALESCE(MAX(position)+1,0) FROM cards WHERE column_id=?", (d['column_id'],)).fetchone()[0]
    tags = json.dumps(d.get('tags', []))
    c.execute("INSERT INTO cards (column_id,title,description,priority,due_date,tags,position) VALUES (?,?,?,?,?,?,?)",
              (d['column_id'], d.get('title','New Task'), d.get('description',''), d.get('priority','medium'), d.get('due_date',''), tags, pos))
    card_id = c.lastrowid
    conn.commit()
    conn.close()
    return jsonify({"id": card_id, "position": pos})

@app.route("/api/cards/<int:card_id>", methods=["PATCH","DELETE"])
def card_ops(card_id):
    conn = db()
    if request.method == "DELETE":
        conn.execute("DELETE FROM cards WHERE id=?", (card_id,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})
    d = request.json
    fields = ['title','description','priority','due_date','column_id','position']
    for f in fields:
        if f in d: conn.execute(f"UPDATE cards SET {f}=? WHERE id=?", (d[f], card_id))
    if 'tags' in d: conn.execute("UPDATE cards SET tags=? WHERE id=?", (json.dumps(d['tags']), card_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/cards/move", methods=["POST"])
def move_card():
    d = request.json
    card_id = d['card_id']
    new_col = d['column_id']
    new_pos = d['position']
    conn = db()
    old = conn.execute("SELECT column_id, position FROM cards WHERE id=?", (card_id,)).fetchone()
    # Shift cards in destination
    conn.execute("UPDATE cards SET position=position+1 WHERE column_id=? AND position>=?", (new_col, new_pos))
    # Move the card
    conn.execute("UPDATE cards SET column_id=?, position=? WHERE id=?", (new_col, new_pos, card_id))
    # Compact source column
    conn.execute("""UPDATE cards SET position=(SELECT COUNT(*) FROM cards c2 WHERE c2.column_id=cards.column_id AND c2.position<cards.position)
                    WHERE column_id=?""", (old['column_id'],))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})



def init_sessions_db():
    conn = db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS writing_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            word_count INTEGER DEFAULT 0,
            char_count INTEGER DEFAULT 0,
            duration_seconds INTEGER DEFAULT 0,
            grace_period INTEGER DEFAULT 5,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()

@app.route("/write")
def write():
    return render_template("write.html")

@app.route("/sessions")
def sessions_page():
    conn = db()
    rows = conn.execute("SELECT * FROM writing_sessions ORDER BY created_at DESC").fetchall()
    conn.close()
    return render_template("sessions.html", sessions=rows)

@app.route("/sessions/<int:session_id>")
def session_detail(session_id):
    conn = db()
    session = conn.execute("SELECT * FROM writing_sessions WHERE id=?", (session_id,)).fetchone()
    conn.close()
    return render_template("session_detail.html", session=session)

@app.route("/api/sessions", methods=["POST"])
def save_session():
    d = request.json
    content = d.get("content", "").strip()
    if not content:
        return jsonify({"error": "No content"}), 400
    conn = db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO writing_sessions (content, word_count, char_count, duration_seconds, grace_period)
        VALUES (?, ?, ?, ?, ?)
    """, (content, d.get("word_count", 0), d.get("char_count", 0), d.get("duration_seconds", 0), d.get("grace_period", 5)))
    session_id = c.lastrowid
    conn.commit()
    conn.close()
    return jsonify({"id": session_id, "ok": True})

@app.route("/api/sessions/<int:session_id>", methods=["DELETE"])
def delete_session(session_id):
    conn = db()
    conn.execute("DELETE FROM writing_sessions WHERE id=?", (session_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})
init_db()
init_sessions_db()

if __name__ == "__main__":
    app.run(debug=True, port=5051)
