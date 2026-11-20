from dotenv import load_dotenv
load_dotenv()

import streamlit as st
import json
import os
from openai import OpenAI
from bigquery_client import BigQueryClient

# ── Configuración de página ───────────────────────────────────────────────────
st.set_page_config(
    page_title="Asistente de datos",
    page_icon="🔍",
    layout="wide"
)

# ── CSS personalizado ─────────────────────────────────────────────────────────
st.markdown("""
    <style>
        [data-testid="stSidebar"] * {
            color: #FFFFFF !important;
        }
        /* Texto del input del chat en negro */
        [data-testid="stChatInput"] textarea {
            color: #FFFFFF !important;
        }
        /* Respuesta del asistente en blanco */
        [data-testid="stChatMessage"] p {
            color: #FFFFFF !important;
        }
    </style>
""", unsafe_allow_html=True)

# ── Logo y título  ←  AQUÍ, fuera del set_page_config ────────────────────────
col1, col2 = st.columns([1, 5])
with col1:
    if os.path.exists("assets/r2-logo.png"):
        st.image("assets/r2-logo.png", width=120)
with col2:
    st.title("Asistente de datos")
    st.caption("Preguntá en lenguaje natural y te respondo con el dato y la query")

PROJECT_ID = "uean-493522"
DATASET_ID = "proptech"
MAX_PASOS = 8  # evita que el agente quede en un loop infinito

# Reglas que el esquema solo (columnas y tipos) no le dice al modelo
REGLAS = """
Data model rules (the schema alone does not tell you this):
- `listings` and `usuarios` are weekly snapshots: the same entity appears in many rows. Count with COUNT(DISTINCT listing_id) / COUNT(DISTINCT user_id).
- Listings stock for a month: periodo = YYYYMM AND aviso_online_al_cierre = 1. "Published listings" with no other detail = stock online at the close of the last month with data (202610).
- In Capital Federal, the column `ciudad` holds the neighborhood (Palermo, Belgrano...); `barrio` is a sub-zone. "CABA" = provincia 'Capital Federal'.
- Sale prices are in USD; rentals mix ARS and USD. precio = 0 means "price on request". superficie_m2 can be 0 (use SAFE_DIVIDE).
- In `leads`, always exclude deleted leads (lead_borrado = 0).
- In `ga4`, count events with SUM(total_events) and sessions with COUNT(DISTINCT unique_session_id). Listing visits = page_view with content_group = 'aviso'.
- `gasto` (ARS) is only in session_start rows of paid sessions (session_medium = 'cpc' or 'paid_social'). Investment = SUM(gasto).
- Joins: leads.listing_id (STRING) = listings.listing_id (INT64) needs CAST; ga4.lead_id (STRING) = leads.lead_id (INT64) needs CAST.
- Data goes from 2025-10-01 to 2026-10-31. A month without a year means the most recent one with data. "Last month" = October 2026.
- Never use SELECT *; read only the columns you need.
"""


def a_texto(x) -> str:
    """El contenido de un mensaje 'tool' tiene que ser texto."""
    return x if isinstance(x, str) else json.dumps(x, default=str, ensure_ascii=False)

# ── Historial de chat ────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []

if "api_messages" not in st.session_state:
    st.session_state.api_messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ── Función del agente ───────────────────────────────────────────────────────
