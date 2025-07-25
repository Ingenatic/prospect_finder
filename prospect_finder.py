# prospect_finder.py – Streamlit app to find & save senior IT / Security prospects (Apollo API)
# -----------------------------------------------------------------------------
# Written in UK English.
#
# Version 3.0 – multiple accounts + CSV upload + saved‑prospects panel
# ---------------------------------------------------------------
# * **Accounts input:** free‑text box (comma/line‑separated) *plus* optional CSV
#   upload (first column = account names). You can search many companies across
#   many geographies in one click.
# * **Save** button under each prospect stores their name & LinkedIn link in
#   `st.session_state.saved`. A sidebar panel lists saved prospects with links.
# * Existing features retained: seniority filter, include‑prospected toggle,
#   contact reveal, geography multiselect.
# * Uses only built‑in `csv` module – no extra dependencies beyond
#   `streamlit` and `requests`.
# -----------------------------------------------------------------------------
from __future__ import annotations

import csv
import io
import os
import re
from typing import List, Dict, Tuple, Optional, Set

import requests
import streamlit as st

st.set_page_config(page_title="Prospect Finder", page_icon="🔍")

# ───────────────────────── Constants ─────────────────────────────────────────
GEOGRAPHIES = [
    "Netherlands", "Sweden", "Finland", "Norway", "Denmark", "Estonia",
]

ROLE_TYPES: dict[str, list[str]] = {
    "ExP": [
        "CIO", "Chief Information Officer", "Information Technology", "IT Director", "IT",
        "Enterprise", "CTIO", "Digital", "Transformation",
        "ICT",
    ],
    "Security": [
        "Security", "CISO", "Cyber", "Risk",
    ],
    "EA": [
        "Architect", "Enterprise Architect", "Architecture",
    ],
    "Procurement": [
        "IT Procurement", "IT Sourcing", "IT Category Management", 
        "Technology Procurement", "IT Portfolio", "IT Strategy",
    ],
}

ROLE_PATTERNS = {k: re.compile("(" + "|".join(map(re.escape, v)) + ")", re.I) for k, v in ROLE_TYPES.items()}

SENIORITY_LEVELS = ["owner", "founder", "c_suite", "partner", "vp", "head", "director", "manager"]

API_BASE = "https://api.apollo.io/api/v1"
SEARCH_ENDPOINT = f"{API_BASE}/mixed_people/search"
ENRICH_ENDPOINT = f"{API_BASE}/people/match"

# ───────────────────────── Apollo helpers ────────────────────────────────────

def _key() -> Optional[str]:
    return os.getenv("APOLLO_API_KEY") or st.secrets.get("APOLLO_API_KEY", None)


