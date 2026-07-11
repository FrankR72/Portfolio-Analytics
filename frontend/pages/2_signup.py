import streamlit as st

st.set_page_config(
    page_title="signup",
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

st.title("Sign up", text_alignment="center")


col1, col2, col3 = st.columns([2, 1, 2])

with col2:
    Signup = st.button("Sign up", use_container_width=True)
    if Signup:
        st.switch_page("pages/1_login.py")


col1, col2, col3 = st.columns([2, 1, 2])

with col2:
    st.write("Already have an account? ")
    st.page_link(
        "pages/1_login.py",
        label="Log in",
    )