def run_agent(user_question: str) -> str:
    client = OpenAI()
    bq = BigQueryClient(PROJECT_ID)
    tools = get_tools_openai(PROJECT_ID, DATASET_ID)

    system_prompt = f"""You are an expert data analyst in BigQuery.
Available dataset: project `{PROJECT_ID}`, dataset `{DATASET_ID}`.

Process you MUST ALWAYS follow:
1. Call get_schema to see the available tables.
2. Build the correct SQL based on the schema.
3. Call run_sql_query with that SQL.
4. In your final response, ALWAYS in Spanish:
   - First, the answer in one or two clear sentences (e.g. "En octubre de 2026 hubo 1.234 leads.")
   - Then, the SQL query generated in a SQL code block

Use BigQuery Standard SQL with full table names:
`{PROJECT_ID}.{DATASET_ID}.table_name`
{REGLAS}"""

    st.session_state.api_messages.append({
        "role": "user",
        "content": user_question
    })

    messages = [
        {"role": "system", "content": system_prompt}
    ] + st.session_state.api_messages

    with st.status("⚙️ Buscando la respuesta...", expanded=True) as status:

        for _ in range(MAX_PASOS):
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0
            )

            msg = response.choices[0].message

            if not msg.tool_calls:
                status.update(label="✅ Listo", state="complete", expanded=False)
                answer = msg.content or ""
                # Guardar la respuesta para que las preguntas siguientes tengan contexto
                st.session_state.api_messages.append({"role": "assistant", "content": answer})
                return answer

            messages.append(msg)

            for tool_call in msg.tool_calls:
                fn = getattr(tool_call, "function", None)
                if fn is None:
                    continue
                tool_name = fn.name
                tool_input = json.loads(fn.arguments)

                if tool_name == "get_schema":
                    st.write("📋 Leyendo el esquema...")
                    try:
                        result = a_texto(bq.get_schema(DATASET_ID))
                    except Exception as e:
                        result = f"Error reading schema: {e}"

                elif tool_name == "run_sql_query":
                    sql = tool_input.get("sql", "")
                    st.write("🚀 Ejecutando la query en BigQuery...")
                    st.code(sql, language="sql")

                    try:
                        if not BigQueryClient.is_safe_query(sql):
                            result = "Error: query not allowed."
                            st.error("La consulta no está permitida (solo se permiten consultas de lectura).")
                        else:
                            rows = bq.run_query(sql)
                            result = a_texto(list(rows)[:50])
                            st.write(f"📊 {len(rows)} filas obtenidas.")
                    except Exception as e:
                        result = f"Error running SQL: {e}"
                        st.warning("La consulta dio error, el agente va a intentar corregirla.")
                else:
                    result = f"Unknown tool: {tool_name}"

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result
                })

        status.update(label="⚠️ No pude completar la respuesta", state="error")

    answer = "No pude completar la respuesta. Probá escribir la pregunta de otra forma."
    st.session_state.api_messages.append({"role": "assistant", "content": answer})
    return answer

# ── Formato de tools para OpenAI ─────────────────────────────────────────────
def get_tools_openai(project_id: str, dataset_id: str) -> list:
    return [
        {
            "type": "function",
            "function": {
                "name": "get_schema",
                "description": (
                    "Gets the BigQuery dataset schema: tables and columns. "
                    "Call this FIRST before generating any SQL."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "run_sql_query",
                "description": (
                    f"Executes a SQL query in BigQuery. "
                    f"Project: `{project_id}`, dataset: `{dataset_id}`."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sql": {
                            "type": "string",
                            "description": "Valid BigQuery Standard SQL query."
                        }
                    },
                    "required": ["sql"]
                }
            }
        }
    ]

# ── Input del usuario ────────────────────────────────────────────────────────
if prompt := st.chat_input("Ej: ¿Cuántos leads hubo en octubre?"):

    with st.chat_message("user"):
        st.markdown(prompt)

    st.session_state.messages.append({
        "role": "user",
        "content": prompt
    })

    with st.chat_message("assistant"):
        answer = run_agent(prompt)
        st.markdown(answer)

    st.session_state.messages.append({
        "role": "assistant",
        "content": answer
    })

# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.divider()
    st.markdown("**Preguntas de ejemplo:**")
    st.markdown("- ¿Cuántas sesiones hubo el mes pasado?")
    st.markdown("- ¿Cuántos leads hubo en CABA en octubre?")

    st.divider()
    if st.button("🗑️ Nueva conversación"):
        st.session_state.messages = []
        st.session_state.api_messages = []
        st.rerun()