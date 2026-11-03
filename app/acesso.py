"""Proteções da versão pública: senha opcional e limite diário de usos da IA.

A chave da API é do dono do app: sem isso, qualquer visitante gastaria a cota dele.
"""

import hmac
import threading
from collections.abc import Callable
from datetime import date


class LimiteDiario:
    """Conta os usos da IA por dia, somando todas as sessões do mesmo servidor."""

    def __init__(self, limite: int, hoje: Callable[[], date] = date.today) -> None:
        self._limite = limite
        self._hoje = hoje
        self._dia = hoje()
        self._usos = 0
        self._trava = threading.Lock()

    def consumir(self) -> bool:
        """Registra um uso; devolve False, sem registrar, se o limite do dia já foi atingido."""
        with self._trava:
            self._virar_o_dia()
            if self._usos >= self._limite:
                return False
            self._usos += 1
            return True

    def restantes(self) -> int:
        with self._trava:
            self._virar_o_dia()
            return self._limite - self._usos

    def _virar_o_dia(self) -> None:
        hoje = self._hoje()
        if hoje != self._dia:
            self._dia, self._usos = hoje, 0


def senha_confere(digitada: str, esperada: str) -> bool:
    """Comparação em tempo constante, para não vazar a senha pela demora da resposta."""
    return hmac.compare_digest(digitada.encode("utf-8"), esperada.encode("utf-8"))
