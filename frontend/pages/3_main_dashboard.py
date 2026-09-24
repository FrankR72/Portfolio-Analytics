import requests
import streamlit as st

PORTFOLIOS_URL = "http://127.0.0.1:8000/api/portfolios"
TRANSACTIONS_URL = "http://127.0.0.1:8000/api/transactions"
HOLDINGS_URL = "http://127.0.0.1:8000/api/holdings"


def format_number(value):
    return f"{value:,.2f}" if value is not None else "N/A"

@st.dialog("Cambiar nombre del portafolio")
def rename_portfolio(portfolio):
    with st.form(f"rename_portfolio_{portfolio['id']}"):
        name = st.text_input("Nombre", value=portfolio["name"], max_chars=100)
        cancel_column, save_column = st.columns(2)
        cancel = cancel_column.form_submit_button("Cancelar", width="stretch")
        save = save_column.form_submit_button("Guardar", type="primary", icon=":material/save:", width="stretch")
    if cancel:
        st.rerun()
    if not save:
        return
    name = name.strip()
    if not name:
        st.error("El nombre no puede estar vacio.")
        return
    if name == portfolio["name"]:
        st.rerun()
    try:
        with st.spinner("Guardando nombre..."):
            updated = requests.put(
                f"{PORTFOLIOS_URL}/{portfolio['id']}",
                headers={"Authorization": f"Bearer {st.session_state.get('access_token', '')}"},
                json={"name": name}, timeout=15,
            )
    except requests.RequestException:
        st.error("No se pudo confirmar el cambio. Revisa el nombre en el dashboard antes de intentarlo de nuevo.")
        return
    if updated.status_code == 200:
        st.session_state["selected_portfolio_id"] = portfolio["id"]
        st.session_state["portfolio_rename_notice"] = "Nombre del portafolio actualizado."
        st.rerun()
    elif updated.status_code == 401:
        st.session_state.pop("access_token", None)
        st.switch_page("pages/1_login.py")
    elif updated.status_code == 409:
        st.error("Ya tienes un portafolio con ese nombre.")
    elif updated.status_code == 422:
        st.error("Introduce un nombre valido de 1 a 100 caracteres.")
    elif updated.status_code == 404:
        st.error("El portafolio ya no esta disponible. Vuelve al dashboard.")
    else:
        st.error("No se pudo actualizar el nombre. Intenta de nuevo mas tarde.")


@st.dialog("Eliminar portafolio")
def confirm_portfolio_deletion(portfolio):
    st.write(f"Eliminar: {portfolio['name']}")
    st.warning(
        "Estas seguro? Se eliminara este portafolio y todas sus transacciones. "
        "Todos los datos de este portafolio se perderan permanentemente. "
        "Esta accion no se puede deshacer."
    )
    cancel_column, delete_column = st.columns(2)
    if cancel_column.button("Cancelar", width="stretch"):
        st.rerun()
    if delete_column.button("Eliminar definitivamente", type="primary", icon=":material/delete:", width="stretch"):
        try:
            with st.spinner("Eliminando portafolio..."):
                deleted = requests.delete(
                    f"{PORTFOLIOS_URL}/{portfolio['id']}",
                    headers={"Authorization": f"Bearer {st.session_state.get('access_token', '')}"},
                    timeout=15,
                )
        except requests.RequestException:
            st.error("No se pudo confirmar la eliminacion. Cierra este dialogo y revisa la lista de portafolios antes de intentarlo de nuevo.")
            return
        if deleted.status_code == 401:
            st.session_state.pop("access_token", None)
            st.switch_page("pages/1_login.py")
        elif deleted.status_code in (204, 404):
            st.session_state.pop("selected_portfolio_id", None)
            st.session_state.pop("performance_cache", None)
            for key in list(st.session_state):
                if key in (f"return_period_{portfolio['id']}", f"history_start_{portfolio['id']}", f"history_end_{portfolio['id']}") or key.startswith(f"return_chart_{portfolio['id']}_"):
                    st.session_state.pop(key, None)
            st.session_state["portfolio_delete_notice"] = (
                "Portafolio eliminado junto con todas sus transacciones."
                if deleted.status_code == 204 else "El portafolio ya no esta disponible."
            )
            st.rerun()
        else:
            st.error("No se pudo eliminar el portafolio. Intenta de nuevo mas tarde.")

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

