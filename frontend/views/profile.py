"""My Profile: the logged-in user's account information.

Reached from the settings menu in the sidebar; it isn't listed in the
navigation. Shows the user that app.py loaded from /api/auth/me.
"""

import streamlit as st


user = st.session_state["current_user"]

st.title("My Profile")

with st.container(border=True):
    st.caption("Nombre de usuario")
    st.markdown(f"**{user['username']}**")
    st.caption("Email")
    st.markdown(user["email"])
