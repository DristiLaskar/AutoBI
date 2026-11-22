"""Run with:  python -m unittest discover -s tests -v"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from autobi.clean import clean_table, parse_dates, parse_numeric  # noqa: E402
from autobi.pipeline import run_pipeline  # noqa: E402
from autobi.validate import validate_project  # noqa: E402
import make_demo_data  # noqa: E402


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_and_validate(self, inp, name, **kw):
        r = run_pipeline(inp, self.tmp / name, **kw)
        problems = validate_project(r["out"], r["pbi"], r["model"], r["res"])
        self.assertEqual(problems, [], problems)
        self.assertEqual(r["res"]["warnings"], [], r["res"]["warnings"])
        return r


class TestCleaning(unittest.TestCase):
    def test_numeric_formats(self):
        s = pd.Series(["$1,200.50", "(300)", "45", None, "1,000"])
        out, _ = parse_numeric(s)
        self.assertEqual(out.dropna().tolist(), [1200.5, -300.0, 45.0, 1000.0])

    def test_percent(self):
        out, info = parse_numeric(pd.Series(["12%", "50%", "7.5%"]))
        self.assertTrue(info["percent"])
        self.assertAlmostEqual(out.iloc[0], 0.12)

    def test_leading_zero_ids_stay_text(self):
        out, _ = parse_numeric(pd.Series(["02134", "00501", "10001"]))
        self.assertIsNone(out)

    def test_dayfirst_detected_from_values(self):
        s = pd.Series(["13-01-2023", "20-01-2023", "27-01-2023", "03-02-2023"])
        out, info = parse_dates(s, "d")
        self.assertEqual(out.iloc[0], pd.Timestamp("2023-01-13"))
        self.assertFalse(info["ambiguous"])

    def test_ambiguous_dates_flagged_and_parsed(self):
        s = pd.Series(["01-02-2023", "03-04-2023", "05-06-2023", "07-08-2023"])
        out, info = parse_dates(s, "d", dayfirst=True)
        self.assertIsNotNone(out)
        self.assertEqual(out.iloc[0], pd.Timestamp("2023-02-01"))
        self.assertTrue(info["ambiguous"])
        out2, _ = parse_dates(s, "d", dayfirst=False)
        self.assertEqual(out2.iloc[0], pd.Timestamp("2023-01-02"))

    def test_headers_whitespace_case_duplicates(self):
        df = pd.DataFrame({"\ufeffUse Chip": ["Swipe ", " Chip", "Swipe "], "Region": ["north", "North", "NORTH"], "x": ["1", "2", "3"]})
        df = pd.concat([df, df.iloc[:1]])
        c, log = clean_table(df, "t")
        self.assertIn("Use_Chip", c.columns)
        self.assertEqual(sorted(c.Use_Chip.unique()), ["Chip", "Swipe"])
        self.assertEqual(c.Region.nunique(), 1)
        self.assertEqual(log["duplicates_removed"], 1)


class TestCreditCardRealData(Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.r = run_pipeline(ROOT / "examples" / "credit_card", cls.tmp / "cc", config=ROOT / "configs" / "credit_card.json")
        cls.raw = {n: pd.read_csv(ROOT / "examples" / "credit_card" / f"{n}.csv", encoding="utf-8-sig")
                   for n in ("credit_card", "cc_add", "customer", "cust_add")}

    def test_schema_drift_repaired_no_nulls(self):
        fact = self.r["model"]["tables"][self.r["model"]["fact"]]
        self.assertEqual(len(fact), 10108 + 185)
        self.assertEqual(int(fact["Total_Trans_Vol"].isna().sum()), 0)
        drift = self.r["model"]["appends"][0]["schema_drift_repaired"]
        self.assertTrue(any({d["from"], d["to"]} == {"Total_Trans_Ct", "Total_Trans_Vol"} for d in drift))

    def test_kpis_reconcile_with_raw_files(self):
        k = {x["label"]: x["value"] for x in self.r["res"]["kpis"]}
        cc = pd.concat([self.raw["credit_card"], self.raw["cc_add"].rename(columns={"Total_Trans_Ct": "Total_Trans_Vol"})])
        cu = pd.concat([self.raw["customer"], self.raw["cust_add"]])
        self.assertEqual(k["Records"], len(cc))
        self.assertAlmostEqual(k["Total Trans Amt"], cc.Total_Trans_Amt.sum())
        self.assertAlmostEqual(k["Total Interest Earned"], cc.Interest_Earned.sum(), places=4)
        self.assertAlmostEqual(k["Total Revenue"], cc.Interest_Earned.sum() + cc.Annual_Fees.sum(), places=4)
        self.assertAlmostEqual(k["Delinquent Acc Rate"], cc.Delinquent_Acc.mean())
        self.assertAlmostEqual(k["Avg Income"], cu.Income.mean(), places=6)

    def test_relationship_and_dates(self):
        rel = {(r["from_table"], r["from_col"], r["to_table"]) for r in self.r["model"]["relationships"]}
        self.assertIn(("Fact_Credit_Card", "Client_Num", "Dim_Customer"), rel)
        self.assertEqual(self.r["model"]["date"]["grain"], "weekly")
        self.assertEqual(self.r["model"]["date"]["min"], "2023-01-01")

    def test_power_bi_project_valid(self):
        self.assertEqual(validate_project(self.r["out"], self.r["pbi"], self.r["model"], self.r["res"]), [])
        self.assertGreaterEqual(self.r["pbi"]["n_visuals"], 30)

    def test_time_risk_signal_found(self):
        bp = self.r["res"]["target"]["by_period"]
        self.assertLess(bp["p_value"], 1e-6)

    def test_outputs_exist(self):
        for f in ("report/dashboard.html", "report/analysis.xlsx", "report/insights.md", "report/summary.json"):
            self.assertTrue((self.r["out"] / f).exists(), f)
        json.loads((self.r["out"] / "report" / "summary.json").read_text())


class TestOtherData(Base):
    def test_ecommerce_excel_multisheet(self):
        p = self.tmp / "ecom.xlsx"
        make_demo_data.make_ecommerce(p)
        r = self.run_and_validate(p, "ecom")
        m = r["model"]
        self.assertEqual(m["fact"], "Fact_Orders")
        self.assertEqual(sorted(m["dims"]), ["Dim_Customers", "Dim_Products"])
        self.assertEqual(r["res"]["target_col"], "returned")

    def test_messy_semicolon_latin1(self):
        p = self.tmp / "messy.csv"
        make_demo_data.make_messy(p)
        r = self.run_and_validate(p, "messy")
        fact = r["model"]["tables"][r["model"]["fact"]]
        self.assertEqual(len(fact), 600)  # 15 duplicates removed
        self.assertTrue(pd.api.types.is_numeric_dtype(fact["Sales"]))
        self.assertIn("Customer_Cafe", fact.columns)
        self.assertEqual(fact["Region"].nunique(), 5)  # North/South/East/West/Unknown

    def test_sklearn_real_datasets(self):
        from sklearn.datasets import load_breast_cancer, load_diabetes, load_wine
        for name, loader in (("breast_cancer", load_breast_cancer), ("diabetes", load_diabetes), ("wine", load_wine)):
            d = loader(as_frame=True).frame
            p = self.tmp / f"{name}.csv"
            d.to_csv(p, index=False)
            self.run_and_validate(p, name)

    def test_tiny_file_no_dates_no_numbers(self):
        p = self.tmp / "tiny.csv"
        pd.DataFrame({"city": ["a", "b", "a", "c"], "note": ["x", "y", "z", "w"]}).to_csv(p, index=False)
        r = run_pipeline(p, self.tmp / "tiny")
        self.assertTrue((r["out"] / "report" / "dashboard.html").exists())

    def test_single_numeric_column(self):
        p = self.tmp / "one.csv"
        pd.DataFrame({"v": np.arange(50) * 1.5}).to_csv(p, index=False)
        r = run_pipeline(p, self.tmp / "one")
        self.assertTrue((r["out"] / "clean" / "Fact_One.csv").exists())

    def test_folder_of_files_and_config_override(self):
        d = self.tmp / "multi"
        d.mkdir()
        make_demo_data.make_messy(d / "a.csv")
        r = run_pipeline(d, self.tmp / "multi_out", config={"primary_measure": "Units", "name": "My Dash"})
        self.assertEqual(r["res"]["primary"], "Units")
        self.assertEqual(r["summary"]["name"], "My Dash")


class TestValidatorCatchesBreakage(Base):
    def test_bad_field_reference_detected(self):
        p = self.tmp / "m2.csv"
        make_demo_data.make_messy(p)
        r = run_pipeline(p, self.tmp / "broken")
        vf = next(Path(r["pbi"]["report"]).rglob("visual.json"))
        v = json.loads(vf.read_text())
        role = next(iter(v["visual"]["query"]["queryState"].values()))
        f = role["projections"][0]["field"]
        kind = "Column" if "Column" in f else "Measure"
        f[kind]["Property"] = "DoesNotExist"
        vf.write_text(json.dumps(v))
        problems = validate_project(r["out"], r["pbi"], r["model"], r["res"])
        self.assertTrue(any("unknown" in x for x in problems))

    def test_bom_detected(self):
        p = self.tmp / "m3.csv"
        make_demo_data.make_messy(p)
        r = run_pipeline(p, self.tmp / "bom")
        f = next((r["out"] / "clean").glob("Fact_*.csv"))
        f.write_bytes(b"\xef\xbb\xbf" + f.read_bytes())
        problems = validate_project(r["out"], r["pbi"], r["model"], r["res"])
        self.assertTrue(any("BOM" in x for x in problems))


if __name__ == "__main__":
    unittest.main()
