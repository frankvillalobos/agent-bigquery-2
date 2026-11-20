-- =====================================================================
-- Consultas de referencia (ground truth) - Tesis Text-to-SQL
-- Dataset: uean-493522.proptech
--
-- Supuestos comunes (ponerlos también en el prompt del LLM):
--   * Niveles: 1 simple, 2 moderada, 3 compleja, 4 muy compleja.
--   * Fecha de referencia ("hoy"): 2026-11-14. Las fechas van fijas, no CURRENT_DATE(),
--     para que el resultado no cambie según el día en que se corre.
--   * "Mes pasado" = octubre 2026. "Últimos N meses" = N meses calendario completos
--     anteriores a noviembre 2026. "Último trimestre" = últimos 3 meses cerrados (ago-oct 2026).
--   * Listings es una foto semanal: el stock de un mes se toma con
--     periodo = AAAAMM AND aviso_online_al_cierre = 1. Siempre COUNT(DISTINCT listing_id).
--   * En Capital Federal, la columna `ciudad` contiene el barrio (Palermo, Belgrano...);
--     `barrio` es una subzona (Belgrano C, Palermo Hollywood...).
--   * Precios de venta en USD; los alquileres mezclan ARS y USD. Se excluyen precios en 0.
--   * Leads: se excluyen los borrados (lead_borrado = 1).
--   * Visitas / impresiones de un aviso = SUM(total_events) de page_view con content_group = 'aviso'.
--   * En las preguntas de "top 10" se comparan los valores del ranking (no los IDs), porque
--     con empates en el puesto 10 cualquier aviso empatado es una respuesta válida.
--   * Precio vigente de un aviso = precio de su última foto semanal.
-- =====================================================================


-- Q01 | Nivel 1 | ¿Cuántos listings hay publicados en Capital Federal?
-- Stock online al cierre del último mes con datos (oct-2026).
SELECT COUNT(DISTINCT listing_id) AS listings_publicados
FROM `uean-493522.proptech.listings`
WHERE provincia = 'Capital Federal'
  AND periodo = 202610
  AND aviso_online_al_cierre = 1;


-- Q02 | Nivel 1 | ¿Cuál es el precio promedio de un departamento en venta en La Plata en octubre 2026?
-- Departamentos en venta (USD) online al cierre de oct-2026.
SELECT ROUND(AVG(precio), 0) AS precio_promedio_usd,
       COUNT(DISTINCT listing_id) AS departamentos
FROM `uean-493522.proptech.listings`
WHERE ciudad = 'La Plata'
  AND tipo_propiedad = 'departamento'
  AND operacion = 'venta'
  AND moneda = 'USD'
  AND precio > 0
  AND periodo = 202610
  AND aviso_online_al_cierre = 1;


-- Q03 | Nivel 1 | ¿Cuántos leads se recibieron en todo el país el mes pasado?
SELECT COUNT(*) AS leads
FROM `uean-493522.proptech.leads`
WHERE fecha_lead >= TIMESTAMP '2026-10-01'
  AND fecha_lead <  TIMESTAMP '2026-11-01'
  AND lead_borrado = 0;


-- Q04 | Nivel 2 | ¿Cuántos leads generó cada propiedad en Capital Federal con precio
--               entre USD 200.000 y 500.000 en los últimos 3 meses?
-- Últimos 3 meses = ago-oct 2026. Precio vigente del aviso (venta en USD).
WITH precio_vigente AS (
  SELECT listing_id, precio
  FROM `uean-493522.proptech.listings`
  WHERE provincia = 'Capital Federal'
    AND operacion = 'venta'
    AND moneda = 'USD'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY listing_id ORDER BY semana_inicio DESC) = 1
)
SELECT p.listing_id,
       p.precio,
       COUNT(*) AS leads
FROM `uean-493522.proptech.leads` AS l
JOIN precio_vigente AS p
  ON CAST(l.listing_id AS INT64) = p.listing_id
WHERE l.fecha_lead >= TIMESTAMP '2026-08-01'
  AND l.fecha_lead <  TIMESTAMP '2026-11-01'
  AND l.lead_borrado = 0
  AND p.precio BETWEEN 200000 AND 500000
