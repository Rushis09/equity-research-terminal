"""
Annual Report Data Extractor
=============================
Extracts financial data from Indian company Annual Report PDFs.
Works on any BSE/NSE listed company AR (Standalone statements).

Usage:
    python annual_report_extractor.py --pdf AR-25.pdf --company "Eicher Motors"

Requirements:
    pip install pdfplumber

Output:
    - Prints extracted financials to terminal
    - Saves results to output_data.json
"""

import re
import json
import argparse
import sys
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    print("ERROR: pdfplumber not installed.")
    print("Fix:   pip install pdfplumber")
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────────────────────────────

def clean_number(text):
    """
    Convert Indian number string to float.
    Handles:  '18,451.46'  '(1,234.56)'  '4,279'  '-500'
    Returns float, or None if not parseable.
    """
    if not text:
        return None
    text = str(text).strip()
    text = text.replace('₹', '').replace('`', '').replace('\u20b9', '').replace(' ', '')
    negative = text.startswith('(') and text.endswith(')')
    text = text.strip('()').replace(',', '')
    try:
        val = float(text)
        return -val if negative else val
    except ValueError:
        return None


def extract_line_value(text, label, min_value=10):
    """
    Find a number on the SAME LINE as a label.
    Skips small note reference numbers (like '29', '34' etc).
    Returns float or None.
    """
    for line in text.split('\n'):
        if label.lower() in line.lower():
            nums = re.findall(r'\(?-?\d{1,3}(?:,\d{2,3})*(?:\.\d+)?\)?', line)
            big = [n for n in nums
                   if clean_number(n) is not None and abs(clean_number(n)) >= min_value]
            if big:
                return clean_number(big[0])
    return None


def find_page_with_keywords(pdf, keywords, search_range=None):
    """
    Scan pages for ALL keywords present on same page.
    Returns (page_number_1indexed, text) of first match, or (None, None).
    search_range: (start, end) 1-indexed inclusive. None = full PDF.
    """
    total = len(pdf.pages)
    start = (search_range[0] - 1) if search_range else 0
    end   = (search_range[1])     if search_range else total

    for i in range(start, min(end, total)):
        text = pdf.pages[i].extract_text() or ''
        if all(kw.lower() in text.lower() for kw in keywords):
            return i + 1, text
    return None, None


# ─────────────────────────────────────────────────────────────────────
# EXTRACTION FUNCTIONS
# ─────────────────────────────────────────────────────────────────────

def extract_pnl(pdf):
    """Extract Standalone Profit & Loss statement."""
    print("\n  Searching for P&L statement...")

    total = len(pdf.pages)
    mid   = total // 2

    # Search second half first (standalone financial statements)
    page_num, text = find_page_with_keywords(
        pdf,
        keywords=["Revenue from operations", "Profit before tax"],
        search_range=(mid, total)
    )

    if not page_num:
        page_num, text = find_page_with_keywords(
            pdf, keywords=["Revenue from operations", "Profit before tax"]
        )

    if not page_num:
        print("  ✗ P&L not found")
        return {}

    print(f"  ✓ Found on page {page_num}")

    pnl = {"source_page": page_num}

    # Income
    pnl["revenue_from_operations"] = extract_line_value(text, "Revenue from operations")
    pnl["other_income"]            = extract_line_value(text, "Other income", min_value=50)
    pnl["total_income"]            = extract_line_value(text, "Total Income")

    # Expenses
    pnl["raw_material_cost"]       = extract_line_value(text, "Cost of raw material")
    pnl["employee_expenses"]       = extract_line_value(text, "Employee benefits expense")
    pnl["finance_costs"]           = extract_line_value(text, "Finance costs", min_value=0.1)
    pnl["depreciation"]            = extract_line_value(text, "Depreciation and amortisation")
    pnl["other_expenses"]          = extract_line_value(text, "Other expenses")
    pnl["total_expenses"]          = extract_line_value(text, "Total expenses")

    # Profit
    pnl["profit_before_tax"]       = extract_line_value(text, "Profit before tax")
    pnl["tax_expense"]             = extract_line_value(text, "Total income tax expense")
    pnl["net_profit"]              = extract_line_value(text, "Net profit after tax")

    # EPS — special: "Basic  44  156.15  136.98" — pick decimal number
    for line in text.split('\n'):
        if re.search(r'\bBasic\b', line, re.IGNORECASE):
            nums = re.findall(r'\d{1,4}\.\d{2}', line)
            if nums:
                pnl["eps_basic"] = float(nums[0])
                break

    return pnl


