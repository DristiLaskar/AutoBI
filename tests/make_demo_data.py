"""Create demo / test datasets.

ecommerce_orders.xlsx  -> SYNTHETIC fashion e-commerce data (3 sheets) used to prove the engine works on a different schema
messy_sales.csv        -> SYNTHETIC deliberately messy export (semicolons, latin-1, $ and %, blanks, duplicates, dd/mm dates)
Both are generated with a fixed random seed - they are test fixtures, not real company data.
"""
from pathlib import Path
import numpy as np
import pandas as pd


def make_ecommerce(path):
    rng = np.random.default_rng(7)
    n_cust, n_prod, n_ord = 1500, 220, 12000
    brands = ["Roadster", "HRX", "Nike", "Puma", "Levis", "H&M", "Allen Solly", "W", "Biba", "Libas"]
    cats = {"Tshirts": 499, "Jeans": 1299, "Kurtas": 899, "Dresses": 1499, "Sneakers": 2499, "Jackets": 2999}
    products = pd.DataFrame({"product_id": [f"P{i:04d}" for i in range(n_prod)],
                             "brand": rng.choice(brands, n_prod, p=np.array([.16, .12, .1, .1, .1, .1, .1, .08, .07, .07])),
                             "category": rng.choice(list(cats), n_prod, p=[.25, .2, .15, .15, .15, .1])})
    products["mrp"] = [int(cats[c] * rng.uniform(0.7, 1.6)) for c in products.category]
    cities = ["Bengaluru", "Mumbai", "Delhi", "Hyderabad", "Chennai", "Pune", "Kolkata", "Jaipur"]
    customers = pd.DataFrame({"customer_id": [f"C{i:05d}" for i in range(n_cust)],
                              "city": rng.choice(cities, n_cust, p=[.2, .18, .17, .12, .1, .1, .07, .06]),
                              "gender": rng.choice(["F", "M"], n_cust, p=[.58, .42]),
                              "age": rng.integers(18, 58, n_cust)})
    customers["signup_date"] = pd.to_datetime("2022-01-01") + pd.to_timedelta(rng.integers(0, 700, n_cust), unit="D")
    days = pd.date_range("2024-01-01", "2024-12-31")
    season = 1 + 0.5 * np.isin(days.month, [10, 11]) + 0.25 * (days.month == 12) + 0.3 * np.isin(days.dayofweek, [5, 6])
    d = rng.choice(days, n_ord, p=season / season.sum())
    o = pd.DataFrame({"order_id": np.arange(100000, 100000 + n_ord), "order_date": pd.to_datetime(d),
                      "customer_id": rng.choice(customers.customer_id, n_ord), "product_id": rng.choice(products.product_id, n_ord),
                      "quantity": rng.choice([1, 1, 1, 2, 3], n_ord)})
    o = o.merge(products[["product_id", "mrp"]], on="product_id")
    o["discount_pct"] = np.clip(rng.normal(0.3, 0.12, len(o)), 0, 0.7).round(2)
    o["net_amount"] = (o.mrp * (1 - o.discount_pct) * o.quantity).round(2)
    p_ret = np.clip(0.08 + 0.35 * (o.discount_pct - 0.3), 0.01, 0.6)
    o["returned"] = (rng.random(len(o)) < p_ret).astype(int)
    o = o.drop(columns="mrp").sort_values("order_date").reset_index(drop=True)
    with pd.ExcelWriter(path) as xw:
        o.to_excel(xw, sheet_name="Orders", index=False)
        products.to_excel(xw, sheet_name="Products", index=False)
        customers.to_excel(xw, sheet_name="Customers", index=False)


def make_messy(path):
    rng = np.random.default_rng(3)
    n = 600
    d = pd.to_datetime("2024-01-01") + pd.to_timedelta(rng.integers(0, 330, n), unit="D")
    df = pd.DataFrame({
        "Order Date": d.strftime("%d/%m/%Y"),
        " Region ": rng.choice(["north", "North", "NORTH ", "South", "south", "East", "West", None], n),
        "Sales ($)": [f"${v:,.2f}" for v in rng.gamma(3, 400, n)],
        "Margin %": [f"{v:.0f}%" for v in rng.uniform(5, 35, n)],
        "Units": rng.integers(1, 40, n).astype(object),
        "Customer Café": rng.choice(["Café Roma", "Bistro Zoë", "Müller GmbH", "N/A"], n),
    })
    df.loc[rng.choice(n, 25, replace=False), "Units"] = ""
    df = pd.concat([df, df.iloc[:15]])  # exact duplicates
    df.to_csv(path, index=False, sep=";", encoding="latin-1")


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "examples"
    out.mkdir(exist_ok=True)
    make_ecommerce(out / "ecommerce_orders.xlsx")
    make_messy(out / "messy_sales.csv")
    print("created", [p.name for p in out.iterdir()])
