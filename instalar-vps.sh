#!/bin/bash
# instalar-vps.sh — instala a Escala dos Colaboradores na VPS Ubuntu
# Uso: bash instalar-vps.sh

set -e

REPO_URL="SEU_REPO_GITHUB_AQUI"   # ex: https://github.com/usuario/escala.git
INSTALL_DIR="/var/www/escala"
SERVICE_NAME="escala"
NGINX_CONF="escala.nginx.conf"

echo "→ Instalando dependências do sistema..."
sudo apt update -qq
sudo apt install -y python3 python3-venv python3-pip nginx git

echo "→ Clonando repositório..."
if [ -d "$INSTALL_DIR" ]; then
    echo "  Diretório já existe, fazendo git pull..."
    cd "$INSTALL_DIR"
    sudo git pull
else
    sudo git clone "$REPO_URL" "$INSTALL_DIR"
fi

sudo chown -R "$USER":"$USER" "$INSTALL_DIR"
cd "$INSTALL_DIR"

echo "→ Criando ambiente virtual e instalando dependências Python..."
python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt

echo "→ Populando banco de dados..."
if [ ! -f data/escala.db ]; then
    .venv/bin/python seed.py
else
    echo "  Banco já existe, pulando seed."
fi

echo "→ Configurando serviço systemd..."
sudo cp escala.service /etc/systemd/system/
sudo chown -R www-data:www-data "$INSTALL_DIR"
sudo systemctl daemon-reload
sudo systemctl enable --now "$SERVICE_NAME"
echo "  Status do serviço:"
sudo systemctl status "$SERVICE_NAME" --no-pager -l | head -5

echo "→ Configurando nginx..."
sudo cp "$NGINX_CONF" /etc/nginx/sites-available/"$SERVICE_NAME"
sudo ln -sf /etc/nginx/sites-available/"$SERVICE_NAME" /etc/nginx/sites-enabled/"$SERVICE_NAME"
sudo nginx -t
sudo systemctl reload nginx

echo ""
echo "✅ Instalação concluída!"
echo "   Acesse: http://escala.gruposingular.cloud"
echo ""
echo "Para HTTPS, rode:"
echo "   sudo apt install -y certbot python3-certbot-nginx"
echo "   sudo certbot --nginx -d escala.gruposingular.cloud"
