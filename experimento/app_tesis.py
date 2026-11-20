"""
App de demostración: usa la MISMA función generar_sql() y la misma ejecución que el experimento.
Correr con:  streamlit run app_tesis.py
"""
from dotenv import load_dotenv
load_dotenv()

import streamlit as st

from estrategias import ESTRATEGIAS, generar_sql
from experimento import ejecutar

NOMBRES = {"zero_shot": "Zero-shot", "few_shot": "Few-shot", "cot": "Chain-of-Thought",
           "optimizada_costo": "Optimizada-Costo"}

st.set_page_config(page_title="Query Agent", page_icon="🔍", layout="wide")
st.markdown("""
    <style>
        [data-testid="stSidebar"] * { color: #FFFFFF !important; }
        [data-testid="stChatInput"] textarea { color: #FFFFFF !important; }
        [data-testid="stChatMessage"] p { color: #FFFFFF !important; }
    </style>
""", unsafe_allow_html=True)

col1, col2 = st.columns([1, 5])
with col1:
    try:
        st.image("assets/r2-logo.png", width=120)
    except Exception:
        pass
with col2:
    st.title("Query Agent")
    st.caption("Preguntá en lenguaje natural sobre el dataset de la proptech")

with st.sidebar:
    estrategia = st.radio("Estrategia de prompting", ESTRATEGIAS, format_func=NOMBRES.get)
    st.divider()
    st.markdown("**Ejemplos:**")
    st.markdown("- ¿Cuántos listings hay publicados en Capital Federal?")
    st.markdown("- ¿Cuál es el precio por m2 en cada barrio de Capital Federal?")
    st.markdown("- ¿Cuál es el CPL por campaña en el último trimestre?")
    st.divider()
    if st.button("🗑️ Limpiar"):
        st.session_state.messages = []
        st.rerun()

# El historial es solo visual: cada pregunta se le manda al modelo sola, sin las anteriores,
# igual que en el experimento.
if "messages" not in st.session_state:
    st.session_state.messages = []
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

if pregunta := st.chat_input("Ej: ¿Cuántos leads se recibieron el mes pasado?"):
    with st.chat_message("user"):
        st.markdown(pregunta)
    st.session_state.messages.append({"role": "user", "content": pregunta})

    with st.chat_message("assistant"):
        with st.status(f"⚙️ Generando SQL ({NOMBRES[estrategia]})...", expanded=True) as status:
            g = generar_sql(pregunta, estrategia)
            st.code(g["sql"], language="sql")
            if estrategia == "cot":
                with st.expander("Ver razonamiento"):
                    st.markdown(g["respuesta"])
            try:
                st.write("🚀 Ejecutando en BigQuery...")
                df, m = ejecutar(g["sql"])
                status.update(label="✅ Listo", state="complete", expanded=False)
                error = None
            except Exception as e:
                status.update(label="❌ Error", state="error")
                error = str(e)

        if error:
            texto = f"La consulta falló:\n\n```\n{error}\n```"
            st.error(error)
        else:
            st.dataframe(df, use_container_width=True)
            c1, c2, c3 = st.columns(3)
            c1.metric("Tiempo total", f"{g['tiempo_llm_s'] + m['tiempo_bq_s']:.1f} s")
            c2.metric("Datos procesados", f"{m['mb_procesados']:,.1f} MB")
            c3.metric("Costo BigQuery", f"USD {m['costo_bq_usd']:.6f}")
            texto = f"```sql\n{g['sql']}\n```\n{len(df)} filas · {m['mb_procesados']:,.1f} MB · USD {m['costo_bq_usd']:.6f}"
    st.session_state.messages.append({"role": "assistant", "content": texto})