GROUP BY p.listing_id, p.precio
ORDER BY leads DESC, p.listing_id;


-- Q05 | Nivel 2 | ¿Cuál es el precio por m2 en cada barrio de Capital Federal?
-- Venta en USD, stock al cierre de oct-2026, promedio del precio/m2 de cada aviso.
SELECT ciudad AS barrio_caba,
       ROUND(AVG(SAFE_DIVIDE(precio, superficie_m2)), 0) AS precio_m2_usd,
       COUNT(DISTINCT listing_id) AS avisos
FROM `uean-493522.proptech.listings`
WHERE provincia = 'Capital Federal'
  AND operacion = 'venta'
  AND moneda = 'USD'
  AND precio > 0
  AND superficie_m2 > 0
  AND periodo = 202610
  AND aviso_online_al_cierre = 1
GROUP BY ciudad
ORDER BY precio_m2_usd DESC;


-- Q06 | Nivel 2 | ¿Cuál es la tasa de conversión (leads sobre visitas) por tipo de propiedad?
-- Todo el período. Visitas de GA4 (page_view de avisos); leads de la tabla leads, sin borrados.
WITH tipo AS (
  SELECT DISTINCT listing_id, tipo_propiedad
  FROM `uean-493522.proptech.listings`
),
visitas AS (
  SELECT listing_id, SUM(total_events) AS visitas
  FROM `uean-493522.proptech.ga4`
  WHERE event_name = 'page_view' AND content_group = 'aviso'
  GROUP BY listing_id
),
leads AS (
  SELECT CAST(listing_id AS INT64) AS listing_id, COUNT(*) AS leads
  FROM `uean-493522.proptech.leads`
  WHERE lead_borrado = 0
  GROUP BY listing_id
)
SELECT t.tipo_propiedad,
       SUM(v.visitas) AS visitas,
       SUM(IFNULL(l.leads, 0)) AS leads,
       ROUND(100 * SAFE_DIVIDE(SUM(IFNULL(l.leads, 0)), SUM(v.visitas)), 2) AS tasa_conversion_pct
FROM tipo AS t
JOIN visitas AS v USING (listing_id)
LEFT JOIN leads AS l USING (listing_id)
GROUP BY t.tipo_propiedad
ORDER BY tasa_conversion_pct DESC;


-- Q07 | Nivel 2 | ¿Cuál es el CPL (costo por lead) por campaña en el último trimestre?
-- Últimos 3 meses cerrados (ago-oct 2026). Gasto de GA4 (session_start de sesiones pagas); leads de la tabla leads.
WITH gasto AS (
  SELECT session_campaign_name AS campana, SUM(gasto) AS gasto_ars
  FROM `uean-493522.proptech.ga4`
  WHERE event_date BETWEEN '2026-08-01' AND '2026-10-31'
    AND gasto IS NOT NULL
  GROUP BY campana
),
leads AS (
  SELECT campaign_id AS campana, COUNT(*) AS leads
  FROM `uean-493522.proptech.leads`
  WHERE fecha_lead >= TIMESTAMP '2026-08-01'
    AND fecha_lead <  TIMESTAMP '2026-11-01'
    AND lead_borrado = 0
    AND campaign_id IS NOT NULL
  GROUP BY campana
)
SELECT g.campana,
       ROUND(g.gasto_ars, 2) AS gasto_ars,
       IFNULL(l.leads, 0) AS leads,
       ROUND(SAFE_DIVIDE(g.gasto_ars, l.leads), 2) AS cpl_ars
FROM gasto AS g
LEFT JOIN leads AS l USING (campana)
ORDER BY cpl_ars;


-- Q08 | Nivel 3 | ¿Cómo evolucionó el volumen de listings publicados mes a mes en los
--               últimos 12 meses, separado por provincia?
-- Stock online al cierre de cada mes, nov-2025 a oct-2026.
SELECT periodo,
       provincia,
       COUNT(DISTINCT listing_id) AS listings_publicados
