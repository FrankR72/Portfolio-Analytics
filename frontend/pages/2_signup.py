import streamlit as st
import requests

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
    username = st.text_input("Username")
    email = st.text_input("Email")
    
    # pending password !!!
    
    signup = st.button("Sign up", use_container_width=True)
    
    response = ...
    
    if signup:
        payload = {
            "username": username,
            "email": email
        }
        response = requests.post(
            "http://127.0.0.1:8000/api/users",
            json=payload
        )
        
        if response.status_code == 201:
            st.success("User created successfully! Please log in.")
        elif response.status_code == 422:
            st.error("Enter a valid email address.")
        elif response.status_code in (406, 409):
            error_message = response.json().get("detail", "An error ocurred.")
            st.error(error_message)

col1, col2, col3 = st.columns([2, 1, 2])

with col2:
    st.write("Already have an account? ")
    st.page_link(
        "pages/1_login.py",
        label="Log in",
    )

