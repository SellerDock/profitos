# ProfitOS self-hosted

Wymagania: Docker z Compose w wersji co najmniej 2.20, domena wskazująca na serwer oraz dostępne z Internetu porty 80 i 443 (TCP; dla HTTP/3 również 443 UDP). Caddy automatycznie uzyskuje i odnawia certyfikat Let's Encrypt.

Wszystkie poniższe polecenia uruchamiaj w katalogu `deploy/selfhosted`.

1. Skopiuj konfigurację: `cp .env.example .env`.
2. Uzupełnij `.env`, w szczególności domenę, hasło bazy i `SECRET_KEY` wygenerowany przez `openssl rand -hex 32`. Użyj hasła bazy bez znaków wymagających kodowania w URL; przy zmianie danych bazy zachowaj zgodność z `DATABASE_URL`. Plik `.env` zawiera sekrety i nie powinien być udostępniany.
3. Zarejestruj aplikację na [apps.developer.allegro.pl](https://apps.developer.allegro.pl/) i wpisz jej identyfikator oraz sekret w `.env`. Ustaw w portalu i w `ALLEGRO_REDIRECT_URI` ten sam adres: `https://<domena>/api/v1/accounts/allegro/callback`.
4. Uruchom: `docker compose up -d --build`.
5. Załóż konto administratora: `docker compose exec apos-backend python -m scripts.setup --company "Nazwa firmy" --email admin@example.com`. Skrypt poprosi o hasło.

## Lokalna instalacja HTTP

Skopiuj `.env.example` do `.env`, uzupełnij wymagane sekrety i ustaw:

```dotenv
APP_BASE_URL=http://localhost
BACKEND_CORS_ORIGINS=http://localhost
ALLEGRO_REDIRECT_URI=http://localhost/api/v1/accounts/allegro/callback
AUTH_COOKIE_SECURE=false
PROFITOS_DOMAIN=localhost
```

`AUTH_COOKIE_SECURE=false` stosuj wyłącznie lokalnie przez HTTP. W `Caddyfile` zastąp pierwszy blok odkomentowanym wariantem `http://localhost`. Uruchom instalację i załóż administratora zgodnie z krokami 4 i 5 powyżej. Produkcyjny redirect URI Allegro może wymagać HTTPS, dlatego pełny OAuth lokalnie może być niedostępny.

## Aktualizacja i kopie zapasowe

Aktualizacja: najpierw wykonaj kopię bazy, następnie uruchom `git pull && docker compose up -d --build`. Migracje wykonują się automatycznie przy starcie backendu.

Kopia bazy zawiera jawne tokeny OAuth Allegro, sekrety TOTP i sesje. Koszty Financial Vault są zaszyfrowane. Przechowuj kopię zaszyfrowaną, z uprawnieniami 600, poza serwerem i regularnie testuj jej odtworzenie. Zachowaj również bezpieczną kopię `.env`, w tym `SECRET_KEY`, potrzebnego do odtworzenia instalacji.

Kopia bazy (podstaw nazwę użytkownika i bazy z `.env`):

```sh
umask 077
docker compose exec -T apos-db pg_dump -U UZYTKOWNIK -d BAZA -Fc > backup.dump
gpg -c backup.dump
chmod 600 backup.dump backup.dump.gpg
```

Po bezpiecznym przeniesieniu zaszyfrowanej kopii poza serwer usuń lokalny jawny plik `backup.dump`. Możesz też użyć narzędzia takiego jak restic.

Odtworzenie kopii do istniejącej bazy zastępuje dane w obiektach zawartych w kopii. Odszyfruj kopię do pliku `backup.dump` z uprawnieniami 600, a następnie zatrzymaj backend i scheduler na czas odtwarzania:

```sh
docker compose stop apos-scheduler apos-backend
docker compose exec -T apos-db pg_restore -U UZYTKOWNIK -d BAZA --clean --if-exists --exit-on-error --single-transaction < backup.dump
docker compose up -d apos-backend apos-scheduler
```

Po odtworzeniu usuń lokalny jawny plik kopii.

**Utrata hasła Financial Vault oznacza nieodwracalną utratę dostępu do kosztów. Hasła nie można odzyskać.**
