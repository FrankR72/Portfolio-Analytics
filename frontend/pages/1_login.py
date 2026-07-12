import streamlit as st
import requests


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
    email = st.text_input("Email")
    # pending password !!!
    
    login = st.button("Log in", use_container_width=True)
        
    if login:
        payload = {
            "email": email
        }
        response = requests.post(
            url="http://127.0.0.1:8000/api/auth",
            json=payload
        )
        if response.status_code == 200:
            st.switch_page("pages/3_main_dashboard.py")
        elif response.status_code in (404, 422):
            st.error("Email not found. Please check your email.")   


col1, col2, col3 = st.columns([2, 1, 2])

with col2:
    st.write("Don't have an account? ")
    st.page_link(
        "pages/2_signup.py",
        label="Sign up",
    )