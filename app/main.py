"""Aplicação FastAPI — Escala de Trabalho Grupo Singular."""
from __future__ import annotations

import os
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import models, utils, auth
from .database import init_db, fazer_backup, listar_backups, restaurar_backup
from .pdf_export import gerar_pdf_escala

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="GS Escala de Trabalho")

# Chave secreta para sessões — em produção, use variável de ambiente
SECRET_KEY = os.environ.get("SECRET_KEY", "singular-escala-secret-2026-change-me")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, max_age=60 * 60 * 12)  # 12h

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

templates = Jinja2Templates(directory=BASE_DIR / "templates")
_BUILD_VER = str(int(time.time()))  # cache-buster: muda a cada restart

templates.env.globals.update(
    {
        "label_turno": utils.label_turno,
        "cor_turno": utils.cor_turno,
        "dia_semana_curto": utils.dia_semana_curto,
        "nome_mes": utils.nome_mes,
        "ABAS_DISPONIVEIS": auth.ABAS_DISPONIVEIS,
        "build_ver": _BUILD_VER,
    }
)


@app.on_event("startup")
def _startup() -> None:
    init_db()


# ---------- Helpers ----------

def _parse_mes(mes_str: Optional[str]) -> tuple[int, int]:
    if mes_str:
        try:
            dt = datetime.strptime(mes_str, "%Y-%m")
            return dt.year, dt.month
        except ValueError:
            raise HTTPException(400, "Formato de mês inválido (use YYYY-MM)")
    hoje = date.today()
    return hoje.year, hoje.month


