# prospect_finder.py – Streamlit programme to locate senior IT & Security prospects via Apollo API
# -----------------------------------------------------------------------------
# Written in UK English.
#
# Version 2.4 – multi‑select geographies
# -------------------------------------
# • Geography input is now an `st.multiselect`, so you can query several Nordic
#   countries at once. Empty selection throws a friendly error.
# • `search_prospects()` unchanged (takes one country); the app simply loops over
#   all selected geographies, merges results, and de‑duplicates by Apollo ID.
# -----------------------------------------------------------------------------
from __future__ import annotations

import os
import re
from typing import List, Dict, Tuple, Optional

import requests
import streamlit as st

st.set_page_config(page_title="Prospect Finder", page_icon="🔍")

# ───────────────────────── Constants ─────────────────────────────────────────
GEOGRAPHIES: list[str] = [
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
    role: re.compile("(" + "|".join(map(re.escape, titles)) + ")", re.I)
    for role, titles in ROLE_TYPES.items()
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


def _apollo_request(method: str, url: str, payload: dict | None = None) -> Optional[dict]:
    api_key = _get_api_key()
    if not api_key:
        st.error("Apollo API key missing. Set APOLLO_API_KEY.")
        return None

    headers = {"x-api-key": api_key, "accept": "application/json", "cache-control": "no-cache"}
    try:
        if method.lower() == "post":
            resp = requests.post(url, headers=headers, params=payload, timeout=30)
        else:
            resp = requests.get(url, headers=headers, params=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        st.error(f"API request failed: {exc}")
        return None

# ─────────────────────── Prospect search per‑country ─────────────────────────

def search_prospects(account: str, geography: str, role_type: str, seniorities: List[str], include_prospected: bool, per_page: int = 25) -> List[Dict[str, str]]:
    """Return prospects for a single country."""
    titles = ROLE_TYPES.get(role_type, [])
    if not account or not titles:
        return []

    params: Dict[str, list[str] | str | int] = {
        "page": 1,
        "per_page": min(max(per_page, 1), 100),
        "q_organization_name": account,
        "person_locations[]": [geography],
        "person_titles[]": titles,
    }
    if seniorities:
        params["person_seniorities[]"] = seniorities
    if include_prospected:
        params["prospected"] = "true"

    data = _apollo_request("post", SEARCH_ENDPOINT, params)
    if not data:
        return []

    pattern = ROLE_PATTERNS[role_type]
    matches: list[dict[str, str]] = []
    for person in data.get("people", []):
        title = person.get("title") or ""
        if not pattern.search(str(title)):
            continue
        matches.append(
            {
                "id": str(person.get("id")),
                "name": person.get("name") or f"{person.get('first_name','')} {person.get('last_name','')}",
                "title": title,
                "company": (person.get("organization") or {}).get("name", account.title()),
                "location": geography,
                "profile_url": person.get("linkedin_url") or person.get("linkedin", {}).get("url", ""),
            }
        )
    return matches

# ───────────────────── Contact enrichment ───────────────────────────────────

@st.cache_data(show_spinner=False)
def get_contact_details(person_id: str) -> Tuple[Optional[str], Optional[str]]:
    payload = {"id": person_id, "reveal_personal_emails": "true", "reveal_phone_number": "true"}
    data = _apollo_request("post", ENRICH_ENDPOINT, payload)
    if not data:
        return None, None
    email = next((e.get("value") for e in data.get("emails", []) if e.get("status") == "verified"), None)
    phone = None
    for key in ("direct_dials", "mobile_phone_numbers"):
        nums = data.get(key, [])
        if nums:
            phone = nums[0].get("phone_number") if isinstance(nums[0], dict) else nums[0]
            break
    return email, phone

# ─────────────────────── Session‑state helpers ──────────────────────────────

def _init_state() -> None:
    defaults = {
        "prospects": {},  # id → dict
        "contacts": {},
        "last_account": "",
        "last_geos": [GEOGRAPHIES[0]],
        "last_role": list(ROLE_TYPES.keys())[0],
        "last_mgmt": True,
        "last_include_prospected": False,
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


def _maybe_rerun() -> None:
    if hasattr(st, "experimental_rerun"):
        st.experimental_rerun()

# ───────────────────────────── Main UI ───────────────────────────────────────

def main() -> None:
    _init_state()

    st.title("🔍 Prospect Finder (Apollo)")
    st.write("Locate senior internal IT and Security leaders across Nordic countries.")

    with st.form("search_form", clear_on_submit=False):
        account = st.text_input("Account Name", value=st.session_state.last_account)
        geos = st.multiselect("Geographies", GEOGRAPHIES, default=st.session_state.last_geos)
        role_type = st.selectbox("Role Type", list(ROLE_TYPES.keys()), index=list(ROLE_TYPES.keys()).index(st.session_state.last_role))
        mgmt_toggle = st.checkbox("Management and above", value=st.session_state.last_mgmt)
        inc_prospected_toggle = st.checkbox("Include previously prospected", value=st.session_state.last_include_prospected)
        submitted = st.form_submit_button("Search")

    if submitted:
        if not account.strip():
            st.error("Please enter an Account Name.")
        elif not geos:
            st.error("Select at least one geography.")
        else:
            st.session_state.prospects.clear()
            st.session_state.contacts.clear()
            st.session_state.last_account = account.strip()
            st.session_state.last_geos = geos
            st.session_state.last_role = role_type
            st.session_state.last_mgmt = mgmt_toggle
            st.session_state.last_include_prospected = inc_prospected_toggle

            seniorities = SENIORITY_LEVELS if mgmt_toggle else []
            with st.spinner("Contacting Apollo…"):
                for geo in geos:
                    for person in search_prospects(
                        account.strip(), geo, role_type, seniorities, inc_prospected_toggle
                    ):
                        st.session_state.prospects[person["id"]] = person
            _maybe_rerun()

    prospects = list(st.session_state.prospects.values())
    if prospects:
        st.success(f"Found {len(prospects)} prospect(s) across selected countries.")
        for p in prospects:
            st.markdown("\n".join([
                f"**{p['name']}** – {p['title']}",
                f"📌 {p['location']} | 🏢 {p['company']}",
                f"[LinkedIn profile]({p['profile_url']})",
            ]))
            if p["id"] in st.session_state.contacts:
                email, phone = st.session_state.contacts[p["id"]]
                st.markdown(f"📞 {phone or '—'} | 📧 {email or '—'}")
            else:
                if st.button("Reveal contact", key=f"reveal_{p['id']}"):
                    with st.spinner("Fetching contact …"):
                        email, phone = get_contact_details(p["id"])
                        st.session_state.contacts[p["id"]] = (email, phone)
                        _maybe_rerun()
                st.markdown("---")
    elif submitted:
        st.info(
            "No prospects matched your filters. Try a different account, geography, or adjust the checkboxes."
        )

    # ───────── Sidebar ─────────
    st.sidebar.header("Configuration")
    st.sidebar.write(
        "Apollo key must allow People Search and People Enrichment. Email/phone retrieval consumes credits."
    )
    st.sidebar.write("Built with Python & Streamlit. UK English spelling.")


if __name__ == "__main__":
    main()
