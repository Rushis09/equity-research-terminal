# Changelog

All notable changes to the Equity Research Terminal project will be documented in this file.

---

# Version 1.0.1

Release Date: July 2026

---

## Fixed

### CS-BUG-001

**Module:** Company Search

Implemented live autocomplete using `st_keyup()`.

Users now receive company suggestions while typing without pressing Enter.

---

## Deployment

Added:

- streamlit-keyup

Updated:

- requirements.txt

Resolved deployment issue on Streamlit Community Cloud.

---

## QA

Smoke Testing : PASS

Retesting : PASS

Regression Testing : PASS

---

## Open Defects

### Company Search

- CS-BUG-002
  Search Everywhere opens incorrect company.

- CS-BUG-003
  Whitespace-only input displays invalid suggestion.

---

### Financial Statements

- FS-BUG-001
  Standalone financial statement not loading.