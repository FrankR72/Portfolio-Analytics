import streamlit as st



st.set_page_config(
    page_title="Plataforma Huella de Carbono",
    page_icon="🏭",
    layout="wide",
)

col1, col2, col3 = st.columns([5, 1, 1])

with col1:
    st.subheader("Huella de carbono")

with col2:
    login = st.button("Log in")
    if login:
        st.switch_page("pages/1_login.py")

with col3:
    signup = st.button("Sign up")
    if signup:
        st.switch_page("pages/2_signup.py")
st.divider()

st.title("HOMEPAGE")

st.space(size=70)

st.write("Design and images")