def extract_balance_sheet(pdf):
    """Extract key Balance Sheet items."""
    print("\n  Searching for Balance Sheet...")

    total = len(pdf.pages)
    mid   = total // 2

    page_num, text = find_page_with_keywords(
        pdf, keywords=["Total Assets", "Total Equity"],
        search_range=(mid, total)
    )

    if not page_num:
        page_num, text = find_page_with_keywords(
            pdf, keywords=["Total Assets", "Total Equity"]
        )

    if not page_num:
        page_num, text = find_page_with_keywords(
            pdf, keywords=["BALANCE SHEET", "Non-current assets"],
            search_range=(mid, total)
        )

    if not page_num:
        print("  ✗ Balance Sheet not found")
        return {}

    print(f"  ✓ Found on page {page_num}")

    # Combine with next page in case BS spans 2 pages
    next_text = ""
    if page_num < total:
        next_text = pdf.pages[page_num].extract_text() or ""
    combined = text + "\n" + next_text

    bs = {"source_page": page_num}
    bs["total_assets"]          = extract_line_value(combined, "Total Assets")
    bs["total_non_current"]     = extract_line_value(combined, "Total non-current assets")
    bs["total_current_assets"]  = extract_line_value(combined, "Total current assets")
    bs["cash_equivalents"]      = extract_line_value(combined, "Cash and cash equivalents",
                                                     min_value=0.01)
    bs["total_equity"]          = extract_line_value(combined, "Total equity")
    bs["total_borrowings"]      = extract_line_value(combined, "Borrowings", min_value=0.01)
    bs["trade_payables"]        = extract_line_value(combined, "Trade payables")
    bs["total_liabilities"]     = extract_line_value(combined, "Total liabilities")

    return bs


def extract_cashflow(pdf):
    """Extract Cash Flow statement."""
    print("\n  Searching for Cash Flow statement...")

    total = len(pdf.pages)
    mid   = total // 2

    page_num, text = find_page_with_keywords(
        pdf, keywords=["CASH FLOW", "operating activities"],
        search_range=(mid, total)
    )

    if not page_num:
        print("  ✗ Cash Flow not found")
        return {}

    print(f"  ✓ Found on page {page_num}")

    next_text = ""
    if page_num < total:
        next_text = pdf.pages[page_num].extract_text() or ""
    combined = text + "\n" + next_text

    cf = {"source_page": page_num}

    # Multiple label variants used across companies
    cf["operating_cashflow"] = (
        extract_line_value(combined, "Net cash flow from / (used in) operating")
        or extract_line_value(combined, "Net cash generated from operating")
        or extract_line_value(combined, "Net cash from operating activities")
        or extract_line_value(combined, "Cash generated from operations")
    )
    cf["investing_cashflow"] = (
        extract_line_value(combined, "Net cash flow from / (used in) investing")
        or extract_line_value(combined, "Net cash used in investing")
        or extract_line_value(combined, "Net cash from investing activities")
    )
    cf["financing_cashflow"] = (
        extract_line_value(combined, "Net cash flow from / (used in) financing")
        or extract_line_value(combined, "Net cash used in financing")
        or extract_line_value(combined, "Net cash from financing activities")
    )
    cf["capex"] = (
        extract_line_value(combined, "Purchase of property, plant")
        or extract_line_value(combined, "Acquisition of property")
        or extract_line_value(combined, "Capital expenditure")
    )
    cf["dividend_paid"] = extract_line_value(combined, "Dividend paid")

    return cf


def extract_multiyear_trends(pdf):
    """
    Find pages with 5-year financial trends (FY21-FY25 style).
    Usually in Integrated Report / MD&A section (first 45% of PDF).
    """
    print("\n  Searching for multi-year trends...")

    total      = len(pdf.pages)
    search_end = min(total, int(total * 0.45))

    trend_pages = []
    for i in range(0, search_end):
        text = pdf.pages[i].extract_text() or ''
        has_years   = any(y in text for y in ["FY21", "FY22", "FY23", "FY24", "FY25",
                                               "2020-21", "2021-22"])
        has_finance = any(k in text for k in ["Revenue", "EBITDA", "PAT", "EPS", "Profit"])
        if has_years and has_finance:
            trend_pages.append((i + 1, text))

    if not trend_pages:
        print("  ⚠ No multi-year data found in first 45% of PDF")
        return {}

    print(f"  ✓ Found {len(trend_pages)} pages with trend data")

    trends = {}
    for page_num, text in trend_pages[:8]:
        large_nums = re.findall(r'\b\d{1,2},\d{3}(?:\.\d+)?\b', text)
        if len(large_nums) >= 3:
            context = "data"
            if "Revenue" in text:   context = "revenue"
            elif "PAT" in text:     context = "pat"
            elif "EBITDA" in text:  context = "ebitda"
            elif "EPS" in text:     context = "eps"
            key = f"{context}_page{page_num}"
            if key not in trends:
                trends[key] = [clean_number(n) for n in large_nums[:8]]

    return trends


