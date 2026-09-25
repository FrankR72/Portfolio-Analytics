"""Closed Transactions tab: realized gain or loss of every SELL."""

import requests
import streamlit as st

from components.formatting import format_number
from session import auth_headers, end_session

TRANSACTIONS_URL = "http://127.0.0.1:8000/api/transactions"


def render_closed_transactions(portfolio_id):
    try:
        closed_response = requests.get(
            f"{TRANSACTIONS_URL}/closed",
            params={"portfolio_id": portfolio_id},
            headers=auth_headers(),
            timeout=5,
        )
    except requests.RequestException:
        st.error("No se pudieron cargar las transacciones cerradas.")
        return

    if closed_response.status_code == 200:
        closed_transactions = closed_response.json()
        if closed_transactions:
            st.dataframe(
                [
                    {
                        "Fecha": transaction["transaction_date"][:10],
                        "Acción": transaction["symbol"],
                        "Acciones vendidas": transaction["number_shares_sold"],
                        "Costo promedio por acción": format_number(transaction["avg_cost_per_share"]),
                        "Precio de venta por acción": format_number(transaction["sold_price_per_share"]),
                        "Costo total de acciones vendidas": format_number(transaction["total_cost_of_shares_sold"]),
                        "Valor total de venta": format_number(transaction["total_sold_price"]),
                        "Ganancia realizada": format_number(transaction["realized_gain_loss"]),
                        "Rendimiento": f"{format_number(transaction['return_percentage'])}%",
                    }
                    for transaction in closed_transactions
                ],
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info("Este portafolio todavía no tiene ventas registradas.")
    elif closed_response.status_code == 401:
        end_session()
    elif closed_response.status_code == 404:
        st.error("El portafolio seleccionado ya no está disponible.")
    else:
        st.error("No se pudieron cargar las transacciones cerradas.")