if notice := st.session_state.pop("portfolio_delete_notice", None):
    st.info(notice)

if notice := st.session_state.pop("portfolio_rename_notice", None):
    st.success(notice)

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
    selected_portfolio = None
else:
    portfolios_by_id = {portfolio["id"]: portfolio for portfolio in portfolios}
    portfolio_ids = list(portfolios_by_id)
    selected_id = st.session_state.get("selected_portfolio_id")
    if selected_id not in portfolios_by_id:
        selected_id = portfolio_ids[0]

    selected_id = st.selectbox(
        "Seleccionar portafolio",
        options=portfolio_ids,
        index=portfolio_ids.index(selected_id),
        format_func=lambda portfolio_id: portfolios_by_id[portfolio_id]["name"],
    )
    st.session_state["selected_portfolio_id"] = selected_id
    selected_portfolio = portfolios_by_id[selected_id]

if selected_portfolio:
    st.subheader(selected_portfolio["name"])
    analytics_action, rename_action, delete_action = st.columns([4, 1, 1])
    if analytics_action.button("Analitica del portafolio", icon=":material/analytics:"):
        st.switch_page("pages/5_portfolio_analytics.py")
    if rename_action.button("", icon=":material/edit:", help="Cambiar nombre del portafolio", key="open_rename_portfolio"):
        rename_portfolio(selected_portfolio)
    if delete_action.button("", icon=":material/delete:", help="Eliminar portafolio", key="open_delete_portfolio"):
        confirm_portfolio_deletion(selected_portfolio)
    holdings_tab, transactions_tab, closed_tab = st.tabs(
        ["Posiciones actuales", "Transacciones", "Transacciones cerradas"]
    )

    with holdings_tab:
        try:
            holdings_response = requests.get(
                f"{HOLDINGS_URL}/{selected_portfolio['id']}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
        except requests.RequestException:
            st.error("No se pudieron cargar las posiciones actuales.")
        else:
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
                st.session_state.pop("access_token", None)
                st.switch_page("pages/1_login.py")
            elif holdings_response.status_code == 404:
                st.error("El portafolio seleccionado ya no está disponible.")
            else:
                st.error("No se pudieron cargar las posiciones actuales.")

    with transactions_tab:
        if st.button("Agregar transacción"):
            st.switch_page("pages/4_edit_portfolio.py")

        try:
            transactions_response = requests.get(
                TRANSACTIONS_URL,
                params={"portfolio_id": selected_portfolio["id"]},
                headers={"Authorization": f"Bearer {token}"},
                timeout=5,
            )
        except requests.RequestException:
            st.error("No se pudieron cargar las transacciones.")
        else:
            if transactions_response.status_code == 200:
                transactions = transactions_response.json()
                if transactions:
                    st.dataframe(
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
                    )
                else:
                    st.info("Este portafolio todavía no tiene transacciones registradas.")
            elif transactions_response.status_code == 401:
                st.session_state.pop("access_token", None)
                st.switch_page("pages/1_login.py")
            elif transactions_response.status_code == 404:
                st.error("El portafolio seleccionado ya no está disponible.")
            else:
                st.error("No se pudieron cargar las transacciones.")

    with closed_tab:
        try:
            closed_response = requests.get(
                f"{TRANSACTIONS_URL}/closed",
                params={"portfolio_id": selected_portfolio["id"]},
                headers={"Authorization": f"Bearer {token}"},
                timeout=5,
            )
        except requests.RequestException:
            st.error("No se pudieron cargar las transacciones cerradas.")
        else:
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
                st.session_state.pop("access_token", None)
                st.switch_page("pages/1_login.py")
            elif closed_response.status_code == 404:
                st.error("El portafolio seleccionado ya no está disponible.")
            else:
                st.error("No se pudieron cargar las transacciones cerradas.")
