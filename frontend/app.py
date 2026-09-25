"""Entrypoint and router of the Streamlit frontend.

Every page is registered with st.navigation on every run, and access is
decided here before the page runs:

- Logged out: only the landing, login and signup pages can be opened, and
  the sidebar navigation is hidden. Any internal page redirects to landing.
- Logged in: the sidebar shows exactly Portfolio and Stock Analysis. The
  public pages are hidden from it and redirect to Portfolio. My Profile is
  private but also hidden; it is opened from the settings menu under the
  navigation.

All pages stay registered in both states because Streamlit shows a
"page not found" message when the current page disappears from the list.
"""

import requests
import streamlit as st

from session import (
    LANDING_PAGE,
    LOGIN_PAGE,
    PORTFOLIO_PAGE,
    PROFILE_PAGE,
    SIGNUP_PAGE,
    STOCK_ANALYSIS_PAGE,
    auth_headers,
    end_session,
    get_token,
)

ME_URL = "http://127.0.0.1:8000/api/auth/me"


st.set_page_config(
    page_title="Romo | Stock Analysis Platform",
    page_icon="📈",
    layout="wide",
)

# Validate a new token once per session; later 401s from any endpoint call
# end_session.
if get_token() and "current_user" not in st.session_state:
    try:
        response = requests.get(ME_URL, headers=auth_headers(), timeout=5)
    except requests.RequestException:
        st.error("Cannot reach the server. Please try again.")
        st.stop()
    if response.status_code == 200:
        st.session_state["current_user"] = response.json()
    else:
        st.session_state.clear()

logged_in = bool(get_token()) and "current_user" in st.session_state
public_visibility = "hidden" if logged_in else "visible"

landing_page = st.Page(LANDING_PAGE, title="Romo", icon=":material/home:", default=True, visibility=public_visibility)
login_page = st.Page(LOGIN_PAGE, title="Log in", icon=":material/login:", visibility=public_visibility)
signup_page = st.Page(SIGNUP_PAGE, title="Sign up", icon=":material/person_add:", visibility=public_visibility)
portfolio_page = st.Page(PORTFOLIO_PAGE, title="Portfolio", icon=":material/account_balance_wallet:")
stock_analysis_page = st.Page(STOCK_ANALYSIS_PAGE, title="Stock Analysis", icon=":material/query_stats:")
profile_page = st.Page(PROFILE_PAGE, title="My Profile", icon=":material/person:", visibility="hidden")

public_pages = [landing_page, login_page, signup_page]
private_pages = [portfolio_page, stock_analysis_page, profile_page]

page = st.navigation(
    private_pages + public_pages,
    position="sidebar" if logged_in else "hidden",
)

if logged_in and any(page is public for public in public_pages):
    st.switch_page(PORTFOLIO_PAGE)
if not logged_in and any(page is private for private in private_pages):
    st.switch_page(LANDING_PAGE)

if logged_in:
    with st.sidebar:
        st.divider()
        user = st.session_state["current_user"]
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown(f"**{user['username']}**", width="stretch")
            with st.popover("", icon=":material/settings:", help="Settings"):
                st.markdown(f"**{user['username']}**")
                st.caption(user["email"])
                st.divider()
                st.page_link(PROFILE_PAGE, label="My Profile", icon=":material/person:")
        if st.button("Log out", icon=":material/logout:", width="stretch"):
            end_session(notice=None, go_to=LANDING_PAGE)

page.run()
