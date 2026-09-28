# Скрипт запускается на VPS от root:
#   scp -r backend/scripts/bootstrap_server.sh root@<ip>:/root/
#   ssh root@<ip> 'bash /root/bootstrap_server.sh'
#
# Переменные можно передать заранее:
#   VPN_PORT=443 REALITY_TARGET=www.microsoft.com:443 bash bootstrap_server.sh
