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


def get_data(url, optional=False):
    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code == 401:
            st.session_state.pop("access_token", None)
            st.switch_page("pages/1_login.py")
        if response.status_code == 404:
            if optional:
                return None
            st.error("El portafolio seleccionado ya no esta disponible.")
            st.stop()
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError):
        if optional:
            return None
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
with st.spinner("Cargando ganancias no realizadas..."):
    gains_payload = get_data(
        f"{PORTFOLIOS_URL}/{portfolio_id}/unrealized_gains_distribution",
        optional=True,
    )
gains = None
try:
    gains = {
        symbol: float(data["unrealized_gain_loss"])
        for symbol, data in gains_payload["unrealized_gains_distribution"].items()
    }
    if set(gains) != set(df["Accion"]) or not all(math.isfinite(value) for value in gains.values()):
        raise ValueError("Incomplete gains")
except (KeyError, TypeError, ValueError, AttributeError):
    gains = None

colors = alt.Scale(domain=df["Accion"].tolist(), scheme="tableau10")
allocation_column, gains_column = st.columns(2)
allocation_column.subheader("Distribucion de las posiciones")
if total > 0 and (df["Asignacion (%)"] >= 0).all():
    chart = (
        alt.Chart(df.assign(Orden=range(len(df))))
        .mark_arc(stroke="white", strokeWidth=2)
        .encode(
            theta=alt.Theta("Asignacion (%):Q", stack=True),
            color=alt.Color("Accion:N", sort=df["Accion"].tolist(), scale=colors),
            order=alt.Order("Orden:Q"),
            tooltip=["Accion:N", alt.Tooltip("Valor actual:Q", format=",.2f"), alt.Tooltip("Asignacion (%):Q", format=".2f")],
        )
        .properties(height=360)
    )
    allocation_column.altair_chart(chart, width="stretch")
else:
    allocation_column.info("La distribucion grafica requiere un valor total positivo y asignaciones no negativas.")

gains_column.subheader("Ganancias no realizadas positivas")
if gains is None:
    gains_column.error("No se pudieron cargar las ganancias. Intenta actualizar de nuevo.")
else:
    df["Ganancia/perdida no realizada"] = df["Accion"].map(gains)
    positive = df[df["Ganancia/perdida no realizada"] > 0].copy()
    if positive.empty:
        gains_column.info("No hay ganancias no realizadas positivas.")
    else:
        positive = positive.sort_values("Ganancia/perdida no realizada", ascending=False)
        positive["Participacion en ganancias (%)"] = (
            positive["Ganancia/perdida no realizada"]
            / positive["Ganancia/perdida no realizada"].sum() * 100
        )
        gains_chart = (
            alt.Chart(positive.assign(Orden=range(len(positive))))
            .mark_arc(stroke="white", strokeWidth=2)
            .encode(
                theta=alt.Theta("Ganancia/perdida no realizada:Q", stack=True),
                color=alt.Color("Accion:N", scale=colors),
                order=alt.Order("Orden:Q"),
                tooltip=[
                    "Accion:N",
                    alt.Tooltip("Ganancia/perdida no realizada:Q", format=",.2f"),
                    alt.Tooltip("Participacion en ganancias (%):Q", format=".2f"),
                ],
            )
            .properties(height=360)
        )
        gains_column.altair_chart(gains_chart, width="stretch")

table = pd.concat([df, pd.DataFrame([{
    "Accion": "TOTAL",
    "Valor actual": total,
    "Asignacion (%)": df["Asignacion (%)"].sum(),
    **({"Ganancia/perdida no realizada": sum(gains.values())} if gains is not None else {}),
}])], ignore_index=True)
st.dataframe(
    table,
    hide_index=True,
    width="stretch",
    column_config={
        "Valor actual": st.column_config.NumberColumn(format="%.2f"),
        "Asignacion (%)": st.column_config.NumberColumn(format="%.2f%%"),
        "Ganancia/perdida no realizada": st.column_config.NumberColumn(format="%.2f"),
    },
)