FROM `uean-493522.proptech.listings`
WHERE periodo BETWEEN 202511 AND 202610
  AND aviso_online_al_cierre = 1
GROUP BY periodo, provincia
ORDER BY provincia, periodo;


-- Q09 | Nivel 3 | ¿Cuáles son las 10 propiedades con más leads y qué porcentaje del
--               total de leads representa cada una?
-- Todo el período.
WITH por_aviso AS (
  SELECT listing_id, COUNT(*) AS leads
  FROM `uean-493522.proptech.leads`
  WHERE lead_borrado = 0
  GROUP BY listing_id
)
SELECT listing_id,
       leads,
       ROUND(100 * leads / SUM(leads) OVER (), 4) AS pct_del_total
FROM por_aviso
ORDER BY leads DESC, listing_id
LIMIT 10;


-- Q10 | Nivel 3 | ¿Cuáles son las 10 propiedades con más impresiones que no tienen
--               leads en los últimos 60 días?
-- Últimos 60 días desde 2026-11-14 => desde 2026-09-15. Leads de la tabla leads, sin borrados.
WITH impresiones AS (
  SELECT listing_id, SUM(total_events) AS impresiones
  FROM `uean-493522.proptech.ga4`
  WHERE event_date >= '2026-09-15'
    AND event_name = 'page_view'
    AND content_group = 'aviso'
  GROUP BY listing_id
),
con_leads AS (
  SELECT DISTINCT CAST(listing_id AS INT64) AS listing_id
  FROM `uean-493522.proptech.leads`
  WHERE fecha_lead >= TIMESTAMP '2026-09-15'
    AND lead_borrado = 0
)
SELECT i.listing_id, i.impresiones
FROM impresiones AS i
LEFT JOIN con_leads AS c USING (listing_id)
WHERE c.listing_id IS NULL
ORDER BY i.impresiones DESC, i.listing_id
LIMIT 10;


-- Q11 | Nivel 3 | ¿Cuál es el tiempo promedio desde la publicación hasta el primer lead,
--               por tipo de propiedad y ciudad?
-- Solo avisos publicados desde 2025-10-01 (para los anteriores no vemos su primer lead).
WITH avisos AS (
  SELECT DISTINCT listing_id, fecha_publicacion, tipo_propiedad, ciudad
  FROM `uean-493522.proptech.listings`
  WHERE fecha_publicacion >= '2025-10-01'
),
primer_lead AS (
  SELECT CAST(listing_id AS INT64) AS listing_id, MIN(fecha_lead) AS primer_lead
  FROM `uean-493522.proptech.leads`
  WHERE lead_borrado = 0
  GROUP BY listing_id
)
SELECT a.tipo_propiedad,
       a.ciudad,
       COUNT(*) AS avisos_con_lead,
       ROUND(AVG(DATE_DIFF(DATE(p.primer_lead), a.fecha_publicacion, DAY)), 1) AS dias_promedio_primer_lead
FROM avisos AS a
JOIN primer_lead AS p USING (listing_id)
GROUP BY a.tipo_propiedad, a.ciudad
ORDER BY a.tipo_propiedad, avisos_con_lead DESC;


-- Q12 | Nivel 3 | ¿Cuántas visitas tiene cada rango de precios (bajo, medio y alto),
--               su precio mínimo, máximo y promedio?
-- Rangos por terciles del precio vigente de venta en USD (P33 = 65.000; P66 = 158.000):
-- bajo hasta 65.000; medio hasta 158.000; alto más de 158.000. Los límites están en el contexto del agente.
WITH avisos AS (
  SELECT listing_id, precio
  FROM `uean-493522.proptech.listings`
  WHERE operacion = 'venta' AND moneda = 'USD' AND precio > 0
  QUALIFY ROW_NUMBER() OVER (PARTITION BY listing_id ORDER BY semana_inicio DESC) = 1
),
visitas AS (
  SELECT listing_id, SUM(total_events) AS visitas
  FROM `uean-493522.proptech.ga4`
  WHERE event_name = 'page_view' AND content_group = 'aviso'
  GROUP BY listing_id
)
SELECT CASE WHEN a.precio <= 65000 THEN 'bajo'
            WHEN a.precio <= 158000 THEN 'medio'
            ELSE 'alto' END AS rango_precio,
       IFNULL(SUM(v.visitas), 0) AS visitas,
       MIN(a.precio) AS precio_min,
       MAX(a.precio) AS precio_max,
       ROUND(AVG(a.precio), 0) AS precio_promedio
