# Deploy na VPS Ubuntu

Guia passo a passo pra subir o sistema na sua VPS Ubuntu (testado em 22.04 e 24.04).

## Pré-requisitos

- Acesso SSH à VPS como usuário com `sudo`
- Um domínio ou subdomínio apontando pra VPS (opcional, mas recomendado pra HTTPS)

## 1. Instalar dependências do sistema

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx git
```

## 2. Clonar/copiar o projeto

Se você versionou no Git:
```bash
cd /var/www
sudo git clone <seu-repo> escala
sudo chown -R $USER:$USER /var/www/escala
```

Ou copie via `scp` do seu Mac:
```bash
# do seu Mac
scp -r "/Users/laismunizlima/Escala dos colaboradores" usuario@seu-ip:/tmp/escala
# na VPS
sudo mv /tmp/escala /var/www/escala
sudo chown -R $USER:$USER /var/www/escala
```

## 3. Instalar dependências Python

```bash
cd /var/www/escala
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

## 4. Rodar o seed (só na primeira vez)

```bash
.venv/bin/python seed.py
```

## 5. Testar que sobe

```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Em outro terminal:
```bash
curl http://127.0.0.1:8000/
```

Se voltar HTML, tá funcionando. `Ctrl+C` pra parar.

## 6. Configurar systemd (pra rodar como serviço)

Crie `/etc/systemd/system/escala.service`:

```bash
sudo nano /etc/systemd/system/escala.service
```

Conteúdo:
```ini
[Unit]
Description=Escala dos Colaboradores
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/var/www/escala
ExecStart=/var/www/escala/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Ajuste as permissões e habilite:
```bash
sudo chown -R www-data:www-data /var/www/escala
sudo systemctl daemon-reload
sudo systemctl enable --now escala
sudo systemctl status escala
```

## 7. Configurar Nginx como proxy reverso

Crie `/etc/nginx/sites-available/escala`:

```bash
sudo nano /etc/nginx/sites-available/escala
```

Conteúdo (substitua `seudominio.com.br`):
```nginx
server {
    listen 80;
    server_name seudominio.com.br;

    client_max_body_size 10M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Ative e recarregue:
```bash
sudo ln -s /etc/nginx/sites-available/escala /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

## 8. HTTPS com Let's Encrypt (recomendado)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d seudominio.com.br
```

Siga o wizard — ele atualiza o nginx automaticamente e configura renovação automática.

## 9. Firewall (UFW)

```bash
sudo ufw allow 'Nginx Full'
sudo ufw allow OpenSSH
sudo ufw enable
```

## Manutenção

### Ver logs
```bash
sudo journalctl -u escala -f        # serviço
sudo tail -f /var/log/nginx/access.log
```

### Reiniciar
```bash
sudo systemctl restart escala
```

### Atualizar código
```bash
cd /var/www/escala
git pull                         # se usa git
sudo systemctl restart escala
```

### Backup do banco
```bash
cp /var/www/escala/data/escala.db ~/escala-backup-$(date +%Y%m%d).db
```

Cron diário (opcional):
```bash
# crontab -e
0 3 * * * cp /var/www/escala/data/escala.db /root/backups/escala-$(date +\%Y\%m\%d).db
```

## Proteger o acesso (opcional, recomendado)

Como o sistema **não tem login**, qualquer um com a URL acessa. Duas opções:

### A) Basic Auth no Nginx (simples)

```bash
sudo apt install -y apache2-utils
sudo htpasswd -c /etc/nginx/.htpasswd seu-usuario
```

No bloco `location /` do Nginx, adicione:
```nginx
auth_basic "Escala — Acesso Restrito";
auth_basic_user_file /etc/nginx/.htpasswd;
```

Recarregue: `sudo systemctl reload nginx`.

### B) Restringir por IP

No mesmo bloco `location /`:
```nginx
allow SEU.IP.AQUI;
deny all;
```

## Troubleshooting

- **500 ou "Bad Gateway"**: `sudo systemctl status escala` e `sudo journalctl -u escala -n 50`
- **PDF não gera**: verifique que `app/fonts/DejaVuSans.ttf` foi copiado pra VPS
- **Mudanças não aparecem**: `sudo systemctl restart escala`
