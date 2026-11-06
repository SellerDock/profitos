# Historia zmian

Format opiera się na [Keep a Changelog](https://keepachangelog.com/pl/1.1.0/).

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
