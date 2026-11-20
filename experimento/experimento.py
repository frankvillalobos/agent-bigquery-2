"""
Experimento: 16 preguntas x 4 estrategias x 3 repeticiones.

Paso 1 (una vez):  python experimento.py referencia
    Corre las consultas de consultas_referencia.sql y guarda el ground truth en referencia/.
Paso 2 (piloto):   python experimento.py correr --preguntas Q01,Q05 --repeticiones 1
Paso 3 (completo): python experimento.py correr

El log queda en resultados/log_ejecuciones.csv (una fila por ejecución) y el resultado de
cada consulta en resultados/salidas/. Si se corta, volvé a correr el mismo comando: saltea
lo que ya está hecho.
"""
import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime

import numpy as np
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

PROYECTO = "uean-493522"
MAX_BYTES_FACTURADOS = 5 * 10**9      # corta cualquier consulta que fuera a leer más de 5 GB
USD_POR_TIB = 6.25                    # tarifa on-demand de BigQuery
PRECIO_LLM_ENTRADA = 2.50 / 1e6       # USD por token de entrada de gpt-4o (verificalo en tu panel de OpenAI)
PRECIO_LLM_SALIDA = 10.00 / 1e6       # USD por token de salida
TOPE_GASTO_LLM_USD = 4.00             # el experimento se detiene si el gasto en OpenAI supera esto

DIR = os.path.dirname(os.path.abspath(__file__))
REF_DIR = os.path.join(DIR, "referencia")
RES_DIR = os.path.join(DIR, "resultados")
SAL_DIR = os.path.join(RES_DIR, "salidas")
LOG = os.path.join(RES_DIR, "log_ejecuciones.csv")
CAMPOS = ["ejecucion_id", "fecha_hora", "pregunta_id", "nivel", "estrategia", "repeticion", "modelo",
          "temperatura", "sql_generado", "error", "filas_devueltas", "correcto", "mismas_columnas",
          "tiempo_llm_s", "tiempo_bq_s", "tiempo_total_s", "bytes_procesados", "bytes_facturados",
          "mb_procesados", "costo_bq_usd", "slot_ms", "tokens_entrada", "tokens_salida", "costo_llm_usd",
          "system_fingerprint"]


# ------------------------------------------------------------------ BigQuery
_bq = None


def bq():
    global _bq
    if _bq is None:
        from google.cloud import bigquery
        _bq = bigquery.Client(project=PROYECTO)
    return _bq


def es_segura(sql):
    s = re.sub(r"--.*?$|/\*.*?\*/", "", sql, flags=re.S | re.M).strip().lower()
    prohibidas = r"\b(insert|update|delete|merge|drop|create|alter|truncate|grant|revoke)\b"
    return s.startswith(("select", "with", "(")) and not re.search(prohibidas, s)


def ejecutar(sql):
    """Ejecuta sin caché. Devuelve (DataFrame, métricas)."""
    from google.cloud import bigquery
    if not es_segura(sql):
        raise ValueError("consulta no permitida (solo SELECT/WITH)")
    cfg = bigquery.QueryJobConfig(use_query_cache=False, maximum_bytes_billed=MAX_BYTES_FACTURADOS)
    t0 = time.perf_counter()
    job = bq().query(sql, job_config=cfg)
    df = job.result().to_dataframe(create_bqstorage_client=False)
    dt = time.perf_counter() - t0
    b = job.total_bytes_processed or 0
    bf = job.total_bytes_billed or 0
    return df, {
        "tiempo_bq_s": round(dt, 3),
        "bytes_procesados": b,
        "bytes_facturados": bf,
        "mb_procesados": round(b / 2**20, 2),
        "costo_bq_usd": round(bf / 2**40 * USD_POR_TIB, 8),
        "slot_ms": job.slot_millis,
    }


# ------------------------------------------------------------------ comparación
def _decimales(v):
    """Cantidad de decimales con que está expresado un vector numérico (0 a 6)."""
    v = v[~np.isnan(v)]
    for d in range(7):
        if np.all(np.abs(v - np.round(v, d)) < 1e-9):
            return d
    return 6


def _normalizar(col):
    s = pd.Series(col).reset_index(drop=True)
    num = pd.to_numeric(s.map(lambda v: float(v) if hasattr(v, "is_finite") else v), errors="coerce")
    if s.notna().sum() > 0 and num.notna().sum() == s.notna().sum():
        return "num", np.sort(num.to_numpy(dtype=float))
    txt = s.map(lambda v: "" if pd.isna(v) else (str(int(v)) if isinstance(v, float) and v.is_integer() else str(v).strip()))
    return "txt", np.sort(txt.to_numpy(dtype=str))


