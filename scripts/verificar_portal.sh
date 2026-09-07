#!/usr/bin/env bash
# Verificacion completa del portal. Un solo comando, un solo veredicto.
#
# Cubre API (bloques 1-5) Y panel (bloque 6). Si el bloque 6 no puede correr,
# el veredicto es ROJO: no ejecutar algo nunca cuenta como que ha pasado.
#
# Es el criterio de «arreglado» de la auditoria de portal: si esto sale en verde,
# los 24 hallazgos estan cerrados y no hay regresion en lo que ya funcionaba.
# Cada bloque puede FALLAR de verdad: no hay ninguno que compruebe solo un 200.
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
FALLOS=0
titulo () { printf "\n\033[1m══ %s ══\033[0m\n" "$1"; }
ok ()     { printf "  \033[32m✔\033[0m %s\n" "$1"; }
mal ()    { printf "  \033[31m✘ %s\033[0m\n" "$1"; FALLOS=$((FALLOS+1)); }

titulo "1 · Compuerta de aislamiento (no debe poder apuntar a produccion)"
if $PY -m pytest -q tests/unit/test_db_guard.py >/dev/null 2>&1; then
  ok "21 casos del contrato de aceptacion/rechazo"
else mal "el contrato de la compuerta falla"; fi

titulo "2 · Matriz de permisos — 8 sujetos x superficie x objetos"
SAL=$($PY scripts/audit_portal_matrix.py --csv /tmp/verif_matriz.csv 2>/dev/null | grep '^filas=')
echo "  $SAL"
if $PY scripts/audit_portal_matrix.py --csv /tmp/verif_matriz.csv >/dev/null 2>&1; then
  ok "0 filas no conformes"
else mal "quedan filas no conformes (ver /tmp/verif_matriz.csv)"; fi

titulo "3 · Fuga de datos a nivel de campo"
# Se mira el CODIGO DE SALIDA, no solo el CSV: si el escaner se cae a mitad, el
# CSV queda corto o vacio y contar sus lineas daria un verde falso. Y se imprime
# su linea de COBERTURA, para que «0 fugas» venga siempre con cuantas sondas se
# examinaron de verdad.
SAL3=$($PY scripts/audit_field_leaks.py --csv /tmp/verif_fugas.csv 2>&1)
RC3=$?
echo "$SAL3" | grep -E '^(COBERTURA|  saltadas|filas de fuga)' | sed 's/^/  /'
if [ "$RC3" -eq 0 ]; then ok "ningun campo vetado alcanza a un rol de portal"
else mal "el escaner de fugas termino en $RC3 (ver /tmp/verif_fugas.csv)"; fi

titulo "4 · Tests RBAC (no debe haber regresion)"
# test_politica_password (O-01) y test_correo_unico (O-02) entran aqui porque
# eran huecos declarados del arnes: la politica de contrasenas no tenia NI UNA
# prueba y la migracion de correos unicos tampoco, asi que borrar cualquiera de
# las dos dejaba esta verificacion entera en verde.
#
# test_espejo_password (el contrato de 51 entradas entre servidor y panel) NO
# estaba en esta lista, y la revision adversarial lo midio: quitando la
# comprobacion de CONTRASENAS_PROHIBIDAS de src/utils/password_policy.py, el
# UNICO fichero que se ponia rojo era ese, y este guion seguia imprimiendo
# «VERDE — los 5 bloques pasan». Un veredicto que no ejecuta la unica prueba
# que ve el fallo no es un veredicto.
if $PY -m pytest -q tests/integration/test_rbac_matrix.py \
      tests/integration/test_portal_scoping.py tests/integration/test_tasks_scoping.py \
      tests/integration/test_security_gates.py tests/integration/test_tasks_auditoria_seguridad.py \
      tests/integration/test_profile_self_service.py tests/unit/test_db_guard.py tests/unit/test_jwt_secreto.py \
      tests/integration/test_portal_ownership.py tests/integration/test_politica_password.py \
      tests/integration/test_correo_unico.py tests/integration/test_password_reset.py \
      tests/unit/test_espejo_password.py tests/integration/test_filtro_jobs_por_tecnico.py \
      >/tmp/verif_pytest.log 2>&1; then
  ok "$(tail -1 /tmp/verif_pytest.log | tr -d '\n')"
else mal "$(tail -3 /tmp/verif_pytest.log | tr '\n' ' ')"; fi

titulo "5 · Flujo end-to-end con sus pruebas negativas"
if $PY scripts/audit_e2e_portal.py >/tmp/verif_e2e.log 2>&1; then
  ok "8 pasos y 3 pruebas negativas"
else mal "$(grep -E '❌|Error' /tmp/verif_e2e.log | head -3 | tr '\n' ' ')"; fi

titulo "6 · Suite RBAC del panel (Playwright)"
# Este guion decia ser «un solo comando, un solo veredicto» para los 24
# hallazgos y no ejecutaba NI UNA prueba del panel: `grep -cE
# "playwright|pnpm|npx"` daba 0. La mitad de los hallazgos (U-01, U-05..U-09,
# U-18) viven ahi, asi que el verde solo cubria la mitad del trabajo.
#
# No poder ejecutarla cuenta como ROJO, no como silencio: un veredicto que se
# salta un bloque cuando no encuentra el panel volveria a decir «verde» sobre
# lo que no ha mirado.
PANEL_DIR="${PANEL_DIR:-$(cd .. && pwd)/gqm-panel-admin}"
if [ ! -d "$PANEL_DIR" ]; then
  mal "no encuentro el panel en $PANEL_DIR (exporta PANEL_DIR=/ruta/al/panel)"
else
  # Directorio de estado PROPIO por corrida: dos suites a la vez comparten
  # /tmp/gqm-rbac-state y el teardown de una borra el estado de la otra, lo que
  # produce fallos de milisegundos que no son reales.
  ESTADO_RBAC=$(mktemp -d /tmp/gqm-rbac-state-XXXXXX)
  # Las credenciales de los 7 roles salen de `scripts/entorno-rbac.sh` del
  # panel, que las deriva de SEED_DEV_PASSWORD. Antes no estaban en ningun
  # fichero —vivian en la sesion de quien lanzaba la suite a mano—, asi que
  # este bloque no habria podido correr aunque existiera.
  if (cd "$PANEL_DIR" && . scripts/entorno-rbac.sh \
        && RBAC_STATE_DIR="$ESTADO_RBAC" corepack pnpm test:rbac) \
        >/tmp/verif_panel.log 2>&1; then
    ok "$(grep -E '[0-9]+ passed' /tmp/verif_panel.log | tail -1 | tr -d '\n')"
  else
    mal "suite del panel en rojo: $(grep -E '^\s+[0-9]+\) |[0-9]+ failed' /tmp/verif_panel.log | head -3 | tr '\n' ' ')"
  fi
  rm -rf "$ESTADO_RBAC"
fi

printf "\n\033[1m"
if [ "$FALLOS" -eq 0 ]; then printf "\033[32m✅ VERDE — los 6 bloques pasan\033[0m\n"
else printf "\033[31m❌ %s bloque(s) en rojo\033[0m\n" "$FALLOS"; fi
exit "$FALLOS"