FROM avisos AS a
LEFT JOIN visitas AS v USING (listing_id)
GROUP BY rango_precio
ORDER BY precio_promedio;


-- Q13 | Nivel 4 | Para departamentos en Capital Federal con precio entre USD 200.000 y
--               400.000 publicados hace menos de 6 meses, ¿cuál es el promedio de días
--               desde que se publica hasta que se da de baja?
-- Hace menos de 6 meses = fecha_publicacion >= 2026-05-14. Solo los que ya se dieron de baja.
WITH avisos AS (
  SELECT listing_id, fecha_publicacion, precio,
         MAX(fecha_baja) OVER (PARTITION BY listing_id) AS fecha_baja
  FROM `uean-493522.proptech.listings`
  WHERE provincia = 'Capital Federal'
    AND tipo_propiedad = 'departamento'
    AND operacion = 'venta'
    AND moneda = 'USD'
    AND fecha_publicacion >= '2026-05-14'
  QUALIFY ROW_NUMBER() OVER (PARTITION BY listing_id ORDER BY semana_inicio DESC) = 1
)
SELECT COUNT(*) AS avisos_dados_de_baja,
       ROUND(AVG(DATE_DIFF(fecha_baja, fecha_publicacion, DAY)), 1) AS dias_promedio_hasta_baja
FROM avisos
WHERE precio BETWEEN 200000 AND 400000
  AND fecha_baja IS NOT NULL;


-- Q14 | Nivel 4 | ¿Cuántos leads por aviso recibe cada plan de publicación, separando
--               los leads que llegan por campañas pagas de los orgánicos, por tipo de operación?
-- Todo el período. Lead pago = tiene campaign_id; orgánico = campaign_id NULL.
-- Avisos = avisos distintos que estuvieron online en el período.
WITH avisos AS (
  SELECT plan_de_publicacion AS plan, operacion,
         COUNT(DISTINCT listing_id) AS avisos
  FROM `uean-493522.proptech.listings`
  WHERE aviso_online_semanal = 1
  GROUP BY plan, operacion
),
leads AS (
  SELECT plan_publicacion AS plan, tipo_de_operacion AS operacion,
         COUNTIF(campaign_id IS NOT NULL) AS leads_pagos,
         COUNTIF(campaign_id IS NULL)     AS leads_organicos
  FROM `uean-493522.proptech.leads`
  WHERE lead_borrado = 0
  GROUP BY plan, operacion
)
SELECT a.operacion,
       a.plan,
       a.avisos,
       IFNULL(l.leads_pagos, 0)     AS leads_pagos,
       IFNULL(l.leads_organicos, 0) AS leads_organicos,
       ROUND(SAFE_DIVIDE(l.leads_pagos, a.avisos), 2)     AS leads_pagos_por_aviso,
       ROUND(SAFE_DIVIDE(l.leads_organicos, a.avisos), 2) AS leads_organicos_por_aviso,
       ROUND(100 * SAFE_DIVIDE(l.leads_pagos, l.leads_pagos + l.leads_organicos), 1) AS pct_leads_pagos
FROM avisos AS a
LEFT JOIN leads AS l USING (plan, operacion)
ORDER BY a.operacion, leads_organicos_por_aviso DESC;


