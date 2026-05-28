"""Entrypoint Streamlit (spec 09 tanda 3).

Correr con:
    .venv/Scripts/python.exe -m streamlit run src/puts_screener/streamlit_app/app.py
"""

import streamlit as st

from puts_screener.config_streamlit import STREAMLIT_PAGE_ICON, STREAMLIT_PAGE_TITLE
from puts_screener.streamlit_app.filters import apply_filters
from puts_screener.streamlit_app.views import (
    _cached_candidate_detail,
    _cached_run_candidates,
    render_candidate_detail,
    render_candidates_table,
    render_sidebar_filters,
    render_sidebar_run_selector,
)


def main() -> None:
    st.set_page_config(
        page_title=STREAMLIT_PAGE_TITLE,
        page_icon=STREAMLIT_PAGE_ICON,
        layout="wide",
    )
    st.title(STREAMLIT_PAGE_TITLE)

    run_id = render_sidebar_run_selector()
    rows = _cached_run_candidates(run_id)
    filter_state = render_sidebar_filters(rows)
    filtered = apply_filters(rows, filter_state)

    selected_ticker = render_candidates_table(filtered)
    if selected_ticker:
        detail = _cached_candidate_detail(run_id, selected_ticker)
        st.divider()
        render_candidate_detail(detail)


if __name__ == "__main__":
    main()
