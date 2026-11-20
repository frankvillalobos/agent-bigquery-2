# Experimento Text-to-SQL

## Archivos

| Archivo | Qué es |
|---|---|
| `esquema.md` | Descripción de las tablas y reglas que recibe el LLM (igual para las 4 estrategias) |
| `ejemplos_few_shot.json` | 4 pares pregunta/SQL para few-shot (distintos de las 16 preguntas) |
| `estrategias.py` | Los 4 prompts y `generar_sql()` (gpt-4o, temperatura 0, sin historial) |
| `preguntas.json` | Las 16 preguntas con su nivel |
| `consultas_referencia.sql` | Ground truth |
| `experimento.py` | Corre la referencia, el experimento y el resumen |
| `app_tesis.py` | App de Streamlit que usa la misma `generar_sql()` |

## Instalación

Copiá esta carpeta junto a tu `.env` (el que tiene `OPENAI_API_KEY`).

```bash
pip install streamlit openai google-cloud-bigquery google-auth python-dotenv pandas db-dtypes
```

## Pasos

```bash
python experimento.py referencia                                   # 1. ground truth -> referencia/
python experimento.py correr --preguntas Q01,Q05,Q07 --repeticiones 1   # 2. piloto
python experimento.py correr                                        # 3. completo (192 ejecuciones)
python experimento.py resumen                                       # 4. tablas por estrategia y nivel
streamlit run app_tesis.py                                          # app para la presentación
```

Antes de la corrida completa, borrá `resultados/` para que el piloto no se mezcle con el experimento.

## Criterio de corrección (para el marco metodológico)

Una respuesta es correcta si devuelve la misma cantidad de filas que la referencia y cada columna de la referencia aparece en la respuesta con los mismos valores. No importan los nombres de columnas ni el orden de las filas. Los números se comparan con la precisión de la columna menos precisa (si una está redondeada a 2 decimales, la otra también se redondea a 2), así un redondeo distinto no cuenta como error pero una diferencia real sí. Un porcentaje expresado como fracción (0,0663 en vez de 6,63) se acepta. Se permiten columnas extra; `mismas_columnas` indica si además coincide la cantidad.

## Controles

- Caché de BigQuery desactivada en todas las ejecuciones.
- Límite de 5 GB facturados por consulta.
- Tope de USD 4 de gasto en OpenAI (`TOPE_GASTO_LLM_USD` en `experimento.py`).
- Si se corta, volvé a correr el mismo comando: saltea lo ya hecho.