def _iguales(a, b):
    ta, va = a
    tb, vb = b
    if len(va) != len(vb):
        return False
    if ta == tb == "num":
        # Se compara con la precisión de la columna menos precisa: si la referencia está redondeada
        # a 2 decimales y la respuesta no (o al revés), ambas se redondean a la misma cantidad.
        # También acepta el mismo porcentaje expresado como fracción (6,63 vs 0,0663).
        for f in (1, 100, 0.01):
            vbf = np.sort(vb * f)
            d = min(_decimales(va), _decimales(vbf))
            if np.all(np.isclose(np.round(va, d), np.round(vbf, d), rtol=0, atol=10.0 ** -d * 0.51, equal_nan=True)):
                return True
        return False
    if ta != tb:  # un lado numérico y otro texto (p. ej. listing_id INT vs STRING)
        to_txt = lambda t, v: np.sort(np.array([str(int(x)) if t == "num" and not np.isnan(x) and float(x).is_integer() else str(x) for x in v]))
        return bool(np.array_equal(to_txt(ta, va), to_txt(tb, vb)))
    return bool(np.array_equal(va, vb))


def comparar(ref, gen, claves=None):
    """Correcto si tiene la misma cantidad de filas que la referencia y cada columna CLAVE de la
    referencia (las que responden la pregunta) aparece en la respuesta con los mismos valores.
    No importan los nombres de columnas, el orden de las filas ni las columnas extra.
    mismas_columnas indica si además coincide la cantidad total de columnas."""
    claves = [c for c in (claves or list(ref.columns)) if c in ref.columns]
    misma_cant = int(ref.shape[1] == gen.shape[1])
    if len(ref) != len(gen):
        return 0, misma_cant
    cols_gen = [_normalizar(gen[c]) for c in gen.columns]
    usadas = set()
    for c in claves:
        r = _normalizar(ref[c])
        match = next((i for i, g in enumerate(cols_gen) if i not in usadas and _iguales(r, g)), None)
        if match is None:
            return 0, misma_cant
        usadas.add(match)
    return 1, misma_cant


# ------------------------------------------------------------------ referencia
def leer_referencias():
    sql = open(os.path.join(DIR, "consultas_referencia.sql"), encoding="utf-8").read()
    partes = re.split(r"\n(?=-- Q\d\d \|)", sql)[1:]
    return {p[3:6]: p.strip().rstrip(";") for p in partes}


def cmd_referencia(_):
    os.makedirs(REF_DIR, exist_ok=True)
    filas = []
    for qid, sql in leer_referencias().items():
        df, m = ejecutar(sql)
        df.to_csv(os.path.join(REF_DIR, f"{qid}.csv"), index=False)
        filas.append({"pregunta_id": qid, "filas": len(df), **m})
        print(f"{qid}: {len(df)} filas, {m['mb_procesados']} MB, {m['tiempo_bq_s']} s")
    pd.DataFrame(filas).to_csv(os.path.join(REF_DIR, "metricas_referencia.csv"), index=False)
    print("\nGround truth guardado en referencia/")


