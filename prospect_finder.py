# prospect_finder.py – Streamlit programme to locate senior IT & Security prospects via Apollo API
# -----------------------------------------------------------------------------
# Written in UK English.
#
# Version 1.8 – seniority-level filter (person_seniorities[])
# ---------------------------------------------------------
# • Replaces previous management-level filter with Apollo’s **person_seniorities[]**
#   parameter as per API documentation.
# • Checkbox **“Management and above”** now adds these seniorities: owner, founder,
#   c_suite, partner, vp, head, director, manager.
# • Everything else unchanged.
#
# Requirements
# ------------
#   pip install --upgrade streamlit requests
#
# Apollo key must allow People Search + People Enrichment.
# -----------------------------------------------------------------------------
from __future__ import annotations

import os
import re
from typing import List, Dict, Tuple, Optional

import requests
import streamlit as st

st.set_page_config(page_title="Prospect Finder", page_icon="🔍")

# ----------------------------- Constants --------------------------------------
GEOGRAPHIES = [
    "Netherlands", "Sweden", "Finland", "Norway", "Denmark", "Estonia",
]

ROLE_TYPES: dict[str, list[str]] = {
    "ExP": [
        "CIO", "Chief Information Officer", "VP IT", "IT Director", "IT",
        "IT Manager", "CTIO", "Director of IT Operations", "IT Infrastructure Director",
        "Senior IT Director",
    ],
    "Security": [
        "Security",
    ],
}

ROLE_PATTERNS: dict[str, re.Pattern] = {
    role: re.compile("(" + "|".join(map(re.escape, titles)) + ")", re.I)
    for role, titles in ROLE_TYPES.items()
}

SENIORITY_LEVELS: list[str] = [
    "owner", "founder", "c_suite", "partner", "vp", "head", "director", "manager",
]

API_BASE = "https://api.apollo.io/api/v1"
SEARCH_ENDPOINT = f"{API_BASE}/mixed_people/search"
ENRICH_ENDPOINT = f"{API_BASE}/people/match"

# ───────────────────────── Helpers ───────────────────────────────────────────

def _get_api_key() -> Optional[str]:
    return os.getenv("APOLLO_API_KEY") or st.secrets.get("APOLLO_API_KEY", None)


def _apollo_request(method: str, url: str, payload: dict | None = None) -> Optional[dict]:
    """Perform a request to Apollo with basic error handling."""
    api_key = _get_api_key()
    if not api_key:
        st.error("Apollo API key missing. Set APOLLO_API_KEY.")
        return None

    headers = {
        "x-api-key": api_key,
        "accept": "application/json",
        "cache-control": "no-cache",
    }

    try:
        if method.lower() == "post":
            if url.endswith("/search"):
                resp = requests.post(url, headers=headers, params=payload, timeout=30)
            else:
                resp = requests.post(url, headers=headers, json=payload, timeout=30)
        else:
            resp = requests.get(url, headers=headers, params=payload, timeout=30)

        if resp.status_code == 403:
            st.error(resp.json().get("error", "403 Forbidden – access denied."))
            return None
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        st.error(f"API request failed: {exc}")
        return None

# ─────────────────────── Prospect search ─────────────────────────────────────

def search_prospects(
    account: str,
    geography: str,
    role_type: str,
    management_only: bool = True,
    include_prospected: bool = False,
    per_page: int = 25,
) -> List[Dict[str, str]]:
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

    if management_only:
        params["person_seniorities[]"] = SENIORITY_LEVELS
    if include_prospected:
        params["prospected_statuses[]"] = ["prospected", "not_prospected"]

    data = _apollo_request("post", SEARCH_ENDPOINT, params)
    if not data:
        return []

    pattern = ROLE_PATTERNS[role_type]
    prospects: list[dict[str, str]] = []
    for person in data.get("people", []):
        raw_title = person.get("title")
        title = raw_title if isinstance(raw_title, str) else str(raw_title or "")
        if not pattern.search(title):
            continue
        prospects.append({
            "id": str(person.get("id", "")),
            "name": person.get("name") or f"{person.get('first_name','')} {person.get('last_name','')}",
            "title": title,
            "company": (person.get("organization") or {}).get("name", account.title()),
            "location": geography,
            "profile_url": person.get("linkedin_url") or person.get("linkedin", {}).get("url", ""),
        })
    return prospects

