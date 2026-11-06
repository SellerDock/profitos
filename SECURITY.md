# Bezpieczeństwo

## Zgłaszanie podatności

Zgłaszaj podatności prywatnie przez [GitHub Security Advisories](https://github.com/SellerDock/profitos/security/advisories/new), wybierając „Report a vulnerability”. Nie publikuj ich w publicznych Issues. Opisz wpływ, warunki i kroki odtworzenia, bez przesyłania rzeczywistych sekretów lub danych osobowych.

Zakres obejmuje kod ProfitOS, instalację self-hosted, API, izolację danych firm i Financial Vault. Problemy dotyczące usług zewnętrznych zgłaszaj również ich operatorom odpowiednim prywatnym kanałem.

## Model zagrożeń Financial Vault

Koszty zakupu są standardowo szyfrowane w przeglądarce za pomocą AES-256-GCM; klucz jest wyprowadzany z hasła przez Argon2id. Serwer przechowuje szyfrogramy kosztów i parametry KDF, a nie hasło ani jawne koszty. Utrata hasła oznacza utratę dostępu do zaszyfrowanych kosztów.

Bezpieczeństwo zależy od zaufania do JavaScriptu dostarczanego przeglądarce. [frontend/index.html](frontend/index.html) ładuje skrypt kryptograficzny z atrybutem `integrity` (SRI), dzięki któremu przeglądarka sprawdza zgodność jego bajtów z podanym skrótem. [VerifyBundleHash.tsx](frontend/src/components/VerifyBundleHash.tsx) pozwala na żądanie pobrać plik i porównać jego SHA-256 z wartością z endpointu `crypto-proof`. HTML, kod weryfikujący i oczekiwany skrót mogą jednak pochodzić od tego samego serwera – jego przejęcie może podważyć te kontrole. Dla niezależnej weryfikacji porównaj kod i skróty z zaufanym wydaniem.

Opcjonalny `POST /api/v1/integrations/profit-by-ean` wykonuje odszyfrowanie na serwerze i jest domyślnie wyłączony (`VAULT_SERVER_DECRYPTION_ENABLED`). Po włączeniu klient przekazuje kod sejfu w żądaniu, więc serwer może uzyskać dostęp do jawnych kosztów podczas jego obsługi.
