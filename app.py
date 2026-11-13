"""AI Finance Assistant - Flask backend.

Run:  python app.py        (then open http://127.0.0.1:5000)
"""
import os
import re
import sqlite3
from datetime import date, datetime, timezone
from functools import wraps
from pathlib import Path

import joblib
import pandas as pd
from flask import Flask, g, jsonify, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from ml.forecast import forecast_next
from ml.text import clean_text  # noqa: F401  (needed so joblib can unpickle the model)

ROOT = Path(__file__).resolve().parent
CATEGORIES = ["Food", "Transport", "Shopping", "Bills", "Entertainment", "Health", "Education", "Other"]
DISCLAIMER = "These insights are educational and are not professional financial advice."

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    description TEXT NOT NULL,
    amount REAL NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('income','expense')),
    category TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tx_user_date ON transactions(user_id, date);
CREATE TABLE IF NOT EXISTS budgets (
    budget_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    month TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'Overall',
    limit_amount REAL NOT NULL,
    UNIQUE(user_id, month, category)
);
CREATE TABLE IF NOT EXISTS predictions (
    prediction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id INTEGER REFERENCES transactions(transaction_id) ON DELETE CASCADE,
    predicted_category TEXT NOT NULL,
    confidence REAL,
    corrected_category TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS insights (
    insight_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    insight_text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def create_app(test_config=None):
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
        DATABASE=os.environ.get("DATABASE", str(ROOT / "instance" / "finance.db")),
        MODEL_PATH=str(ROOT / "models" / "category_model.joblib"),
        ADMIN_EMAIL=os.environ.get("ADMIN_EMAIL", "admin@example.com"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if test_config:
        app.config.update(test_config)
    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- database helpers
    def get_db():
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DATABASE"])
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    with sqlite3.connect(app.config["DATABASE"]) as con:
        con.executescript(SCHEMA)

    # ---------------------------------------------------------------- ML model (kept separate from app logic)
    class Classifier:
        def __init__(self, path):
            self.path, self.model = path, None
            self.load()

        def load(self):
            try:
                self.model = joblib.load(self.path)
            except Exception:  # model missing -> app still works, category falls back to 'Other'
                self.model = None

        def predict(self, description: str):
            if self.model is None or not clean_text(description):
                return "Other", 0.0
            probs = self.model.predict_proba([description])[0]
            i = int(probs.argmax())
            return str(self.model.classes_[i]), float(probs[i])

    classifier = Classifier(app.config["MODEL_PATH"])
    app.classifier = classifier

    # ---------------------------------------------------------------- auth helpers
    def current_user():
        uid = session.get("user_id")
        if uid is None:
            return None
        return get_db().execute("SELECT * FROM users WHERE user_id = ?", (uid,)).fetchone()

    def login_required(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            user = current_user()
            if user is None:
                return jsonify(error="Please log in first."), 401
            g.user = user
            return fn(*a, **kw)
        return wrapper

    def admin_required(fn):
        @wraps(fn)
        @login_required
        def wrapper(*a, **kw):
            if not g.user["is_admin"]:
                return jsonify(error="Admin access required."), 403
            return fn(*a, **kw)
        return wrapper

    # ---------------------------------------------------------------- validation helpers
    EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

    def bad(msg, code=400):
        return jsonify(error=msg), code

    def parse_tx(data, partial=False):
        """Validate a transaction payload. Returns (clean_dict, error)."""
        out = {}
        if not partial or "amount" in data:
            try:
                amount = float(data.get("amount"))
            except (TypeError, ValueError):
                return None, "Amount must be a number."
            if not (0 < amount < 1e9):
                return None, "Amount must be greater than 0."
            out["amount"] = round(amount, 2)
        if not partial or "date" in data:
            try:
                d = datetime.strptime(str(data.get("date", "")), "%Y-%m-%d").date()
            except ValueError:
                return None, "Date must be in YYYY-MM-DD format."
            if d > date.today().replace(year=date.today().year + 1):
                return None, "Date is too far in the future."
            out["date"] = d.isoformat()
        if not partial or "description" in data:
            desc = str(data.get("description", "")).strip()
            if not desc:
                return None, "Description is required."
            if len(desc) > 200:
                return None, "Description must be 200 characters or fewer."
            out["description"] = desc
        if not partial or "type" in data:
            t = str(data.get("type", "")).lower()
            if t not in ("income", "expense"):
                return None, "Type must be 'income' or 'expense'."
            out["type"] = t
        cat = data.get("category")
        if cat not in (None, ""):
            if cat not in CATEGORIES + ["Income"]:
                return None, f"Category must be one of: {', '.join(CATEGORIES)}."
            out["category"] = cat
        return out, None

    def tx_row(r):
        return {k: r[k] for k in ("transaction_id", "date", "description", "amount", "type", "category")}

    # ================================================================= pages
    @app.get("/")
    def index():
        return render_template("index.html")

    # ================================================================= 9.1 Authentication
    @app.post("/register")
    def register():
        data = request.get_json(silent=True) or {}
        name, email, pw = (str(data.get(k, "")).strip() for k in ("name", "email", "password"))
        if not name or not email or not pw:
            return bad("Name, email and password are required.")
        if not EMAIL_RE.match(email):
            return bad("Please enter a valid email address.")
        if len(pw) < 6:
            return bad("Password must be at least 6 characters.")
        db = get_db()
        if db.execute("SELECT 1 FROM users WHERE email = ?", (email.lower(),)).fetchone():
            return bad("An account with this email already exists.", 409)
        is_admin = 1 if email.lower() == app.config["ADMIN_EMAIL"].lower() else 0
        cur = db.execute(
            "INSERT INTO users (name, email, password_hash, is_admin, created_at) VALUES (?,?,?,?,?)",
            (name, email.lower(), generate_password_hash(pw), is_admin, datetime.now(timezone.utc).isoformat()))
        db.commit()
        session["user_id"] = cur.lastrowid
        return jsonify(message="Account created.", user={"name": name, "email": email.lower(), "is_admin": bool(is_admin)}), 201

    @app.post("/login")
    def login():
        data = request.get_json(silent=True) or {}
        email, pw = str(data.get("email", "")).strip().lower(), str(data.get("password", ""))
        if not email or not pw:
            return bad("Email and password are required.")
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user is None or not check_password_hash(user["password_hash"], pw):
            return bad("Invalid email or password.", 401)
        session.clear()
        session["user_id"] = user["user_id"]
        return jsonify(message="Logged in.", user={"name": user["name"], "email": user["email"], "is_admin": bool(user["is_admin"])})

    @app.post("/logout")
    def logout():
        session.clear()
        return jsonify(message="Logged out.")

    @app.get("/me")
    @login_required
    def me():
        u = g.user
        return jsonify(user={"name": u["name"], "email": u["email"], "is_admin": bool(u["is_admin"])})

    @app.get("/categories")
    def categories():
        return jsonify(categories=CATEGORIES)

    # ================================================================= 9.3 AI categorisation
    @app.post("/predict-category")
    @login_required
    def predict_category():
        data = request.get_json(silent=True) or {}
        desc = str(data.get("description", "")).strip()
        if not desc:
            return bad("Description is required.")
        cat, conf = classifier.predict(desc)
        return jsonify(category=cat, confidence=round(conf, 3), low_confidence=conf < 0.5)

    # ================================================================= 9.2 Transactions
    @app.post("/transactions")
    @login_required
    def add_transaction():
        clean, err = parse_tx(request.get_json(silent=True) or {})
        if err:
            return bad(err)
        db = get_db()
        predicted = None
        if clean["type"] == "income":
            clean["category"] = "Income"
        elif not clean.get("category"):  # user left category blank -> ask the ML model
            cat, conf = classifier.predict(clean["description"])
            clean["category"], predicted = cat, (cat, conf)
        cur = db.execute(
            "INSERT INTO transactions (user_id, date, description, amount, type, category) VALUES (?,?,?,?,?,?)",
            (g.user["user_id"], clean["date"], clean["description"], clean["amount"], clean["type"], clean["category"]))
        tid = cur.lastrowid
        if predicted:
            db.execute("INSERT INTO predictions (transaction_id, predicted_category, confidence, created_at) VALUES (?,?,?,?)",
                       (tid, predicted[0], predicted[1], datetime.now(timezone.utc).isoformat()))
        db.commit()
        out = tx_row(db.execute("SELECT * FROM transactions WHERE transaction_id = ?", (tid,)).fetchone())
        if predicted:
            out["predicted"] = True
            out["confidence"] = round(predicted[1], 3)
        return jsonify(out), 201

    @app.get("/transactions")
    @login_required
    def list_transactions():
        q = ["user_id = ?"]
        args = [g.user["user_id"]]
        a = request.args
        if a.get("type") in ("income", "expense"):
            q.append("type = ?"); args.append(a["type"])
        if a.get("category"):
            q.append("category = ?"); args.append(a["category"])
        if a.get("search"):
            q.append("description LIKE ?"); args.append(f"%{a['search'].strip()}%")
        if a.get("from"):
            q.append("date >= ?"); args.append(a["from"])
        if a.get("to"):
            q.append("date <= ?"); args.append(a["to"])
        if a.get("min_amount"):
            try:
                q.append("amount >= ?"); args.append(float(a["min_amount"]))
            except ValueError:
                return bad("min_amount must be a number.")
        if a.get("max_amount"):
            try:
                q.append("amount <= ?"); args.append(float(a["max_amount"]))
            except ValueError:
                return bad("max_amount must be a number.")
        try:
            page, per = max(int(a.get("page", 1)), 1), min(max(int(a.get("per_page", 50)), 1), 200)
        except ValueError:
            return bad("page and per_page must be integers.")
        where = " AND ".join(q)
        db = get_db()
        total = db.execute(f"SELECT COUNT(*) c FROM transactions WHERE {where}", args).fetchone()["c"]
        rows = db.execute(
            f"SELECT * FROM transactions WHERE {where} ORDER BY date DESC, transaction_id DESC LIMIT ? OFFSET ?",
            args + [per, (page - 1) * per]).fetchall()
        return jsonify(transactions=[tx_row(r) for r in rows], total=total, page=page, per_page=per)

    def _own_tx(tid):
        return get_db().execute("SELECT * FROM transactions WHERE transaction_id = ? AND user_id = ?",
                                (tid, g.user["user_id"])).fetchone()

    @app.put("/transactions/<int:tid>")
    @login_required
    def update_transaction(tid):
        existing = _own_tx(tid)
        if existing is None:
            return bad("Transaction not found.", 404)
        clean, err = parse_tx(request.get_json(silent=True) or {}, partial=True)
        if err:
            return bad(err)
        if not clean:
            return bad("Nothing to update.")
        db = get_db()
        new_type = clean.get("type", existing["type"])
        if new_type == "income":
            clean["category"] = "Income"
        elif "category" not in clean and existing["type"] == "income":
            clean["category"] = classifier.predict(clean.get("description", existing["description"]))[0]
        sets = ", ".join(f"{k} = ?" for k in clean)
        db.execute(f"UPDATE transactions SET {sets} WHERE transaction_id = ? AND user_id = ?",
                   list(clean.values()) + [tid, g.user["user_id"]])
        # SRS 9.3: a user's correction of the prediction is kept as future training data
        if "category" in clean and new_type == "expense" and clean["category"] != existing["category"]:
            pred = db.execute("SELECT prediction_id FROM predictions WHERE transaction_id = ? ORDER BY prediction_id DESC LIMIT 1", (tid,)).fetchone()
            if pred:
                db.execute("UPDATE predictions SET corrected_category = ? WHERE prediction_id = ?", (clean["category"], pred["prediction_id"]))
            else:
                db.execute("INSERT INTO predictions (transaction_id, predicted_category, confidence, corrected_category, created_at) VALUES (?,?,?,?,?)",
                           (tid, existing["category"], None, clean["category"], datetime.now(timezone.utc).isoformat()))
        db.commit()
        return jsonify(tx_row(_own_tx(tid)))

    @app.delete("/transactions/<int:tid>")
    @login_required
    def delete_transaction(tid):
        if _own_tx(tid) is None:
            return bad("Transaction not found.", 404)
        db = get_db()
        db.execute("DELETE FROM transactions WHERE transaction_id = ? AND user_id = ?", (tid, g.user["user_id"]))
        db.commit()
        return jsonify(message="Transaction deleted.")

    # ================================================================= analytics helpers
    def month_of(arg):
        m = arg or date.today().strftime("%Y-%m")
        return m if MONTH_RE.match(m) else None

    def prev_month(m):
        y, mo = int(m[:4]), int(m[5:])
        return f"{y - 1}-12" if mo == 1 else f"{y}-{mo - 1:02d}"

    def monthly_expense_series(uid, upto=None):
        """Chronological [(month, total)] for the user's expenses, with empty months filled with 0."""
        rows = get_db().execute(
            "SELECT substr(date,1,7) m, SUM(amount) t FROM transactions WHERE user_id=? AND type='expense' GROUP BY m ORDER BY m", (uid,)).fetchall()
        if not rows:
            return []
        data = {r["m"]: r["t"] for r in rows}
        months = pd.period_range(rows[0]["m"], upto or rows[-1]["m"], freq="M").strftime("%Y-%m")
        return [(m, round(data.get(m, 0.0), 2)) for m in months]

    def category_spend(uid, month, upto_day=31):
        rows = get_db().execute(
            "SELECT category, SUM(amount) t FROM transactions WHERE user_id=? AND type='expense' AND substr(date,1,7)=? "
            "AND CAST(substr(date,9,2) AS INTEGER) <= ? GROUP BY category ORDER BY t DESC",
            (uid, month, upto_day)).fetchall()
        return {r["category"]: round(r["t"], 2) for r in rows}

    def budget_status(uid, month):
        spend = category_spend(uid, month)
        total_spent = round(sum(spend.values()), 2)
        out = []
        for b in get_db().execute("SELECT * FROM budgets WHERE user_id=? AND month=? ORDER BY category", (uid, month)):
            spent = total_spent if b["category"] == "Overall" else spend.get(b["category"], 0.0)
            pct = round(spent / b["limit_amount"] * 100, 1) if b["limit_amount"] else 0
            status = "exceeded" if pct > 100 else "warning" if pct >= 80 else "ok"
            out.append({"budget_id": b["budget_id"], "category": b["category"], "limit_amount": b["limit_amount"],
                        "spent": spent, "remaining": round(b["limit_amount"] - spent, 2), "utilization_pct": pct, "status": status})
        return out

    def build_forecast(uid, month):
        # use only completed months before the selected month, so a half-finished month does not skew the trend
        series = [t for m, t in monthly_expense_series(uid) if m < month]
        return forecast_next(series[-12:])

    # ================================================================= 9.4 Budgets
    @app.post("/budgets")
    @login_required
    def set_budget():
        data = request.get_json(silent=True) or {}
        month = month_of(data.get("month"))
        if month is None:
            return bad("Month must be in YYYY-MM format.")
        cat = data.get("category") or "Overall"
        if cat != "Overall" and cat not in CATEGORIES:
            return bad(f"Category must be 'Overall' or one of: {', '.join(CATEGORIES)}.")
        try:
            limit = float(data.get("limit_amount"))
        except (TypeError, ValueError):
            return bad("limit_amount must be a number.")
        if limit <= 0:
            return bad("limit_amount must be greater than 0.")
        db = get_db()
        db.execute("""INSERT INTO budgets (user_id, month, category, limit_amount) VALUES (?,?,?,?)
                      ON CONFLICT(user_id, month, category) DO UPDATE SET limit_amount = excluded.limit_amount""",
                   (g.user["user_id"], month, cat, round(limit, 2)))
        db.commit()
        return jsonify(message="Budget saved.", budgets=budget_status(g.user["user_id"], month)), 201

    @app.get("/budgets")
    @login_required
    def get_budgets():
        month = month_of(request.args.get("month"))
        if month is None:
            return bad("Month must be in YYYY-MM format.")
        return jsonify(month=month, budgets=budget_status(g.user["user_id"], month))

    @app.delete("/budgets/<int:bid>")
    @login_required
    def delete_budget(bid):
        db = get_db()
        cur = db.execute("DELETE FROM budgets WHERE budget_id = ? AND user_id = ?", (bid, g.user["user_id"]))
        db.commit()
        if cur.rowcount == 0:
            return bad("Budget not found.", 404)
        return jsonify(message="Budget deleted.")

    # ================================================================= 9.5 Dashboard
    @app.get("/dashboard")
    @login_required
    def dashboard():
        uid = g.user["user_id"]
        month = month_of(request.args.get("month"))
        if month is None:
            return bad("Month must be in YYYY-MM format.")
        db = get_db()
        sums = db.execute(
            "SELECT type, SUM(amount) t FROM transactions WHERE user_id=? AND substr(date,1,7)=? GROUP BY type", (uid, month)).fetchall()
        s = {r["type"]: r["t"] for r in sums}
        income, expense = round(s.get("income", 0.0), 2), round(s.get("expense", 0.0), 2)
        all_time = db.execute("SELECT type, SUM(amount) t FROM transactions WHERE user_id=? GROUP BY type", (uid,)).fetchall()
        a = {r["type"]: r["t"] for r in all_time}
        trend = [{"month": m, "expense": t} for m, t in monthly_expense_series(uid)][-12:]
        income_rows = db.execute(
            "SELECT substr(date,1,7) m, SUM(amount) t FROM transactions WHERE user_id=? AND type='income' GROUP BY m", (uid,)).fetchall()
        inc_map = {r["m"]: round(r["t"], 2) for r in income_rows}
        for row in trend:
            row["income"] = inc_map.get(row["month"], 0.0)
        budgets = budget_status(uid, month)
        alerts = [f"{b['category']} budget {'exceeded' if b['status'] == 'exceeded' else 'is at ' + str(b['utilization_pct']) + '%'}"
                  for b in budgets if b["status"] != "ok"]
        return jsonify(month=month, total_income=income, total_expenses=expense, month_balance=round(income - expense, 2),
                       available_balance=round(a.get("income", 0.0) - a.get("expense", 0.0), 2),
                       category_spending=category_spend(uid, month), monthly_trend=trend, budgets=budgets,
                       alerts=alerts, forecast=build_forecast(uid, month))

    # ================================================================= 9.7 Insights
    def generate_insights(uid, month):
        tips = []
        spend = category_spend(uid, month)
        total = sum(spend.values())
        if not spend:
            return ["No expenses recorded for this month yet. Add a few transactions to get insights."]
        top_cat, top_val = next(iter(spend.items()))
        tips.append(f"Your highest-spending category this month is {top_cat} (₹{top_val:,.0f}, {top_val / total * 100:.0f}% of expenses).")
        # for the month in progress, compare like-for-like (same days of the previous month)
        today = date.today()
        in_progress = month == today.strftime("%Y-%m")
        prev = category_spend(uid, prev_month(month), today.day if in_progress else 31)
        for cat, val in spend.items():
            before = prev.get(cat, 0.0)
            if before >= 500 and val > before * 1.2:
                tips.append(f"Your {cat.lower()} expenses increased by {(val - before) / before * 100:.0f}% compared with the previous month.")
            elif before >= 500 and val < before * 0.8:
                tips.append(f"Nice - your {cat.lower()} spending dropped by {(before - val) / before * 100:.0f}% compared with the previous month.")
        for b in budget_status(uid, month):
            if b["status"] == "exceeded":
                tips.append(f"You have exceeded your {b['category'].lower()} budget by ₹{-b['remaining']:,.0f}. Consider reviewing these expenses.")
            elif b["status"] == "warning":
                tips.append(f"You have used {b['utilization_pct']:.0f}% of your {b['category'].lower()} budget, with ₹{b['remaining']:,.0f} left.")
        inc = get_db().execute("SELECT SUM(amount) t FROM transactions WHERE user_id=? AND type='income' AND substr(date,1,7)=?", (uid, month)).fetchone()["t"] or 0
        if inc > 0:
            rate = (inc - total) / inc * 100
            tips.append(f"You are saving about {rate:.0f}% of your income this month." if rate >= 0
                        else "Your expenses are higher than your income this month.")
        return tips

    @app.get("/insights")
    @login_required
    def insights():
        month = month_of(request.args.get("month"))
        if month is None:
            return bad("Month must be in YYYY-MM format.")
        tips = generate_insights(g.user["user_id"], month)
        db = get_db()
        now = datetime.now(timezone.utc).isoformat()
        db.executemany("INSERT INTO insights (user_id, insight_text, created_at) VALUES (?,?,?)",
                       [(g.user["user_id"], t, now) for t in tips])
        db.commit()
        return jsonify(month=month, insights=tips, disclaimer=DISCLAIMER)

    # ================================================================= 8. Chatbot (rule-based, app questions + own data)
    FAQ = [
        (r"\b(hi|hello|hey)\b", "Hi! I can help with using this app, e.g. 'how do I add a budget?' or 'how much did I spend this month?'"),
        (r"add.*(transaction|expense|income)", "Go to the Transactions tab, fill in the date, description, amount and type, then click Add. Leave the category empty and the AI will suggest one."),
        (r"categor", "Categories are Food, Transport, Shopping, Bills, Entertainment, Health, Education and Other. The AI predicts one from your description, and you can correct it any time - corrections help improve the model."),
        (r"budget", "Open the Budgets tab, pick a month, choose 'Overall' or a category and enter a limit. You get a warning at 80% usage and an alert when you exceed it."),
        (r"forecast|predict|estimate", "The forecast uses Linear Regression on your monthly spending history. It needs at least 3 months of data and is only an estimate."),
        (r"insight", "Insights are generated from your spending patterns, such as category changes vs last month and budget usage. They are educational, not professional financial advice."),
        (r"password|security|safe|privacy", "Passwords are stored hashed, and you can only ever see your own transactions."),
        (r"delete|edit|change", "In the Transactions table, use Edit or Delete next to a transaction."),
        (r"advice|invest|stock|tax|loan", "I can't give investment, tax or loan advice. This app is for tracking and learning only."),
    ]

    @app.post("/chatbot")
    @login_required
    def chatbot():
        msg = str((request.get_json(silent=True) or {}).get("message", "")).strip().lower()
        if not msg:
            return bad("Message is required.")
        uid, month = g.user["user_id"], date.today().strftime("%Y-%m")
        if re.search(r"(how much|total).*(spend|spent|expense)", msg):
            spend = category_spend(uid, month)
            for c in CATEGORIES:
                if c.lower() in msg:
                    return jsonify(reply=f"You spent ₹{spend.get(c, 0):,.0f} on {c} so far this month.")
            return jsonify(reply=f"You have spent ₹{sum(spend.values()):,.0f} so far this month.")
        if re.search(r"(my|current).*(balance)|balance.*left", msg):
            row = get_db().execute("SELECT type, SUM(amount) t FROM transactions WHERE user_id=? GROUP BY type", (uid,)).fetchall()
            d = {r["type"]: r["t"] for r in row}
            return jsonify(reply=f"Your available balance is ₹{d.get('income', 0) - d.get('expense', 0):,.0f}.")
        for pattern, reply in FAQ:
            if re.search(pattern, msg):
                return jsonify(reply=reply)
        return jsonify(reply="Sorry, I only know about this app (transactions, categories, budgets, forecast, insights). Try asking 'how do I add a budget?'")

    # ================================================================= 9. Admin (optional)
    @app.get("/admin/users")
    @admin_required
    def admin_users():
        rows = get_db().execute(
            """SELECT u.user_id, u.name, u.email, u.is_admin, u.created_at,
                      (SELECT COUNT(*) FROM transactions t WHERE t.user_id = u.user_id) AS transactions
               FROM users u ORDER BY u.user_id""").fetchall()
        return jsonify(users=[dict(r) for r in rows])

    @app.delete("/admin/users/<int:uid>")
    @admin_required
    def admin_delete_user(uid):
        if uid == g.user["user_id"]:
            return bad("You cannot delete your own admin account.")
        db = get_db()
        cur = db.execute("DELETE FROM users WHERE user_id = ?", (uid,))
        db.commit()
        return jsonify(message="User deleted.") if cur.rowcount else bad("User not found.", 404)

    @app.post("/admin/retrain")
    @admin_required
    def admin_retrain():
        """Retrain the classifier on the base dataset + all user corrections (SRS 9.3)."""
        from ml.train import CATEGORIES as TRAIN_CATS, build_pipeline, load_and_clean
        from sklearn.linear_model import LogisticRegression
        df, _ = load_and_clean()
        base = df[(df["transaction_type"] == "expense") & df["category"].isin(TRAIN_CATS)][["description", "category"]]
        rows = get_db().execute(
            """SELECT t.description, p.corrected_category AS category FROM predictions p
               JOIN transactions t ON t.transaction_id = p.transaction_id WHERE p.corrected_category IS NOT NULL""").fetchall()
        extra = pd.DataFrame([dict(r) for r in rows], columns=["description", "category"])
        data = pd.concat([base, extra], ignore_index=True)
        model = build_pipeline(LogisticRegression(max_iter=2000, C=10)).fit(data["description"], data["category"])
        joblib.dump(model, app.config["MODEL_PATH"])
        classifier.load()
        return jsonify(message="Model retrained.", training_rows=len(data), user_corrections=len(extra))

    @app.errorhandler(404)
    def not_found(_e):
        if request.path.startswith("/static"):
            return "Not found", 404
        return jsonify(error="Not found."), 404

    @app.errorhandler(405)
    def method_not_allowed(_e):
        return jsonify(error="Method not allowed."), 405

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
