"""Overview tab: plain-language summary of the portfolio, written by an LLM.

The summary is generated only when the user clicks the button (each call
uses the model's quota and takes several seconds), then kept in
`summary_cache` in session state per portfolio, so switching tabs or
portfolios doesn't call the model again. Adding or deleting a transaction
drops that portfolio's cached summary (see forget_summary).
"""

from datetime import datetime

import requests
import streamlit as st

from session import auth_headers, end_session

PORTFOLIOS_URL = "http://127.0.0.1:8000/api/portfolios"

# Longer than the backend can take (price lookups plus up to two LLM
# attempts of 60 s each), so the backend's clean 503 arrives before this
# gives up.
SUMMARY_TIMEOUT = 150


def forget_summary(portfolio_id):
    """Drop a portfolio's cached summary, e.g. after its transactions change."""
    st.session_state.get("summary_cache", {}).pop(portfolio_id, None)


def request_summary(portfolio_id):
    """Ask the backend for a new summary and cache it.

    Shows any error itself and returns True only when a summary was cached.
    """
    try:
        with st.spinner("Generando el resumen... puede tardar hasta un minuto."):
            response = requests.post(
                f"{PORTFOLIOS_URL}/{portfolio_id}/summary",
                headers=auth_headers(),
                timeout=SUMMARY_TIMEOUT,
            )
    except requests.Timeout:
        st.warning("El resumen tardó demasiado. Intenta de nuevo en unos minutos.")
        return False
    except requests.RequestException:
        st.error("No se pudo generar el resumen. Intenta de nuevo más tarde.")
        return False

    if response.status_code == 200:
        st.session_state.setdefault("summary_cache", {})[portfolio_id] = {
            "text": response.json()["summary"],
            "generated_at": datetime.now(),
        }
        return True
    if response.status_code == 401:
        end_session()
    elif response.status_code == 404:
        st.error("El portafolio seleccionado ya no está disponible.")
    elif response.status_code == 400:
        st.error("El historial de transacciones tiene un error; revisa la pestaña Transactions.")
    elif response.status_code == 503:
        st.warning("El resumen no está disponible en este momento. Intenta de nuevo en unos minutos.")
    else:
        st.error("No se pudo generar el resumen. Intenta de nuevo más tarde.")
    return False


def render_overview(portfolio):
    st.subheader("Resumen del portafolio")
    cached = st.session_state.get("summary_cache", {}).get(portfolio["id"])

    if cached is None:
        st.write(
            "Obtén una explicación en lenguaje sencillo de tu portafolio: cómo está "
            "repartido, cuánto ganas o pierdes y cómo le ha ido en el último año."
        )
        # On success, rerun so the page redraws in the "summary shown" state.
        if st.button("Explicar mi portafolio", icon=":material/auto_awesome:", type="primary") \
                and request_summary(portfolio["id"]):
            st.rerun()
        return

    with st.container(border=True):
        # "$" would start a LaTeX formula in st.markdown, so escape it.
        st.markdown(cached["text"].replace("$", r"\$"))
    st.caption(
        f"Generado por IA a las {cached['generated_at']:%H:%M}. "
        "Es una explicación de tus datos, no una asesoría financiera."
    )
    # Rerun only on success: a rerun would wipe the error message, and on
    # failure the previous summary simply stays.
    if st.button("Regenerar", icon=":material/refresh:") and request_summary(portfolio["id"]):
        st.rerun()