# ───────────────────── Contact enrichment ───────────────────────────────────

@st.cache_data(show_spinner=False)
def get_contact_details(person_id: str) -> Tuple[Optional[str], Optional[str]]:
    if not person_id:
        return None, None

    payload = {
        "id": person_id,
        "reveal_personal_emails": "true",
        "reveal_phone_number": "true",
    }

    data = _apollo_request("post", ENRICH_ENDPOINT, payload)
    if not data:
        return None, None

    email = next(
        (e.get("value") for e in data.get("emails", []) if e.get("status") == "verified"),
        None,
    ) or (data.get("emails", [{}])[0].get("value") if data.get("emails") else None)

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
        "prospects": [],
        "contacts": {},
        "last_account": "",
        "last_geo": GEOGRAPHIES[0],
        "last_role": list(ROLE_TYPES.keys())[0],
        "last_mgmt": True,
        "last_include_prospected": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _maybe_rerun() -> None:
    if hasattr(st, "experimental_rerun"):
        st.experimental_rerun()

# ─────────────────────────────── Main UI ─────────────────────────────────────

def main() -> None:
    _init_state()

    st.title("🔍 Prospect Finder (Apollo)")
    st.write("Locate senior internal IT and Security leaders for a company and country.")

    # ───────── Search form ───────────
    with st.form("search", clear_on_submit=False):
        account = st.text_input(
            "Account Name",
            st.session_state.last_account,
            placeholder="Enter company name …",
        )
        geography = st.selectbox(
            "Geography",
            GEOGRAPHIES,
            index=GEOGRAPHIES.index(st.session_state.last_geo),
        )
        role_type = st.selectbox(
            "Role Type",
            list(ROLE_TYPES.keys()),
            index=list(ROLE_TYPES.keys()).index(st.session_state.last_role),
        )
        mgmt_toggle = st.checkbox(
            "Management and above", value=st.session_state.last_mgmt
        )
        inc_prospected_toggle = st.checkbox(
            "Include previously prospected contacts",
            value=st.session_state.last_include_prospected,
        )
        submitted = st.form_submit_button("Search")

    # ───────── Handle submission ─────────
    if submitted:
        if not account.strip():
            st.error("Please enter an Account Name before searching.")
        else:
            with st.spinner("Contacting Apollo …"):
                st.session_state.prospects = search_prospects(
                    account.strip(),
                    geography,
                    role_type,
                    mgmt_toggle,
                    inc_prospected_toggle,
                )
                st.session_state.contacts.clear()
                st.session_state.last_account = account.strip()
                st.session_state.last_geo = geography
                st.session_state.last_role = role_type
                st.session_state.last_mgmt = mgmt_toggle
                st.session_state.last_include_prospected = inc_prospected_toggle
            _maybe_rerun()

    # ───────── Display results ─────────
    prospects = st.session_state.prospects
    if prospects:
        st.success(
            f"Found {len(prospects)} prospect(s) for {st.session_state.last_account.title()} in {st.session_state.last_geo}:"
        )
        for p in prospects:
            with st.container():
                st.markdown(
                    f"**{p['name']}** – {p['title']}"
                    f"📌 {p['location']} | 🏢 {p['company']}"
                    f"[LinkedIn profile]({p['profile_url']})"
                )

                if p["id"] in st.session_state.contacts:
                    email, phone = st.session_state.contacts[p["id"]]
                    st.markdown(f"📞 {phone or '—'} | 📧 {email or '—'}")
                else:
                    if st.button("Reveal contact", key=f"reveal_{p['id']}"):
                        with st.spinner("Fetching contact details …"):
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
