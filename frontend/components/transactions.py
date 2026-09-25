"""Transactions tab: list of a portfolio's transactions, add and delete."""

from datetime import date

import requests
import streamlit as st

from session import auth_headers, end_session


TRANSACTIONS_URL = "http://127.0.0.1:8000/api/transactions"


# Closing the dialog reruns the app so the tables behind it show the new
# transactions. It stays open after saving so several can be added in a row.
@st.dialog("Agregar transacción", on_dismiss="rerun")
def add_transaction_dialog(portfolio):
    portfolio_id = portfolio["id"]
    st.caption(f"Portafolio: {portfolio['name']}")

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
                    headers=auth_headers(),
                    json=payload,
                    timeout=5,
                )
            except requests.RequestException:
                st.error("No se pudo conectar con el servidor.")
            else:
                if created.status_code in (200, 201):
                    st.success("Transacción guardada. Puedes agregar otra o cerrar este diálogo.")
                elif created.status_code == 404:
                    st.error("El portafolio ya no está disponible.")
                elif created.status_code == 401:
                    end_session()
                else:
                    st.error("No se pudo guardar la transacción.")


@st.dialog("Eliminar transacción")
def confirm_transaction_deletion(portfolio, transaction):
    st.write(
        f"{transaction['transaction_type']} · {transaction['symbol']} · "
        f"{transaction['quantity_actions']} acciones a {transaction['price']:,.2f} · "
        f"{transaction['transaction_date'][:10]}"
    )
    st.warning(
        "Estas seguro? Las posiciones, las ganancias realizadas y la analitica "
        "se recalcularan sin esta transaccion. Esta accion no se puede deshacer."
    )
    cancel_column, delete_column = st.columns(2)
    if cancel_column.button("Cancelar", width="stretch"):
        st.rerun()
    if delete_column.button("Eliminar definitivamente", type="primary", icon=":material/delete:", width="stretch"):
        try:
            with st.spinner("Eliminando transacción..."):
                deleted = requests.delete(
                    f"{TRANSACTIONS_URL}/{transaction['id']}",
                    params={"portfolio_id": portfolio["id"]},
                    headers=auth_headers(),
                    timeout=15,
                )
        except requests.RequestException:
            st.error("No se pudo confirmar la eliminacion. Cierra este dialogo y revisa la tabla antes de intentarlo de nuevo.")
            return
        if deleted.status_code == 401:
            end_session()
        elif deleted.status_code in (204, 404):
            # Returns and gains change, so drop cached performance data, and
            # give the table a new key so the deleted row's selection is gone.
            st.session_state.pop("performance_cache", None)
            st.session_state["transactions_table_version"] = st.session_state.get("transactions_table_version", 0) + 1
            st.session_state["transaction_delete_notice"] = (
                "Transacción eliminada."
                if deleted.status_code == 204 else "La transacción ya no estaba disponible."
            )
            st.rerun()
        elif deleted.status_code == 409:
            st.error(
                "No se puede eliminar esta compra: una venta posterior quedaria "
                "sin acciones suficientes. Elimina primero esa venta."
            )
        else:
            st.error("No se pudo eliminar la transacción. Intenta de nuevo mas tarde.")


def render_transactions(portfolio):
    if notice := st.session_state.pop("transaction_delete_notice", None):
        st.success(notice)

    # The delete button needs the table's selection, so it is added to this
    # row after the table is drawn.
    actions = st.container(horizontal=True)
    if actions.button("Agregar transacción", icon=":material/add:"):
        add_transaction_dialog(portfolio)

    try:
        transactions_response = requests.get(
            TRANSACTIONS_URL,
            params={"portfolio_id": portfolio["id"]},
            headers=auth_headers(),
            timeout=5,
        )
    except requests.RequestException:
        st.error("No se pudieron cargar las transacciones.")
        return

    if transactions_response.status_code == 200:
        transactions = transactions_response.json()
        if transactions:
            table_version = st.session_state.get("transactions_table_version", 0)
            table = st.dataframe(
                [
                    {
                        "Fecha": transaction["transaction_date"][:10],
                        "Símbolo": transaction["symbol"],
                        "Tipo": transaction["transaction_type"],
                        "Acciones": transaction["quantity_actions"],
                        "Precio por acción": transaction["price"],
                        "Valor total": transaction["total_value"],
                    }
                    for transaction in transactions
                ],
                hide_index=True,
                use_container_width=True,
                on_select="rerun",
                selection_mode="single-row",
                key=f"transactions_table_{portfolio['id']}_{table_version}",
            )
            selected_rows = [row for row in table.selection.rows if row < len(transactions)]
            if actions.button(
                "Eliminar transacción",
                icon=":material/delete:",
                disabled=not selected_rows,
                help="Selecciona una transacción en la tabla para eliminarla.",
            ) and selected_rows:
                confirm_transaction_deletion(portfolio, transactions[selected_rows[0]])
        else:
            st.info("Este portafolio todavía no tiene transacciones registradas.")
    elif transactions_response.status_code == 401:
        end_session()
    elif transactions_response.status_code == 404:
        st.error("El portafolio seleccionado ya no está disponible.")
    else:
        st.error("No se pudieron cargar las transacciones.")
