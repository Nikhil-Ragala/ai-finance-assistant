"""Generate a synthetic (non-personal) transaction dataset for training.

Fields: transaction_id, date, description, amount, transaction_type, category, merchant
Run:  python ml/generate_dataset.py
"""
import random
from pathlib import Path

import numpy as np
import pandas as pd

random.seed(42)
np.random.seed(42)

# category -> (merchants/keywords, description templates, amount range)
CATALOG = {
    "Food": (
        ["Swiggy", "Zomato", "Dominos", "McDonalds", "KFC", "Starbucks", "Chai Point",
         "Haldirams", "BigBasket", "Blinkit", "Zepto", "Subway", "Pizza Hut", "Barbeque Nation",
         "Local Hotel", "Sri Balaji Mess", "Amma Canteen"],
        ["{m} dinner", "{m} lunch", "{m} order", "{m} breakfast", "{m} biryani", "{m} snacks",
         "{m} groceries", "{m} coffee", "{m} pizza", "lunch at {m}", "dinner at {m}", "{m} food delivery",
         "tea and snacks {m}", "vegetables and fruits", "grocery shopping {m}", "{m} ice cream"],
        (40, 1200),
    ),
    "Transport": (
        ["Uber", "Ola", "Rapido", "IRCTC", "RedBus", "MetroCard", "Indian Oil", "HP Petrol",
         "Shell", "FASTag", "Namma Yatri", "Chennai Metro", "MTC Bus", "IndiGo"],
        ["{m} ride", "{m} cab", "{m} auto", "{m} ticket", "{m} recharge", "petrol {m}", "{m} fuel",
         "train ticket {m}", "bus ticket {m}", "{m} bike taxi", "metro card recharge", "{m} flight booking",
         "auto fare", "toll {m}", "{m} trip"],
        (20, 3500),
    ),
    "Shopping": (
        ["Amazon", "Flipkart", "Myntra", "Ajio", "Decathlon", "Reliance Trends", "Lifestyle",
         "Croma", "Nykaa", "Meesho", "Max Fashion", "Westside", "Pantaloons"],
        ["{m} order", "{m} shopping", "{m} clothes", "{m} shoes", "{m} headphones", "{m} purchase",
         "{m} sale", "bought tshirt {m}", "{m} electronics", "{m} gadget", "{m} accessories",
         "{m} jeans", "{m} backpack", "{m} gift"],
        (150, 8000),
    ),
    "Bills": (
        ["Jio", "Airtel", "Vi", "BSNL", "TNEB", "Tata Power", "BESCOM", "ACT Fibernet",
         "Hathway", "LIC", "HDFC Insurance", "Tata Sky", "Piped Gas"],
        ["{m} recharge", "{m} bill", "{m} postpaid", "electricity bill {m}", "{m} broadband",
         "{m} premium", "mobile recharge {m}", "water bill", "{m} wifi bill", "house rent", "hostel fees",
         "{m} dth recharge", "gas bill", "{m} monthly bill", "mess bill"],
        (99, 6000),
    ),
    "Entertainment": (
        ["Netflix", "Spotify", "BookMyShow", "PVR", "INOX", "Hotstar", "Prime Video", "YouTube Premium",
         "Steam", "PlayStation", "Dream11", "Sony LIV", "Zee5"],
        ["{m} subscription", "{m} movie tickets", "{m} monthly plan", "{m} membership", "movie at {m}",
         "{m} game purchase", "{m} renewal", "{m} show tickets", "{m} concert", "bowling and arcade",
         "{m} premium plan", "gaming credits {m}"],
        (79, 2500),
    ),
    "Health": (
        ["Apollo Pharmacy", "MedPlus", "Practo", "1mg", "Pharmeasy", "Netmeds", "Cult.fit",
         "Fortis", "Local Clinic", "Dr Reddy Clinic", "Dental Care", "Eye Care Centre"],
        ["{m} medicines", "{m} consultation", "{m} lab test", "{m} gym membership", "{m} pharmacy",
         "doctor visit {m}", "{m} checkup", "{m} tablets", "{m} vitamins", "{m} dental", "{m} physiotherapy",
         "{m} health checkup", "medical store"],
        (50, 4000),
    ),
    "Education": (
        ["Udemy", "Coursera", "Unacademy", "Byjus", "NPTEL", "Amazon Books", "Crossword",
         "LeetCode", "Coding Ninjas", "GeeksforGeeks", "College Stationery", "Exam Board"],
        ["{m} course", "{m} subscription", "{m} books", "{m} exam fee", "{m} study material", "{m} workshop",
         "{m} certification", "{m} tuition", "{m} notebooks", "{m} online class", "stationery {m}",
         "{m} premium plan", "photocopy and printouts"],
        (50, 6000),
    ),
    "Other": (
        ["ATM", "Gift Shop", "Charity", "Temple", "Laundry", "Salon", "Courier", "Post Office",
         "Local Store", "Misc"],
        ["{m} withdrawal", "{m} donation", "{m} charges", "{m} service", "{m} payment", "haircut {m}",
         "{m} fee", "laundry {m}", "{m} courier", "miscellaneous {m}", "gift to friend", "{m} repair",
         "pocket money", "lent to friend"],
        (20, 3000),
    ),
}

