#!/usr/bin/env bash
# Verificacion completa del portal. Un solo comando, un solo veredicto.
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
if $PY -m pytest -q tests/integration/test_rbac_matrix.py \
      tests/integration/test_portal_scoping.py tests/integration/test_tasks_scoping.py \
      tests/integration/test_security_gates.py tests/integration/test_tasks_auditoria_seguridad.py \
      tests/integration/test_profile_self_service.py tests/unit/test_db_guard.py tests/unit/test_jwt_secreto.py \
      tests/integration/test_portal_ownership.py tests/integration/test_politica_password.py \
      tests/integration/test_correo_unico.py tests/integration/test_password_reset.py \
      >/tmp/verif_pytest.log 2>&1; then
  ok "$(tail -1 /tmp/verif_pytest.log | tr -d '\n')"
else mal "$(tail -3 /tmp/verif_pytest.log | tr '\n' ' ')"; fi

titulo "5 · Flujo end-to-end con sus pruebas negativas"
if $PY scripts/audit_e2e_portal.py >/tmp/verif_e2e.log 2>&1; then
  ok "8 pasos y 3 pruebas negativas"
else mal "$(grep -E '❌|Error' /tmp/verif_e2e.log | head -3 | tr '\n' ' ')"; fi

printf "\n\033[1m"
if [ "$FALLOS" -eq 0 ]; then printf "\033[32m✅ VERDE — los 5 bloques pasan\033[0m\n"
else printf "\033[31m❌ %s bloque(s) en rojo\033[0m\n" "$FALLOS"; fi
exit "$FALLOS"
