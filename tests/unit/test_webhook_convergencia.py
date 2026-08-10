"""La comprobación de convergencia tiene que aguantar la carrera entre entregas.

Podio entrega el mismo evento por cada hook activo y en paralelo. El perdedor de
la carrera revienta con la PK duplicada; si comprueba el estado ANTES de que el
ganador haga commit, ve que no está y manda a la dead-letter un evento que sí
acabó bien — un fallo visible en el panel del cliente por algo que no falló.
Pasó de verdad: failed_sync #47, jobs_pkey QID60096 duplicada.
"""
from contextlib import contextmanager

import src.routes.Webhook_bp as wb


class _SesionFalsa:
    def __init__(self, hay_fila):
        self._hay = hay_fila

    def exec(self, _stmt):
        return self

    def first(self):
        return object() if self._hay else None


def _fingir_sesiones(monkeypatch, secuencia):
    """get_session devuelve, en orden, una sesión por cada valor de `secuencia`.
    Así se simula 'aún no había commit' seguido de 'ya está'."""
    restantes = list(secuencia)

    @contextmanager
    def falsa():
        yield _SesionFalsa(restantes.pop(0) if restantes else False)

    monkeypatch.setattr(wb, "get_session", falsa)
    monkeypatch.setattr(wb.time, "sleep", lambda *_: None)


def test_un_solo_intento_pierde_la_carrera(monkeypatch):
    _fingir_sesiones(monkeypatch, [False, True])
    assert wb._webhook_state_converged("item.create", "123") is False


def test_reintentar_ve_el_commit_del_ganador(monkeypatch):
    _fingir_sesiones(monkeypatch, [False, True])
    assert wb._webhook_state_converged(
        "item.create", "123", intentos=3, espera=1.0) is True


def test_si_de_verdad_no_convergio_devuelve_falso(monkeypatch):
    _fingir_sesiones(monkeypatch, [False, False, False])
    assert wb._webhook_state_converged(
        "item.create", "123", intentos=3, espera=1.0) is False


def test_delete_converge_cuando_la_fila_ya_no_esta(monkeypatch):
    _fingir_sesiones(monkeypatch, [True, False])
    assert wb._webhook_state_converged(
        "item.delete", "123", intentos=3, espera=1.0) is True


def test_sin_item_id_no_converge(monkeypatch):
    _fingir_sesiones(monkeypatch, [True])
    assert wb._webhook_state_converged("item.create", None) is False
