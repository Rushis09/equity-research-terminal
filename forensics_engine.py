"""
Enhanced Forensics Engine
==========================
Checks data from 3 sources automatically:
  1. Screener.in data (already scraped - ratios, shareholding, financials)
  2. Annual Report PDF (uploaded - auditor report, RPT, contingent liabilities)
  3. Direct links to NSE/BSE for items needing manual verification

Usage:  from forensics_engine import run_full_forensics, scan_ar_pdf
"""

import re

# ─────────────────────────────────────────────────────────────────────
# PDF SCANNER — reads AR and extracts forensic signals
# ─────────────────────────────────────────────────────────────────────

def scan_ar_pdf(pdf_bytes) -> dict:
    """
    Scan Annual Report PDF for forensic red flags.
    Returns dict of findings keyed by category.
    """
    try:
        import pdfplumber, io
        pdf_file = io.BytesIO(pdf_bytes)
    except ImportError:
        return {"error": "pip install pdfplumber"}

    findings = {
        "auditor":          [],
        "related_party":    [],
        "contingent_liab":  [],
        "going_concern":    [],
        "caro":             [],
        "promoter_loans":   [],
        "management_risk":  [],
        "raw_extracts":     {}
    }

    # Keywords to search per category
    audit_red = [
        "qualified opinion", "adverse opinion", "disclaimer of opinion",
        "emphasis of matter", "material uncertainty", "except for",
        "subject to", "qualified report"
    ]
    audit_good = [
        "unqualified opinion", "clean opinion", "true and fair view",
        "unmodified opinion", "fairly present"
    ]
    rpt_bad = [
        "loans to directors", "loan to promoter", "loan to related party",
        "advance to director", "unsecured loan to", "interest free loan",
        "loan given to subsidiary", "guarantee on behalf of promoter"
    ]
    contingent_keywords = [
        "contingent liabilities", "contingent liability",
        "disputed tax", "pending litigation", "show cause notice",
        "demand notice", "arbitration", "sub judice"
    ]
    going_concern_keywords = [
        "going concern", "ability to continue", "material uncertainty",
        "substantial doubt", "ceasing operations"
    ]
    promoter_loan_keywords = [
        "pledged", "pledge", "encumbered", "lien on shares",
        "margin pledge", "promoter loan"
    ]

    with pdfplumber.open(pdf_file) as pdf:
        total = len(pdf.pages)
        # Scan full PDF in chunks
        for page_num, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            text_lower = text.lower()

            # ── Auditor's Report (usually pages 250-350) ──
            if any(k in text_lower for k in ["auditor", "audit report", "independent auditor"]):
                for kw in audit_red:
                    if kw in text_lower:
                        snippet = _extract_snippet(text, kw, 200)
                        findings["auditor"].append({
                            "type": "RED_FLAG",
                            "keyword": kw,
                            "page": page_num + 1,
                            "snippet": snippet
                        })
                for kw in audit_good:
                    if kw in text_lower:
                        findings["auditor"].append({
                            "type": "CLEAN",
                            "keyword": kw,
                            "page": page_num + 1,
                            "snippet": _extract_snippet(text, kw, 150)
                        })

            # ── Related Party Transactions ──
            if "related part" in text_lower:
                for kw in rpt_bad:
                    if kw in text_lower:
                        snippet = _extract_snippet(text, kw, 250)
                        findings["related_party"].append({
                            "type": "ALERT",
                            "keyword": kw,
                            "page": page_num + 1,
                            "snippet": snippet
                        })
                # Extract RPT amounts
                rpt_amounts = re.findall(
                    r'(?:loan|advance|transaction)[^\n]{0,50}?'
                    r'(?:₹|Rs\.?|INR)?\s*(\d[\d,]*(?:\.\d+)?)\s*(?:Cr|crore|lakh)?',
                    text, re.IGNORECASE
                )
                if rpt_amounts:
                    findings["related_party"].append({
                        "type": "AMOUNT",
                        "keyword": "RPT amounts found",
                        "page": page_num + 1,
                        "snippet": f"Amounts on this page: {rpt_amounts[:5]}"
                    })

            # ── Contingent Liabilities ──
            if "contingent" in text_lower:
                for kw in contingent_keywords:
                    if kw in text_lower:
                        snippet = _extract_snippet(text, kw, 300)
                        # Try to find amounts near keyword
                        amounts = re.findall(
                            r'(\d[\d,]*(?:\.\d+)?)\s*(?:Cr|crore|lakh)',
                            snippet, re.IGNORECASE
                        )
                        findings["contingent_liab"].append({
                            "type": "FOUND",
                            "keyword": kw,
                            "page": page_num + 1,
                            "snippet": snippet[:200],
                            "amounts": amounts[:3]
                        })
                        break  # One entry per page

            # ── Going Concern ──
            for kw in going_concern_keywords:
                if kw in text_lower:
                    findings["going_concern"].append({
                        "type": "ALERT",
                        "keyword": kw,
                        "page": page_num + 1,
                        "snippet": _extract_snippet(text, kw, 200)
                    })

            # ── CARO Remarks ──
            if "caro" in text_lower or "companies auditor" in text_lower:
                if any(k in text_lower for k in
                       ["fraud", "default", "not paid", "overdue", "deposited late"]):
                    findings["caro"].append({
                        "type": "FLAG",
                        "page": page_num + 1,
                        "snippet": _extract_snippet(text, "caro", 300)
                    })

            # ── Promoter Pledge / Loans ──
            for kw in promoter_loan_keywords:
                if kw in text_lower:
                    pledge_pct = re.findall(r'(\d+(?:\.\d+)?)\s*%', text)
                    findings["promoter_loans"].append({
                        "type": "FOUND",
                        "keyword": kw,
                        "page": page_num + 1,
                        "snippet": _extract_snippet(text, kw, 200),
                        "percentages": pledge_pct[:5]
                    })

    # Deduplicate
    for key in findings:
        if isinstance(findings[key], list) and len(findings[key]) > 10:
            findings[key] = findings[key][:10]

    return findings


