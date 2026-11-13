"""Create demo accounts with ~7 months of realistic sample data (no real personal data).

    python seed_demo.py

Logins:   demo@example.com / demo123     (normal user)
          admin@example.com / admin123   (admin)
"""
import random
import sqlite3
from datetime import date, timedelta

from werkzeug.security import generate_password_hash

from app import SCHEMA, app

random.seed(7)
DB = app.config["DATABASE"]

# (description, category, low, high, relative weight)
EXPENSES = [
    ("swiggy dinner", "Food", 180, 650, 9), ("zomato lunch order", "Food", 150, 500, 7), ("bigbasket groceries", "Food", 600, 2200, 3),
    ("chai point snacks", "Food", 40, 220, 6), ("dominos pizza", "Food", 250, 800, 2),
    ("uber ride", "Transport", 90, 480, 6), ("rapido bike taxi", "Transport", 40, 160, 5), ("metro card recharge", "Transport", 200, 500, 1),
    ("petrol hp", "Transport", 300, 1200, 2), ("irctc train ticket", "Transport", 350, 1800, 1),
    ("amazon order headphones", "Shopping", 500, 3500, 2), ("myntra shirt", "Shopping", 500, 2200, 2), ("flipkart electronics", "Shopping", 400, 4000, 1),
    ("jio mobile recharge", "Bills", 239, 399, 1), ("act fibernet broadband", "Bills", 700, 1100, 1), ("tneb electricity bill", "Bills", 350, 1400, 1),
    ("netflix subscription", "Entertainment", 199, 649, 1), ("bookmyshow movie tickets", "Entertainment", 250, 900, 2), ("spotify premium", "Entertainment", 119, 119, 1),
    ("apollo pharmacy medicines", "Health", 120, 900, 2), ("cult fit gym membership", "Health", 600, 1500, 1),
    ("udemy course", "Education", 449, 1999, 1), ("college stationery", "Education", 80, 450, 1), ("leetcode premium", "Education", 300, 900, 1),
    ("atm withdrawal", "Other", 500, 3000, 2), ("laundry", "Other", 80, 300, 2), ("gift to friend", "Other", 200, 1200, 1),
]


def month_start(y, m):
    return date(y, m, 1)


def main():
    today = date.today()
    with sqlite3.connect(DB) as con:
        con.executescript(SCHEMA)
        con.execute("PRAGMA foreign_keys = ON")
        for email in ("demo@example.com", "admin@example.com"):
            con.execute("DELETE FROM users WHERE email = ?", (email,))
        uid = con.execute("INSERT INTO users (name,email,password_hash,is_admin,created_at) VALUES (?,?,?,?,datetime('now'))",
                          ("Demo User", "demo@example.com", generate_password_hash("demo123"), 0)).lastrowid
        con.execute("INSERT INTO users (name,email,password_hash,is_admin,created_at) VALUES (?,?,?,?,datetime('now'))",
                    ("Admin", "admin@example.com", generate_password_hash("admin123"), 1))

        rows = []
        weights = [e[4] for e in EXPENSES]
        for back in range(6, -1, -1):  # 7 months ending with the current one
            y, m = today.year, today.month - back
            while m <= 0:
                y, m = y - 1, m + 12
            start = month_start(y, m)
            end = today if back == 0 else (month_start(y + (m == 12), (m % 12) + 1) - timedelta(days=1))
            days = (end - start).days + 1
            growth = 1 + 0.04 * (6 - back)  # spending creeps up over time so the forecast has a trend
            rows.append((uid, start.isoformat(), "salary credited", 42000, "income", "Income"))
            if days > 10:
                rows.append((uid, (start + timedelta(days=9)).isoformat(), "freelance payment", random.choice([3000, 4500, 6000]), "income", "Income"))
            for _ in range(int(days * 1.3)):
                d = start + timedelta(days=random.randrange(days))
                desc, cat, lo, hi, _w = random.choices(EXPENSES, weights)[0]
                amt = round(random.uniform(lo, hi) * growth)
                rows.append((uid, d.isoformat(), desc, amt, "expense", cat))
        con.executemany("INSERT INTO transactions (user_id,date,description,amount,type,category) VALUES (?,?,?,?,?,?)", rows)

        month = today.strftime("%Y-%m")
        for cat, limit in [("Overall", 22000), ("Food", 3000), ("Transport", 3500), ("Shopping", 4000), ("Entertainment", 400)]:
            con.execute("INSERT INTO budgets (user_id,month,category,limit_amount) VALUES (?,?,?,?)", (uid, month, cat, limit))
    print(f"Seeded {len(rows)} transactions for demo@example.com (password: demo123).")
    print("Admin login: admin@example.com / admin123")


if __name__ == "__main__":
    main()
