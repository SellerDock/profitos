# ProfitOS self-hosted

Wymagania: Docker z Compose w wersji co najmniej 2.20, domena wskazująca na serwer oraz dostępne z Internetu porty 80 i 443 (TCP; dla HTTP/3 również 443 UDP). Caddy automatycznie uzyskuje i odnawia certyfikat Let's Encrypt.

Wszystkie poniższe polecenia uruchamiaj w katalogu `deploy/selfhosted`.

1. Skopiuj konfigurację: `cp .env.example .env`.
2. Uzupełnij `.env`, w szczególności domenę, hasło bazy i `SECRET_KEY` wygenerowany przez `openssl rand -hex 32`. Użyj hasła bazy bez znaków wymagających kodowania w URL; przy zmianie danych bazy zachowaj zgodność z `DATABASE_URL`. Plik `.env` zawiera sekrety i nie powinien być udostępniany.
3. Zarejestruj aplikację na [apps.developer.allegro.pl](https://apps.developer.allegro.pl/) i wpisz jej identyfikator oraz sekret w `.env`. Ustaw w portalu i w `ALLEGRO_REDIRECT_URI` ten sam adres: `https://<domena>/api/v1/accounts/allegro/callback`.
4. Uruchom: `docker compose up -d --build`.
5. Załóż konto administratora: `docker compose exec apos-backend python -m scripts.setup --company "Nazwa firmy" --email admin@example.com`. Skrypt poprosi o hasło.

Aktualizacja: najpierw wykonaj kopię bazy, następnie uruchom `git pull && docker compose up -d --build`. Migracje wykonują się automatycznie przy starcie backendu.

Kopia bazy (podstaw nazwę użytkownika i bazy z `.env`):

```sh
docker compose exec -T apos-db pg_dump -U UZYTKOWNIK -d BAZA -Fc > backup.dump
```

Odtworzenie kopii do istniejącej bazy zastępuje dane w obiektach zawartych w kopii. Zatrzymaj aplikację na czas odtwarzania:

```sh
docker compose stop apos-scheduler apos-backend
docker compose exec -T apos-db pg_restore -U UZYTKOWNIK -d BAZA --clean --if-exists < backup.dump
docker compose up -d
```

**Utrata hasła Financial Vault oznacza nieodwracalną utratę dostępu do kosztów. Hasła nie można odzyskać.**
