#!/bin/bash
# Se o banco ainda não existe no volume, copia o banco inicial do container
if [ ! -f /app/data/escala.db ]; then
    echo "→ Banco não encontrado no volume, copiando banco inicial..."
    mkdir -p /app/data
    cp /app/data_seed/escala.db /app/data/escala.db
    echo "→ Banco copiado com sucesso!"
else
    echo "→ Banco já existe no volume, mantendo dados."
fi

exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
