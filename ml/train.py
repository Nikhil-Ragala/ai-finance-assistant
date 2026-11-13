"""Train + evaluate the ML models and save them with joblib.

Run from the project root:   python -m ml.train
Outputs:
  models/category_model.joblib      - TF-IDF + best classifier (expense category)
  models/metrics.json               - all evaluation numbers (used by the report)
  docs/confusion_matrix.png         - classifier confusion matrix
  docs/forecast_eval.png            - forecast backtest chart
"""
import json
from pathlib import Path

import joblib
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import (ConfusionMatrixDisplay, accuracy_score, classification_report,
                             confusion_matrix, f1_score, mean_absolute_error,
                             mean_squared_error, r2_score)
from sklearn.model_selection import train_test_split
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.svm import LinearSVC

from ml.text import clean_text

ROOT = Path(__file__).resolve().parent.parent
CATEGORIES = ["Food", "Transport", "Shopping", "Bills", "Entertainment", "Health", "Education", "Other"]


def load_and_clean(path=ROOT / "data" / "transactions.csv") -> tuple[pd.DataFrame, dict]:
    """Data preprocessing steps (documented per SRS 11.3 / 14)."""
    df = pd.read_csv(path)
    log = {"raw_rows": len(df)}
    df = df.drop_duplicates(subset=["transaction_id"])
    log["after_dedup"] = len(df)
    df = df.dropna(subset=["description", "amount", "category", "date"])
    log["after_dropping_missing"] = len(df)
    df["category"] = df["category"].astype(str).str.strip().str.title()
    df["transaction_type"] = df["transaction_type"].str.lower().str.strip()
    df["description"] = df["description"].astype(str)
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["amount"] > 0]
    log["clean_rows"] = len(df)
    return df, log


def build_pipeline(clf):
    features = FeatureUnion([
        ("word", TfidfVectorizer(preprocessor=clean_text, analyzer="word", ngram_range=(1, 2), sublinear_tf=True)),
        # char n-grams make the model robust to typos like 'strbucks'
        ("char", TfidfVectorizer(preprocessor=clean_text, analyzer="char_wb", ngram_range=(2, 5), sublinear_tf=True)),
    ])
    return Pipeline([("tfidf", features), ("clf", clf)])


def train_classifier(df: pd.DataFrame, metrics: dict):
    exp = df[(df["transaction_type"] == "expense") & (df["category"].isin(CATEGORIES))]
    X, y = exp["description"], exp["category"]
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

    candidates = {
        "Logistic Regression": LogisticRegression(max_iter=2000, C=10),
        "Naive Bayes": MultinomialNB(alpha=0.1),
        "Linear SVM": LinearSVC(C=1.0),
        "Random Forest": RandomForestClassifier(n_estimators=200, random_state=42, n_jobs=-1),
    }
    results, fitted = {}, {}
    for name, clf in candidates.items():
        pipe = build_pipeline(clf).fit(X_tr, y_tr)
        pred = pipe.predict(X_te)
        results[name] = {"accuracy": round(accuracy_score(y_te, pred), 4),
                         "macro_f1": round(f1_score(y_te, pred, average="macro"), 4)}
        fitted[name] = pipe
        print(f"{name:20s} acc={results[name]['accuracy']:.3f}  macro-F1={results[name]['macro_f1']:.3f}")

    # Choose the final model: prefer one that outputs probabilities (confidence is shown to users).
    proba_models = {k: v for k, v in results.items() if k in ("Logistic Regression", "Naive Bayes", "Random Forest")}
    best_name = max(proba_models, key=lambda k: proba_models[k]["macro_f1"])
    # Prefer the simple, explainable model when it is within 1 F1 point of the best (SRS: explainability).
    if proba_models["Logistic Regression"]["macro_f1"] >= proba_models[best_name]["macro_f1"] - 0.01:
        best_name = "Logistic Regression"
    best = fitted[best_name]
    pred = best.predict(X_te)
    report = classification_report(y_te, pred, output_dict=True, zero_division=0)

    metrics["classifier"] = {
        "train_size": len(X_tr), "test_size": len(X_te), "comparison": results, "selected": best_name,
        "accuracy": round(accuracy_score(y_te, pred), 4),
        "per_class": {c: {k: round(report[c][k], 3) for k in ("precision", "recall", "f1-score", "support")}
                      for c in CATEGORIES if c in report},
        "macro_avg": {k: round(report["macro avg"][k], 3) for k in ("precision", "recall", "f1-score")},
    }

    fig, ax = plt.subplots(figsize=(7.5, 6.5))
    ConfusionMatrixDisplay(confusion_matrix(y_te, pred, labels=CATEGORIES), display_labels=CATEGORIES).plot(
        ax=ax, cmap="Blues", xticks_rotation=40, colorbar=False)
    ax.set_title(f"Expense classifier - confusion matrix ({best_name})")
    fig.tight_layout()
    fig.savefig(ROOT / "docs" / "confusion_matrix.png", dpi=150)
    plt.close(fig)

    # refit on all data for the shipped model
    final = build_pipeline(type(best.named_steps["clf"])(**best.named_steps["clf"].get_params())).fit(X, y)
    joblib.dump(final, ROOT / "models" / "category_model.joblib")
    print(f"Selected: {best_name}  (test accuracy {metrics['classifier']['accuracy']})")


