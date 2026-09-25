"""Analytics tab: return curve, allocation and unrealized-gains charts."""

from datetime import date, datetime, timedelta
import math

import altair as alt
import pandas as pd
import requests
import streamlit as st

from components.transactions import add_transaction_dialog
from session import auth_headers, end_session, get_token


PORTFOLIOS_URL = "http://127.0.0.1:8000/api/portfolios"


def get_data(url, optional=False):
    """GET a JSON payload. On failure show an error (unless optional) and
    return None."""
    try:
        response = requests.get(url, headers=auth_headers(), timeout=30)
        if response.status_code == 401:
            end_session()
        if response.status_code == 404:
            if not optional:
                st.error("El portafolio seleccionado ya no esta disponible.")
            return None
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError):
        if not optional:
            st.error("No se pudo cargar la analitica. Intenta actualizar de nuevo.")
        return None


@st.fragment
def show_portfolio_history(portfolio_id):
    st.subheader("Rendimiento del portafolio")
    period = st.segmented_control(
        "Periodo", ["1W", "1M", "3M", "6M", "YTD", "1Y", "All"],
        default="3M", required=True, key=f"return_period_{portfolio_id}",
        label_visibility="collapsed",
    )
    end_date = date.today()
    cache = st.session_state.setdefault("performance_cache", {})

    def fetch(url, params):
        cache_key = ("dates_v2", get_token(), url, tuple(sorted(params.items())))
        cached = cache.get(cache_key)
        now = datetime.now().timestamp()
        if cached and now - cached[0] < 300:
            return cached[1]
        response = requests.get(url, params=params, headers=auth_headers(), timeout=60)
        if response.status_code == 401:
            end_session()
        if response.status_code == 422:
            detail = response.json().get("detail")
            raise ValueError(detail if isinstance(detail, str) else "Periodo no disponible.")
        response.raise_for_status()
        data = response.json()
        cache[cache_key] = (now, data)
        return data

    try:
        with st.spinner("Cargando rendimiento..."):
            if period == "All":
                transactions = fetch(
                    "http://127.0.0.1:8000/api/transactions",
                    {"portfolio_id": portfolio_id},
                )
                if not transactions:
                    st.info("No hay transacciones en este portafolio.")
                    return
                start_date = min(date.fromisoformat(t["transaction_date"][:10]) for t in transactions)
            elif period == "YTD":
                start_date = date(date.today().year, 1, 1) - timedelta(days=1)
            elif period == "1W":
                start_date = end_date - timedelta(days=7)
            else:
                months = {"1M": 1, "3M": 3, "6M": 6, "1Y": 12}[period]
                start_date = (pd.Timestamp(end_date) - pd.DateOffset(months=months)).date()
            if start_date > end_date:
                st.info("Todavia no hay suficientes datos para este periodo.")
                return
            payload = fetch(
                f"{PORTFOLIOS_URL}/{portfolio_id}/performance",
                {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
            )
        points = payload["points"]
        if not isinstance(points, list):
            raise ValueError("Historial invalido.")
        if not points:
            st.info("No hay historial disponible para este periodo.")
            return
        history = pd.DataFrame(points)[["date", "return_percentage"]]
        history["date"] = pd.to_datetime(history["date"], errors="raise")
        history["return_percentage"] = pd.to_numeric(history["return_percentage"], errors="raise")
        if history["date"].isna().any() or history["date"].duplicated().any() or not history["return_percentage"].map(math.isfinite).all():
            raise ValueError("Historial invalido.")
        history = history.sort_values("date")
    except requests.RequestException:
        st.error("No se pudo cargar el rendimiento. Intenta actualizar de nuevo.")
        return
    except (ValueError, KeyError, TypeError) as exc:
        st.warning(str(exc) if isinstance(exc, ValueError) else "El servidor devolvio un historial incompleto.")
        return

    history["day"] = history["date"].dt.strftime("%Y-%m-%d")
    history["return_ratio"] = history["return_percentage"] / 100
    last = history.iloc[-1]
    limited = history.iloc[0]["date"].date() > start_date
    period_label = "Desde la primera inversion" if limited or period == "All" else f"Rendimiento {period}"
    headline = st.empty()
    st.caption(f"{history.iloc[0]['day']} - {last['day']} | Rendimiento aproximado de las posiciones")
    if limited:
        st.caption(f"Periodo solicitado: {period}. Historial disponible desde la primera inversion: {history.iloc[0]['day']}.")
    if payload.get("provisional"):
        st.caption("Hoy: valor provisional con los ultimos precios disponibles.")
    older_prices = [
        f"{symbol}: {price_date or 'sin fecha'}"
        for symbol, price_date in payload.get("price_dates", {}).items()
        if price_date is None or price_date < last["day"]
    ]
    if older_prices:
        st.caption("Precios de una sesion anterior: " + ", ".join(older_prices))
    color = "#16806a" if last["return_percentage"] >= 0 else "#c44040"
    selection = alt.selection_point(
        name="selected_day", fields=["day"], nearest=True,
        on="click", clear="dblclick", empty=False,
    )
    base = alt.Chart(history).encode(
        x=alt.X("date:T", title=None),
        y=alt.Y("return_ratio:Q", title="Rendimiento", axis=alt.Axis(format=".1%")),
        tooltip=[alt.Tooltip("day:N", title="Fecha"), alt.Tooltip("return_ratio:Q", title="Rendimiento", format="+.2%")],
    )
    line = base.mark_line(color=color, strokeWidth=2, point=len(history) == 1)
    targets = base.mark_point(size=65, color=color).encode(
        opacity=alt.condition(selection, alt.value(1), alt.value(0)),
    ).add_params(selection)
    zero = alt.Chart(pd.DataFrame({"zero": [0]})).mark_rule(
        color="#999999", strokeDash=[4, 4],
    ).encode(y="zero:Q")
    chart = (zero + line + targets).properties(height=340)
    event = st.altair_chart(
        chart, width="stretch", on_select="rerun",
        selection_mode="selected_day",
        key=f"return_chart_{portfolio_id}_{period}_{start_date}_{end_date}",
    )
    selected = event.selection.get("selected_day", [])
    displayed = last
    if selected:
        matched = history[history["day"] == selected[0].get("day")]
        if not matched.empty:
            displayed = matched.iloc[0]
    with headline.container():
        selected_column, period_column = st.columns(2)
        selected_column.metric(
            f"Rendimiento al {displayed['day']}",
            f"{displayed['return_percentage']:+.2f}%",
        )
        period_column.metric(period_label, f"{last['return_percentage']:+.2f}%")


def render_analytics(portfolio):
    portfolio_id = portfolio["id"]

    if st.button("Actualizar", icon=":material/refresh:", help="Actualizar valores del portafolio"):
        st.session_state.pop("performance_cache", None)

    with st.spinner("Cargando analitica..."):
        payload = get_data(f"{PORTFOLIOS_URL}/{portfolio_id}/distribution")
    if payload is None:
        return

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
        return

    st.metric("Valor total de las posiciones", f"{total:,.2f}")
    st.caption(f"Datos consultados: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}")

    show_portfolio_history(portfolio_id)

    if not rows:
        st.info("Este portafolio todavia no tiene posiciones abiertas.")
        if st.button("Agregar transaccion", icon=":material/add:", key="analytics_add_transaction"):
            add_transaction_dialog(portfolio)
        return

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
