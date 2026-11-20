Proyecto y dataset: `uean-493522.proptech`. BigQuery Standard SQL. Usá siempre el nombre completo de la tabla, por ejemplo `uean-493522.proptech.listings`.
La fecha de hoy es 2026-11-14. Los datos van del 2025-10-01 al 2026-10-31.

## listings — foto semanal de avisos (una fila por aviso y por semana)
listing_id INT64, fecha_publicacion DATE, fecha_baja DATE (NULL si sigue activo), tipo_propiedad STRING (departamento, casa, ph, terreno, local, oficina, galpon, cochera, quinta, edificio), operacion STRING (venta, alquiler, alquiler_temporal), precio NUMERIC, moneda STRING (USD, ARS), superficie_m2 FLOAT64 (total), superficie_cubierta_m2 FLOAT64, latitud FLOAT64, longitud FLOAT64, estado STRING (activo, dado_de_baja, vendido), provincia STRING, ciudad STRING, barrio STRING, periodo INT64 (AAAAMM), idempresa INT64 (publicador), tipo_publicador STRING (inmobiliaria, particular, corredor, constructora), plan_de_publicacion STRING (gratis, simple, destacado, super_destacado), idavisopadre INT64 (-1 si no tiene padre), aviso_padre STRING (SI/NO), antiguedad INT64 (antigüedad del inmueble en meses; NO es el tiempo que lleva publicado el aviso), habitaciones INT64, banos INT64, ambientes INT64, cocheras INT64, aviso_online_al_cierre INT64 (1 si estaba online al cierre del mes), aviso_online_semanal INT64 (1 si estaba online esa semana), semana_inicio DATE, semana_fin DATE.

## usuarios — foto semanal de cuentas (una fila por cuenta y por semana)
user_id STRING, fecha_registro DATE, tipo_usuario STRING (comprador, vendedor, agente), provincia_residencia STRING, canal_adquisicion STRING (orgánico, paid_search, paid_social, referido), semana_inicio DATE, semana_fin DATE, semanal INT64 (siempre 1), cierre INT64 (1 en la última semana del mes), periodo INT64 (AAAAMM), idempresa INT64 (solo vendedores y agentes), nombre_cuenta STRING, ciudad_residencia STRING, barrio_residencia STRING, cp INT64, estado STRING (activo, inactivo, suspendido, baja), flag_pago BOOL, flag_desarrollo BOOL, flag_padre BOOL, flag_bloqueado BOOL, antiguedad INT64 (meses desde el registro de la cuenta), periodo_alta INT64, detalle_estado STRING, estado_cierre STRING (solo en filas con cierre = 1), motivo_baja STRING.

## leads — un registro por lead
lead_id INT64, fecha_lead TIMESTAMP, listing_id STRING, campaign_id STRING (nombre de la campaña paga; NULL si no vino de pago), canal STRING (whatsapp, formulario, telefono), cuenta_publicadora STRING, provincia STRING, ciudad STRING, zona STRING, tipo_de_operacion STRING, tipo_de_propiedad STRING, plan_publicacion STRING, periodo INT64 (AAAAMM), tipo_de_lead STRING, tipodeusuario STRING (tipo de publicador), idempresa INT64, semana_inicio DATE, semana_fin DATE, lead_borrado INT64 (1 = spam o duplicado).

## ga4 — eventos agregados (una fila por sesión × evento × contenido × aviso)
event_date DATE, listing_id INT64, platform STRING (web, app), city STRING, country STRING, region STRING, device STRING (desktop, mobile, tablet), user_id STRING (NULL si la sesión es anónima), unique_session_id STRING, event_name STRING (session_start, page_view, generate_lead), lead_id STRING, session_source STRING, session_medium STRING (organic, (none), cpc, paid_social, email, referral), session_campaign_name STRING, total_events INT64, content_group STRING (home, listado, aviso), province_param STRING, city_param STRING, zona_param STRING, gasto NUMERIC (gasto de marketing en ARS), moneda STRING.

## Reglas del modelo de datos
- listings y usuarios son fotos semanales: la misma entidad aparece en muchas filas. Contá entidades con COUNT(DISTINCT listing_id) o COUNT(DISTINCT user_id).
- Stock de avisos de un mes: periodo = AAAAMM AND aviso_online_al_cierre = 1. "Avisos publicados" sin otra aclaración = stock online al cierre del último mes con datos (202610).
- En Capital Federal, la columna `ciudad` contiene el barrio (Palermo, Belgrano, Recoleta...); `barrio` es una subzona. En el resto del país, `ciudad` es la ciudad o el partido.
- Los precios de venta están en USD; los alquileres mezclan ARS y USD. precio = 0 significa "consultar precio". superficie_m2 puede ser 0.
- En los leads, excluí los borrados (lead_borrado = 0).
- En ga4, los eventos se cuentan con SUM(total_events) y las sesiones con COUNT(DISTINCT unique_session_id). Las visitas a un aviso son page_view con content_group = 'aviso'. Cada generate_lead tiene un lead_id que existe en la tabla leads.
- gasto solo está informado en las filas session_start de sesiones pagas (session_medium = 'cpc' o 'paid_social'). La inversión es SUM(gasto).
- Relaciones: leads.listing_id (STRING) = listings.listing_id (INT64); ga4.lead_id (STRING) = leads.lead_id (INT64); ga4.listing_id = listings.listing_id; ga4.user_id = usuarios.user_id; listings.idempresa = leads.idempresa = usuarios.idempresa.
- Rangos de precio (terciles del precio de venta en USD de los avisos): bajo = hasta USD 65.000; medio = más de 65.000 y hasta USD 158.000; alto = más de USD 158.000.
