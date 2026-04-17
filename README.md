# Escala dos Colaboradores

Sistema web para organizar a escala dos funcionários (contratados + extras) da Singular.

## O que o sistema faz

- **Equipe do dia** — seleciona uma data e mostra quem trabalha, agrupado por setor e tipo (contratado/extra)
- **Grade mensal editável** — clique numa célula pra alternar turnos (Manhã → Tarde → Folga → Férias → vazio). Shift+clique apaga
- **Visão individual** — escala de um funcionário no mês com totais (manhãs, tardes, folgas, férias)
- **Cadastro de funcionários** — CRUD completo
- **Exportação em PDF** — escala de contratados e de extras, layout similar aos PDFs originais

## Stack

- Python 3.9+ (usa o que já vem no macOS e Ubuntu)
- FastAPI + Uvicorn
- SQLite (banco em arquivo, zero configuração)
- Jinja2 + Tailwind CSS (via CDN)
- fpdf2 (geração de PDFs)

## Rodando no seu Mac

```bash
# 1. Criar ambiente virtual (só na primeira vez)
python3 -m venv .venv

# 2. Ativar e instalar dependências (só na primeira vez)
.venv/bin/pip install -r requirements.txt

# 3. Popular banco com dados de abril/2026 (só na primeira vez)
.venv/bin/python seed.py

# 4. Subir o servidor (sempre que quiser usar)
.venv/bin/uvicorn app.main:app --reload
```

Depois abra http://127.0.0.1:8000 no navegador.

Para resetar o banco e recomeçar:
```bash
.venv/bin/python seed.py --reset
```

## Estrutura

```
.
├── app/
│   ├── main.py           # FastAPI (rotas e APIs)
│   ├── database.py       # Conexão SQLite
│   ├── models.py         # Queries (funcionários, escala)
│   ├── pdf_export.py     # Geração de PDFs
│   ├── utils.py          # Utilitários de data
│   ├── templates/        # HTML (Jinja2)
│   ├── static/           # CSS
│   └── fonts/            # DejaVu Sans (TTF Unicode pra PDFs)
├── data/
│   └── escala.db         # Banco SQLite (gerado no primeiro run)
├── exports/              # PDFs gerados
├── seed.py               # Importa dados iniciais de abril/2026
├── requirements.txt
└── DEPLOY.md             # Guia de deploy na VPS Ubuntu
```

## Backup

O banco inteiro é um único arquivo: `data/escala.db`. Pra fazer backup:
```bash
cp data/escala.db data/escala-backup-$(date +%Y%m%d).db
```

## Deploy na VPS Ubuntu

Veja [DEPLOY.md](DEPLOY.md).
