# ProfitOS

## In English

ProfitOS is an open-source tool for analyzing net profit from Allegro sales. It combines orders, fees, returns, advertising and stock data; purchase costs are encrypted in the browser. See the [self-hosting guide](deploy/selfhosted/README.md). Commercial hosting is available at [profitos.pl](https://profitos.pl). Licensed under AGPL-3.0-or-later; see [LICENSE](LICENSE), [CLA](CLA.md) and [trademarks](TRADEMARKS.md).

## O projekcie

ProfitOS pomaga analizować zysk netto ze sprzedaży na Allegro. Łączy dane o zamówieniach, opłatach Allegro, zwrotach, reklamach i magazynie. Koszty zakupu są szyfrowane w przeglądarce w Financial Vault za pomocą Argon2id i AES-GCM. Model bezpieczeństwa opisuje [SECURITY.md](SECURITY.md).

Zrzuty ekranu dodamy później.

## Szybki start

Instrukcja instalacji własnej instancji znajduje się w [deploy/selfhosted/README.md](deploy/selfhosted/README.md). Dostępny jest również komercyjny hosting na [profitos.pl](https://profitos.pl).

## Architektura

- Frontend: React i Vite.
- Backend: FastAPI w katalogu `backend/`.
- Dane aplikacji: PostgreSQL.
- Zadania cykliczne: APScheduler w osobnym procesie.
- Integracja Allegro pobiera dane sprzedaży i opłat.
- Silnik raportów łączy dane do analizy zysku.
- Financial Vault szyfruje koszty w przeglądarce.
- `TenantScope` wspiera izolację danych firm.
- `DEPLOYMENT_MODE=selfhosted` to domyślny tryb jednej firmy.
- `DEPLOYMENT_MODE=hosted` służy do prowadzenia usługi profitos.pl.

## Rozwój lokalny

Do pracy lokalnej użyj zestawu z `deploy/selfhosted/`. Skopiuj `.env.example` do `.env`, uzupełnij wymagane sekrety i ustaw w nim wszystkie poniższe wartości:

```dotenv
APP_BASE_URL=http://localhost
BACKEND_CORS_ORIGINS=http://localhost
ALLEGRO_REDIRECT_URI=http://localhost/api/v1/accounts/allegro/callback
AUTH_COOKIE_SECURE=false
PROFITOS_DOMAIN=localhost
```

`AUTH_COOKIE_SECURE=false` stosuj wyłącznie lokalnie przez HTTP. W `Caddyfile` zastąp pierwszy blok odkomentowanym wariantem `http://localhost`. Produkcyjny redirect URI Allegro może wymagać HTTPS, dlatego pełny OAuth lokalnie może być niedostępny. Następnie:

```bash
cd deploy/selfhosted
docker compose up -d --build
docker compose exec apos-backend python -m scripts.setup --company "Moja firma" --email admin@example.com
```

Aplikacja będzie dostępna pod http://localhost.

Testy backendu wymagają **osobnej instancji PostgreSQL i bazy testowej** – fixture'y modyfikują dane. Ustaw dane dostępu i wymagane zmienne aplikacji, w tym `DATABASE_URL`, a następnie uruchom migracje i testy:

```bash
cd backend
export POSTGRES_HOST=localhost POSTGRES_DB=apos_test APOS_TEST_DB=1
alembic upgrade head
python -m pytest tests -q
```

`DATABASE_URL` musi wskazywać tę samą osobną bazę testową. Szczegóły zabezpieczeń są w [backend/tests/conftest.py](backend/tests/conftest.py).

Frontend:

```bash
cd frontend
npm ci
npx vitest run
npx tsc --noEmit
```

Zasady udziału w projekcie opisuje [CONTRIBUTING.md](CONTRIBUTING.md).

## Licencja i znak towarowy

Autorem projektu jest Wojciech Skarbek. Kod jest dostępny na licencji [AGPL-3.0-or-later](LICENSE). Wkład wymaga podpisania [CLA](CLA.md). Nazwa i logo podlegają zasadom opisanym w [TRADEMARKS.md](TRADEMARKS.md).