def evaluate_forecast(df: pd.DataFrame, metrics: dict):
    exp = df[df["transaction_type"] == "expense"].copy()
    monthly = exp.groupby(exp["date"].dt.to_period("M"))["amount"].sum()
    monthly = monthly.iloc[:-1] if len(monthly) > 12 else monthly  # last month may be partial
    y = monthly.values
    n_test = max(3, len(y) // 5)
    X = np.arange(len(y)).reshape(-1, 1)
    X_tr, X_te, y_tr, y_te = X[:-n_test], X[-n_test:], y[:-n_test], y[-n_test:]

    lr = LinearRegression().fit(X_tr, y_tr)
    pred = lr.predict(X_te)
    baseline = np.full_like(y_te, y_tr.mean(), dtype=float)
    mae, rmse = mean_absolute_error(y_te, pred), float(np.sqrt(mean_squared_error(y_te, pred)))
    metrics["forecast"] = {
        "months_total": int(len(y)), "train_months": int(len(y_tr)), "test_months": int(n_test),
        "linear_regression": {"MAE": round(mae, 2), "MSE": round(mean_squared_error(y_te, pred), 2),
                              "RMSE": round(rmse, 2), "R2": round(r2_score(y_te, pred), 3)},
        "mean_baseline": {"MAE": round(mean_absolute_error(y_te, baseline), 2),
                          "RMSE": round(float(np.sqrt(mean_squared_error(y_te, baseline))), 2)},
    }
    print("Forecast:", metrics["forecast"])

    fig, ax = plt.subplots(figsize=(8, 3.8))
    labels = [str(p) for p in monthly.index]
    ax.plot(labels, y, marker="o", label="Actual monthly spending")
    ax.plot(labels[-n_test:], pred, marker="s", linestyle="--", label="Linear regression (test months)")
    ax.axvline(len(y_tr) - 0.5, color="grey", linestyle=":")
    ax.set_title("Spending forecast backtest")
    ax.set_ylabel("INR")
    ax.legend()
    plt.xticks(rotation=60, fontsize=7)
    fig.tight_layout()
    fig.savefig(ROOT / "docs" / "forecast_eval.png", dpi=150)
    plt.close(fig)


def main():
    (ROOT / "models").mkdir(exist_ok=True)
    (ROOT / "docs").mkdir(exist_ok=True)
    df, log = load_and_clean()
    metrics = {"preprocessing": log}
    print("Preprocessing:", log)
    train_classifier(df, metrics)
    evaluate_forecast(df, metrics)
    (ROOT / "models" / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print("Saved models/metrics.json")


if __name__ == "__main__":
    main()
