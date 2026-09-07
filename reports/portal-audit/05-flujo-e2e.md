# Fase 5 — Flujo end-to-end

Recorrido completo por API, verificando **la fila en la BD** en cada paso y ejecutando la
**prueba negativa** de cada paso: quién *no* debía ver ese cambio, y comprobar que no lo ve.

| # | Paso | HTTP | Verificación en BD | Prueba negativa |
|---|---|---|---|---|
| 1 | admin crea job | 201 | fila `QID-I60027` existe | — |
| 2 | admin lo asigna al sub | 201 | fila en `job_subcontractor` existe | — |
| 3 | el sub lo ve | **200** | — | **sub_B → 404** ✅ |
| 4 | el sub crea tarea para su técnico | 201 | `ID_Technician=TEC60001` | — |
| 5 | el técnico ve su tarea | — | — | **tech_de_sub_B no la ve**: solo `['TSK60003']` ✅ |
| 6 | el técnico actualiza el estado | 200 | `Task_status='Work-in-progress'` | — |
| 7 | sub y admin ven el cambio | 200 | ambos leen `Work-in-progress` | **sub_B → 404** ✅ |
| 8 | admin cierra el job | 200 | `Job_status='Completed'` | — |

**El flujo de negocio central funciona, y sus pruebas negativas también.** Las ocho pruebas
positivas y las tres negativas pasan, cada escritura confirmada releyendo la fila.

## Lo que esto significa para la entrega

Es el resultado más importante en positivo de toda la auditoría, y conviene enunciarlo con
precisión: **el camino principal —R1, R2, R3 y R6 sobre el recorrido feliz— está bien
construido.** `scope_jobs_statement` y `scope_tasks_statement` hacen su trabajo en
`/jobs/*` y `/tasks/*`, que es donde vive el flujo.

Los 8 hallazgos de la Fase 3 y los 6 de la Fase 4 **no están en este camino**: están en las
rutas laterales —`/technician/`, `/attachments/`, `/tlactivity/`, `/subcontractors/`,
`/certificate/`— que nadie recorre al hacer el trabajo, pero que cualquiera puede pedir con
un `curl` y el token que la propia aplicación le entrega al iniciar sesión.

Dicho de otro modo: **la aplicación funciona; lo que no está cerrado es todo lo que hay
alrededor de lo que funciona.**

## Lo que este recorrido NO cubre

- El mismo recorrido **por UI** se audita en la Fase 6. Lo que aquí se prueba es la API.
- No se ejercitó el ciclo con adjuntos ni con certificados dentro del flujo: se auditan por
  separado en las Fases 3 y 4, donde ya salen no conformes.