INCOME = [
    ("Salary credited", (15000, 60000)), ("Stipend", (5000, 25000)), ("Freelance payment", (2000, 20000)),
    ("Pocket money from parents", (2000, 8000)), ("Scholarship", (3000, 15000)),
    ("Cashback received", (20, 400)), ("Interest credited", (50, 1500)), ("Refund", (100, 3000)),
]


def _typo(text: str) -> str:
    if len(text) > 5 and random.random() < 0.08:
        i = random.randrange(1, len(text) - 1)
        text = text[:i] + text[i + 1:]  # drop a char
    return text


# Real transactions are messy: generic UPI-style text and merchants that sell many things.
# These rows are intentionally ambiguous, so the classifier cannot reach 100% (no label leakage).
AMBIGUOUS = [
    "upi payment", "paytm payment", "phonepe transfer", "gpay {n}", "payment to {n}", "paid {n}",
    "amazon pay {n}", "cash payment", "online payment", "card payment {n}", "bill payment {n}",
    "swiggy instamart", "amazon order", "flipkart order", "jio mart", "reliance smart", "d mart",
]
NAMES = ["ravi", "suresh", "kumar", "anita", "store", "shop", "stores", "mart", "traders", "enterprises"]


def make_ambiguous(category: str):
    desc = random.choice(AMBIGUOUS).format(n=random.choice(NAMES))
    lo, hi = CATALOG[category][2]
    amount = round(random.uniform(lo, hi / 2), 2)
    return desc, amount, ""


def make_expense(category: str):
    if random.random() < 0.15:
        return make_ambiguous(category)
    merchants, templates, (lo, hi) = CATALOG[category]
    m = random.choice(merchants)
    desc = random.choice(templates).format(m=m)
    if random.random() < 0.35:  # users often write the amount in the description
        pass
    desc = _typo(desc.lower() if random.random() < 0.6 else desc)
    amount = round(float(np.random.lognormal(mean=np.log((lo + hi) / 4), sigma=0.6)), 2)
    amount = float(min(max(amount, lo), hi))
    return desc, amount, m


def main(n_expenses_per_cat: int = 420, out: str = "data/transactions.csv"):
    rows = []
    start = pd.Timestamp("2025-01-01")
    for cat in CATALOG:
        for _ in range(n_expenses_per_cat):
            desc, amount, m = make_expense(cat)
            date = start + pd.Timedelta(days=random.randint(0, 700))
            rows.append([date.date().isoformat(), desc, amount, "expense", cat, m])
    for _ in range(300):
        desc, (lo, hi) = random.choice(INCOME)
        date = start + pd.Timedelta(days=random.randint(0, 700))
        rows.append([date.date().isoformat(), desc.lower(), round(random.uniform(lo, hi), 2), "income", "Income", ""])

    df = pd.DataFrame(rows, columns=["date", "description", "amount", "transaction_type", "category", "merchant"])
    df = df.sample(frac=1, random_state=42).reset_index(drop=True)
    df.insert(0, "transaction_id", range(1, len(df) + 1))

    # Inject realistic dirt so the cleaning step in the notebook has something to do
    dirty = df.copy()
    for idx in random.sample(range(len(dirty)), 25):
        dirty.loc[idx, "description"] = None
    dirty = pd.concat([dirty, dirty.sample(30, random_state=1)], ignore_index=True)  # duplicates
    for idx in random.sample(range(len(dirty)), 20):
        dirty.loc[idx, "category"] = str(dirty.loc[idx, "category"]).upper()  # inconsistent casing

    Path(out).parent.mkdir(parents=True, exist_ok=True)
    dirty.to_csv(out, index=False)
    print(f"Wrote {len(dirty)} rows to {out}")


if __name__ == "__main__":
    main()