# ------------------------------------------------------------------ experimento
def cmd_correr(a):
    from estrategias import ESTRATEGIAS, MODELO, TEMPERATURA, generar_sql
    from openai import OpenAI

    preguntas = json.load(open(os.path.join(DIR, "preguntas.json"), encoding="utf-8"))
    if a.preguntas:
        ids = a.preguntas.split(",")
        preguntas = [p for p in preguntas if p["id"] in ids]
    estrategias = a.estrategias.split(",") if a.estrategias else ESTRATEGIAS
    if not os.path.exists(os.path.join(REF_DIR, "Q01.csv")):
        sys.exit("Falta el ground truth: corré primero  python experimento.py referencia")

    os.makedirs(SAL_DIR, exist_ok=True)
    hechas, gasto_llm, sig_id = set(), 0.0, 1
    if os.path.exists(LOG):
        prev = pd.read_csv(LOG)
        hechas = set(zip(prev.pregunta_id, prev.estrategia, prev.repeticion))
        gasto_llm = prev.costo_llm_usd.fillna(0).sum()
        sig_id = int(prev.ejecucion_id.max()) + 1
    nuevo = not os.path.exists(LOG)
    f = open(LOG, "a", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=CAMPOS)
    if nuevo:
        w.writeheader()

    cliente = OpenAI()
    total = len(preguntas) * len(estrategias) * a.repeticiones
    n = 0
    # Orden: repetición -> pregunta -> estrategia (las estrategias se alternan, no corren en bloque)
    for rep in range(1, a.repeticiones + 1):
        for p in preguntas:
            ref = pd.read_csv(os.path.join(REF_DIR, f"{p['id']}.csv"))
            for est in estrategias:
                n += 1
                if (p["id"], est, rep) in hechas:
                    continue
                if gasto_llm >= TOPE_GASTO_LLM_USD:
                    print(f"Se alcanzó el tope de gasto en OpenAI (USD {TOPE_GASTO_LLM_USD}). Subilo para continuar.")
                    f.close()
                    return
                fila = {c: None for c in CAMPOS}
                fila.update(ejecucion_id=sig_id, fecha_hora=datetime.now().isoformat(timespec="seconds"),
                            pregunta_id=p["id"], nivel=p["nivel"], estrategia=est, repeticion=rep,
                            modelo=MODELO, temperatura=TEMPERATURA, correcto=0)
                try:
                    g = generar_sql(p["pregunta"], est, cliente)
                    fila.update(sql_generado=g["sql"], tiempo_llm_s=g["tiempo_llm_s"], modelo=g["modelo"],
                                tokens_entrada=g["tokens_entrada"], tokens_salida=g["tokens_salida"],
                                system_fingerprint=g["system_fingerprint"])
                    fila["costo_llm_usd"] = round(g["tokens_entrada"] * PRECIO_LLM_ENTRADA + g["tokens_salida"] * PRECIO_LLM_SALIDA, 6)
                    gasto_llm += fila["costo_llm_usd"]
                    try:
                        df, m = ejecutar(g["sql"])
                        fila.update(m)
                        fila["filas_devueltas"] = len(df)
                        fila["correcto"], fila["mismas_columnas"] = comparar(ref, df, p.get("columnas_clave"))
                        df.to_csv(os.path.join(SAL_DIR, f"{p['id']}_{est}_r{rep}.csv"), index=False)
                    except Exception as e:
                        fila["error"] = str(e).replace("\n", " ")[:500]
                except Exception as e:
                    fila["error"] = f"LLM: {e}"[:500]
                fila["tiempo_total_s"] = round((fila["tiempo_llm_s"] or 0) + (fila["tiempo_bq_s"] or 0), 3)
                w.writerow(fila)
                f.flush()
                sig_id += 1
                estado = "OK " if fila["correcto"] else ("ERR" if fila["error"] else "MAL")
                print(f"[{n}/{total}] {p['id']} {est:<17} r{rep}  {estado}  "
                      f"{fila['mb_procesados'] or 0:>8} MB  gasto LLM acumulado USD {gasto_llm:.3f}")
    f.close()
    print(f"\nListo. Log en {LOG}")


def cmd_recalcular(_):
    """Vuelve a evaluar el log con el criterio actual, usando las salidas guardadas (no llama al LLM ni a BigQuery)."""
    preguntas = {p["id"]: p for p in json.load(open(os.path.join(DIR, "preguntas.json"), encoding="utf-8"))}
    d = pd.read_csv(LOG)
    for i, r in d.iterrows():
        sal = os.path.join(SAL_DIR, f"{r.pregunta_id}_{r.estrategia}_r{r.repeticion}.csv")
        if not os.path.exists(sal):
            continue
        ref = pd.read_csv(os.path.join(REF_DIR, f"{r.pregunta_id}.csv"))
        try:
            gen = pd.read_csv(sal)
        except pd.errors.EmptyDataError:
            gen = pd.DataFrame()
        d.loc[i, ["correcto", "mismas_columnas"]] = comparar(ref, gen, preguntas[r.pregunta_id].get("columnas_clave"))
    d.to_csv(LOG, index=False)
    print(d[["pregunta_id", "estrategia", "repeticion", "correcto", "error"]].to_string(index=False))


def cmd_resumen(_):
    d = pd.read_csv(LOG)
    print("\nPor estrategia:")
    print(d.groupby("estrategia").agg(exactitud=("correcto", "mean"), errores=("error", lambda x: x.notna().sum()),
                                      mb_promedio=("mb_procesados", "mean"), tiempo_total_s=("tiempo_total_s", "mean"),
                                      costo_bq_usd=("costo_bq_usd", "sum"), costo_llm_usd=("costo_llm_usd", "sum")).round(3))
    print("\nExactitud por nivel y estrategia:")
    print(d.pivot_table(index="nivel", columns="estrategia", values="correcto", aggfunc="mean").round(2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("referencia")
    c = sub.add_parser("correr")
    c.add_argument("--preguntas", help="ej: Q01,Q05")
    c.add_argument("--estrategias", help="ej: zero_shot,cot")
    c.add_argument("--repeticiones", type=int, default=3)
    sub.add_parser("resumen")
    sub.add_parser("recalcular")
    a = ap.parse_args()
    {"referencia": cmd_referencia, "correr": cmd_correr, "resumen": cmd_resumen,
     "recalcular": cmd_recalcular}[a.cmd](a)
