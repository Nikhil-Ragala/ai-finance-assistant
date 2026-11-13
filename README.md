# AI Finance Assistant

A beginner-friendly personal finance app with machine learning, built from the *AI Finance Assistant SRS v1.0*.

Add income and expenses, let an ML model **auto-categorise** them (`"swiggy dinner 450"` → Food), set **budgets**, see **dashboards**, get a **spending forecast** and simple **AI insights**, and ask a small **chatbot** how the app works.

> Educational / portfolio project. Insights are not professional financial advice.

![Dashboard](docs/screenshots/02_dashboard.png)

## Features (mapped to the SRS)

| SRS section | What's implemented |
|---|---|
| 9.1 Authentication | Register / login / logout, hashed passwords, session cookies, users only see their own data |
| 9.2 Transactions | Add, edit, delete, history, search + filters (text, type, category, date range, amount) + pagination |
| 9.3 AI categorisation | TF-IDF + Logistic Regression; live suggestion while typing; user can correct it; corrections are stored and used when the admin retrains |
| 9.4 Budgets | Monthly overall + per-category limits, usage %, warning at 80%, alert when exceeded |
| 9.5 Dashboard | Income, expenses, balance, category chart, monthly trend chart |
| 9.6 Forecast | Linear Regression on monthly totals; shown as an estimate; falls back to an average (or a message) when there is too little history |
| 9.7 Insights | Rule-based messages (top category, change vs last month, budget usage, savings rate) + disclaimer |
| 8 / 12 Chatbot | Rule-based assistant for app questions and "how much did I spend…" |
| 8 / 12 Admin (optional) | List/delete users, retrain the model with user corrections |

## Tech stack

Python · Flask · SQLite · scikit-learn · pandas / NumPy · joblib · HTML / CSS / vanilla JS · Chart.js (bundled locally, works offline)

## Quick start

```bash
# 1. install
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. (optional) re-generate data and re-train. A trained model is already included.
python ml/generate_dataset.py
python -m ml.train

# 3. load demo data (creates demo@example.com / demo123 and admin@example.com / admin123)
python seed_demo.py

# 4. run
python app.py
# open http://127.0.0.1:5000
```

Or skip the demo data and just click **Register** to create your own account.
Any account registered with the email `admin@example.com` becomes the admin (change with the `ADMIN_EMAIL` env var).

Run the tests:

```bash
python -m pytest -q          # 30 tests
```

## Project structure

```
app.py                  Flask app: all API endpoints, auth, analytics, insights, chatbot, admin
seed_demo.py            Demo users + ~7 months of sample transactions
ml/
  generate_dataset.py   Synthetic, non-personal transaction dataset
  text.py               Text preprocessing (shared by training and the app)
  train.py              Data cleaning, model comparison, evaluation, saves model + metrics
  forecast.py           Spending forecast (Linear Regression)
models/                 category_model.joblib, metrics.json
data/transactions.csv   Generated dataset
notebooks/train_models.ipynb   Explained, executed training notebook
templates/ static/      Frontend (HTML, CSS, JS, Chart.js)
tests/test_app.py       Functional + ML tests (SRS section 22)
docs/                   Charts and screenshots used in the report
```

## API (SRS section 20)

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/register`, `/login`, `/logout` | Accounts (`GET /me` returns the current user) |
| POST / GET | `/transactions` | Add / list (filters: `search`, `type`, `category`, `from`, `to`, `min_amount`, `max_amount`, `page`, `per_page`) |
| PUT / DELETE | `/transactions/<id>` | Update (changing the category records a correction) / delete |
| POST | `/predict-category` | `{"description": "..."}` → category + confidence |
| GET | `/dashboard?month=YYYY-MM` | Totals, category spending, trend, budgets, alerts, forecast |
| POST / GET | `/budgets` | Create or update / list budgets for a month (`DELETE /budgets/<id>`) |
| GET | `/insights?month=YYYY-MM` | Insight messages + disclaimer |
| POST | `/chatbot` | `{"message": "..."}` → reply |
| GET / DELETE / POST | `/admin/users`, `/admin/retrain` | Admin only |

## ML results

Numbers below are from `models/metrics.json` (80/20 train/test split, unseen test data).

**Expense classifier** (3,000+ synthetic transactions, 8 categories): ~**85% accuracy**. Logistic Regression, Naive Bayes, Linear SVM and Random Forest all land within about 1 point of each other, so Logistic Regression was chosen because it is simple and explainable. The dataset deliberately includes ambiguous descriptions (e.g. "upi payment", "amazon order") that cannot be classified from text alone; an earlier, cleaner version scored 100%, which was a sign of label leakage rather than a good model.

**Spending forecast:** Linear Regression, evaluated with MAE / MSE / RMSE / R² on the last months of the data. The synthetic data has no real trend, so it does **not** beat a simple average baseline here (R² is negative). This is reported honestly in the report rather than hidden.

![Confusion matrix](docs/confusion_matrix.png)

## Security notes

- Passwords hashed with Werkzeug (`pbkdf2`/`scrypt`), never stored or logged in plain text.
- Every query is scoped by `user_id`; other users' records return 404.
- All SQL is parameterised; the UI escapes all user text before rendering.
- Before deploying for real: set `SECRET_KEY`, serve over HTTPS, and run behind a production server (gunicorn / waitress) instead of `app.run(debug=True)`.
- The model file is loaded with joblib (pickle) - only load model files you trained yourself.

## Limitations

ML predictions depend on training data quality; new users have little history for forecasting; descriptions can be ambiguous; forecasts are estimates; this app does not replace a financial advisor. Out of scope per the SRS: stock trading, bank integrations, loan decisions, tax advice, automatic transfers.

## Future work

Bank/UPI integration, OCR receipt scanning, voice entry, better time-series forecasting (e.g. seasonality), anomaly detection, savings goals, mobile app, cloud deployment.
