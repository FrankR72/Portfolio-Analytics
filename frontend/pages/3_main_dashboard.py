import requests
import streamlit as st

PORTFOLIOS_URL = "http://127.0.0.1:8000/api/portfolios"

token = st.session_state.get("access_token")
if not token:
    st.switch_page("pages/1_login.py")

try:
    response = requests.get(
        "http://127.0.0.1:8000/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=5,
    )
except requests.RequestException:
    st.error("Cannot reach the server. Please try again.")
    st.stop()

if response.status_code != 200:
    st.session_state.pop("access_token", None)
    st.switch_page("pages/1_login.py")

user = response.json()
st.title(f"Welcome, {user['username']}")


st.write(user["email"])

if st.button("Crear portafolio"):
    st.session_state["show_create_portfolio"] = True

if st.session_state.get("show_create_portfolio", False):
    with st.form("create_portfolio"):
        portfolio_name = st.text_input("Nombre del portafolio", max_chars=100)
        submitted = st.form_submit_button("Crear")

    if submitted:
        if not portfolio_name.strip():
            st.error("Introduce un nombre para el portafolio.")
        else:
            try:
                created = requests.post(
                    url=PORTFOLIOS_URL,
                    headers={"Authorization": f"Bearer {token}"},
                    json={"name": portfolio_name.strip()},
                    timeout=5,
                )
            except requests.RequestException:
                st.error("No se pudo conectar con el servidor.")
            else:
                if created.status_code == 201:
                    st.session_state["show_create_portfolio"] = False
                    st.session_state["selected_portfolio_id"] = created.json()["id"]
                    st.rerun()
                elif created.status_code == 406:
                    st.error("Ya tienes un portafolio con ese nombre.")
                else:
                    st.error("No se pudo crear el portafolio.")

try:
    portfolios_response = requests.get(
        url=PORTFOLIOS_URL,
        headers={"Authorization": f"Bearer {token}"},
        timeout=5,
    )
except requests.RequestException:
    st.error("No se pudieron cargar los portafolios.")
    st.stop()

if portfolios_response.status_code != 200:
    st.error("No se pudieron cargar los portafolios.")
    st.stop()

portfolios = portfolios_response.json()
st.subheader("Mis portafolios")

if not portfolios:
    st.info("Todavía no tienes portafolios.")

for portfolio in portfolios:
    if st.button(portfolio["name"], key=f"portfolio_{portfolio['id']}"):
        st.session_state["selected_portfolio_id"] = portfolio["id"]

selected_portfolio = next(
    (portfolio for portfolio in portfolios
     if portfolio["id"] == st.session_state.get("selected_portfolio_id")),
    None,
)
if selected_portfolio:
    st.subheader(selected_portfolio["name"])
    st.write("This portfolio has no data yet.")
