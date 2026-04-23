"""Geração de PDFs da escala — preto e branco, layout limpo.

Usa fpdf2 (puro Python) e DejaVu Sans (TTF Unicode) em app/fonts/.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

from fpdf import FPDF

from . import models, utils

FONT_DIR = Path(__file__).resolve().parent / "fonts"
FONT_REGULAR = FONT_DIR / "DejaVuSans.ttf"
FONT_BOLD    = FONT_DIR / "DejaVuSans-Bold.ttf"

# ── Paleta preto/branco ──────────────────────────────────────────
COR_HEADER_BG  = (0,   0,   0)    # cabeçalho preto
COR_HEADER_FG  = (255, 255, 255)  # texto branco
COR_DOMINGO_BG = (185, 28,  28)   # domingo vermelho
COR_SETOR_BG   = (40,  40,  40)   # setor cinza escuro
COR_SETOR_FG   = (255, 255, 255)
COR_GRID       = (200, 200, 200)
COR_TEXTO      = (0,   0,   0)

# turno → (bg_rgb, fg_rgb, label)
TURNO_ESTILO = {
    "MANHA":       ((254, 243, 199), (120,  53,  15),  "M"),
    "TARDE":       ((253, 215, 170), (124,  45,  18), "T"),
    "FOLGA":       ((220, 252, 231), ( 20,  83,  45),  "F"),
    "FERIAS":      ((224, 242, 254), ( 12,  74, 110),  "FE"),
    "AFASTAMENTO": ((255, 237, 213), (124,  45,  18),  "AF"),
}


def _preparar_fonte(pdf: FPDF) -> None:
    pdf.add_font("DejaVu", "",  str(FONT_REGULAR))
    pdf.add_font("DejaVu", "B", str(FONT_BOLD))


def gerar_pdf_escala(ano: int, mes: int, tipo: str) -> bytes:
    funcionarios = models.listar_funcionarios(tipo=tipo, ativos_apenas=False)
    dias  = utils.dias_do_mes(ano, mes)
    escalas = models.escala_mensal(ano, mes, tipo=tipo)

    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=False)
    _preparar_fonte(pdf)
    pdf.add_page()
    pdf.set_margins(left=8, top=10, right=8)

    # ── Título ───────────────────────────────────────────────────
    pdf.set_font("DejaVu", "B", 13)
    pdf.set_text_color(*COR_TEXTO)
    titulo = (
        f"ESCALA DE TRABALHO — {utils.nome_mes(mes).upper()} / {ano}"
        if tipo == "CONTRATADO"
        else f"ESCALA DE EXTRAS — {utils.nome_mes(mes).upper()} / {ano}"
    )
    pdf.cell(0, 8, titulo, ln=True, align="C")
    pdf.ln(2)

    # ── Dimensões ────────────────────────────────────────────────
    page_w  = pdf.w - pdf.l_margin - pdf.r_margin
    col_nome  = 48
    col_cargo = 40
    col_dia   = max(5.5, (page_w - col_nome - col_cargo) / len(dias))
    altura    = 6

    # ── Cabeçalho: dia da semana ─────────────────────────────────
    pdf.set_font("DejaVu", "B", 6)
    pdf.set_draw_color(*COR_GRID)

    pdf.set_fill_color(*COR_HEADER_BG)
    pdf.set_text_color(*COR_HEADER_FG)
    pdf.cell(col_nome,  altura, "Colaborador", border=1, fill=True)
    pdf.cell(col_cargo, altura, "Cargo",       border=1, fill=True)
    for d in dias:
        if d.weekday() == 6:
            pdf.set_fill_color(*COR_DOMINGO_BG)
        pdf.cell(col_dia, altura, utils.dia_semana_curto(d), border=1, fill=True, align="C")
        if d.weekday() == 6:
            pdf.set_fill_color(*COR_HEADER_BG)
    pdf.ln()

    # ── Cabeçalho: número do dia ─────────────────────────────────
    pdf.set_fill_color(*COR_HEADER_BG)
    pdf.cell(col_nome,  altura, "", border=1, fill=True)
    pdf.cell(col_cargo, altura, "", border=1, fill=True)
    for d in dias:
        if d.weekday() == 6:
            pdf.set_fill_color(*COR_DOMINGO_BG)
        pdf.cell(col_dia, altura, str(d.day), border=1, fill=True, align="C")
        if d.weekday() == 6:
            pdf.set_fill_color(*COR_HEADER_BG)
    pdf.ln()

    # ── Linhas por setor ─────────────────────────────────────────
    setores = sorted(
        {f["setor"] for f in funcionarios},
        key=lambda s: models.SETORES_ORDEM.index(s) if s in models.SETORES_ORDEM else 99,
    )
    for setor in setores:
        pdf.set_font("DejaVu", "B", 7)
        pdf.set_fill_color(*COR_SETOR_BG)
        pdf.set_text_color(*COR_SETOR_FG)
        pdf.cell(col_nome + col_cargo + col_dia * len(dias), altura, setor, border=1, fill=True)
        pdf.ln()

        pdf.set_font("DejaVu", "", 7)
        for f in [x for x in funcionarios if x["setor"] == setor]:
            pdf.set_fill_color(255, 255, 255)
            pdf.set_text_color(*COR_TEXTO)
            pdf.cell(col_nome,  altura, f["nome"][:38],  border=1)
            pdf.cell(col_cargo, altura, f["cargo"][:32], border=1)
            turnos_func = escalas.get(f["id"], {})
            for d in dias:
                turno = turnos_func.get(d.isoformat(), "")
                if turno in TURNO_ESTILO:
                    bg, fg, label = TURNO_ESTILO[turno]
                else:
                    bg, fg, label = (255, 255, 255), (200, 200, 200), ""
                pdf.set_fill_color(*bg)
                pdf.set_text_color(*fg)
                pdf.cell(col_dia, altura, label, border=1, fill=True, align="C")
            pdf.ln()

    # ── Legenda ──────────────────────────────────────────────────
    pdf.ln(2)
    pdf.set_font("DejaVu", "", 6)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 4, "M = Manhã   T = Tarde   F = Folga   FE = Férias   AF = Afastamento", ln=True)
    pdf.cell(0, 4, f"Grupo Singular — Gerado em {utils.nome_mes(mes)}/{ano}", ln=True)

    buf = BytesIO()
    pdf.output(buf)
    return buf.getvalue()


def gerar_pdf_entregadores(ano: int, mes: int, dias_selecionados: list[str]) -> bytes:
    """Gera PDF da escala de entregadores para os dias selecionados. Nomes sem cor."""
    from datetime import date as _date

    lista   = models.listar_entregadores(ativos_apenas=True)
    dias    = sorted([_date.fromisoformat(d) for d in dias_selecionados if d])
    if not dias:
        dias = utils.dias_do_mes(ano, mes)
    n_dias  = len(dias)
    escalas = models.escala_entregadores_mensal(ano, mes)

    # Paisagem para muitos dias, retrato para poucos
    orientation = "P" if n_dias <= 14 else "L"

    pdf = FPDF(orientation=orientation, unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=14)
    _preparar_fonte(pdf)
    pdf.add_page()
    pdf.set_margins(left=8, top=10, right=8)

    page_w   = pdf.w - pdf.l_margin - pdf.r_margin
    col_nome = 50
    col_dia  = max(5.5, (page_w - col_nome) / n_dias) if n_dias else 10
    HDR      = 5.0   # altura das linhas de cabeçalho
    ROW      = 9.0   # altura das linhas de dados (nome + obs)

    # ── Título ───────────────────────────────────────────────────
    pdf.set_font("DejaVu", "B", 14)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 8, "ESCALA DE ENTREGADORES", ln=True, align="C")

    # Subtítulo com período
    if dias[0].month == dias[-1].month:
        periodo = f"{dias[0].day} a {dias[-1].day} de {utils.nome_mes(mes).title()} / {ano}"
    else:
        periodo = (f"{dias[0].strftime('%d/%m')} a "
                   f"{dias[-1].strftime('%d/%m')}/{ano}")
    pdf.set_font("DejaVu", "", 9)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 5, periodo, ln=True, align="C")
    pdf.ln(3)

    # ── Cabeçalho: dia da semana ─────────────────────────────────
    pdf.set_font("DejaVu", "B", 5.5)
    pdf.set_draw_color(*COR_GRID)
    pdf.set_fill_color(*COR_HEADER_BG)
    pdf.set_text_color(*COR_HEADER_FG)
    pdf.cell(col_nome, HDR, "ENTREGADOR", border=1, fill=True)
    for d in dias:
        pdf.set_fill_color(*(COR_DOMINGO_BG if d.weekday() == 6 else COR_HEADER_BG))
        pdf.cell(col_dia, HDR, utils.dia_semana_curto(d).upper(), border=1, fill=True, align="C")
    pdf.ln()

    # ── Cabeçalho: número do dia ─────────────────────────────────
    pdf.set_font("DejaVu", "B", 7)
    pdf.set_fill_color(*COR_HEADER_BG)
    pdf.set_text_color(*COR_HEADER_FG)
    pdf.cell(col_nome, HDR, "", border=1, fill=True)
    for d in dias:
        pdf.set_fill_color(*(COR_DOMINGO_BG if d.weekday() == 6 else COR_HEADER_BG))
        pdf.cell(col_dia, HDR, str(d.day), border=1, fill=True, align="C")
    pdf.ln()

    # ── Linhas dos entregadores ──────────────────────────────────
    for i, e in enumerate(lista):
        nome     = e["nome"]
        obs      = (e.get("obs") or "").strip()
        turnos_e = escalas.get(e["id"], {})
        linha_bg = (255, 255, 255) if i % 2 == 0 else (248, 248, 247)

        x0 = pdf.get_x()
        y0 = pdf.get_y()

        # Célula do nome — fundo + borda
        pdf.set_fill_color(*linha_bg)
        pdf.set_draw_color(*COR_GRID)
        pdf.cell(col_nome, ROW, "", border=1, fill=True)

        # Nome (negrito, linha superior)
        pdf.set_xy(x0 + 1.5, y0 + 1.2)
        pdf.set_font("DejaVu", "B", 7.5)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(col_nome - 2, 4.5, nome[:34], ln=False)

        # Obs (menor, abaixo do nome)
        if obs:
            pdf.set_xy(x0 + 1.5, y0 + 5.5)
            pdf.set_font("DejaVu", "", 5.5)
            pdf.set_text_color(110, 110, 110)
            pdf.cell(col_nome - 2, 3.0, obs[:32], ln=False)

        # Reposiciona cursor para as células de dia
        pdf.set_xy(x0 + col_nome, y0)

        for d in dias:
            status  = turnos_e.get(d.isoformat(), "")
            is_dom  = d.weekday() == 6
            if status == "ESCALADO":
                bg, fg, label, bold = (254, 243, 199), (120, 53, 15),  "E", "B"
            elif status == "CONFIRMADO":
                bg, fg, label, bold = (220, 252, 231), (20,  83,  45), "C", "B"
            else:
                bg    = (242, 242, 240) if is_dom else linha_bg
                fg    = (200, 200, 200)
                label = ""
                bold  = ""
            pdf.set_fill_color(*bg)
            pdf.set_draw_color(*COR_GRID)
            pdf.set_text_color(*fg)
            pdf.set_font("DejaVu", bold, 7)
            pdf.cell(col_dia, ROW, label, border=1, fill=True, align="C")

        pdf.ln()

    # ── Linha de totais ──────────────────────────────────────────
    pdf.set_fill_color(230, 230, 228)
    pdf.set_draw_color(*COR_GRID)
    pdf.set_text_color(30, 30, 30)
    pdf.set_font("DejaVu", "B", 6)
    pdf.cell(col_nome, 6, "TOTAL (E + C)", border=1, fill=True)
    for d in dias:
        iso   = d.isoformat()
        total = sum(
            1 for e in lista
            if escalas.get(e["id"], {}).get(iso, "") in ("ESCALADO", "CONFIRMADO")
        )
        pdf.cell(col_dia, 6, str(total) if total else "—", border=1, fill=True, align="C")
    pdf.ln()

    # ── Rodapé ───────────────────────────────────────────────────
    pdf.ln(3)
    pdf.set_font("DejaVu", "", 6)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 4, "E = Escalado   C = Confirmado", ln=True)
    pdf.cell(0, 4, f"Grupo Singular — {utils.nome_mes(mes).title()}/{ano}", ln=True)

    buf = BytesIO()
    pdf.output(buf)
    return buf.getvalue()
