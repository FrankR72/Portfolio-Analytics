"""Holdings tab: open positions of a portfolio with live prices."""

import requests
import streamlit as st

from components.formatting import format_number
from session import auth_headers, end_session

HOLDINGS_URL = "http://127.0.0.1:8000/api/holdings"


def render_holdings(portfolio_id):
    try:
        holdings_response = requests.get(
            f"{HOLDINGS_URL}/{portfolio_id}",
            headers=auth_headers(),
            timeout=30,
        )
    except requests.RequestException:
        st.error("No se pudieron cargar las posiciones actuales.")
        return

    if holdings_response.status_code == 200:
        holdings = holdings_response.json()
        if holdings:
            st.dataframe(
                [
                    {
                        "Acción": holding["symbol"],
                        "Acciones actuales": holding["number_current_shares"],
                        "Costo promedio por acción": format_number(holding["avg_cost_per_share"]),
                        "Costo base": format_number(holding["cost_bases"]),
                        "Precio actual por acción": format_number(holding["current_price_per_share"]),
                        "Valor actual": format_number(holding["current_value"]),
                        "Ganancia no realizada": format_number(holding["unrealized_gain_loss"]),
                        "Rendimiento": (
                            f"{format_number(holding['return_percentage'])}%"
                            if holding["return_percentage"] is not None
                            else "N/A"
                        ),
                    }
                    for holding in holdings
                ],
                hide_index=True,
                use_container_width=True,
            )
            if any(holding["current_price_per_share"] is None for holding in holdings):
                st.caption("N/A indica que no se pudo obtener el precio actual.")
        else:
            st.info("Este portafolio todavía no tiene posiciones abiertas.")
    elif holdings_response.status_code == 401:
        end_session()
    elif holdings_response.status_code == 404:
        st.error("El portafolio seleccionado ya no está disponible.")
    else:
        st.error("No se pudieron cargar las posiciones actuales.")