def _people_search(params: dict) -> list[dict]:
    k = _key()
    if not k:
        st.error("Apollo API key missing."); return []
    try:
        r = requests.post(SEARCH_ENDPOINT, headers={"x-api-key": k}, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        return data.get("people", []) if isinstance(data, dict) else []
    except requests.RequestException as e:
        st.error(e); return []


def _people_enrich(pid: str) -> dict | None:
    k = _key();
    if not k: return None
    try:
        r = requests.post(ENRICH_ENDPOINT, headers={"x-api-key": k}, json={"id": pid, "reveal_personal_emails": "true", "reveal_phone_number": "true"}, timeout=30)
        r.raise_for_status(); return r.json()
    except requests.RequestException: return None

# ───────────────────────── Search wrappers ───────────────────────────────────

def search_one(account: str, geo: str, role: str, seniorities: list[str], prospected: bool) -> list[dict]:
    params = {
        "page": 1,
        "per_page": 25,
        "q_organization_name": account,
        "person_locations[]": [geo],
        "person_titles[]": ROLE_TYPES[role],
    }
    if seniorities: params["person_seniorities[]"] = seniorities
    if prospected: params["prospected"] = "true"
    return _people_search(params)

# ───────────────────────── Cached contact fetch ─────────────────────────────

@st.cache_data(show_spinner=False)
def get_contact(pid: str) -> Tuple[Optional[str], Optional[str]]:
    d = _people_enrich(pid)
    if not d: return None, None
    email = next((e["value"] for e in d.get("emails", []) if e.get("status") == "verified"), None)
    phone = next((p.get("phone_number") for p in d.get("direct_dials", [])), None) or next((p.get("phone_number") for p in d.get("mobile_phone_numbers", [])), None)
    return email, phone

# ───────────────────────── Session state ------------------------------------

def _init_state():
    st.session_state.setdefault("prospects", {})   # id → prospect dict
    st.session_state.setdefault("contacts", {})    # id → (email, phone)
    st.session_state.setdefault("saved", {})       # id → saved dict


def _rerun():
    if hasattr(st, "experimental_rerun"): st.experimental_rerun()

# ───────────────────────── UI ------------------------------------------------

def main():
    _init_state()

    st.title("🔍 Prospect Finder (Apollo)")

    with st.expander("Accounts", expanded=True):
        txt = st.text_area("Account names (comma or newline)")
        up = st.file_uploader("or CSV upload", type="csv")

    with st.form("controls"):
        geos = st.multiselect("Geographies", GEOGRAPHIES, default=GEOGRAPHIES)
        role = st.selectbox("Role", list(ROLE_TYPES.keys()))
        mgmt = st.checkbox("Management and above", True)
        incp = st.checkbox("Include previously prospected")
        go = st.form_submit_button("Search")

    # Parse account list
    accts: Set[str] = {a.strip() for a in re.split(r"[\n,]", txt) if a.strip()}
    if up is not None:
        reader = csv.reader(io.StringIO(up.read().decode("utf-8")))
        for row in reader:
            if row and row[0].strip(): accts.add(row[0].strip())

    if go:
        if not accts:
            st.error("Provide at least one account name.")
        elif not geos:
            st.error("Select at least one geography.")
        else:
            st.session_state.prospects.clear(); st.session_state.contacts.clear()
            seniorities = SENIORITY_LEVELS if mgmt else []
            with st.spinner("Searching Apollo …"):
                for acc in accts:
                    for g in geos:
                        for p in search_one(acc, g, role, seniorities, False):
                            st.session_state.prospects[p["id"]] = p
                        if incp:
                            for p in search_one(acc, g, role, seniorities, True):
                                st.session_state.prospects[p["id"]] = p
            st.success(f"Found {len(st.session_state.prospects)} unique prospects.")
            _rerun()

    # ── Results
    for p in st.session_state.prospects.values():
        name   = p.get("name", "[No name]")
        title  = p.get("title", "")
        loc    = p.get("location", "—")
        comp   = p.get("company") or p.get("organization", {}).get("name", "—")
        url    = p.get("linkedin_url", "")
        st.markdown("\n".join([
            f"**{name}** – {title}",
            f"📌 {loc} | 🏢 {comp}",
            f"[LinkedIn profile]({url})" if url else "[No LinkedIn URL]",
        ]))

        c1, c2, _ = st.columns(3)
        with c1:
            if p["id"] in st.session_state.contacts:
                email, phone = st.session_state.contacts[p["id"]]
                st.markdown(f"📧 {email or '—'} | 📞 {phone or '—'}")
            else:
                if st.button("Reveal contact", key=f"reveal_{p['id']}"):
                    with st.spinner("Fetching …"):
                        email, phone = get_contact(p["id"])
                    st.session_state.contacts[p["id"]] = (email, phone)
                    _rerun()
        with c2:
            if p["id"] in st.session_state.saved:
                st.markdown("✅ Saved")
            else:
                if st.button("Save", key=f"save_{p['id']}"):
                    st.session_state.saved[p["id"]] = {
                        "name": name,
                        "title": title,
                        "company": comp,
                        "url": url,
                    }
                    _rerun()
        st.markdown("---")

    # ── Saved sidebar
    with st.sidebar.expander("⭐️ Saved prospects", True):
        if st.session_state.saved:
            # List in sidebar
            for s in st.session_state.saved.values():
                bullet = f"• **{s['name']}** – {s['title']} | 🏢 {s['company']}"
                bullet += f" ([LinkedIn]({s['url']}))" if s['url'] else ""
                st.markdown(bullet)

            # CSV export button
            csv_buf = io.StringIO()
            writer = csv.writer(csv_buf)
            writer.writerow(["Name", "Title", "Company", "LinkedIn URL"])
            for s in st.session_state.saved.values():
                writer.writerow([s['name'], s['title'], s['company'], s['url']])
            st.download_button(
                label="⬇️ Download CSV",
                data=csv_buf.getvalue(),
                file_name="saved_prospects.csv",
                mime="text/csv",
            )
        else:
            st.write("None yet.")


if __name__ == "__main__":
    main()
