import { KeyRound, ListChecks } from 'lucide-react'
import { CliVerificationSnippets } from '../components/CliVerificationSnippets'
import CryptoProof from '../components/CryptoProof'
import { OfflineDecryptWalkthrough } from '../components/OfflineDecryptWalkthrough'
import { SecurityFAQ } from '../components/SecurityFAQ'
import { VerifyBundleHash } from '../components/VerifyBundleHash'
import { useAuth } from '../context/AuthContext'
import { productName } from '../config/brand'

const HOW_IT_WORKS = [
  'Ustalasz hasło sejfu finansowego. Standardowo nie wysyłamy go na serwer ani nie zapisujemy.',
  'Z hasła w Twojej przeglądarce powstaje klucz szyfrujący (Argon2id). Standardowo klucz pozostaje na komputerze.',
  'Koszty zakupu są szyfrowane (AES-256-GCM) jeszcze zanim wyjdą z przeglądarki.',
  'Standardowo na serwer trafia zaszyfrowana treść. Ponowny odczyt kwoty wymaga Twojego hasła.',
]

const COMMITMENTS = [
  'Nie mamy klucza zapasowego – jeśli zgubisz hasło sejfu, nie odzyskamy kosztów.',
  'Nie logujemy hasła ani odszyfrowanych kwot; w logach i kopiach zapasowych bazy jest wyłącznie zaszyfrowana treść.',
  'Kod odpowiedzialny za szyfrowanie jest publiczny, wersjonowany i ma jawny odcisk pliku do weryfikacji.',
  'Zmiana ceny zakupu tworzy nowy zaszyfrowany rekord — historia kosztów także jest szyfrowana, nie zwykłym tekstem.',
  'Koszt możesz odszyfrować również poza panelem, offline, korzystając z opublikowanego narzędzia.',
]

export default function Security() {
  const { user } = useAuth()

  return (
    <div className="max-w-4xl space-y-8">
      <section>
        <h1 className="mb-3 text-2xl font-bold text-slate-950">Bezpieczeństwo danych finansowych</h1>
        <p className="max-w-3xl text-sm leading-6 text-slate-600">
          Koszty zakupu produktów są szyfrowane na Twoim komputerze. Na serwer {productName()}{' '}
          standardowo trafia zaszyfrowana wersja. Opcjonalna integracja serwerowa jest domyślnie wyłączona; działa dopiero po włączeniu przez administratora i podaniu kodu sejfu przez klienta. Wtedy serwer może odszyfrować koszty podczas obsługi żądania.
          To najbardziej wrażliwa część danych sprzedawcy, więc traktujemy ją inaczej niż resztę —
          poniżej tłumaczymy, jak to działa i jak możesz to samodzielnie sprawdzić.
        </p>
      </section>

      <section className="apos-panel p-5">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <KeyRound size={18} className="text-finance-blue" />
          <h2 className="text-lg font-semibold text-slate-950">Jak to działa w skrócie</h2>
        </div>
        <p className="mb-4 max-w-3xl text-sm leading-6 text-slate-600">
          Szyfrowanie po stronie przeglądarki oznacza, że wrażliwe kwoty stają się nieczytelne
          jeszcze zanim opuszczą Twój komputer. Cały proces w czterech krokach:
        </p>
        <ol className="space-y-3">
          {HOW_IT_WORKS.map((step, index) => (
            <li key={step} className="flex gap-3">
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-finance-blue text-xs font-bold text-white">
                {index + 1}
              </span>
              <span className="text-sm leading-6 text-slate-600">{step}</span>
            </li>
          ))}
        </ol>
      </section>

      <section className="apos-panel p-5">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <ListChecks size={18} className="text-finance-blue" />
          <h2 className="text-lg font-semibold text-slate-950">Zasady, których się trzymamy</h2>
        </div>
        <ul className="space-y-2">
          {COMMITMENTS.map(item => (
            <li key={item} className="flex gap-3 text-sm leading-6 text-slate-600">
              <span aria-hidden className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-finance-blue" />
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </section>

      <CryptoProof />

      <VerifyBundleHash />

      <CliVerificationSnippets />

      {user ? (
        <OfflineDecryptWalkthrough />
      ) : (
        <section className="apos-panel p-4">
          <h2 className="mb-2 text-base font-semibold text-slate-950">Sprawdzenie własnego rekordu</h2>
          <p className="text-sm leading-6 text-slate-600">
            Publicznie pokazujemy sposób szyfrowania i hash pliku. Pobranie konkretnego
            zaszyfrowanego kosztu jest dostępne po zalogowaniu, bo dotyczy danych z Twojego konta.
          </p>
        </section>
      )}

      <SecurityFAQ />

      <section className="apos-panel p-4">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <h2 className="text-base font-semibold text-slate-950">Odblokowanie odciskiem w aplikacji Android</h2>
        </div>
        <p className="text-sm leading-6 text-slate-600">
          W aplikacji na Androida możesz opcjonalnie włączyć odblokowanie sejfu odciskiem palca.
          Opcja jest domyślnie wyłączona — decydujesz sam. Gdy ją włączysz, klucz sejfu jest
          opakowywany kluczem z Android Keystore (StrongBox, jeśli urządzenie go udostępnia,
          albo bezpieczny magazyn TEE) i zapisywany wyłącznie w telefonie;
          każde użycie wymaga potwierdzenia biometrią. Standardowo hasło nie jest wysyłane na serwer.
          Zmiana biometrii w ustawieniach systemu unieważnia zapis — wtedy włączasz opcję ponownie.
          Zapamiętany klucz możesz w każdej chwili usunąć w aplikacji, a przy wylogowaniu usuwamy
          go automatycznie.
        </p>
      </section>

      <section className="apos-panel p-4">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <h2 className="text-base font-semibold text-slate-950">Co warto wiedzieć</h2>
        </div>
        <p className="text-sm leading-6 text-slate-600">
          Gdy wpisujesz hasło sejfu w przeglądarce, nadal musisz ufać stronie, którą właśnie
          otwierasz. Dlatego pokazujemy publiczny kod szyfrowania, hashe plików i narzędzie do
          sprawdzenia danych poza panelem. To zmniejsza ryzyko, ale nie zastępuje pełnego audytu
          zewnętrznego.
        </p>
      </section>
    </div>
  )
}
