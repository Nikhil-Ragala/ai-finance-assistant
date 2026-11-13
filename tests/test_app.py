"""Tests following SRS section 22 (functional + ML testing)."""
import os
import tempfile

import pytest

from app import create_app
from ml.forecast import forecast_next
from ml.text import clean_text


@pytest.fixture()
def client():
    d = tempfile.mkdtemp()
    app = create_app({"TESTING": True, "DATABASE": os.path.join(d, "test.db"), "ADMIN_EMAIL": "boss@x.com"})
    return app.test_client()


def register(c, email="a@x.com", pw="secret1", name="Alice"):
    return c.post("/register", json={"name": name, "email": email, "password": pw})


def add(c, desc="uber ride", amount=300, typ="expense", date="2026-11-02", **extra):
    return c.post("/transactions", json={"date": date, "description": desc, "amount": amount, "type": typ, **extra})


# ----------------------------------------------------------------- 22.1 functional
class TestAuth:
    def test_register_login_logout(self, client):
        assert register(client).status_code == 201
        client.post("/logout")
        assert client.get("/me").status_code == 401
        assert client.post("/login", json={"email": "a@x.com", "password": "secret1"}).status_code == 200
        assert client.get("/me").get_json()["user"]["name"] == "Alice"

    def test_bad_credentials_and_validation(self, client):
        register(client)
        client.post("/logout")
        assert client.post("/login", json={"email": "a@x.com", "password": "wrong"}).status_code == 401
        assert client.post("/register", json={"name": "B", "email": "not-an-email", "password": "secret1"}).status_code == 400
        assert client.post("/register", json={"name": "B", "email": "b@x.com", "password": "123"}).status_code == 400
        assert client.post("/register", json={"name": "", "email": "b@x.com", "password": "secret1"}).status_code == 400
        assert register(client).status_code == 409  # duplicate email

    def test_password_not_stored_in_plain_text(self, client):
        import sqlite3
        register(client, pw="mypassword")
        db = sqlite3.connect(client.application.config["DATABASE"])
        stored = db.execute("SELECT password_hash FROM users").fetchone()[0]
        assert "mypassword" not in stored

    def test_endpoints_require_login(self, client):
        for method, path in [("get", "/transactions"), ("get", "/dashboard"), ("get", "/insights"),
                             ("post", "/budgets"), ("post", "/predict-category"), ("post", "/chatbot")]:
            assert getattr(client, method)(path).status_code == 401, path

    def test_users_cannot_access_each_others_data(self, client):
        register(client, "a@x.com")
        tid = add(client).get_json()["transaction_id"]
        client.post("/logout")
        register(client, "b@x.com", name="Bob")
        assert client.get("/transactions").get_json()["total"] == 0
        assert client.put(f"/transactions/{tid}", json={"amount": 1}).status_code == 404
        assert client.delete(f"/transactions/{tid}").status_code == 404


class TestTransactions:
    def test_add_edit_delete(self, client):
        register(client)
        t = add(client, category="Food", desc="lunch").get_json()
        assert t["category"] == "Food"
        r = client.put(f"/transactions/{t['transaction_id']}", json={"amount": 450.5})
        assert r.get_json()["amount"] == 450.5
        assert client.delete(f"/transactions/{t['transaction_id']}").status_code == 200
        assert client.get("/transactions").get_json()["total"] == 0

    def test_validation(self, client):
        register(client)
        assert add(client, amount=-5).status_code == 400
        assert add(client, amount="abc").status_code == 400
        assert add(client, amount=0).status_code == 400
        assert add(client, desc="  ").status_code == 400
        assert add(client, date="14-11-2026").status_code == 400
        assert add(client, typ="gift").status_code == 400
        assert add(client, category="Nonsense").status_code == 400

    def test_income_gets_income_category(self, client):
        register(client)
        assert add(client, "salary", 30000, "income").get_json()["category"] == "Income"

    def test_search_and_filter(self, client):
        register(client)
        add(client, "swiggy dinner", 400, date="2026-10-01")
        add(client, "uber ride", 200, date="2026-11-01")
        add(client, "salary", 9000, "income", date="2026-11-02")
        g = lambda q: client.get("/transactions?" + q).get_json()["total"]
        assert g("search=swiggy") == 1
        assert g("type=income") == 1
        assert g("from=2026-11-01&to=2026-11-30") == 2
        assert g("min_amount=300") == 2
        assert g("category=Transport") == 1


