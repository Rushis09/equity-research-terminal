"""
Fixed Screener.in scraper — paste this to replace the scrape_screener function in dashboard_v2.py
Or run standalone:  python screener_fix.py SOLARINDS
"""

import sys, json

def scrape_screener(ticker: str, consolidated: bool = True) -> dict:
    try:
        import requests
        from bs4 import BeautifulSoup, NavigableString
    except ImportError:
        return {"error": "Run: pip install requests beautifulsoup4"}

    suffix = "consolidated" if consolidated else "standalone"
    url    = f"https://www.screener.in/company/{ticker.upper()}/{suffix}/"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        r = requests.get(url, headers=headers, timeout=25)
    except Exception as e:
        return {"error": f"Network error: {e}"}

    if r.status_code == 404:
        return {"error": f"'{ticker}' not found. Try standalone: uncheck Consolidated."}
    if r.status_code != 200:
        return {"error": f"Screener.in returned HTTP {r.status_code}"}

    soup = BeautifulSoup(r.text, "html.parser")
    result = {}

    # ── Company name ──────────────────────────────────────────────
    for sel in ["h1.margin-0", "h1", ".company-name"]:
        el = soup.select_one(sel)
        if el:
            result["company_name"] = el.get_text(strip=True)
            break
    else:
        result["company_name"] = ticker

    # ── Market info bar ───────────────────────────────────────────
    info = {}
    for li in soup.select("#top-ratios li"):
        name_el = li.select_one("span.name")
        val_el  = li.select_one("span.number") or li.select_one("span.value")
        if name_el and val_el:
            key = name_el.get_text(strip=True)
            val = val_el.get_text(strip=True)
            info[key] = val
    result["market_info"] = info

    # ── Robust table parser ───────────────────────────────────────
    def get_cell_text(td):
        """
        Extract clean text from a <td> or <th>.
        Screener uses <button class='add-ratio'> inside cells —
        we strip those and any icon spans.
        """
        # Remove button elements (the + expand icons)
        for tag in td.find_all(["button", "span", "a"]):
            # Keep text-only spans, remove icon/button elements
            if tag.name in ["button"]:
                tag.decompose()
            elif tag.get("class") and any(
                c in str(tag.get("class", [])) for c in
                ["icon","add","remove","button","nowrap","text-nowrap"]
            ):
                tag.decompose()
        return td.get_text(separator=" ", strip=True)

    def parse_section(section_id):
        section = soup.find("section", {"id": section_id})
        if not section:
            # fallback: search by data-section attribute
            section = soup.find(attrs={"data-section": section_id})
        if not section:
            return [], []

        table = section.find("table")
        if not table:
            return [], []

        # ── Headers ──
        thead = table.find("thead")
        if thead:
            header_cells = thead.find_all("th")
        else:
            # First <tr> is header
            rows_all = table.find_all("tr")
            header_cells = rows_all[0].find_all(["th","td"]) if rows_all else []

        headers = [get_cell_text(th) for th in header_cells]
        # Clean empty / whitespace headers
        headers = [h if h else f"Col{i}" for i, h in enumerate(headers)]

        # ── Body rows ──
        tbody = table.find("tbody")
        tr_list = tbody.find_all("tr") if tbody else table.find_all("tr")[1:]

        rows_out = []
        for tr in tr_list:
            cells = tr.find_all(["td", "th"])
            if not cells:
                continue

            values = [get_cell_text(c) for c in cells]

            # If row has fewer cells than headers, pad with "—"
            while len(values) < len(headers):
                values.append("—")

            # Skip completely empty rows
            if all(v in ["", "—", " "] for v in values):
                continue

            row_dict = {headers[i]: values[i] for i in range(min(len(headers), len(values)))}
            rows_out.append(row_dict)

        return headers, rows_out

    # ── Parse all sections ────────────────────────────────────────
    sections = {
        "profit-loss":   ("pnl_cols",   "pnl_rows"),
        "balance-sheet": ("bs_cols",    "bs_rows"),
        "cash-flow":     ("cf_cols",    "cf_rows"),
        "ratios":        ("ratio_cols", "ratio_rows"),
        "quarters":      ("q_cols",     "q_rows"),
        "shareholding":  ("sh_cols",    "sh_rows"),
    }

    for sec_id, (col_key, row_key) in sections.items():
        cols, rows = parse_section(sec_id)
        result[col_key] = cols
        result[row_key] = rows

    return result


# ── Standalone test ───────────────────────────────────────────────────
if __name__ == "__main__":
    ticker = sys.argv[1] if len(sys.argv) > 1 else "SOLARINDS"
    consolidated = "--standalone" not in sys.argv

    print(f"\nFetching {ticker} ({'consolidated' if consolidated else 'standalone'})...")
    data = scrape_screener(ticker, consolidated)

    if "error" in data:
        print(f"ERROR: {data['error']}")
        sys.exit(1)

    print(f"Company: {data.get('company_name')}")
    print(f"Market info: {data.get('market_info')}")

    for label, rows_key, cols_key in [
        ("P&L",          "pnl_rows",   "pnl_cols"),
        ("Balance Sheet","bs_rows",    "bs_cols"),
        ("Cash Flow",    "cf_rows",    "cf_cols"),
        ("Ratios",       "ratio_rows", "ratio_cols"),
    ]:
        rows = data.get(rows_key, [])
        cols = data.get(cols_key, [])
        print(f"\n{label}: {len(rows)} rows, {len(cols)} cols")
        if rows:
            print("  First row:", list(rows[0].items())[:5])
            print("  Cols:", cols[:6])

    # Save to JSON for testing
    with open("screener_data.json", "w") as f:
        json.dump(data, f, indent=2)
    print("\nSaved to screener_data.json")
