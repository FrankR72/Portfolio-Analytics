"""Landing page for visitors without a session."""

import streamlit as st

from session import LOGIN_PAGE, SIGNUP_PAGE


with st.container(horizontal=True, horizontal_alignment="right"):
    if st.button("Log in"):
        st.switch_page(LOGIN_PAGE)
    if st.button("Sign up", type="primary"):
        st.switch_page(SIGNUP_PAGE)

st.space(size=40)

_, center, _ = st.columns([1, 2, 1])

with center:
    st.title("Romo", text_alignment="center")
    st.subheader("Stock Analysis Platform", text_alignment="center")

    with st.container(
        border=True,
        height=320,
        horizontal_alignment="center",
        vertical_alignment="center",
    ):
        st.markdown(":material/image: **Pending Image**", text_alignment="center")

    with st.container(border=True):
        st.markdown("Pending Information", text_alignment="center")