# ─────────────────────────────────────────────────────────────────────
# COMPUTED RATIOS
# ─────────────────────────────────────────────────────────────────────

def compute_ratios(pnl, bs, cf):
    """Standard financial ratios — pure math, no AI."""
    print("\n  Computing ratios...")
    ratios = {}

    rev = pnl.get("revenue_from_operations")
    pat = pnl.get("net_profit")
    pbt = pnl.get("profit_before_tax")
    fin = pnl.get("finance_costs") or 0
    dep = pnl.get("depreciation")  or 0

    if rev and pbt:
        ebitda = pbt + fin + dep
        ratios["ebitda_cr"]      = round(ebitda, 2)
        ratios["opm_percent"]    = round(ebitda / rev * 100, 2)

    if rev and pat:
        ratios["pat_margin_pct"] = round(pat / rev * 100, 2)

    equity = bs.get("total_equity")
    assets = bs.get("total_assets")
    debt   = bs.get("total_borrowings") or 0

    if pat and equity:
        ratios["roe_pct"]        = round(pat / equity * 100, 2)

    ratios["debt_to_equity"]     = round(debt / equity, 3) if equity else 0.0

    if rev and assets:
        ratios["asset_turnover"] = round(rev / assets, 2)

    ocf = cf.get("operating_cashflow")
    if ocf and pat:
        ratios["cash_conversion_pct"] = round(ocf / pat * 100, 1)

    return ratios


# ─────────────────────────────────────────────────────────────────────
# PIOTROSKI F-SCORE  (like Tijori "9 Yes / 2 No" forensics)
# ─────────────────────────────────────────────────────────────────────

def compute_piotroski(pnl, bs, cf):
    """
    9-point fundamental health check.
    Score 7-9 = strong · 4-6 = neutral · 0-3 = weak
    """
    checks = {}
    score  = 0

    pat    = pnl.get("net_profit")
    assets = bs.get("total_assets")
    equity = bs.get("total_equity")
    debt   = bs.get("total_borrowings") or 0
    ocf    = cf.get("operating_cashflow")
    rev    = pnl.get("revenue_from_operations")
    fin    = pnl.get("finance_costs") or 0
    dep    = pnl.get("depreciation")  or 0
    pbt    = pnl.get("profit_before_tax")

    def add(label, condition):
        nonlocal score
        if condition is None:
            checks[label] = "? N/A"
        else:
            checks[label] = "✓ Yes" if condition else "✗ No"
            score += int(bool(condition))

    add("ROA positive (net profit / assets > 0)",
        (pat / assets > 0) if pat and assets else None)

    add("Operating cash flow positive",
        (ocf > 0) if ocf is not None else None)

    add("Cash flow > Net profit (quality earnings)",
        (ocf > pat) if ocf and pat else None)

    add("Debt to equity < 0.5",
        (debt / equity < 0.5) if equity else None)

    add("Finance cost < 2% of revenue (low leverage)",
        (fin / rev < 0.02) if rev else None)

    add("OPM > 10%",
        ((pbt + fin + dep) / rev > 0.10) if rev and pbt else None)

    add("PAT margin > 5%",
        (pat / rev > 0.05) if pat and rev else None)

    add("Other income < 15% of revenue",
        ((pnl.get("other_income") or 0) / rev < 0.15) if rev else None)

    add("Positive net worth (equity > 0)",
        (equity > 0) if equity is not None else None)

    return score, checks


# ─────────────────────────────────────────────────────────────────────
# DISPLAY
# ─────────────────────────────────────────────────────────────────────

