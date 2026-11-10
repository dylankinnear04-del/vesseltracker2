"""webapp.state: URL parameters and per-visitor detection settings (run inside AppTest scripts)."""
from streamlit.testing.v1 import AppTest


def _run(script, params=None):
    at = AppTest.from_function(script)
    for k, v in (params or {}).items():
        at.query_params[k] = v
    at.run()
    assert not at.exception, at.exception
    return at


def test_param_rejects_unknown_value():
    def script():
        import streamlit as st
        from webapp import state
        st.write(state.param("group", ("mining", "china", "all"), "mining"))
    at = _run(script, {"group": "foo"})
    assert at.markdown[0].value == "mining"


def test_param_accepts_known_value():
    def script():
        import streamlit as st
        from webapp import state
        st.write(state.param("group", ("mining", "china", "all"), "mining"))
    at = _run(script, {"group": "china"})
    assert at.markdown[0].value == "china"


def test_int_param_bad_value():
    def script():
        import streamlit as st
        from webapp import state
        st.write(repr(state.int_param("area")), repr(state.int_param("n", 5)))
    at = _run(script, {"area": "abc", "n": "x"})
    assert at.markdown[0].value == "None 5"


def test_int_param_good_value():
    def script():
        import streamlit as st
        from webapp import state
        st.write(repr(state.int_param("area")))
    at = _run(script, {"area": "7"})
    assert at.markdown[0].value == "7"


def test_set_params_none_removes_key():
    def script():
        from webapp import state
        state.set_params(area=None, group="china")
    at = _run(script, {"area": "7"})
    assert "area" not in at.query_params
    assert at.query_params["group"] == ["china"] or at.query_params["group"] == "china"


def test_is_custom_after_change_and_reset():
    def script():
        import streamlit as st
        from webapp import state
        out = [state.is_custom()]
        state.settings()["min_lines_per_block"] = 99
        out.append(state.is_custom())
        state.reset_settings()
        out.append(state.is_custom())
        st.write(str(out))
    at = _run(script)
    assert at.markdown[0].value == "[False, True, False]"
