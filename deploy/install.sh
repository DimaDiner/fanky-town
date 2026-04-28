#!/usr/bin/env bash
# Установка на Ubuntu 24.04 (root). Каталог приложения: /opt/fanky-town
set -euo pipefail

APP_DIR=/opt/fanky-town
REPO_URL="${REPO_URL:-https://github.com/DimaDiner/fanky-town.git}"

echo ">>> Обновление пакетов..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get upgrade -y
apt-get install -y python3.12-venv python3-pip git nginx ufw certbot python3-certbot-nginx

echo ">>> Фаервол..."
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable || true

if [[ ! -d "${APP_DIR}/.git" ]]; then
  echo ">>> Клонирование репозитория..."
  git clone "${REPO_URL}" "${APP_DIR}"
else
  echo ">>> Обновление из git..."
  cd "${APP_DIR}"
  git pull origin main
fi

cd "${APP_DIR}"

echo ">>> venv и зависимости..."
python3 -m venv venv
# shellcheck source=/dev/null
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

BOT_OK=false
if [[ -f .env ]]; then
  TOK=$(grep '^BOT_TOKEN=' .env | head -1 | cut -d= -f2- | tr -d '\r' | xargs)
  [[ -n "${TOK}" && ${#TOK} -ge 20 ]] && BOT_OK=true
fi
if [[ "${BOT_OK}" != true ]]; then
  [[ ! -f .env ]] && cp .env.example .env && chmod 600 .env
  echo ""
  echo ">>> ВАЖНО: в ${APP_DIR}/.env укажите BOT_TOKEN (из @BotFather), строка вида BOT_TOKEN=123456:ABC..."
  echo ">>> nano ${APP_DIR}/.env   затем снова:  bash ${APP_DIR}/deploy/install.sh"
  exit 1
fi
chmod 600 .env 2>/dev/null || true

chown -R www-data:www-data "${APP_DIR}"

echo ">>> systemd..."
cp "${APP_DIR}/deploy/funky-api.service" /etc/systemd/system/
cp "${APP_DIR}/deploy/funky-bot.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable funky-api funky-bot

echo ">>> Nginx..."
cp "${APP_DIR}/deploy/funky-town.conf" /etc/nginx/sites-available/funky-town
rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/funky-town /etc/nginx/sites-enabled/funky-town
nginx -t
systemctl reload nginx

echo ">>> Запуск приложения..."
systemctl restart funky-api funky-bot
systemctl status funky-api --no-pager -l || true

echo ""
echo ">>> Готово. Дальше:"
echo "    1) Убедитесь, что в ${APP_DIR}/.env указан BOT_TOKEN и WEBAPP_URL=https://funky-town-kst.kz"
echo "    2) HTTPS: certbot --nginx -d funky-town-kst.kz -d www.funky-town-kst.kz"
echo "    3) Логи: journalctl -u funky-api -u funky-bot -f"
