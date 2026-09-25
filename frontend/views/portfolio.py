"""Portfolio section: create or pick a portfolio and browse it in tabs."""

import requests
import streamlit as st

from components.analytics import render_analytics
from components.closed_transactions import render_closed_transactions
from components.holdings import render_holdings
from components.transactions import render_transactions
from session import auth_headers, end_session

PORTFOLIOS_URL = "http://127.0.0.1:8000/api/portfolios"


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
                headers=auth_headers(),
                json={"name": name}, timeout=15,
            )
    except requests.RequestException:
        st.error("No se pudo confirmar el cambio. Revisa el nombre del portafolio antes de intentarlo de nuevo.")
        return
    if updated.status_code == 200:
        st.session_state["selected_portfolio_id"] = portfolio["id"]
        st.session_state["portfolio_rename_notice"] = "Nombre del portafolio actualizado."
        st.rerun()
    elif updated.status_code == 401:
        end_session()
    elif updated.status_code == 409:
        st.error("Ya tienes un portafolio con ese nombre.")
    elif updated.status_code == 422:
        st.error("Introduce un nombre valido de 1 a 100 caracteres.")
    elif updated.status_code == 404:
        st.error("El portafolio ya no esta disponible. Cierra este dialogo.")
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
                    headers=auth_headers(),
                    timeout=15,
                )
        except requests.RequestException:
            st.error("No se pudo confirmar la eliminacion. Cierra este dialogo y revisa la lista de portafolios antes de intentarlo de nuevo.")
            return
        if deleted.status_code == 401:
            end_session()
        elif deleted.status_code in (204, 404):
            st.session_state.pop("selected_portfolio_id", None)
            st.session_state.pop("performance_cache", None)
            for key in list(st.session_state):
                if key == f"return_period_{portfolio['id']}" or key.startswith(f"return_chart_{portfolio['id']}_"):
                    st.session_state.pop(key, None)
            st.session_state["portfolio_delete_notice"] = (
                "Portafolio eliminado junto con todas sus transacciones."
                if deleted.status_code == 204 else "El portafolio ya no esta disponible."
            )
            st.rerun()
        else:
            st.error("No se pudo eliminar el portafolio. Intenta de nuevo mas tarde.")


def create_portfolio(name):
    """Create a portfolio and select it. Return True on success; otherwise
    show the error and return False."""
    name = name.strip()
    if not name:
        st.error("Introduce un nombre para el portafolio.")
        return False
    try:
        created = requests.post(
            url=PORTFOLIOS_URL,
            headers=auth_headers(),
            json={"name": name},
            timeout=5,
        )
    except requests.RequestException:
        st.error("No se pudo conectar con el servidor.")
        return False
    if created.status_code == 201:
        st.session_state["selected_portfolio_id"] = created.json()["id"]
        return True
    if created.status_code == 401:
        end_session()
    if created.status_code == 406:
        st.error("Ya tienes un portafolio con ese nombre.")
    else:
        st.error("No se pudo crear el portafolio.")
    return False


st.title("Portfolio")

if notice := st.session_state.pop("portfolio_delete_notice", None):
    st.info(notice)

if notice := st.session_state.pop("portfolio_rename_notice", None):
    st.success(notice)

try:
    portfolios_response = requests.get(
        url=PORTFOLIOS_URL,
        headers=auth_headers(),
        timeout=5,
    )
except requests.RequestException:
    st.error("No se pudieron cargar los portafolios.")
    st.stop()

if portfolios_response.status_code == 401:
    end_session()
if portfolios_response.status_code != 200:
    st.error("No se pudieron cargar los portafolios.")
    st.stop()

portfolios = portfolios_response.json()

if not portfolios:
    # Empty state: the only thing to do is create the first portfolio.
    st.info("No portfolios yet. Create a portfolio")
    with st.form("create_first_portfolio"):
        portfolio_name = st.text_input("Nombre del portafolio", max_chars=100)
        submitted = st.form_submit_button("Create portfolio", type="primary")
    if submitted and create_portfolio(portfolio_name):
        st.rerun()
    st.stop()

portfolios_by_id = {portfolio["id"]: portfolio for portfolio in portfolios}
portfolio_ids = list(portfolios_by_id)
selected_id = st.session_state.get("selected_portfolio_id")
if selected_id not in portfolios_by_id:
    selected_id = portfolio_ids[0]

selector_column, rename_column, delete_column, create_column = st.columns(
    [6, 1, 1, 2], vertical_alignment="bottom"
)
selected_id = selector_column.selectbox(
    "Seleccionar portafolio",
    options=portfolio_ids,
    index=portfolio_ids.index(selected_id),
    format_func=lambda portfolio_id: portfolios_by_id[portfolio_id]["name"],
)
st.session_state["selected_portfolio_id"] = selected_id
selected_portfolio = portfolios_by_id[selected_id]

if rename_column.button("", icon=":material/edit:", help="Cambiar nombre del portafolio", key="open_rename_portfolio", width="stretch"):
    rename_portfolio(selected_portfolio)
if delete_column.button("", icon=":material/delete:", help="Eliminar portafolio", key="open_delete_portfolio", width="stretch"):
    confirm_portfolio_deletion(selected_portfolio)
if create_column.button("Crear portafolio", icon=":material/add:", width="stretch"):
    st.session_state["show_create_portfolio"] = not st.session_state.get("show_create_portfolio", False)

if st.session_state.get("show_create_portfolio", False):
    with st.form("create_portfolio"):
        portfolio_name = st.text_input("Nombre del portafolio", max_chars=100)
        submitted = st.form_submit_button("Crear")
    if submitted and create_portfolio(portfolio_name):
        st.session_state["show_create_portfolio"] = False
        st.rerun()

# on_change="rerun" makes the tabs stateful: only the open tab runs, so the
# other tabs don't refetch prices, and the key keeps the chosen tab when the
# selected portfolio changes.
overview_tab, holdings_tab, transactions_tab, closed_tab, analytics_tab = st.tabs(
    ["Overview", "Holdings", "Transactions", "Closed Transactions", "Analytics"],
    key="portfolio_tab",
    on_change="rerun",
)

with overview_tab:
    if overview_tab.open:
        st.info("Pending")

with holdings_tab:
    if holdings_tab.open:
        render_holdings(selected_portfolio["id"])

with transactions_tab:
    if transactions_tab.open:
        render_transactions(selected_portfolio)

with closed_tab:
    if closed_tab.open:
        render_closed_transactions(selected_portfolio["id"])

with analytics_tab:
    if analytics_tab.open:
        render_analytics(selected_portfolio)
