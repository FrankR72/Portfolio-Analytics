import streamlit as st
import requests


LOGIN_URL = "http://127.0.0.1:8000/api/auth/token"

st.set_page_config(
    page_title="Plataforma Huella de Carbono",
    page_icon="🏭",
    layout="wide",
)

st.space(size=75)

st.title("Log in", text_alignment="center")



col1, col2, col3 = st.columns([2, 1, 2])

with col2:
    email = st.text_input("Email")
    password = st.text_input("Contraseña", type="password")

    login = st.button("Log in", use_container_width=True)
        
    if login:
        payload = {
            "username": email,
            "password": password
        }
        response = requests.post(
            url=LOGIN_URL,
            data=payload
        )
        if response.status_code == 200:
            token_data = response.json()
            access_token = token_data.get("access_token")
            st.session_state["access_token"] = token_data["access_token"]
            
            st.switch_page("pages/3_main_dashboard.py")
        elif response.status_code in (401, 404, 422):
            st.error("Email o contraseña incorrectos. Por favor, inténtalo de nuevo.")   


col1, col2, col3 = st.columns([2, 1, 2])

with col2:
    st.write("¿No tienes una cuenta?")
    st.page_link(
        "pages/2_signup.py",
        label="Crear cuenta",
    )

