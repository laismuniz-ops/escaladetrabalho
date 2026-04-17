FROM python:3.11-slim

WORKDIR /app

# Instala dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o código
COPY . .

# Guarda o banco inicial numa pasta separada (seed)
RUN mkdir -p /app/data_seed && \
    if [ -f /app/data/escala.db ]; then cp /app/data/escala.db /app/data_seed/escala.db; fi

RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

CMD ["/app/entrypoint.sh"]
