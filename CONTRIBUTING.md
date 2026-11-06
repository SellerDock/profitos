# Współtworzenie ProfitOS

## Zgłaszanie błędów

Sprawdź istniejące Issues, a następnie użyj szablonu błędu. Podaj kroki odtworzenia, oczekiwany i rzeczywisty wynik oraz wersję i środowisko. Usuń sekrety i dane osobowe. Podatności zgłaszaj prywatnie zgodnie z [SECURITY.md](SECURITY.md).

## Pull request

Przed większą zmianą otwórz Issue, aby uzgodnić kierunek. Opisz zmianę i sposób jej sprawdzenia, dodaj potrzebne testy i wypełnij checklistę PR. Przy pierwszym PR bot CLA Assistant poprosi o podpisanie [CLA](CLA.md).

Stosuj konwencję z historii: `feat(scope): opis po polsku`, `fix(scope): opis po polsku`, `test(scope): opis po polsku` lub `chore(scope): opis po polsku`.

## Testy

Uruchom testy dotyczące zmienionego modułu; przed PR sprawdź również testy backendu i frontendu oraz typy i build frontendu zgodnie z [README](README.md) i [CI](.github/workflows/ci.yml). Testy backendu wymagają osobnej instancji PostgreSQL i `APOS_TEST_DB=1` – nie używaj bazy zawierającej dane aplikacji.

## Izolacja danych firm

Każdą nową trasę API dopisz do `ROUTE_CLASSIFICATION` w [backend/tests/test_route_tenant_classification.py](backend/tests/test_route_tenant_classification.py). Trasa obsługująca dane firmy musi mieć test w [backend/tests/test_tenant_isolation_endpoints.py](backend/tests/test_tenant_isolation_endpoints.py). Zapytania o dane firm zawsze ograniczaj filtrem `tenant_id`, korzystając z `TenantScope`; sprawdzaj również własność obiektów i powiązań.

## Dodawanie kanału sprzedaży

Obecny kod jest pisany pod Allegro, między innymi w [allegro.py](backend/app/services/allegro.py) i [import_service.py](backend/app/services/import_service.py). Wspólny interfejs kanałów jest planowany. Przed większym PR dotyczącym nowego kanału rozpocznij dyskusję w Issues.
