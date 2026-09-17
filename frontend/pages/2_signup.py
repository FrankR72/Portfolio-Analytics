import streamlit as st
import requests

CREATE_USER_URL = "http://127.0.0.1:8000/api/users"

st.set_page_config(
    page_title="Plataforma Huella de Carbono",
    page_icon="🏭",
    layout="wide"
)

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
        response = requests.post(
            url=CREATE_USER_URL,
            json=payload
        )
        
        if response.status_code == 201:
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
        "pages/1_login.py",
        label="Log in",
    )

