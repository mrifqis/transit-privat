# Transit Privat

Notepad dan transit file untuk satu pengguna. Login memakai kode TOTP dari HP.
Teks maksimal 256 KiB, file maksimal 25 MiB, dan kuota isi 500 MiB.
Masa simpan per kiriman 1–1.440 menit dengan default 60 menit. Sesi berakhir
setelah 15 menit tanpa akses atau 8 jam sejak masuk.

## Pemasangan di Ubuntu 24.04 dengan Nginx

Siapkan subdomain baru yang mengarah ke VPS. Ikuti langkah dari direktori paket.
Paket memakai Python dan SQLite tersendiri agar tidak perlu mengubah PHP-FPM
atau MariaDB yang dipakai aplikasi lain.

```bash
sudo apt update
sudo apt install python3-flask gunicorn qrencode
sudo bash deploy/pasang.sh
```

Di sesi SSH yang privat, buat kunci dan langsung tampilkan sebagai QR di terminal.
Pindai dengan aplikasi autentikator di HP. QR ini setara dengan kunci login.
Jangan simpan tangkapan layar atau rekaman terminal yang berisi QR.

```bash
sudo -u transit-privat /usr/bin/python3 /opt/transit-privat/app.py reset | qrencode -t ANSIUTF8
sudo systemctl enable --now transit-privat.service transit-privat-cleanup.timer
```

Isi variabel `transit_domain` dengan subdomain Anda.

```bash
transit_domain=transit.example.com
sed "s/transit\.example\.com/${transit_domain}/g" deploy/nginx.conf |
  sudo tee /etc/nginx/sites-available/transit-privat >/dev/null
sudo ln -s /etc/nginx/sites-available/transit-privat /etc/nginx/sites-enabled/transit-privat
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx --redirect -d "$transit_domain"
```

Jika Certbot belum tersedia, pasang paket `certbot` dan
`python3-certbot-nginx` melalui APT. Setelah sertifikat aktif, buka URL HTTPS
dan pastikan URL HTTP mengalihkan ke HTTPS. Periksa sinkronisasi waktu VPS
dengan `timedatectl status`. Setelah satu kode berhasil dipakai, tunggu kode
berikutnya untuk masuk pada komputer lain.

## Pemeriksaan setelah pemasangan

```bash
sudo systemctl status transit-privat.service
sudo systemctl list-timers transit-privat-cleanup.timer
sudo journalctl -u transit-privat-cleanup.service -n 15
```

Uji dengan catatan dan file contoh bermasa simpan satu menit. Pastikan tanpa
sesi URL item mengembalikan HTTP 401, dan dengan sesi URL item mengembalikan
404 setelah habis. Penghapusan SQLite berjalan pada jadwal menit berikutnya.
Tombol Kunci sekarang mengakhiri sesi browser tersebut.

## Mengganti autentikator

Jalankan dari SSH yang privat. Proses mencabut semua sesi aktif dan menyimpan
kiriman yang masih berlaku.

```bash
sudo systemctl stop transit-privat.service
sudo -u transit-privat /usr/bin/python3 /opt/transit-privat/app.py reset | qrencode -t ANSIUTF8
sudo systemctl start transit-privat.service
```

Data sementara berada di `/var/lib/transit-privat`. Jika kebijakan backup
memungkinkan, kecualikan lokasi itu agar kiriman kedaluwarsa tidak ikut
tersimpan. Kuota berlaku untuk isi kiriman. SQLite dan jurnal transaksi
membutuhkan ruang tambahan. Penghapusan di VPS tidak menghapus salinan yang
sudah diunduh atau disalin di perangkat. Pada komputer bersama, klik tombol
kunci dan hapus salinan lokal bila sudah selesai.
