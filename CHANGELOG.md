# Historia zmian

Format opiera się na [Keep a Changelog](https://keepachangelog.com/pl/1.1.0/).

## [1.2.0] – 2026-11-07

### Bezpieczeństwo

- Podłączanie konta Allegro (OAuth) jest jednorazową transakcją przypisaną do przeglądarki, która je rozpoczęła (#1). Parametr `state` zawiera losowy kod zapisany także w ciasteczku `apos_oauth` (httponly, SameSite=Lax); w bazie trzymamy tylko jego skrót. Powrót z Allegro bez tego ciasteczka, ponowne użycie tego samego `state` oraz transakcja starsza niż 15 minut są odrzucane. Firma i konto pochodzą z zapisanej transakcji, nie z treści `state`.
- Nowa tabela `allegro_oauth_transactions` (migracja `20261107_0023`).

### Zmieniono

- W aplikacji Android konto Allegro podłącza się w przeglądarce – aplikacja otwiera Allegro poza WebView, więc powrót nie trafiłby do tej samej sesji. Ustawienia pokazują w aplikacji wyjaśnienie zamiast przycisku.

## [1.1.2] – 2026-11-07

### Poprawiono

- Tworzenie pierwszego administratora (`bootstrap`) sprawdza adres e-mail tymi samymi regułami co logowanie. Wcześniej dało się utworzyć konto, na które nie można się zalogować, a ponowna konfiguracja była już zablokowana.
- Testy backendu przerywają się, gdy `DATABASE_URL` aplikacji wskazuje inną bazę niż `POSTGRES_HOST`/`POSTGRES_DB` bazy testowej (#7).

## [1.1.1] – 2026-11-07

### Poprawiono

- Regulamin (`/terms`, `/regulamin`) otwiera się bez logowania – wcześniej nieudane odświeżenie sesji przekierowywało na stronę logowania.

## [1.1.0] – 2026-11-07

### Dodano

- Tryb `hosted`: pula 1000 zamówień na start dla nowych firm, potem darmowe 200 zamówień miesięcznie; firmy istniejące zachowują okres próbny.
- Pakiety roczne: zamówienie przez klienta, faktura w iFirmie lub numer wpisany ręcznie, oznaczanie płatności, wyższy pakiet od dnia opłaty i odnowienie od końca bieżącego.
- Przypomnienia e-mail i baner w panelu: przekroczenie limitu, propozycja wyższego pakietu, odnowienie i wygaśnięcie pakietu.
- Panel operatora „Zamówienia pakietów” oraz przychód z pakietów rocznych.

### Zmieniono

- Regulamin w wersji 2026-11-07 (pula startowa, pakiety roczne, płatności).
- Zadania harmonogramu z `misfire_grace_time`, żeby spóźniony przebieg nie był pomijany.

## [1.0.1] – 2026-11-06

### Poprawiono

- Tytuł karty przeglądarki bierze nazwę produktu z konfiguracji (`BRAND_PRODUCT_NAME`).

## [1.0.0] – 2026-11-06

Pierwsze wydanie open source.

### Dodano

- Samodzielną instalację z Compose i Caddy oraz konfigurację marki i adresów.
- Tryby `selfhosted` i `hosted`, konfigurację dostępną we frontendzie oraz CLI do zakładania instalacji jednej firmy.
- Integrację profit-by-ean z opcjonalnym odszyfrowaniem Financial Vault po stronie serwera, domyślnie wyłączonym.
- Testy izolacji firm i klasyfikacji tras oraz syntetyczne testy rozliczeń, zwrotów i dostaw.
- Konfigurowalny User-Agent Allegro.
- Walidację `SECRET_KEY` i logowanie administratora instalacji self-hosted.
- Limity przesyłanych plików.

### Poprawiono

- Bezpieczeństwo wylogowania i izolację danych w przeglądarce.

### Zmieniono

- Usunięto tryb testów na bazie produkcyjnej i starsze pomocnicze mechanizmy.
- Ograniczono wzorce mnożników SKU do właściwej firmy.
