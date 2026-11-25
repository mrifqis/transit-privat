#!/bin/bash
set -eu
cd -- "$(dirname -- "$0")/.."
if [ "$(id -u)" -ne 0 ]; then
    echo "Jalankan dengan sudo."
    exit 1
fi
if ! id transit-privat >/dev/null 2>&1; then
    useradd --system --gid www-data --no-create-home --shell /usr/sbin/nologin transit-privat
fi
install -d -m 0755 /opt/transit-privat/web
install -d -m 0700 -o transit-privat -g www-data /var/lib/transit-privat /etc/transit-privat
install -m 0644 app.py /opt/transit-privat/
install -m 0644 web/* /opt/transit-privat/web/
install -m 0644 deploy/*.service deploy/*.timer /etc/systemd/system/
systemctl daemon-reload
runuser -u transit-privat -- /usr/bin/python3 /opt/transit-privat/app.py init
echo "Lanjutkan penyiapan autentikator dan HTTPS sesuai README.md."