def _extract_snippet(text, keyword, chars=200):
    """Extract text around a keyword."""
    idx = text.lower().find(keyword.lower())
    if idx == -1:
        return ""
    start = max(0, idx - 50)
    end   = min(len(text), idx + chars)
    return "..." + text[start:end].strip() + "..."


# ─────────────────────────────────────────────────────────────────────
# SCREENER DATA FORENSICS — uses already-scraped data
# ─────────────────────────────────────────────────────────────────────

def build_series(rows, label, yr_cols):
    for row in rows:
        first = list(row.values())[0] if row else ""
        if label.lower() in first.lower():
            return {col: _clean(row.get(col)) for col in yr_cols if col in row}
    return {}

def _clean(s):
    if not s or s in ["-","","—","NA","N/A"]: return None
    try: return float(str(s).strip().replace(",","").replace("%","").replace("₹",""))
    except: return None

def run_full_forensics(screener_data, pdf_findings=None, ticker=""):
    """
    Full 14-point forensic check combining Screener data + AR PDF findings.
    Returns list of check dicts with auto-populated results where possible.
    """
    checks = []
    pnl_rows = screener_data.get("pnl_rows", [])
    bs_rows  = screener_data.get("bs_rows",  [])
    cf_rows  = screener_data.get("cf_rows",  [])
    sh_rows  = screener_data.get("sh_rows",  [])
    pnl_cols = screener_data.get("pnl_cols", [])[1:]
    yr_cols  = [c for c in pnl_cols if c and c != "TTM"]

    # Links for manual verification
    nse_url       = f"https://www.nseindia.com/get-quotes/equity?symbol={ticker}"
    bse_filings   = f"https://www.bseindia.com/stock-share-price/a/a/a/"
    screener_url  = f"https://www.screener.in/company/{ticker}/"
    tijori_url    = f"https://www.tijorifinance.com/company/{ticker.lower()}/"

    def add(cat, check, result, detail="", source="screener", link=""):
        checks.append({
            "category": cat, "check": check, "result": result,
            "detail": detail, "source": source, "link": link
        })

    if not yr_cols:
        add("Data", "No Screener data loaded", "na",
            "Type NSE ticker and click Fetch 10-Year Data", "manual")
        return checks

    recent_yrs = yr_cols[-5:]

    def get(rows, label):
        return build_series(rows, label, recent_yrs)

    sales    = get(pnl_rows, "Sales")
    net_p    = get(pnl_rows, "Net Profit")
    opm      = get(pnl_rows, "OPM %")
    other_i  = get(pnl_rows, "Other Income")
    dep      = get(pnl_rows, "Depreciation")
    interest = get(pnl_rows, "Interest")
    pbt      = get(pnl_rows, "Profit before tax")
    debtors  = get(bs_rows,  "Debtors")
    inventory= get(bs_rows,  "Inventory")
    borrow   = get(bs_rows,  "Borrowings")
    equity_c = get(bs_rows,  "Equity Capital")
    reserves = get(bs_rows,  "Reserves")
    cfo      = get(cf_rows,  "Cash from Operating Activity")
    capex    = get(cf_rows,  "Capital Expenditure")
    ta       = get(bs_rows,  "Total Assets")

    sales_v  = [v for v in sales.values()  if v is not None]
    net_v    = [v for v in net_p.values()  if v is not None]
    opm_v    = [v for v in opm.values()    if v is not None]
    cfo_v    = [v for v in cfo.values()    if v is not None]
    borrow_v = [v for v in borrow.values() if v is not None]
    deb_v    = [v for v in debtors.values()if v is not None]

    # ═══ 1. RED FLAG ANALYSIS ════════════════════════════════════════
    cat = "1. Red Flag Analysis"

    if len(sales_v) >= 3:
        g_recent = (sales_v[-1]-sales_v[-2])/abs(sales_v[-2])*100 if sales_v[-2] else 0
        g_prev   = (sales_v[-2]-sales_v[-3])/abs(sales_v[-3])*100 if sales_v[-3] else 0
        add(cat, "Revenue growth vs prior year",
            "warn" if g_recent < g_prev * 0.5 else "yes",
            f"Latest: {g_recent:.1f}%  |  Prior year: {g_prev:.1f}%",
            "screener")

    if net_v and sales_v and len(net_v) >= 2:
        s_g = (sales_v[-1]-sales_v[-2])/abs(sales_v[-2]) if sales_v[-2] else 0
        p_g = (net_v[-1]-net_v[-2])/abs(net_v[-2]) if net_v[-2] else 0
        add(cat, "Profit growth in line with sales",
            "warn" if (p_g > s_g*3 and s_g < 0.05) else "yes",
            f"Sales growth {s_g*100:.1f}%  |  PAT growth {p_g*100:.1f}%",
            "screener")

    if len(opm_v) >= 3:
        std = _std(opm_v)
        add(cat, "OPM stable (< 5% std dev)",
            "warn" if std > 5 else "yes",
            f"OPM: {opm_v[0]:.1f}% → {opm_v[-1]:.1f}%  |  Std dev: {std:.1f}%",
            "screener")

    if cfo_v and net_v:
        mismatch = sum(1 for c,n in zip(cfo_v, net_v) if n and n > 0 and c < n*0.5)
        add(cat, f"CFO ≥ 50% of Net Profit ({len(cfo_v)-mismatch}/{len(cfo_v)} years)",
            "no" if mismatch > 1 else "yes",
            "Persistent CFO < PAT = earnings may be non-cash / manipulated",
            "screener")

    # ═══ 2. MANAGEMENT ACTIONS ═══════════════════════════════════════
    cat = "2. Management Actions"

    if len(borrow_v) >= 2:
        d_change = (borrow_v[-1]-borrow_v[0])/abs(borrow_v[0])*100 if borrow_v[0] else 0
        add(cat, "Debt not rising excessively (< 50% over 5yr)",
            "warn" if d_change > 50 else "yes",
            f"Borrowings changed {d_change:+.1f}% over period  |  "
            f"Latest: ₹{borrow_v[-1]:,.0f} Cr",
            "screener")

    capex_v = [abs(v) for v in capex.values() if v is not None]
    if capex_v and sales_v:
        cpx_pct = sum(capex_v[-3:])/sum(sales_v[-3:])*100 if sum(sales_v[-3:]) else 0
        add(cat, "Investing in growth (Capex/Sales > 3%)",
            "warn" if cpx_pct < 3 else "yes",
            f"3yr avg Capex/Sales: {cpx_pct:.1f}%",
            "screener")

    int_last = list(interest.values())[-1] if interest else None
    pbt_last = list(pbt.values())[-1] if pbt else None
    if int_last and pbt_last and int_last > 0:
        cov = (pbt_last + int_last) / int_last
        add(cat, "Interest coverage > 3x",
            "yes" if cov >= 3 else "no",
            f"Coverage ratio: {cov:.1f}x",
            "screener")
    elif int_last == 0 or int_last is None:
        add(cat, "Interest coverage > 3x", "yes",
            "Minimal/no debt — not applicable", "screener")

    # ═══ 3. RELATED PARTY TRANSACTIONS ═══════════════════════════════
    cat = "3. Related Party Transactions"

    # Check from PDF
    if pdf_findings and pdf_findings.get("related_party"):
        rpt = pdf_findings["related_party"]
        alerts = [r for r in rpt if r["type"] == "ALERT"]
        if alerts:
            for a in alerts[:3]:
                add(cat, f"⚠ RPT alert: '{a['keyword']}'",
                    "warn",
                    f"Page {a['page']}: {a['snippet'][:120]}",
                    "pdf")
        else:
            add(cat, "No suspicious RPT keywords in AR", "yes",
                "No loans-to-directors or promoter-loan keywords found", "pdf")
    else:
        add(cat, "Related Party Transactions — check AR",
            "na",
            "Upload Annual Report PDF for auto-check  |  "
            f"Or check manually on Screener: {screener_url}annual-report/",
            "manual", screener_url)

    oi_v = [v for v in other_i.values() if v is not None]
    if oi_v and sales_v:
        oi_pct = sum(oi_v[-3:])/sum(sales_v[-3:])*100 if sum(sales_v[-3:]) else 0
        add(cat, "Other income < 15% of sales",
            "warn" if oi_pct > 15 else "yes",
            f"Avg other income/sales (3yr): {oi_pct:.1f}%",
            "screener")

    # ═══ 4. MANIPULATION IN REVENUE ══════════════════════════════════
    cat = "4. Manipulation in Revenue"

    if len(deb_v) >= 2 and len(sales_v) >= 2:
        d_g = (deb_v[-1]-deb_v[0])/abs(deb_v[0]) if deb_v[0] else 0
        s_g = (sales_v[-1]-sales_v[0])/abs(sales_v[0]) if sales_v[0] else 0
        add(cat, "Debtors not growing faster than sales",
            "warn" if d_g > s_g*1.5 and d_g > 0.3 else "yes",
            f"Debtor growth: {d_g*100:.0f}%  |  Sales growth: {s_g*100:.0f}%",
            "screener")

    if deb_v and sales_v:
        dd = deb_v[-1]/(sales_v[-1]/365) if sales_v[-1] else 0
        add(cat, "Debtor days < 90",
            "warn" if dd > 90 else "yes",
            f"Current debtor days: {dd:.0f}",
            "screener")

    if cfo_v and sales_v:
        cfo_s = cfo_v[-1]/sales_v[-1]*100 if sales_v[-1] else 0
        add(cat, "CFO/Sales > 10% (cash confirms revenue)",
            "no" if cfo_s < 5 else "warn" if cfo_s < 10 else "yes",
            f"CFO/Sales: {cfo_s:.1f}%",
            "screener")

    # ═══ 5. MANIPULATION IN DEPRECIATION ═════════════════════════════
    cat = "5. Manipulation in Depreciation"
    dep_v = [v for v in dep.values() if v is not None]
    if len(dep_v) >= 2 and len(sales_v) >= 2:
        dep_g = (dep_v[-1]-dep_v[0])/abs(dep_v[0]) if dep_v[0] else 0
        sal_g = (sales_v[-1]-sales_v[0])/abs(sales_v[0]) if sales_v[0] else 0
        add(cat, "Depreciation growing with assets",
            "warn" if dep_g < -0.1 and sal_g > 0.2 else "yes",
            f"Depreciation: ₹{dep_v[0]:,.0f}→₹{dep_v[-1]:,.0f} Cr  |  "
            f"Sales grew {sal_g*100:.0f}%",
            "screener")

    if pdf_findings:
        add(cat, "Check useful life changes in AR accounting policies",
            "na",
            "Uploaded AR scanned — search for 'useful life', 'change in accounting policy'",
            "pdf")
    else:
        add(cat, "Check useful life changes in AR accounting policies",
            "na",
            "Upload AR PDF for auto-check  |  "
            "Manually check Note on Property/Depreciation",
            "manual")

    # ═══ 6. MANIPULATION OF EARNINGS ═════════════════════════════════
    cat = "6. Manipulation of Earnings"

    if deb_v and sales_v and len(deb_v) >= 2:
        dsri = (deb_v[-1]/sales_v[-1])/(deb_v[0]/sales_v[0]) \
               if sales_v[-1] and sales_v[0] and deb_v[0] else 1
        add(cat, "DSRI (receivables/sales ratio) stable (< 1.3)",
            "warn" if dsri > 1.3 else "yes",
            f"DSRI proxy: {dsri:.2f}  (>1.3 = Beneish M-Score flag)",
            "screener")

    if oi_v and opm_v and sales_v:
        op_profit = opm_v[-1]/100 * sales_v[-1] if opm_v and sales_v else 0
        oi_last   = oi_v[-1] if oi_v else 0
        add(cat, "Core operating profit > other income",
            "warn" if op_profit < oi_last else "yes",
            f"Op Profit: ₹{op_profit:,.0f} Cr  |  Other Income: ₹{oi_last:,.0f} Cr",
            "screener")

    # ═══ 7. CASH FLOW MANIPULATIONS ══════════════════════════════════
    cat = "7. Cash Flow Manipulations"

    pos = sum(1 for v in cfo_v if v and v > 0)
    add(cat, f"OCF positive ({pos}/{len(cfo_v)} years)",
        "no" if pos < len(cfo_v)*0.7 else "yes",
        "Negative OCF = company burning cash, not generating it",
        "screener")

    mis = sum(1 for c,n in zip(cfo_v, net_v)
              if c is not None and n and n>0 and c < n*0.5)
    add(cat, "OCF/PAT > 0.5 consistently",
        "warn" if mis > 0 else "yes",
        f"Years where OCF < 50% of PAT: {mis} / {min(len(cfo_v),len(net_v))}",
        "screener")

    # ═══ 8. DEBTORS ══════════════════════════════════════════════════
    cat = "8. Debtors"
    if deb_v and sales_v:
        dd_all = [d/(s/365) for d,s in zip(deb_v, sales_v) if d and s]
        if dd_all:
            trend = "✓ improving" if dd_all[-1] < dd_all[0] else "⚠ worsening"
            add(cat, f"Debtor days trend ({trend})",
                "yes" if dd_all[-1] < 90 else "warn",
                f"Debtor days: {dd_all[0]:.0f} → {dd_all[-1]:.0f}  |  Avg: {sum(dd_all)/len(dd_all):.0f}",
                "screener")

    # ═══ 9. INVENTORY ════════════════════════════════════════════════
    cat = "9. Inventory"
    inv_v = [v for v in inventory.values() if v is not None]
    if inv_v and sales_v:
        id_all = [i/(s/365) for i,s in zip(inv_v, sales_v) if i and s]
        if id_all:
            trend = "✓ improving" if id_all[-1] < id_all[0] else "⚠ worsening"
            add(cat, f"Inventory days trend ({trend})",
                "yes" if id_all[-1] < 120 else "warn",
                f"Inventory days: {id_all[0]:.0f} → {id_all[-1]:.0f}",
                "screener")

    # ═══ 10. PAYABLES ════════════════════════════════════════════════
    cat = "10. Payables"
    # Get payables from BS
    payables_s = build_series(bs_rows, "Trade Payables", recent_yrs)
    pay_v = [v for v in payables_s.values() if v is not None]
    if pay_v and sales_v:
        pd_all = [p/(s/365) for p,s in zip(pay_v, sales_v) if p and s]
        if pd_all:
            add(cat, f"Payable days stable ({pd_all[0]:.0f}→{pd_all[-1]:.0f} days)",
                "warn" if pd_all[-1] > pd_all[0]*1.5 else "yes",
                f"Rising payables days = may be delaying supplier payments (cash stress)",
                "screener")
    else:
        add(cat, "Check payable days (manual)",
            "na",
            f"View on Screener: {screener_url}",
            "manual", screener_url)

    # ═══ 11. LIABILITIES ═════════════════════════════════════════════
    cat = "11. Liabilities"

    eq_v = [(equity_c.get(yr) or 0) + (reserves.get(yr) or 0) for yr in recent_yrs]
    eq_v = [v for v in eq_v if v]
    if borrow_v and eq_v:
        de_now  = borrow_v[-1]/eq_v[-1] if eq_v[-1] else 0
        de_old  = borrow_v[0]/eq_v[0]   if eq_v[0]  else 0
        add(cat, "D/E ratio improving or stable",
            "warn" if de_now > de_old * 1.3 else "yes",
            f"D/E: {de_old:.2f} → {de_now:.2f}",
            "screener")

    # Contingent liabilities from PDF
    if pdf_findings and pdf_findings.get("contingent_liab"):
        cl = pdf_findings["contingent_liab"]
        total_str = ""
        all_amounts = []
        for c in cl:
            all_amounts.extend(c.get("amounts", []))
        if all_amounts:
            add(cat, f"Contingent liabilities found in AR ({len(cl)} pages)",
                "warn",
                f"Amounts mentioned: {all_amounts[:5]} Cr  |  "
                "Verify significance vs net profit",
                "pdf")
        else:
            add(cat, "Contingent liabilities mentioned in AR",
                "warn",
                f"Found on {len(cl)} pages — review manually",
                "pdf")
    else:
        add(cat, "Contingent liabilities — check AR Note",
            "na",
            "Upload AR PDF for auto-extract  |  "
            "Manually check Notes to Accounts",
            "manual")

    # ═══ 12. ASSETS ══════════════════════════════════════════════════
    cat = "12. Assets"
    ta_v = [v for v in ta.values() if v is not None]
    if ta_v and sales_v:
        at_now  = sales_v[-1]/ta_v[-1] if ta_v[-1] else 0
        at_old  = sales_v[0]/ta_v[0]   if ta_v[0]  else 0
        add(cat, "Asset turnover not deteriorating",
            "warn" if at_now < at_old * 0.7 else "yes",
            f"Asset turnover: {at_old:.2f}x → {at_now:.2f}x",
            "screener")

    capex_vs_dep = None
    if capex_v and dep_v:
        ratio = sum(capex_v[-3:]) / sum(dep_v[-3:]) if sum(dep_v[-3:]) else 0
        capex_vs_dep = ratio
        add(cat, "Capex > Depreciation (actively reinvesting)",
            "warn" if ratio < 1 else "yes",
            f"3yr Capex/Depreciation: {ratio:.2f}x  (>1 = growing, <1 = shrinking asset base)",
            "screener")

    # ═══ 13. OPERATIONAL ISSUES ══════════════════════════════════════
    cat = "13. Operational Issues"

    if len(opm_v) >= 3:
        add(cat, "Operating margins not under structural decline",
            "warn" if opm_v[-1] < opm_v[0]*0.8 else "yes",
            f"OPM: {opm_v[0]:.1f}% → {opm_v[-1]:.1f}%",
            "screener")

    if len(sales_v) >= 2:
        rev_g = (sales_v[-1]-sales_v[-2])/abs(sales_v[-2])*100 if sales_v[-2] else 0
        add(cat, "Revenue growing > 5%",
            "warn" if rev_g < 5 else "yes",
            f"Latest revenue growth: {rev_g:.1f}%",
            "screener")

    # ═══ 14. CORPORATE GOVERNANCE ════════════════════════════════════
    cat = "14. Corporate Governance"

    # Promoter holding from Screener shareholding
    sh_yr_cols = [c for c in screener_data.get("sh_cols", [])[1:] if c]
    if sh_rows and sh_yr_cols:
        prom_s = build_series(sh_rows, "Promoters", sh_yr_cols[-6:])
        prom_v = [v for v in prom_s.values() if v is not None]
        if prom_v:
            trend = "⬆ increasing" if prom_v[-1] > prom_v[0] else "⬇ decreasing"
            add(cat, f"Promoter holding stable/increasing ({trend})",
                "yes" if prom_v[-1] >= prom_v[0] - 2 else "warn",
                f"Promoter %: {prom_v[0]:.1f}% → {prom_v[-1]:.1f}%  |  "
                f"Change: {prom_v[-1]-prom_v[0]:+.1f}%",
                "screener", screener_url)

        # Pledge check from Screener
        pledge_s = build_series(sh_rows, "Pledge", sh_yr_cols[-4:])
        pledge_v = [v for v in pledge_s.values() if v is not None]
        if pledge_v:
            add(cat, "Promoter pledge low (< 10%)",
                "no" if pledge_v[-1] > 20 else "warn" if pledge_v[-1] > 5 else "yes",
                f"Pledge: {pledge_v[-1]:.1f}%  |  Trend: {pledge_v[0]:.1f}→{pledge_v[-1]:.1f}%",
                "screener", screener_url)
        else:
            add(cat, "Promoter pledge (check Screener)",
                "na",
                f"View shareholding: {screener_url}",
                "manual", screener_url)
    else:
        add(cat, "Promoter holding trend",
            "na",
            f"View at: {screener_url}",
            "manual", screener_url)

    # Auditor qualifications from PDF
    if pdf_findings and pdf_findings.get("auditor"):
        aud = pdf_findings["auditor"]
        red = [a for a in aud if a["type"] == "RED_FLAG"]
        clean = [a for a in aud if a["type"] == "CLEAN"]
        if red:
            for r in red[:2]:
                add(cat, f"⚠ Auditor report: '{r['keyword']}'",
                    "no",
                    f"Page {r['page']}: {r['snippet'][:150]}",
                    "pdf")
        elif clean:
            add(cat, "Auditor gave clean (unqualified) opinion",
                "yes",
                f"Found on page {clean[0]['page']}: {clean[0]['snippet'][:100]}",
                "pdf")
        else:
            add(cat, "Auditor qualifications — review AR",
                "na",
                "AR scanned but auditor section unclear — check manually",
                "pdf")
    else:
        add(cat, "Auditor qualifications — check Annual Report",
            "na",
            "Upload AR PDF for auto-check  |  "
            "Look for 'Independent Auditor's Report' in AR",
            "manual")

    # CARO from PDF
    if pdf_findings and pdf_findings.get("caro"):
        add(cat, "CARO report has red flags",
            "warn",
            f"Found {len(pdf_findings['caro'])} CARO flags in AR — review carefully",
            "pdf")
    else:
        add(cat, "CARO report (Companies Auditor Report Order)",
            "na",
            "Upload AR PDF for auto-check  |  Applicable to companies above threshold",
            "manual")

    # Related party loans from PDF
    if pdf_findings and pdf_findings.get("promoter_loans"):
        pl = pdf_findings["promoter_loans"]
        add(cat, "Promoter pledge / share encumbrance",
            "warn" if pl else "yes",
            f"Found {len(pl)} pledge-related mentions in AR  |  "
            f"Page {pl[0]['page']}: {pl[0]['snippet'][:100]}" if pl else "",
            "pdf")

    # NSE link for corporate announcements
    add(cat, "Corporate announcements (NSE filing)",
        "na",
        f"Check NSE for latest announcements",
        "link",
        f"https://www.nseindia.com/companies-listing/corporate-filings-announcements")

    return checks


def _std(lst):
    if len(lst) < 2: return 0
    mean = sum(lst)/len(lst)
    return (sum((x-mean)**2 for x in lst)/len(lst))**0.5
