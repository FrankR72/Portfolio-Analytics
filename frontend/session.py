"""Session helpers shared by the entrypoint, the views and the components.

The JWT lives in st.session_state["access_token"] and the user returned by
/api/auth/me in st.session_state["current_user"]. app.py treats a session as
logged in only when both are present.
"""

import streamlit as st


# Page files, relative to app.py. st.switch_page matches them against the
# pages registered in st.navigation.
LANDING_PAGE = "views/landing.py"
LOGIN_PAGE = "views/login.py"
SIGNUP_PAGE = "views/signup.py"
PORTFOLIO_PAGE = "views/portfolio.py"
STOCK_ANALYSIS_PAGE = "views/stock_analysis.py"
PROFILE_PAGE = "views/profile.py"


def get_token():
    return st.session_state.get("access_token")


def auth_headers():
    return {"Authorization": f"Bearer {get_token() or ''}"}


def start_session(token):
    """Store a new token. app.py loads the user on the next run."""
    st.session_state["access_token"] = token
    st.session_state.pop("current_user", None)


def end_session(notice="Tu sesion expiro. Inicia sesion de nuevo.", go_to=LOGIN_PAGE):
    """Forget the token and every piece of user state, then leave the app.

    Clearing everything (not only the token) keeps the next user who logs in
    in this browser tab from seeing the previous user's selected portfolio or
    cached charts.
    """
    st.session_state.clear()
    if notice:
        st.session_state["auth_notice"] = notice
    st.switch_page(go_to)