class TestBudgetsAndDashboard:
    def test_budget_usage_and_alerts(self, client):
        register(client)
        add(client, "dinner", 900, category="Food", date="2026-11-03")
        add(client, "lunch", 200, category="Food", date="2026-11-04")
        client.post("/budgets", json={"month": "2026-11", "category": "Food", "limit_amount": 1000})
        client.post("/budgets", json={"month": "2026-11", "limit_amount": 5000})  # overall
        b = {x["category"]: x for x in client.get("/budgets?month=2026-11").get_json()["budgets"]}
        assert b["Food"]["status"] == "exceeded" and b["Food"]["utilization_pct"] == 110.0
        assert b["Overall"]["spent"] == 1100 and b["Overall"]["status"] == "ok"
        assert client.get("/dashboard?month=2026-11").get_json()["alerts"]

    def test_budget_validation_and_upsert(self, client):
        register(client)
        assert client.post("/budgets", json={"month": "2026-13", "limit_amount": 5}).status_code == 400
        assert client.post("/budgets", json={"month": "2026-11", "limit_amount": -5}).status_code == 400
        client.post("/budgets", json={"month": "2026-11", "limit_amount": 100})
        client.post("/budgets", json={"month": "2026-11", "limit_amount": 200})
        budgets = client.get("/budgets?month=2026-11").get_json()["budgets"]
        assert len(budgets) == 1 and budgets[0]["limit_amount"] == 200

    def test_dashboard_calculations(self, client):
        register(client)
        add(client, "salary", 10000, "income", date="2026-11-01")
        add(client, "dinner", 400, category="Food", date="2026-11-02")
        add(client, "ride", 100, category="Transport", date="2026-11-03")
        add(client, "old", 50, category="Food", date="2026-10-03")
        d = client.get("/dashboard?month=2026-11").get_json()
        assert (d["total_income"], d["total_expenses"], d["month_balance"]) == (10000, 500, 9500)
        assert d["available_balance"] == 9450
        assert d["category_spending"] == {"Food": 400, "Transport": 100}

    def test_insights_have_disclaimer_and_comparison(self, client):
        register(client)
        add(client, "a", 1000, category="Food", date="2026-10-05")
        add(client, "b", 2000, category="Food", date="2026-11-05")
        r = client.get("/insights?month=2026-11").get_json()
        assert "not professional financial advice" in r["disclaimer"]
        assert any("food expenses increased" in t for t in r["insights"])


    def test_insight_compares_like_for_like_for_current_month(self, client):
        from datetime import date
        today = date.today()
        py, pm = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
        register(client)
        add(client, "x", 1000, category="Food", date=f"{today.year}-{today.month:02d}-01")
        add(client, "y", 1000, category="Food", date=f"{py}-{pm:02d}-01")
        if today.day < 28:  # a late-month purchase last month must not make this month look cheaper
            add(client, "z", 9000, category="Food", date=f"{py}-{pm:02d}-28")
        tips = client.get(f"/insights?month={today.strftime('%Y-%m')}").get_json()["insights"]
        assert not any("dropped" in t for t in tips)


class TestMisc:
    def test_chatbot(self, client):
        register(client)
        add(client, "dinner", 400, category="Food", date=__import__("datetime").date.today().isoformat())
        assert "budget" in client.post("/chatbot", json={"message": "how do I add a budget?"}).get_json()["reply"].lower()
        assert "400" in client.post("/chatbot", json={"message": "how much did I spend this month"}).get_json()["reply"]
        assert "can't give" in client.post("/chatbot", json={"message": "which stock should I invest in"}).get_json()["reply"]

    def test_admin_only(self, client):
        register(client)
        assert client.get("/admin/users").status_code == 403
        client.post("/logout")
        register(client, "boss@x.com", name="Boss")
        assert client.get("/admin/users").status_code == 200

    def test_json_errors(self, client):
        assert client.get("/nope").status_code == 404
        assert client.get("/nope").get_json()["error"]


# ----------------------------------------------------------------- 22.2 ML
class TestML:
    def test_preprocessing(self):
        assert clean_text("Swiggy Dinner 450!!") == "swiggy dinner"
        assert clean_text(None) == "" and clean_text("   ") == ""

    @pytest.mark.parametrize("desc,expected", [
        ("swiggy dinner 450", "Food"), ("uber ride 300", "Transport"), ("netflix subscription", "Entertainment"),
        ("apollo pharmacy medicines", "Health"), ("udemy python course", "Education"), ("jio recharge", "Bills"),
        ("amazon headphones", "Shopping"),
    ])
    def test_common_descriptions(self, client, desc, expected):
        client.application  # fixture ensures app exists
        register(client)
        assert client.post("/predict-category", json={"description": desc}).get_json()["category"] == expected

    def test_uncommon_and_empty_descriptions_do_not_crash(self, client):
        register(client)
        r = client.post("/predict-category", json={"description": "xqzv 12345 ???"})
        assert r.status_code == 200 and r.get_json()["category"] in client.get("/categories").get_json()["categories"]
        assert client.post("/predict-category", json={"description": ""}).status_code == 400

    def test_typo_robustness(self, client):
        register(client)
        assert client.post("/predict-category", json={"description": "swigy dinner"}).get_json()["category"] == "Food"

    def test_auto_category_and_correction_stored(self, client):
        import sqlite3
        register(client)
        t = add(client, "uber ride 300").get_json()
        assert t["category"] == "Transport" and t["predicted"] is True
        client.put(f"/transactions/{t['transaction_id']}", json={"category": "Other"})
        db = sqlite3.connect(client.application.config["DATABASE"])
        assert db.execute("SELECT corrected_category FROM predictions").fetchone()[0] == "Other"

    def test_forecast_insufficient_data(self):
        assert forecast_next([])["estimate"] is None
        r = forecast_next([100, 200])
        assert r["status"] == "insufficient_data" and r["estimate"] == 150

    def test_forecast_trend(self):
        r = forecast_next([1000, 2000, 3000, 4000])
        assert r["status"] == "ok" and abs(r["estimate"] - 5000) < 1
