from datetime import date

import requests
import streamlit as st


PORTFOLIOS_URL = "http://127.0.0.1:8000/api/portfolios"
TRANSACTIONS_URL = "http://127.0.0.1:8000/api/transactions"

token = st.session_state.get("access_token")
if not token:
    st.switch_page("pages/1_login.py")

if st.button("Volver al dashboard"):
    st.switch_page("pages/3_main_dashboard.py")

portfolio_id = st.session_state.get("selected_portfolio_id")
if portfolio_id is None:
    st.info("Selecciona un portafolio en el dashboard para editarlo.")
    st.stop()

headers = {"Authorization": f"Bearer {token}"}
try:
    response = requests.get(PORTFOLIOS_URL, headers=headers, timeout=5)
except requests.RequestException:
    st.error("No se pudieron cargar los portafolios.")
    st.stop()

if response.status_code == 401:
    st.session_state.pop("access_token", None)
    st.switch_page("pages/1_login.py")
if response.status_code != 200:
    st.error("No se pudieron cargar los portafolios.")
    st.stop()

portfolio = next(
    (item for item in response.json() if item["id"] == portfolio_id),
    None,
)
if portfolio is None:
    st.session_state.pop("selected_portfolio_id", None)
    st.error("El portafolio seleccionado ya no está disponible.")
    st.stop()

st.title(f"Editar portafolio: {portfolio['name']}")
st.subheader("Agregar transacción")

use_custom_date = st.checkbox("Elegir la fecha de la transacción")

with st.form("create_transaction", clear_on_submit=True):
    symbol = st.text_input("Símbolo", max_chars=20)
    transaction_type = st.selectbox("Tipo de transacción", ["BUY", "SELL"])
    quantity = st.number_input("Cantidad de acciones", min_value=1, step=1)
    price = st.number_input("Precio por acción", min_value=0.01, step=0.01)
    if use_custom_date:
        transaction_date = st.date_input("Fecha de la transacción", value=date.today())
    submitted = st.form_submit_button("Guardar transacción")

if submitted:
    if not symbol.strip():
        st.error("Introduce el símbolo de la acción.")
    else:
        payload = {
            "symbol": symbol.strip().upper(),
            "transaction_type": transaction_type,
            "quantity_actions": quantity,
            "price": price,
        }
        if use_custom_date:
            payload["transaction_date"] = transaction_date.isoformat()

        try:
            created = requests.post(
                TRANSACTIONS_URL,
                params={"portfolio_id": portfolio_id},
                headers=headers,
                json=payload,
                timeout=5,
            )
        except requests.RequestException:
            st.error("No se pudo conectar con el servidor.")
        else:
            if created.status_code in (200, 201):
                st.success("Transacción guardada. Puedes agregar otra o volver al dashboard.")
            elif created.status_code == 404:
                st.error("El portafolio ya no está disponible.")
            elif created.status_code == 401:
                st.session_state.pop("access_token", None)
                st.switch_page("pages/1_login.py")
            else:
                st.error("No se pudo guardar la transacción.")
