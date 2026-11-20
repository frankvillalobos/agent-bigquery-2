"""
Las 4 estrategias de prompting y la función única de generación de SQL.

La usan tanto el experimento (experimento.py) como la app (app_tesis.py),
así lo que se mide es exactamente lo que hace la herramienta.
"""
import json
import os
import re
import time

from openai import OpenAI

MODELO = "gpt-4o"
TEMPERATURA = 0
SEED = 2026  # OpenAI usa la semilla para respuestas más reproducibles (no lo garantiza al 100%)

_DIR = os.path.dirname(os.path.abspath(__file__))
ESQUEMA = open(os.path.join(_DIR, "esquema.md"), encoding="utf-8").read()
EJEMPLOS = json.load(open(os.path.join(_DIR, "ejemplos_few_shot.json"), encoding="utf-8"))

BASE = (
    "Sos un analista de datos experto en Google BigQuery. Tu tarea es traducir una pregunta de negocio "
    "en una única consulta SQL (BigQuery Standard SQL) que la responda.\n\n"
    "# Esquema y reglas\n" + ESQUEMA
)
FORMATO = ("Respondé con la consulta SQL final dentro de un único bloque ```sql ... ```. "
           "Solo consultas de lectura (SELECT / WITH).")

INSTRUCCIONES = {
    "zero_shot": FORMATO + " No agregues explicaciones.",

    "few_shot": "Estos son ejemplos de preguntas resueltas sobre el mismo dataset:\n\n" + "\n\n".join(
        f"Pregunta: {e['pregunta']}\n```sql\n{e['sql']}\n```" for e in EJEMPLOS
    ) + "\n\n" + FORMATO + " No agregues explicaciones.",

    "cot": (
        "Antes de escribir el SQL, razoná paso a paso y por escrito:\n"
        "1. Qué tablas y columnas necesitás.\n"
        "2. Qué reglas del modelo de datos aplican (fotos semanales, leads borrados, monedas, fechas).\n"
        "3. Qué filtros, uniones y agregaciones hacen falta.\n"
        "4. Cómo verificar que el resultado responde exactamente la pregunta.\n"
        "Después escribí la consulta final. " + FORMATO
    ),

    "optimizada_costo": (
        "BigQuery cobra por los bytes que lee cada consulta, así que además de correcta tiene que ser eficiente:\n"
        "- Leé solo las columnas que necesitás; nunca uses SELECT *.\n"
        "- Filtrá por fecha o período lo antes posible (event_date, fecha_lead, periodo, semana_inicio).\n"
        "- Filtrá y agregá cada tabla en un CTE antes de unirla con otra.\n"
        "- Usá la tabla más chica que responda la pregunta (por ejemplo, leads en vez de ga4 para contar leads).\n"
        "- Evitá subconsultas repetidas sobre la misma tabla.\n" + FORMATO + " No agregues explicaciones."
    ),
}
ESTRATEGIAS = list(INSTRUCCIONES)


def armar_mensajes(pregunta, estrategia):
    return [
        {"role": "system", "content": BASE + "\n\n# Instrucciones\n" + INSTRUCCIONES[estrategia]},
        {"role": "user", "content": f"Pregunta: {pregunta}"},
    ]


def extraer_sql(texto):
    """Toma el último bloque ```sql``` de la respuesta (en CoT el razonamiento va antes)."""
    bloques = re.findall(r"```(?:sql)?\s*(.*?)```", texto or "", flags=re.S | re.I)
    sql = bloques[-1] if bloques else (texto or "")
    return sql.strip().rstrip(";").strip()


def generar_sql(pregunta, estrategia, cliente=None):
    """Devuelve dict con sql, respuesta completa, tokens y tiempo del LLM. Sin historial: cada pregunta es independiente."""
    cliente = cliente or OpenAI()
    t0 = time.perf_counter()
    r = cliente.chat.completions.create(
        model=MODELO,
        messages=armar_mensajes(pregunta, estrategia),
        temperature=TEMPERATURA,
        seed=SEED,
    )
    dt = time.perf_counter() - t0
    texto = r.choices[0].message.content
    return {
        "sql": extraer_sql(texto),
        "respuesta": texto,
        "tiempo_llm_s": round(dt, 3),
        "tokens_entrada": r.usage.prompt_tokens,
        "tokens_salida": r.usage.completion_tokens,
        "modelo": r.model,
        "system_fingerprint": getattr(r, "system_fingerprint", None),
    }