-- Q15 | Nivel 4 | ¿Cuáles son los barrios con mayor crecimiento en oferta de propiedades
--               (mes a mes) y cómo varía su precio medio en ese período?
-- Barrios de Capital Federal, nov-2025 vs oct-2026, stock al cierre. Precio medio: venta USD.
WITH mensual AS (
  SELECT ciudad AS barrio_caba,
         periodo,
         COUNT(DISTINCT listing_id) AS oferta,
         AVG(IF(operacion = 'venta' AND moneda = 'USD' AND precio > 0, precio, NULL)) AS precio_medio_usd
  FROM `uean-493522.proptech.listings`
  WHERE provincia = 'Capital Federal'
    AND periodo BETWEEN 202511 AND 202610
    AND aviso_online_al_cierre = 1
  GROUP BY ciudad, periodo
),
con_lag AS (
  SELECT *,
         SAFE_DIVIDE(oferta - LAG(oferta) OVER w, LAG(oferta) OVER w) AS crec_mensual
  FROM mensual
  WINDOW w AS (PARTITION BY barrio_caba ORDER BY periodo)
),
resumen AS (
  SELECT barrio_caba,
         MAX(IF(periodo = 202511, oferta, NULL))           AS oferta_nov25,
         MAX(IF(periodo = 202610, oferta, NULL))           AS oferta_oct26,
         AVG(crec_mensual)                                 AS crec_mensual_prom,
         MAX(IF(periodo = 202511, precio_medio_usd, NULL)) AS precio_nov25,
         MAX(IF(periodo = 202610, precio_medio_usd, NULL)) AS precio_oct26
  FROM con_lag
  GROUP BY barrio_caba
)
SELECT barrio_caba,
       oferta_nov25,
       oferta_oct26,
       ROUND(100 * crec_mensual_prom, 2) AS crec_mensual_prom_pct,
       ROUND(precio_nov25, 0) AS precio_medio_nov25,
       ROUND(precio_oct26, 0) AS precio_medio_oct26,
       ROUND(100 * SAFE_DIVIDE(precio_oct26 - precio_nov25, precio_nov25), 2) AS var_precio_pct
FROM resumen
WHERE oferta_nov25 >= 30
ORDER BY crec_mensual_prom_pct DESC
LIMIT 10;


-- Q16 | Nivel 4 | ¿Qué ubicaciones geográficas tienen demanda alta (leads) pero oferta
--               baja (listings), y cuál es su precio promedio?
-- Por ciudad, últimos 3 meses (ago-oct 2026). Demanda alta = leads por encima de la mediana;
-- oferta baja = stock promedio al cierre por debajo de la mediana. Orden: leads por aviso.
WITH demanda AS (
  SELECT provincia, ciudad, COUNT(*) AS leads
  FROM `uean-493522.proptech.leads`
  WHERE fecha_lead >= TIMESTAMP '2026-08-01'
    AND fecha_lead <  TIMESTAMP '2026-11-01'
    AND lead_borrado = 0
  GROUP BY provincia, ciudad
),
oferta AS (
  SELECT provincia, ciudad,
         COUNT(DISTINCT CONCAT(CAST(listing_id AS STRING), '-', CAST(periodo AS STRING))) / 3 AS stock_promedio,
         AVG(IF(operacion = 'venta' AND moneda = 'USD' AND precio > 0, precio, NULL)) AS precio_promedio_usd
  FROM `uean-493522.proptech.listings`
  WHERE periodo BETWEEN 202608 AND 202610
    AND aviso_online_al_cierre = 1
  GROUP BY provincia, ciudad
),
base AS (
  SELECT d.provincia, d.ciudad, d.leads, o.stock_promedio, o.precio_promedio_usd,
         PERCENTILE_CONT(d.leads, 0.5) OVER ()          AS mediana_leads,
         PERCENTILE_CONT(o.stock_promedio, 0.5) OVER () AS mediana_stock
  FROM demanda AS d
  JOIN oferta AS o USING (provincia, ciudad)
)
SELECT provincia,
       ciudad,
       leads,
       ROUND(stock_promedio, 1) AS stock_promedio,
       ROUND(leads / stock_promedio, 2) AS leads_por_aviso,
       ROUND(precio_promedio_usd, 0) AS precio_promedio_usd
FROM base
WHERE leads > mediana_leads
  AND stock_promedio < mediana_stock
ORDER BY leads_por_aviso DESC
LIMIT 15;
