import streamlit as st
import requests

from session import LANDING_PAGE, LOGIN_PAGE, PORTFOLIO_PAGE, start_session

CREATE_USER_URL = "http://127.0.0.1:8000/api/users"
LOGIN_URL = "http://127.0.0.1:8000/api/auth/token"

st.page_link(LANDING_PAGE, label="Romo", icon=":material/arrow_back:")

st.space(size=75)

st.title("Sign up", text_alignment="center")


col1, col2, col3 = st.columns([2, 1, 2])

with col2:
    username = st.text_input("Nombre de usuario")
    email = st.text_input("Email")
    password = st.text_input("Contraseña", type="password")


    signup = st.button("Crear cuenta", use_container_width=True)


    if signup:
        payload = {
            "username": username,
            "email": email,
            "password": password
        }
        try:
            response = requests.post(
                url=CREATE_USER_URL,
                json=payload,
                timeout=10,
            )
        except requests.RequestException:
            st.error("No se pudo conectar con el servidor.")
            st.stop()

        if response.status_code == 201:
            # The sign-up endpoint doesn't return a token, so log in with the
            # same credentials to go straight to the app.
            try:
                login_response = requests.post(
                    url=LOGIN_URL,
                    data={"username": email, "password": password},
                    timeout=10,
                )
            except requests.RequestException:
                login_response = None
            if login_response is not None and login_response.status_code == 200:
                start_session(login_response.json()["access_token"])
                st.switch_page(PORTFOLIO_PAGE)
            st.success("User created successfully! Please log in.")
        elif response.status_code == 406:
            st.error("Username already exists.")
        elif response.status_code == 400:
            st.error("Email already registered.")
        elif response.status_code == 500:
            st.error("An error ocurred.")
        elif response.status_code == 422:
            error = response.json()["detail"][0]

            if error["loc"][-1] == "password":
                st.error("La contraseña debe tener al menos 8 caracteres.")
            elif error["loc"][-1] == "email":
                st.error("Introduce un correo electrónico válido.")
            else:
                st.error(error["msg"])

col1, col2, col3 = st.columns([2, 1, 2])

with col2:
    st.write("¿Ya tienes una cuenta?")
    st.page_link(
        LOGIN_PAGE,
        label="Log in",
    )
