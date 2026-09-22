from datetime import datetime
import math

import altair as alt
import pandas as pd
import requests
import streamlit as st


PORTFOLIOS_URL = "http://127.0.0.1:8000/api/portfolios"

token = st.session_state.get("access_token")
if not token:
    st.switch_page("pages/1_login.py")

if st.button("Volver al portafolio", icon=":material/arrow_back:"):
    st.switch_page("pages/3_main_dashboard.py")

portfolio_id = st.session_state.get("selected_portfolio_id")
if portfolio_id is None:
    st.info("Selecciona un portafolio en el dashboard.")
    st.stop()

st.button("Actualizar", icon=":material/refresh:", help="Actualizar valores del portafolio")
headers = {"Authorization": f"Bearer {token}"}


def get_data(url):
    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code == 401:
            st.session_state.pop("access_token", None)
            st.switch_page("pages/1_login.py")
        if response.status_code == 404:
            st.error("El portafolio seleccionado ya no esta disponible.")
            st.stop()
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError):
        st.error("No se pudo cargar la analitica. Intenta actualizar de nuevo.")
        st.stop()


with st.spinner("Cargando analitica..."):
    portfolio = get_data(f"{PORTFOLIOS_URL}/{portfolio_id}")
    payload = get_data(f"{PORTFOLIOS_URL}/{portfolio_id}/distribution")

st.title(f"{portfolio['name']} / Analitica")

try:
    total = float(payload["total_value"])
    rows = [
        {
            "Accion": symbol,
            "Valor actual": float(data["current_value"]),
            "Asignacion (%)": float(data["distribution_percentage"]),
        }
        for symbol, data in payload["distribution"].items()
    ]
    if not math.isfinite(total) or any(
        not math.isfinite(row[key])
        for row in rows
        for key in ("Valor actual", "Asignacion (%)")
    ):
        raise ValueError("Invalid values")
except (KeyError, TypeError, ValueError, AttributeError):
    st.error("El servidor devolvio valores incompletos. Intenta actualizar de nuevo.")
    st.stop()

st.metric("Valor total de las posiciones", f"{total:,.2f}")
st.caption(f"Datos consultados: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}")

if not rows:
    st.info("Este portafolio todavia no tiene posiciones abiertas.")
    if st.button("Agregar transaccion", icon=":material/add:"):
        st.switch_page("pages/4_edit_portfolio.py")
    st.stop()

df = pd.DataFrame(rows).sort_values("Asignacion (%)", ascending=False)
st.subheader("Distribucion de las posiciones")
if total > 0 and (df["Asignacion (%)"] >= 0).all():
    chart = (
        alt.Chart(df.assign(Portafolio="", Orden=range(len(df))))
        .mark_bar()
        .encode(
            x=alt.X("Asignacion (%):Q", stack="zero", title="Asignacion (%)"),
            y=alt.Y("Portafolio:N", axis=None),
            color=alt.Color("Accion:N", sort=df["Accion"].tolist(), scale=alt.Scale(scheme="tableau10")),
            order=alt.Order("Orden:Q"),
            tooltip=["Accion:N", alt.Tooltip("Valor actual:Q", format=",.2f"), alt.Tooltip("Asignacion (%):Q", format=".2f")],
        )
        .properties(height=100)
    )
    st.altair_chart(chart, use_container_width=True)
else:
    st.info("La distribucion grafica requiere un valor total positivo y asignaciones no negativas.")

table = pd.concat([df, pd.DataFrame([{
    "Accion": "TOTAL",
    "Valor actual": total,
    "Asignacion (%)": df["Asignacion (%)"].sum(),
}])], ignore_index=True)
st.dataframe(
    table,
    hide_index=True,
    use_container_width=True,
    column_config={
        "Valor actual": st.column_config.NumberColumn(format="%.2f"),
        "Asignacion (%)": st.column_config.NumberColumn(format="%.2f%%"),
    },
)
