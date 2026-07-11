import streamlit as st

st.set_page_config(
    page_title="Log in",
    page_icon="💹",
    layout="wide"
)

st.write("")
st.write("")
st.write("")
st.write("")
st.write("")
st.write("")
st.write("")
st.write("")

st.title("Log in", text_alignment="center")


col1, col2, col3 = st.columns([2, 1, 2])

with col2:
    login = st.button("Log in", use_container_width=True)
    if login:
        st.switch_page("pages/3_main_dashboard.py")

col1, col2, col3 = st.columns([2, 1, 2])

with col2:
    st.write("Don't have an account? ")
    st.page_link(
        "pages/2_signup.py",
        label="Sign up",
    )