def print_results(company, pnl, bs, cf, ratios, trends, fscore, fchecks):
    W   = 60
    SEP = "─" * W

    print(f"\n{'═'*W}")
    print(f"  EQUITY RESEARCH EXTRACT  |  {company}")
    print(f"{'═'*W}")

    if pnl:
        print(f"\n  PROFIT & LOSS  (page {pnl.get('source_page','?')})")
        print(SEP)
        rows = [
            ("Revenue from Operations",  pnl.get("revenue_from_operations"), "Cr"),
            ("Other Income",             pnl.get("other_income"),            "Cr"),
            ("Total Income",             pnl.get("total_income"),            "Cr"),
            ("  Raw Material Cost",      pnl.get("raw_material_cost"),       "Cr"),
            ("  Employee Expenses",      pnl.get("employee_expenses"),       "Cr"),
            ("  Depreciation",           pnl.get("depreciation"),            "Cr"),
            ("  Finance Costs",          pnl.get("finance_costs"),           "Cr"),
            ("  Other Expenses",         pnl.get("other_expenses"),          "Cr"),
            ("Total Expenses",           pnl.get("total_expenses"),          "Cr"),
            ("Profit Before Tax",        pnl.get("profit_before_tax"),       "Cr"),
            ("Net Profit (PAT)",         pnl.get("net_profit"),              "Cr"),
            ("EPS Basic",                pnl.get("eps_basic"),               "₹ "),
        ]
        for label, val, unit in rows:
            if val is not None:
                print(f"  {label:<36} {unit} {val:>9,.2f}")

    if bs:
        print(f"\n  BALANCE SHEET  (page {bs.get('source_page','?')})")
        print(SEP)
        rows = [
            ("Total Assets",             bs.get("total_assets")),
            ("  Non-current Assets",     bs.get("total_non_current")),
            ("  Current Assets",         bs.get("total_current_assets")),
            ("  Cash & Equivalents",     bs.get("cash_equivalents")),
            ("Total Equity (Net Worth)", bs.get("total_equity")),
            ("Borrowings (Debt)",        bs.get("total_borrowings")),
            ("Trade Payables",           bs.get("trade_payables")),
        ]
        for label, val in rows:
            if val is not None:
                print(f"  {label:<36} Cr {val:>9,.2f}")

    if cf:
        print(f"\n  CASH FLOW  (page {cf.get('source_page','?')})")
        print(SEP)
        rows = [
            ("Operating Cash Flow",   cf.get("operating_cashflow")),
            ("Investing Cash Flow",   cf.get("investing_cashflow")),
            ("Financing Cash Flow",   cf.get("financing_cashflow")),
            ("Capex",                 cf.get("capex")),
            ("Dividend Paid",         cf.get("dividend_paid")),
        ]
        for label, val in rows:
            if val is not None:
                print(f"  {label:<36} Cr {val:>9,.2f}")

    if ratios:
        print(f"\n  COMPUTED RATIOS")
        print(SEP)
        rows = [
            ("EBITDA",               ratios.get("ebitda_cr"),           "Cr"),
            ("OPM %",                ratios.get("opm_percent"),         "% "),
            ("PAT Margin %",         ratios.get("pat_margin_pct"),      "% "),
            ("ROE %",                ratios.get("roe_pct"),             "% "),
            ("Debt to Equity",       ratios.get("debt_to_equity"),      "x "),
            ("Asset Turnover",       ratios.get("asset_turnover"),      "x "),
            ("Cash Conversion %",    ratios.get("cash_conversion_pct"), "% "),
        ]
        for label, val, unit in rows:
            if val is not None:
                print(f"  {label:<36} {unit} {val:>9,.2f}")

    yes = sum(1 for v in fchecks.values() if "Yes" in v)
    no  = sum(1 for v in fchecks.values() if "No"  in v)
    print(f"\n  PIOTROSKI F-SCORE:  {fscore}/9  "
          f"({yes} Yes · {no} No)")
    print(SEP)
    for check, result in fchecks.items():
        print(f"  {result}  {check}")

    if trends:
        print(f"\n  MULTI-YEAR TRENDS  (auto-detected numbers)")
        print(SEP)
        for key, vals in list(trends.items())[:5]:
            clean = [v for v in vals if v is not None]
            print(f"  {key:<30} {clean}")

    print(f"\n{'═'*W}\n")


# ─────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Extract financial data from Indian company Annual Report PDF"
    )
    parser.add_argument("--pdf",     required=True,              help="Path to Annual Report PDF")
    parser.add_argument("--company", default="Company",          help="Company name (for display)")
    parser.add_argument("--output",  default="output_data.json", help="Output JSON file path")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"ERROR: File not found — {pdf_path}")
        sys.exit(1)

    print(f"\n{'─'*50}")
    print(f"  Annual Report Extractor")
    print(f"  PDF    : {pdf_path.name}")
    print(f"  Company: {args.company}")
    print(f"{'─'*50}")

    with pdfplumber.open(pdf_path) as pdf:
        print(f"  Pages  : {len(pdf.pages)}")
        pnl    = extract_pnl(pdf)
        bs     = extract_balance_sheet(pdf)
        cf     = extract_cashflow(pdf)
        trends = extract_multiyear_trends(pdf)

    ratios          = compute_ratios(pnl, bs, cf)
    fscore, fchecks = compute_piotroski(pnl, bs, cf)

    print_results(args.company, pnl, bs, cf, ratios, trends, fscore, fchecks)

    output = {
        "company":          args.company,
        "source_pdf":       pdf_path.name,
        "profit_and_loss":  pnl,
        "balance_sheet":    bs,
        "cash_flow":        cf,
        "ratios":           ratios,
        "piotroski_score":  fscore,
        "piotroski_checks": fchecks,
        "multiyear_trends": trends,
    }
    out_path = Path(args.output)
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"  Saved to: {out_path}\n")


if __name__ == "__main__":
    main()
