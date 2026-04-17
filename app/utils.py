"""Utilitários de data e formatação."""
from __future__ import annotations

from calendar import monthrange
from datetime import date

DIAS_SEMANA_CURTO = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sab", "Dom"]
MESES_PT = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]
TURNO_LABEL = {
    "MANHA":       "Manhã",
    "TARDE":       "Tarde",
    "FOLGA":       "Folga",
    "FERIAS":      "FE",
    "AFASTAMENTO": "AF",
    "":            "",
    None:          "",
}
# Cores para o PDF (preto/branco)
TURNO_COR = {
    "MANHA":       (255, 255, 255),   # branco
    "TARDE":       (30,  30,  30),    # preto
    "FOLGA":       (220, 220, 220),   # cinza claro
    "FERIAS":      (180, 180, 180),   # cinza médio
    "AFASTAMENTO": (100, 100, 100),   # cinza escuro
}


def dias_do_mes(ano: int, mes: int) -> list[date]:
    _, ultimo = monthrange(ano, mes)
    return [date(ano, mes, d) for d in range(1, ultimo + 1)]


def dia_semana_curto(d: date) -> str:
    return DIAS_SEMANA_CURTO[d.weekday()]


def nome_mes(mes: int) -> str:
    return MESES_PT[mes - 1]


def label_turno(turno: str | None) -> str:
    return TURNO_LABEL.get(turno or "", "")


def cor_turno(turno: str | None) -> tuple[int, int, int]:
    return TURNO_COR.get(turno or "", (255, 255, 255))
