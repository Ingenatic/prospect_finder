# prospect_finder.py – Streamlit app to find & save senior IT / Security prospects (Apollo API)
# -----------------------------------------------------------------------------
# Written in UK English.
#
# Version 3.0 – multiple accounts + CSV upload + saved‑prospects panel
# ---------------------------------------------------------------
# * **Accounts input:** free‑text box (comma/line‑separated) *plus* optional CSV
#   upload (first column = account names). You can search many companies across
#   many geographies in one click.
# * **Save** button under each prospect stores their name & LinkedIn link in
#   `st.session_state.saved`. A sidebar panel lists saved prospects with links.
# * Existing features retained: seniority filter, include‑prospected toggle,
#   contact reveal, geography multiselect.
# * Uses only built‑in `csv` module – no extra dependencies beyond
#   `streamlit` and `requests`.
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
        "IT Manager", "CTIO", "Digital", "IT Infrastructure Director",
        "Senior IT Director",
    ],
    "Security": [
        "Security", "CISO", "Cyber",
    ],
}

ROLE_PATTERNS = {
    r: re.compile("(" + "|".join(map(re.escape, ts)) + ")", re.I) for r, ts in ROLE_TYPES.items()
}

SENIORITY_LEVELS = [
    "owner", "founder", "c_suite", "partner", "vp", "head", "director", "manager",
]

API_BASE = "https://api.apollo.io/api/v1"
SEARCH_ENDPOINT = f"{API_BASE}/mixed_people/search"
ENRICH_ENDPOINT = f"{API_BASE}/people/match"

# ───────────────────────── Helpers ───────────────────────────────────────────

def _get_api_key() -> Optional[str]:
    return os.getenv("APOLLO_API_KEY") or st.secrets.get("APOLLO_API_KEY", None)


def _apollo_request(params: dict) -> list[dict]:
    api_key = _get_api_key()
    if not api_key:
        st.error("Apollo API key missing. Set APOLLO_API_KEY.")
        return []
    headers = {"x-api-key": api_key, "accept": "application/json"}
    try:
        resp = requests.post(SEARCH_ENDPOINT, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data.get("people", []) if isinstance(data, dict) else []
    except requests.RequestException as exc:
        st.error(f"API request failed: {exc}")
        return []

# ─────────────────────── Prospect search (one call) ─────────────────────────

def search_for(account: str, geo: str, role: str, seniorities: List[str], prospected: bool) -> list[dict]:
    titles = ROLE_TYPES[role]
    params = {
        "page": 1,
        "per_page": 25,
        "q_organization_name": account,
        "person_locations[]": [geo],
        "person_titles[]": titles,
    }
    if seniorities:
        params["person_seniorities[]"] = seniorities
    if prospected:
        params["prospected"] = "true"
    return _apollo_request(params)

# ───────────────────── Contact enrichment ───────────────────────────────────

@st.cache_data(show_spinner=False)
def get_contact(person_id: str) -> Tuple[Optional[str], Optional[str]]:
    api_key = _get_api_key()
    if not api_key:
        return None, None
    headers = {"x-api-key": api_key, "accept": "application/json"}
    payload = {"id": person_id, "reveal_personal_emails": "true", "reveal_phone_number": "true"}
    try:
        r = requests.post(ENRICH_ENDPOINT, headers=headers, json=payload, timeout=30)
        r.raise_for_status()
        d = r.json()
    except requests.RequestException:
        return None, None
    email = next((e["value"] for e in d.get("emails", []) if e.get("status") == "verified"), None)
    phone = next((p.get("phone_number") for p in d.get("direct_dials", [])), None) or \
        next((p.get("phone_number") for p in d.get("mobile_phone_numbers", [])), None)
    return email, phone

# ─────────────────────── Session state init ─────────────────────────────────

def _init_state():
    st.session_state.setdefault("prospects", {})  # id -> prospect dict
    st.session_state.setdefault("contacts", {})   # id -> (email, phone)
    st.session_state.setdefault("saved", {})      # id -> (name, url)


# ───────────────────────────── Main UI ───────────────────────────────────────

def main():
    _init_state()

    st.title("🔍 Prospect Finder (Apollo)")

    with st.expander("Accounts input", expanded=True):
        text_accounts = st.text_area(
            "Enter one or more account names (comma or newline separated)",
            height=120,
        )
        uploaded_file = st.file_uploader("…or upload a CSV of account names", type=["csv"])

    with st.form("search_form"):
        geos = st.multiselect("Geographies", GEOGRAPHIES, default=GEOGRAPHIES)
        role = st.selectbox("Role Type", list(ROLE_TYPES.keys()))
        mgmt_only = st.checkbox("Management and above", value=True)
        inc_prospected = st.checkbox("Include previously prospected")
        submitted = st.form_submit_button("Search")

    # Parse account list
    accounts: Set[str] = set()
    for token in re.split(r"[\n,]", text_accounts):
        name = token.strip()
        if name:
            accounts.add(name)
    if uploaded_file is not None:
        try:
            decoded = uploaded_file.read().decode("utf-8")
            reader = csv.reader(io.StringIO(decoded))
            for row in reader:
                if row:
                    accounts.add(row[0].strip())
        except Exception as e:
            st.error(f"Could not read CSV: {e}")

    # Search
    if submitted:
        if not accounts:
            st.warning("No account names provided.")
        elif not geos:
            st.warning("Select at least one geography.")
        else:
            st.session_state.prospects.clear()
            seniorities = SENIORITY_LEVELS if mgmt_only else []
            with st.spinner("Searching Apollo …"):
                for acc in accounts:
                    for geo in geos:
                        # unprospected first
                        for person in search_for(acc, geo, role, seniorities, prospected=False):
                            st.session_state.prospects[person["id"]] = person
                        if inc_prospected:
                            for person in search_for(acc, geo, role, seniorities, prospected=True):
                                st.session_state.prospects[person["id"]] = person
            st.success(f"Found {len(st.session_state.prospects)} unique prospects.")

    # Display results
    for p in st.session_state.prospects.values():
        st.markdown("\n".join([
            f"**{p['name']}** – {p['title']}",
            f"📌 {p['location']} | 🏢 {p['company']}",
            f"[LinkedIn profile]({p['profile_url']})",
        ]))
        cols = st.columns(3)
        with cols[0]:
            if p["id"] in st.session_state.contacts:
                email, phone = st.session_state.contacts[p["id"]]
                st.markdown(f"📧 {email or '—'} \| 📞 {phone or '—'}")
            else:
                if st.button("Reveal contact", key=f"reveal_{p['id']}"):
                    with st.spinner("Fetching …"):
                        email, phone = get_contact(person_id=p["id"])
                    st.session_state.contacts[p["id"]] = (email, phone)
                    st.experimental_rerun()
        with cols[1]:
            if p["id"] in st.session_state.saved:
                st.markdown("✅ Saved")
            else:
                if st.button("Save", key=f"save_{p['id']}"):
                    st.session_state.saved[p["id"]] = (p["name"], p["profile_url"])
                    st.experimental_rerun()
        with cols[2]:
            st.write("")
        st.markdown("---")

    # Saved prospects sidebar
    with st.sidebar.expander("⭐️ Saved prospects", expanded=True):
        if st.session_state.saved:
            for name, url in st.session_state.saved.values():
                st.markdown(f"• [{name}]({url})")
        else:
            st.write("No prospects saved yet.")


if __name__ == "__main__":
    main()
