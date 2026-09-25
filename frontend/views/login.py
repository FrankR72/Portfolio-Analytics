import streamlit as st
import requests

from session import LANDING_PAGE, PORTFOLIO_PAGE, SIGNUP_PAGE, start_session


LOGIN_URL = "http://127.0.0.1:8000/api/auth/token"

st.page_link(LANDING_PAGE, label="Romo", icon=":material/arrow_back:")

st.space(size=75)

st.title("Log in", text_alignment="center")



col1, col2, col3 = st.columns([2, 1, 2])

with col2:
    if notice := st.session_state.pop("auth_notice", None):
        st.info(notice)

    email = st.text_input("Email")
    password = st.text_input("Contraseña", type="password")

    login = st.button("Log in", use_container_width=True)

    if login:
        payload = {
            "username": email,
            "password": password
        }
        try:
            response = requests.post(
                url=LOGIN_URL,
                data=payload,
                timeout=10,
            )
        except requests.RequestException:
            st.error("No se pudo conectar con el servidor.")
            st.stop()
        if response.status_code == 200:
            token_data = response.json()
            start_session(token_data["access_token"])

            st.switch_page(PORTFOLIO_PAGE)
        elif response.status_code in (401, 404, 422):
            st.error("Email o contraseña incorrectos. Por favor, inténtalo de nuevo.")


col1, col2, col3 = st.columns([2, 1, 2])

with col2:
    st.write("¿No tienes una cuenta?")
    st.page_link(
        SIGNUP_PAGE,
        label="Crear cuenta",
    )