def _parse_data(data_str: Optional[str]) -> date:
    if data_str:
        try:
            return datetime.strptime(data_str, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(400, "Formato de data inválido (use YYYY-MM-DD)")
    return date.today()


def _ctx(request: Request, **kwargs) -> dict:
    """Contexto base com usuário da sessão."""
    return {"request": request, "usuario": auth.get_usuario_sessao(request), **kwargs}


# ---------- Login / Logout ----------

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/") -> HTMLResponse:
    if auth.get_usuario_sessao(request):
        return RedirectResponse(url="/", status_code=302)
    erro = request.session.pop("login_erro", None)
    return templates.TemplateResponse("login.html", {"request": request, "next": next, "erro": erro})


@app.post("/login")
def login_post(
    request: Request,
    username: str = Form(...),
    senha: str = Form(...),
    next: str = Form("/"),
) -> RedirectResponse:
    import json
    usuario = auth.obter_usuario_por_username(username.strip().lower())
    if not usuario or not auth.verificar_senha(senha, usuario["senha_hash"]):
        request.session["login_erro"] = "Usuário ou senha incorretos."
        return RedirectResponse(url=f"/login?next={next}", status_code=302)
    try:
        abas = json.loads(usuario["abas_permitidas"])
    except Exception:
        abas = []
    request.session["usuario"] = {
        "id": usuario["id"],
        "username": usuario["username"],
        "nome": usuario["nome"],
        "is_admin": bool(usuario["is_admin"]),
        "abas_permitidas": abas,
    }
    safe_next = next if next.startswith("/") else "/"
    return RedirectResponse(url=safe_next, status_code=302)


@app.post("/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)


@app.get("/sem-acesso", response_class=HTMLResponse)
def sem_acesso(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("sem_acesso.html", _ctx(request))


# ---------- Páginas principais ----------

@app.get("/", response_class=HTMLResponse)
def home(request: Request, data: Optional[str] = None) -> HTMLResponse:
    if redir := auth.verificar_permissao(request, "dia"):
        return redir
    dia = _parse_data(data)
    escalados = models.escala_do_dia(dia.isoformat())
    grupos: dict[str, dict[str, list[dict]]] = {}
    for e in escalados:
        grupos.setdefault(e["setor"], {}).setdefault(e["tipo"], []).append(e)
    setores_ordenados = sorted(
        grupos.keys(),
        key=lambda s: models.SETORES_ORDEM.index(s) if s in models.SETORES_ORDEM else 99,
    )
    # Alertas de mínimos para o dia
    minimos = models.get_minimos()
    dow_dia = dia.weekday()  # 0=Seg, 6=Dom
    contagens_dia: dict[str, dict[str, int]] = {
        s: {"MANHA": 0, "TARDE": 0} for s in ("COZINHA", "ATENDIMENTO")
    }
    for e in escalados:
        if e["setor"] in contagens_dia:
            if "MANHA" in e["turno"]:
                contagens_dia[e["setor"]]["MANHA"] += 1
            if "TARDE" in e["turno"]:
                contagens_dia[e["setor"]]["TARDE"] += 1
    alertas_dia = []
    for setor, tmap in minimos.items():
        for turno_key, dia_vals in tmap.items():
            min_val = dia_vals.get(dow_dia, 0)
            if min_val > 0:
                atual = contagens_dia.get(setor, {}).get(turno_key, 0)
                if atual < min_val:
                    alertas_dia.append({
                        "setor": setor,
                        "turno": turno_key,
                        "atual": atual,
                        "minimo": min_val,
                        "deficit": min_val - atual,
                    })
    return templates.TemplateResponse(
        "dia.html",
        _ctx(request, data=dia, grupos=grupos, setores=setores_ordenados,
             total=len(escalados), alertas_dia=alertas_dia),
    )


@app.get("/grade", response_class=HTMLResponse)
def grade(request: Request, mes: Optional[str] = None, tipo: Optional[str] = None) -> HTMLResponse:
    if redir := auth.verificar_permissao(request, "grade"):
        return redir
    ano, mes_num = _parse_mes(mes)
    funcionarios = models.listar_funcionarios(tipo=tipo)
    escalas = models.escala_mensal(ano, mes_num, tipo=tipo)
    dias = utils.dias_do_mes(ano, mes_num)
    por_setor: dict[str, list[dict]] = {}
    for f in funcionarios:
        por_setor.setdefault(f["setor"], []).append(f)
    TIPO_PRIO = {"CONTRATADO": 0, "EXTRA": 1}
    for setor in por_setor:
        por_setor[setor].sort(key=lambda f: (TIPO_PRIO.get(f["tipo"], 2), f["ordem"], f["id"]))
    setores_ordenados = sorted(
        por_setor.keys(),
        key=lambda s: models.SETORES_ORDEM.index(s) if s in models.SETORES_ORDEM else 99,
    )
    # Alertas de mínimos por dia (usa TODOS os funcionários, independente do filtro)
    minimos = models.get_minimos()
    todos_func = models.listar_funcionarios()
    todas_escalas = models.escala_mensal(ano, mes_num)
    dias_alerta: dict[str, list[dict]] = {}
    for dia in dias:
        iso = dia.isoformat()
        cont: dict[str, dict[str, int]] = {
            s: {"MANHA": 0, "TARDE": 0} for s in ("COZINHA", "ATENDIMENTO")
        }
        for f in todos_func:
            if f["setor"] not in cont:
                continue
            t = todas_escalas.get(f["id"], {}).get(iso, "")
            if "MANHA" in t:
                cont[f["setor"]]["MANHA"] += 1
            if "TARDE" in t:
                cont[f["setor"]]["TARDE"] += 1
        dow = dia.weekday()  # 0=Seg, 6=Dom
        alertas = []
        for setor, tmap in minimos.items():
            for turno_key, dia_vals in tmap.items():
                min_val = dia_vals.get(dow, 0)
                if min_val > 0:
                    atual = cont[setor][turno_key]
                    if atual < min_val:
                        alertas.append({
                            "setor": setor, "turno": turno_key,
                            "atual": atual, "minimo": min_val,
                        })
        if alertas:
            dias_alerta[iso] = alertas
    feriados = models.listar_feriados_ano(ano)
    return templates.TemplateResponse(
        "grade.html",
        _ctx(request, ano=ano, mes=mes_num, mes_str=f"{ano:04d}-{mes_num:02d}",
             tipo_filtro=tipo or "", dias=dias, por_setor=por_setor,
             setores=setores_ordenados, escalas=escalas,
             minimos=minimos, dias_alerta=dias_alerta, feriados=feriados),
    )


@app.post("/api/minimos")
async def salvar_minimos(request: Request) -> RedirectResponse:
    if not auth.get_usuario_sessao(request):
        raise HTTPException(401, "Não autenticado")
    form = await request.form()
    mes = str(form.get("mes", ""))
    for setor in ("COZINHA", "ATENDIMENTO"):
        for turno in ("MANHA", "TARDE"):
            for dia in range(7):
                key = f"min_{setor}_{turno}_{dia}"
                try:
                    val = int(form.get(key, 0) or 0)
                except (ValueError, TypeError):
                    val = 0
                models.set_minimo(setor, turno, dia, val)
    return RedirectResponse(url=f"/grade?mes={mes}" if mes else "/grade", status_code=303)


@app.get("/funcionario/{func_id}", response_class=HTMLResponse)
def funcionario_view(request: Request, func_id: int, mes: Optional[str] = None) -> HTMLResponse:
    if redir := auth.verificar_permissao(request, "individual"):
        return redir
    func = models.obter_funcionario(func_id)
    if not func:
        raise HTTPException(404, "Funcionário não encontrado")
    ano, mes_num = _parse_mes(mes)
    escala = models.escala_individual(func_id, ano, mes_num)
    dias = utils.dias_do_mes(ano, mes_num)
    contagem = models.contar_turnos(func_id, ano, mes_num)
    notas = models.notas_do_mes(func_id, ano, mes_num)
    return templates.TemplateResponse(
        "individual.html",
        _ctx(request, func=func, ano=ano, mes=mes_num,
             mes_str=f"{ano:04d}-{mes_num:02d}", dias=dias,
             escala=escala, contagem=contagem, notas=notas),
    )


@app.get("/cadastros", response_class=HTMLResponse)
def cadastros(request: Request) -> HTMLResponse:
    if redir := auth.verificar_permissao(request, "cadastros"):
        return redir
    contratados = models.listar_funcionarios(tipo="CONTRATADO", ativos_apenas=False)
    extras = models.listar_funcionarios(tipo="EXTRA", ativos_apenas=False)
    return templates.TemplateResponse(
        "cadastros.html",
        _ctx(request, contratados=contratados, extras=extras),
    )


# ---------- Administração (admin) ----------

@app.get("/admin", response_class=HTMLResponse)
def admin_home(request: Request) -> HTMLResponse:
    return RedirectResponse(url="/admin/usuarios", status_code=302)


@app.get("/admin/usuarios", response_class=HTMLResponse)
def admin_usuarios(request: Request) -> HTMLResponse:
    if redir := auth.verificar_permissao(request, "usuarios"):
        return redir
    lista = auth.listar_usuarios()
    erro = request.session.pop("usuario_erro", None)
    ok = request.session.pop("usuario_ok", None)
    return templates.TemplateResponse(
        "admin.html",
        _ctx(request, tab="usuarios", lista=lista, erro=erro, ok=ok),
    )


@app.get("/admin/backups", response_class=HTMLResponse)
def admin_backups(request: Request) -> HTMLResponse:
    if redir := auth.verificar_permissao(request, "usuarios"):
        return redir
    backups = listar_backups()
    ok = request.session.pop("backup_ok", None)
    erro = request.session.pop("backup_erro", None)
    return templates.TemplateResponse(
        "admin.html",
        _ctx(request, tab="backups", backups=backups, ok=ok, erro=erro),
    )


@app.post("/api/admin/backup")
def api_fazer_backup(request: Request) -> RedirectResponse:
    if redir := auth.verificar_permissao(request, "usuarios"):
        return redir
    try:
        nome = fazer_backup()
        request.session["backup_ok"] = f"Backup criado: {nome}"
    except Exception as e:
        request.session["backup_erro"] = f"Erro ao criar backup: {e}"
    return RedirectResponse(url="/admin/backups", status_code=303)


@app.post("/api/admin/restaurar")
async def api_restaurar_backup(request: Request) -> RedirectResponse:
    if redir := auth.verificar_permissao(request, "usuarios"):
        return redir
    form = await request.form()
    nome = str(form.get("nome", ""))
    try:
        restaurar_backup(nome)
        request.session["backup_ok"] = f"Banco restaurado para: {nome}"
    except Exception as e:
        request.session["backup_erro"] = f"Erro ao restaurar: {e}"
    return RedirectResponse(url="/admin/backups", status_code=303)


# Redireciona /usuarios para o novo endereço
@app.get("/usuarios", response_class=HTMLResponse)
def usuarios_redirect(request: Request) -> HTMLResponse:
    return RedirectResponse(url="/admin/usuarios", status_code=302)


@app.post("/api/usuarios")
async def criar_usuario_route(request: Request) -> RedirectResponse:
    if redir := auth.verificar_permissao(request, "usuarios"):
        return redir
    form = await request.form()
    username = str(form.get("username", ""))
    nome = str(form.get("nome", ""))
    senha = str(form.get("senha", ""))
    is_admin = form.get("is_admin") is not None
    abas = form.getlist("abas") or []
    try:
        auth.criar_usuario(username=username, nome=nome, senha=senha, is_admin=is_admin, abas=abas)
        request.session["usuario_ok"] = f"Usuário '{nome}' criado com sucesso."
    except Exception as e:
        request.session["usuario_erro"] = f"Erro: {e}"
    return RedirectResponse(url="/usuarios", status_code=303)


@app.post("/api/usuarios/{uid}/atualizar")
async def atualizar_usuario_route(
    request: Request,
    uid: int,
) -> RedirectResponse:
    if redir := auth.verificar_permissao(request, "usuarios"):
        return redir
    form = await request.form()
    nome = str(form.get("nome", ""))
    senha = str(form.get("senha", "")) or None
    is_admin = form.get("is_admin") is not None
    ativo = form.get("ativo") is not None
    abas_raw = form.getlist("abas")
    abas = abas_raw if abas_raw else []
    auth.atualizar_usuario(
        uid,
        nome=nome,
        senha=senha,
        is_admin=is_admin,
        abas=abas,
        ativo=ativo,
    )
    request.session["usuario_ok"] = "Usuário atualizado."
    return RedirectResponse(url="/usuarios", status_code=303)


@app.post("/api/usuarios/{uid}/remover")
def remover_usuario_route(request: Request, uid: int) -> RedirectResponse:
    if redir := auth.verificar_permissao(request, "usuarios"):
        return redir
    sessao = auth.get_usuario_sessao(request)
    if sessao and sessao.get("id") == uid:
        request.session["usuario_erro"] = "Não é possível remover seu próprio usuário."
        return RedirectResponse(url="/usuarios", status_code=303)
    auth.remover_usuario(uid)
    return RedirectResponse(url="/usuarios", status_code=303)


# ---------- Ações de funcionários ----------

@app.post("/api/funcionarios")
def criar_func(
    request: Request,
    nome: str = Form(...),
    cargo: str = Form(...),
    setor: str = Form(...),
    tipo: str = Form(...),
) -> RedirectResponse:
    if redir := auth.verificar_permissao(request, "cadastros"):
        return redir
    models.criar_funcionario(nome.strip(), cargo.strip(), setor.strip(), tipo)
    return RedirectResponse(url="/cadastros", status_code=303)


@app.post("/api/funcionarios/{func_id}/atualizar")
def atualizar_func(
    request: Request,
    func_id: int,
    nome: str = Form(...),
    cargo: str = Form(...),
    setor: str = Form(...),
    tipo: str = Form(...),
    ativo: str = Form("1"),
) -> RedirectResponse:
    if redir := auth.verificar_permissao(request, "cadastros"):
        return redir
    models.atualizar_funcionario(
        func_id, nome=nome.strip(), cargo=cargo.strip(),
        setor=setor.strip(), tipo=tipo, ativo=(ativo == "1"),
    )
    return RedirectResponse(url="/cadastros", status_code=303)


@app.post("/api/funcionarios/{func_id}/remover")
def remover_func(request: Request, func_id: int) -> RedirectResponse:
    if redir := auth.verificar_permissao(request, "cadastros"):
        return redir
    models.remover_funcionario(func_id)
    return RedirectResponse(url="/cadastros", status_code=303)


@app.post("/api/funcionarios/{func_id}/toggle-ativo")
def api_toggle_ativo(request: Request, func_id: int) -> dict:
    if not auth.get_usuario_sessao(request):
        raise HTTPException(401, "Não autenticado")
    novo = models.toggle_ativo(func_id)
    return {"ok": True, "ativo": novo}


@app.post("/api/funcionarios/{func_id}/mover")
def api_mover_func(
    request: Request,
    func_id: int,
    direcao: str = Form(...),
) -> RedirectResponse:
    if redir := auth.verificar_permissao(request, "cadastros"):
        return redir
    models.mover_funcionario(func_id, direcao)
    return RedirectResponse(url="/cadastros", status_code=303)


@app.post("/api/escala/set")
def api_set_turno(
    request: Request,
    funcionario_id: int = Form(...),
    data: str = Form(...),
    turno: str = Form(""),
) -> dict:
    if not auth.get_usuario_sessao(request):
        raise HTTPException(401, "Não autenticado")
    models.set_turno(funcionario_id, data, turno or None)
    return {"ok": True, "turno": turno, "data": data}


@app.post("/api/nota/set")
def api_set_nota(
    request: Request,
    funcionario_id: int = Form(...),
    data: str = Form(...),
    texto: str = Form(""),
) -> dict:
    if not auth.get_usuario_sessao(request):
        raise HTTPException(401, "Não autenticado")
    models.set_nota(funcionario_id, data, texto)
    return {"ok": True, "data": data, "texto": texto.strip()}


# ---------- Entregadores ----------

@app.get("/entregadores", response_class=HTMLResponse)
def entregadores_page(request: Request, mes: Optional[str] = None) -> HTMLResponse:
    if redir := auth.verificar_permissao(request, "entregadores"):
        return redir
    ano, mes_num = _parse_mes(mes)
    lista = models.listar_entregadores(ativos_apenas=False)
    escalas = models.escala_entregadores_mensal(ano, mes_num)
    dias = utils.dias_do_mes(ano, mes_num)
    feriados = models.listar_feriados_ano(ano)
    return templates.TemplateResponse(
        "entregadores.html",
        _ctx(request, lista=lista, escalas=escalas, dias=dias,
             ano=ano, mes=mes_num, mes_str=f"{ano:04d}-{mes_num:02d}", feriados=feriados),
    )

@app.post("/api/entregadores")
async def criar_entregador_route(request: Request) -> RedirectResponse:
    if redir := auth.verificar_permissao(request, "entregadores"):
        return redir
    form = await request.form()
    nome = str(form.get("nome", "")).strip()
    if nome:
        models.criar_entregador(nome)
    return RedirectResponse(url="/entregadores", status_code=303)

@app.post("/api/entregadores/{eid}/remover")
def remover_entregador_route(request: Request, eid: int) -> RedirectResponse:
    if redir := auth.verificar_permissao(request, "entregadores"):
        return redir
    models.remover_entregador(eid)
    return RedirectResponse(url="/entregadores", status_code=303)

@app.post("/api/entregadores/{eid}/toggle-ativo")
def toggle_entregador_route(request: Request, eid: int) -> dict:
    if not auth.get_usuario_sessao(request):
        raise HTTPException(401, "Não autenticado")
    novo = models.toggle_ativo_entregador(eid)
    return {"ok": True, "ativo": novo}

@app.post("/api/entregadores/{eid}/mover")
async def mover_entregador_route(request: Request, eid: int) -> RedirectResponse:
    if redir := auth.verificar_permissao(request, "entregadores"):
        return redir
    form = await request.form()
    models.mover_entregador(eid, str(form.get("direcao", "")))
    return RedirectResponse(url="/entregadores", status_code=303)

@app.post("/api/entregadores/escala/set")
def api_set_status_entregador(
    request: Request,
    entregador_id: int = Form(...),
    data: str = Form(...),
    status: str = Form(""),
) -> dict:
    if not auth.get_usuario_sessao(request):
        raise HTTPException(401, "Não autenticado")
    models.set_status_entregador(entregador_id, data, status or None)
    return {"ok": True}

@app.post("/api/entregadores/{eid}/obs")
async def api_set_obs_entregador(request: Request, eid: int) -> dict:
    if not auth.get_usuario_sessao(request):
        raise HTTPException(401, "Não autenticado")
    form = await request.form()
    texto = str(form.get("texto", ""))
    models.set_obs_entregador(eid, texto)
    return {"ok": True}

@app.post("/api/entregadores/{eid}/cor")
async def api_set_cor_entregador(request: Request, eid: int) -> dict:
    if not auth.get_usuario_sessao(request):
        raise HTTPException(401, "Não autenticado")
    form = await request.form()
    cor = str(form.get("cor", ""))
    models.set_cor_entregador(eid, cor)
    return {"ok": True, "cor": cor}

@app.post("/api/entregadores/{eid}/telefone")
async def api_set_telefone_entregador(request: Request, eid: int) -> dict:
    if not auth.get_usuario_sessao(request):
        raise HTTPException(401, "Não autenticado")
    form = await request.form()
    telefone = str(form.get("telefone", ""))
    models.set_telefone_entregador(eid, telefone)
    return {"ok": True}


@app.post("/api/entregadores/limpar-escala")
async def api_limpar_escala_entregadores(request: Request) -> dict:
    if not auth.get_usuario_sessao(request):
        raise HTTPException(401, "Não autenticado")
    form = await request.form()
    mes_str = str(form.get("mes", ""))
    ano, mes_num = _parse_mes(mes_str if mes_str else None)
    dias_raw = form.getlist("dias_especificos")
    dias_especificos = dias_raw if dias_raw else None
    removidos = models.limpar_escala_entregadores(ano, mes_num, dias_especificos)
    return {"ok": True, "removidos": removidos}

@app.post("/api/entregadores/gerar-escala")
async def api_gerar_escala_entregadores(request: Request) -> dict:
    if not auth.get_usuario_sessao(request):
        raise HTTPException(401, "Não autenticado")
    form = await request.form()
    mes_str = str(form.get("mes", ""))
    ano, mes_num = _parse_mes(mes_str if mes_str else None)
    # 7 valores, um por dia da semana (0=Seg … 6=Dom)
    totais = [int(form.get(f"total_{i}", 4)) for i in range(7)]
    min_r_list = [int(form.get(f"min_rapido_{i}", 0)) for i in range(7)]
    min_n_list = [int(form.get(f"min_normal_{i}", 0)) for i in range(7)]
    sobrescrever = form.get("sobrescrever", "") == "1"
    dias_raw       = form.getlist("dias_especificos")
    dias_especificos = dias_raw if dias_raw else None
    resultado  = models.gerar_escala_auto(ano, mes_num, totais, min_r_list, min_n_list, dias_especificos, sobrescrever)
    return resultado


# ---------- PDF ----------

@app.get("/pdf/{tipo}")
def exportar_pdf(request: Request, tipo: str, mes: Optional[str] = None) -> Response:
    if redir := auth.verificar_permissao(request, "grade"):
        return redir
    tipo_upper = tipo.upper()
    if tipo_upper not in {"CONTRATADO", "EXTRA"}:
        raise HTTPException(400, "Tipo deve ser 'contratado' ou 'extra'")
    ano, mes_num = _parse_mes(mes)
    pdf_bytes = gerar_pdf_escala(ano, mes_num, tipo_upper)
    nome_arquivo = f"Escala_{tipo_upper.title()}s_{utils.nome_mes(mes_num)}_{ano}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'},
    )
