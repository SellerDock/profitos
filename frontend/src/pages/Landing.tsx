import { FormEvent, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, Navigate } from 'react-router-dom'
import {
  BarChart3,
  Boxes,
  CheckCircle2,
  ChevronDown,
  DatabaseZap,
  Github,
  Layers,
  Lock,
  Megaphone,
  Receipt,
  ShieldCheck,
  TrendingUp,
} from 'lucide-react'
import { authApi } from '../api/client'
import { CRYPTO_REPO_URL } from '../crypto/CRYPTO_PIN'
import { PublicThemeToggle } from '../components/PublicThemeToggle'
import { productName, supportEmail, appUrl, SOURCE_REPO_URL, SELFHOST_GUIDE_URL, ISSUES_URL } from '../config/brand'
import { BrandLogo } from '../components/BrandLogo'
import { useTheme } from '../context/ThemeContext'
import { IS_APP } from '../utils/isApp'

function Section({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`mx-auto max-w-6xl px-5 py-20 ${className}`}>{children}</section>
}

const featureCards = [
  {
    icon: BarChart3,
    title: 'Pełny wynik Allegro',
    text: 'Dla każdego SKU, okresu i konta. Prowizje, reklamy, zwroty, wyrównania Allegro Ceny, wszystko zmapowane i policzone netto.',
  },
  {
    icon: ShieldCheck,
    title: 'Twoje koszty są Twoje',
    text: 'Koszty zakupu szyfrowane Argon2id+AES-256-GCM po stronie Twojej przeglądarki. Standardowo klucz nie trafia na serwer. Opcjonalna integracja serwerowa, domyślnie wyłączona, wymaga włączenia przez administratora i podania kodu sejfu przez klienta.',
  },
  {
    icon: DatabaseZap,
    title: 'Wiele kont Allegro w jednym widoku',
    text: 'Importujemy zamówienia, rozliczenia, zwroty, refundy i statystyki reklam dla każdego konta. Możesz zobaczyć wynik łącznie albo osobno dla wybranego konta.',
  },
]

const pricing = [
  ['Do 200 zamówień miesięcznie', '0 zł', 'za darmo'],
  ['Do 1000 zamówień miesięcznie', '99 zł', 'rocznie netto'],
  ['Do 5000 zamówień miesięcznie', '299 zł', 'rocznie netto'],
  ['Do 25 000 zamówień miesięcznie', '499 zł', 'rocznie netto'],
  ['Powyżej 25 000 zamówień miesięcznie', 'Indywidualnie', 'kontakt'],
]

const benefits = [
  {
    icon: TrendingUp,
    title: 'Zysk netto, nie sam przychód',
    text: 'Widzisz realny wynik po prowizjach, reklamach, zwrotach i kosztach zakupu. Bez ręcznego zbierania danych z kilku miejsc.',
  },
  {
    icon: Layers,
    title: 'Rentowność w każdym przekroju',
    text: 'Analiza per SKU, konto, dzień i dowolny okres. Od razu wiesz, które produkty realnie zarabiają, a które tylko generują obrót.',
  },
  {
    icon: Megaphone,
    title: 'Allegro Ads wliczone w wynik',
    text: 'Importujemy statystyki kampanii i przypisujemy koszt reklam do właściwych ofert. Ocena ROI przestaje być zgadywanką.',
  },
  {
    icon: Receipt,
    title: 'Prowizje i zwroty rozliczone',
    text: 'Rozliczenia Allegro, korekty cen, refundy prowizji i zwroty klientów są zmapowane i policzone netto zgodnie z rozliczeniem Allegro.',
  },
  {
    icon: Boxes,
    title: 'Stany magazynowe pod ręką',
    text: 'Poziomy zapasów obok danych sprzedażowych, żeby planowanie zatowarowania opierało się na rzeczywistej rotacji.',
  },
  {
    icon: Lock,
    title: 'Koszty zakupu tylko dla Ciebie',
    text: 'Ceny zakupu szyfrujesz hasłem w przeglądarce. Standardowo na serwer trafia zaszyfrowana treść. Opcjonalna integracja serwerowa jest domyślnie wyłączona i wymaga włączenia przez administratora oraz podania kodu sejfu przez klienta.',
  },
]

const steps = [
  {
    title: 'Podłącz konto Allegro',
    text: 'Autoryzujesz dostęp przez oficjalne OAuth Allegro. Zaciągamy zamówienia, rozliczenia, zwroty, refundy i statystyki reklam. Kont możesz podłączyć kilka.',
  },
  {
    title: 'Wprowadź koszty zakupu',
    text: 'Ustalasz hasło do sejfu i wpisujesz ceny zakupu SKU. Szyfrowanie Argon2id + AES-256-GCM wykonuje się w Twojej przeglądarce, zanim dane opuszczą komputer.',
  },
  {
    title: 'Czytaj gotowy wynik',
    text: 'Dashboard pokazuje zysk netto, marżę i strukturę kosztów dla wybranego okresu i SKU. Dane odświeżają się automatycznie co godzinę.',
  },
]

const faqItems = [
  {
    q: 'Czym jest ProfitOS.pl?',
    a: 'To narzędzie do analizy rentowności sprzedaży na Allegro. Łączy zamówienia, rozliczenia, reklamy i koszty zakupu w jeden rachunek zysków i strat – per SKU, konto i okres.',
  },
  {
    q: 'Czy widzicie moje koszty zakupu i marże?',
    a: 'Standardowo ceny zakupu szyfrujesz w przeglądarce (Argon2id + AES-256-GCM). Opcjonalna integracja serwerowa jest domyślnie wyłączona; jeśli administrator ją włączy, a klient poda kod sejfu, serwer może odszyfrować koszty podczas obsługi żądania. Kod modułu szyfrującego jest publiczny i można go zweryfikować.',
  },
  {
    q: 'Ile kont Allegro mogę podłączyć?',
    a: 'Możesz połączyć wiele kont i oglądać wynik łącznie albo osobno dla wybranego konta. Import zamówień, rozliczeń, zwrotów i statystyk reklam działa niezależnie dla każdego konta.',
  },
  {
    q: 'Skąd biorą się liczby na dashboardzie?',
    a: 'Bezpośrednio z Twojego konta Allegro. Pobieramy surowe zamówienia, wpisy rozliczeniowe, zwroty i refundy, a statystyki Allegro Ads wgrywasz z pliku. Wszystko przeliczamy netto zgodnie z rozliczeniem Allegro.',
  },
  {
    q: 'Czy jest okres próbny?',
    a: 'Tak. Otrzymujesz 1000 zamówień za darmo na start, potem do 200 zamówień miesięcznie bez opłat.',
  },
  {
    q: 'Czy ProfitOS jest darmowy?',
    a: 'Kod ProfitOS jest open source na licencji AGPL-3.0, a instalacja na własnym serwerze jest bez opłat. Hosting na profitos.pl jest dostępny według cennika, który obejmuje także darmowy próg.',
  },
  {
    q: 'Za co płacę, skoro kod jest otwarty?',
    a: 'Opłata za usługę na profitos.pl obejmuje hosting, aktualizacje, kopie zapasowe, wsparcie i utrzymanie integracji z Allegro.',
  },
  {
    q: 'Jak liczycie cenę abonamentu?',
    a: 'Pakiet roczny wybierasz według liczby zamówień w miesiącu, niezależnie od liczby kont i funkcji. Do 200 zamówień miesięcznie korzystasz za darmo, a powyżej 25 000 obowiązuje wycena indywidualna. Ceny są netto, do faktury doliczamy VAT zgodnie z przepisami.',
  },
]

function MiniWaitlistForm({ isDark }: { isDark: boolean }) {
  const [email, setEmail] = useState('')
  const [privacyAccepted, setPrivacyAccepted] = useState(false)
  const [status, setStatus] = useState<'idle' | 'sending' | 'ok' | 'error'>('idle')

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!email || !privacyAccepted || status === 'sending') return
    setStatus('sending')
    try {
      await authApi.waitlist({ email, privacy_accepted: true })
      setStatus('ok')
    } catch {
      setStatus('error')
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="flex flex-col gap-3 sm:flex-row">
        <input
          type="email"
          required
          value={email}
          onChange={event => setEmail(event.target.value)}
          placeholder="email@firma.pl"
          className={`min-h-11 flex-1 rounded border px-4 text-sm outline-none focus:border-indigo-500 ${
            isDark
              ? 'border-slate-600 bg-slate-950 text-white'
              : 'border-slate-300 bg-white text-slate-950'
          }`}
        />
        <button
          type="submit"
          disabled={status === 'sending' || !privacyAccepted}
          className="min-h-11 rounded bg-indigo-600 px-5 text-sm font-semibold text-white hover:bg-indigo-500 disabled:opacity-60"
        >
          {status === 'sending' ? 'Wysyłanie...' : 'Uruchom konto'}
        </button>
      </div>
      <label className={`flex cursor-pointer items-start gap-3 text-xs leading-5 ${isDark ? 'text-slate-300' : 'text-slate-700'}`}>
        <input
          type="checkbox"
          required
          checked={privacyAccepted}
          onChange={event => setPrivacyAccepted(event.target.checked)}
          className="mt-0.5 h-4 w-4 rounded border-slate-600 text-indigo-500 focus:ring-indigo-500"
        />
        <span>
          Znam <Link to="/privacy" className={isDark ? 'text-emerald-300 hover:text-emerald-200' : 'text-emerald-700 hover:text-emerald-900'}>Politykę prywatności</Link>
          {' '}i zgadzam się na kontakt w sprawie uruchomienia konta w {productName()}.
        </span>
      </label>
      {status === 'ok' && <p className={isDark ? 'text-sm text-emerald-300 sm:self-center' : 'text-sm text-emerald-700 sm:self-center'}>Wysłaliśmy link aktywacyjny na email.</p>}
      {status === 'error' && <p className={isDark ? 'text-sm text-red-300 sm:self-center' : 'text-sm text-red-700 sm:self-center'}>Coś poszło nie tak.{supportEmail() && <> Napisz na {supportEmail()}.</>}</p>}
    </form>
  )
}

export default function Landing() {
  const { theme } = useTheme()
  if (IS_APP) return <Navigate to="/dashboard" replace />
  const isDark = theme === 'dark'
  const pageClass = isDark
    ? 'bg-slate-950 text-slate-100'
    : 'bg-[#f6f4ed] text-slate-950'
  const headerClass = isDark
    ? 'border-slate-800 bg-slate-950/85'
    : 'border-slate-300 bg-white/90'
  const mutedClass = isDark ? 'text-slate-300' : 'text-slate-700'
  const softMutedClass = isDark ? 'text-slate-400' : 'text-slate-600'
  const headingClass = isDark ? 'text-white' : 'text-slate-950'
  const panelClass = isDark ? 'border-slate-700 bg-slate-900' : 'border-slate-300 bg-white'
  const innerPanelClass = isDark ? 'border-slate-800 bg-slate-950' : 'border-slate-200 bg-slate-50'

  return (
    <div className={`public-theme min-h-screen ${pageClass}`}>
      <header className={`border-b ${headerClass}`}>
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-5 py-4">
          <Link to="/" className={headingClass}>
            <BrandLogo markClassName="h-8 w-8" textClassName="text-sm font-bold" />
          </Link>
          <nav className={`flex flex-wrap items-center justify-end gap-x-3 gap-y-2 text-sm ${mutedClass}`}>
            <PublicThemeToggle />
            <Link to="/security" className={isDark ? 'hover:text-white' : 'hover:text-slate-950'}>Bezpieczeństwo</Link>
            <Link to="/pobierz" className={isDark ? 'hover:text-white' : 'hover:text-slate-950'}>Aplikacja</Link>
            <a href={appUrl('/login')} className={isDark ? 'hover:text-white' : 'hover:text-slate-950'}>Zaloguj</a>
            <Link to="/register" className="rounded bg-indigo-600 px-3 py-1.5 text-white hover:bg-indigo-500">
              Rozpocznij
            </Link>
          </nav>
        </div>
      </header>

      <Section className="grid grid-cols-[minmax(0,1fr)] gap-12 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)] lg:items-center">
        <div className="min-w-0">
          <p className="mb-4 text-sm font-semibold uppercase tracking-wide text-emerald-300">
            Wynik Allegro z prywatnym sejfem kosztów
          </p>
          <h1 className={`max-w-4xl text-4xl font-bold leading-tight md:text-5xl ${headingClass}`}>
            Rentowność Twojej sprzedaży na Allegro, bez naszego dostępu do Twoich kosztów
          </h1>
          <p className={`mt-6 max-w-2xl text-lg leading-8 ${mutedClass}`}>
            {productName()} analizuje prowizje, reklamy, zwroty i koszty zakupu. Koszty zakupu szyfrujemy
            w Twojej przeglądarce, zanim opuszczą komputer. Operator nie widzi Twoich marż.
            Open source (AGPL-3.0).
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link to="/register" className="rounded bg-indigo-600 px-5 py-3 text-sm font-semibold text-white hover:bg-indigo-500">
              Zacznij za darmo
            </Link>
            <a href={SOURCE_REPO_URL} target="_blank" rel="noopener noreferrer" className={`inline-flex items-center gap-2 rounded border px-5 py-3 text-sm font-semibold ${
              isDark
                ? 'border-slate-600 text-slate-100 hover:border-slate-400'
                : 'border-slate-300 bg-white text-slate-950 hover:border-slate-500'
            }`}>
              <Github size={18} aria-hidden="true" /> Kod na GitHubie
            </a>
            <Link to="/security" className={`rounded border px-5 py-3 text-sm font-semibold ${
              isDark
                ? 'border-slate-600 text-slate-100 hover:border-slate-400'
                : 'border-slate-300 bg-white text-slate-950 hover:border-slate-500'
            }`}>
              Zobacz jak działa szyfrowanie
            </Link>
          </div>
          <p className={`mt-4 text-sm ${softMutedClass}`}>
            Do 200 zamówień miesięcznie ProfitOS pozostaje darmowy.
          </p>
        </div>

        <ProductPreview isDark={isDark} />
      </Section>

      <Section className="pt-0">
        <div className="mb-6 max-w-3xl">
          <p className="mb-2 text-sm font-semibold uppercase tracking-wide text-emerald-300">Podgląd produktu</p>
          <h2 className={`text-2xl font-bold ${headingClass}`}>Dashboard na realnych danych sprzedaży</h2>
          <p className={`mt-3 text-sm leading-6 ${mutedClass}`}>
            Liczby pochodzą z prawdziwego konta Allegro. Nazwy produktów w podglądzie są zamazane,
            same wartości zostają realne.
          </p>
        </div>
        <ProductPreview isDark={isDark} />
      </Section>

      <Section>
        <h2 className={`mb-8 text-2xl font-bold ${headingClass}`}>Co dostajesz</h2>
        <div className="grid gap-5 md:grid-cols-3">
          {featureCards.map(({ icon: Icon, title, text }) => (
            <article key={title} className={`rounded-lg border p-5 shadow-sm ${panelClass}`}>
              <Icon size={24} className="mb-4 text-emerald-300" />
              <h3 className={`mb-2 text-lg font-semibold ${headingClass}`}>{title}</h3>
              <p className={`text-sm leading-6 ${mutedClass}`}>{text}</p>
            </article>
          ))}
        </div>
      </Section>

      <Section className="pt-0">
        <div className="mb-8 max-w-3xl">
          <p className="mb-2 text-sm font-semibold uppercase tracking-wide text-emerald-300">Dlaczego ProfitOS</p>
          <h2 className={`text-2xl font-bold ${headingClass}`}>Wszystko, co wpływa na wynik, w jednym miejscu</h2>
          <p className={`mt-3 text-sm leading-6 ${mutedClass}`}>
            Zamiast arkusza sklejanego z kilku eksportów dostajesz jeden spójny obraz rentowności,
            liczony na Twoich realnych danych z Allegro.
          </p>
        </div>
        <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
          {benefits.map(({ icon: Icon, title, text }) => (
            <article key={title} className={`rounded-lg border p-5 shadow-sm ${panelClass}`}>
              <Icon size={22} className="mb-4 text-emerald-300" />
              <h3 className={`mb-2 text-base font-semibold ${headingClass}`}>{title}</h3>
              <p className={`text-sm leading-6 ${mutedClass}`}>{text}</p>
            </article>
          ))}
        </div>
      </Section>

      <Section className="pt-0">
        <RevenueChart isDark={isDark} />
      </Section>

      <Section className="pt-0">
        <div className="mb-8 max-w-3xl">
          <p className="mb-2 text-sm font-semibold uppercase tracking-wide text-emerald-300">Jak zacząć</p>
          <h2 className={`text-2xl font-bold ${headingClass}`}>Pełny wynik w trzech krokach</h2>
          <p className={`mt-3 text-sm leading-6 ${mutedClass}`}>
            Bez wdrożeniowych spotkań i bez oddawania nam wrażliwych danych. Konto uruchamiasz sam.
          </p>
        </div>
        <div className="grid gap-5 md:grid-cols-3">
          {steps.map(({ title, text }, index) => (
            <article key={title} className={`rounded-lg border p-5 shadow-sm ${panelClass}`}>
              <span className="mb-4 inline-flex h-9 w-9 items-center justify-center rounded-full bg-indigo-600 text-sm font-bold text-white">
                {index + 1}
              </span>
              <h3 className={`mb-2 text-base font-semibold ${headingClass}`}>{title}</h3>
              <p className={`text-sm leading-6 ${mutedClass}`}>{text}</p>
            </article>
          ))}
        </div>
      </Section>

      <Section className="grid gap-8 lg:grid-cols-[0.85fr_1.15fr] lg:items-center">
        <div>
          <h2 className={`mb-3 text-2xl font-bold ${headingClass}`}>Jak chronimy Twoje koszty</h2>
          <p className={`text-sm leading-6 ${mutedClass}`}>
            Publiczny moduł szyfrujący i reproducible build pozwalają porównać kod ładowany przez
            aplikację z hashem opublikowanym w GitHub Release.
          </p>
          <Link to="/security" className={`mt-5 inline-flex rounded px-4 py-2 text-sm font-semibold ${
            isDark ? 'bg-slate-100 text-slate-950 hover:bg-white' : 'bg-slate-950 text-white hover:bg-slate-800'
          }`}>
            Zweryfikuj sam pod /security
          </Link>
        </div>
        <div className={`space-y-3 rounded-lg border p-5 shadow-sm ${panelClass}`}>
          {[
            'Argon2id + AES-256-GCM w przeglądarce',
            `Publiczny moduł na GitHub: ${CRYPTO_REPO_URL}`,
            'Reproducible build, hash bundla weryfikowany w przeglądarce',
          ].map(text => (
            <div key={text} className={`flex gap-3 text-sm ${isDark ? 'text-slate-200' : 'text-slate-800'}`}>
              <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-emerald-300" />
              <span>{text}</span>
            </div>
          ))}
        </div>
      </Section>

      <Section>
        <h2 className={`mb-8 text-2xl font-bold ${headingClass}`}>Open source</h2>
        <div className="grid gap-5 md:grid-cols-3">
          <article className={`rounded-lg border p-5 shadow-sm ${panelClass}`}>
            <h3 className={`mb-2 text-base font-semibold ${headingClass}`}>Kod otwarty</h3>
            <p className={`text-sm leading-6 ${mutedClass}`}>Cały kod aplikacji jest publiczny na GitHubie. Każdy może sprawdzić, jak liczony jest zysk i jak szyfrowane są koszty.</p>
          </article>
          <article className={`rounded-lg border p-5 shadow-sm ${panelClass}`}>
            <h3 className={`mb-2 text-base font-semibold ${headingClass}`}>Zainstaluj u siebie</h3>
            <p className={`text-sm leading-6 ${mutedClass}`}>Darmowa instalacja na własnym serwerze z użyciem Dockera, dla jednej firmy.</p>
            <a href={SELFHOST_GUIDE_URL} target="_blank" rel="noopener noreferrer" className={`mt-3 inline-block text-sm underline ${mutedClass}`}>Instrukcja instalacji</a>
          </article>
          <article className={`rounded-lg border p-5 shadow-sm ${panelClass}`}>
            <h3 className={`mb-2 text-base font-semibold ${headingClass}`}>Albo korzystaj z hostingu</h3>
            <p className={`text-sm leading-6 ${mutedClass}`}>profitos.pl to gotowa usługa oparta na tym samym kodzie: aktualizacje, kopie zapasowe i wsparcie, bez własnego serwera.</p>
          </article>
        </div>
        <a href={ISSUES_URL} target="_blank" rel="noopener noreferrer" className={`mt-5 inline-block text-sm underline ${mutedClass}`}>Zgłoś pomysł lub dodaj kanał sprzedaży</a>
      </Section>

      <Section>
        <div className={`rounded-lg border p-6 shadow-sm ${panelClass}`}>
          <h2 className={`mb-2 text-2xl font-bold ${headingClass}`}>Cennik</h2>
          <p className={`mb-6 text-sm leading-6 ${mutedClass}`}>
            1000 zamówień za darmo na start, potem do 200 zamówień miesięcznie bez opłat. Możesz wybrać pakiet roczny według liczby zamówień.
          </p>
          <div className="grid gap-3 md:grid-cols-5">
            {pricing.map(([label, price, note]) => (
              <div key={label} className={`min-w-0 rounded border p-4 ${innerPanelClass}`}>
                <p className={`text-sm font-semibold ${headingClass}`}>{label}</p>
                <p className={`mt-3 whitespace-nowrap font-bold text-emerald-300 ${price === 'Indywidualnie' ? 'text-xl md:text-base lg:text-xl xl:text-2xl' : 'text-2xl'}`}>{price}</p>
                <p className={`mt-1 break-words text-sm ${mutedClass}`}>{note === 'kontakt' ? (supportEmail() ? `kontakt: ${supportEmail()}` : 'skontaktuj się z nami') : note}</p>
              </div>
            ))}
          </div>
          <p className={`mt-4 text-xs ${softMutedClass}`}>* Ceny netto. Do faktury doliczany jest VAT zgodnie z obowiązującymi przepisami.</p>
        </div>
      </Section>

      <Section className="pt-0">
        <div className="mb-8 max-w-3xl">
          <p className="mb-2 text-sm font-semibold uppercase tracking-wide text-emerald-300">FAQ</p>
          <h2 className={`text-2xl font-bold ${headingClass}`}>Najczęstsze pytania</h2>
        </div>
        <FaqList isDark={isDark} />
      </Section>

      <Section>
        <div className={`rounded-lg border p-6 ${
          isDark ? 'border-indigo-500/40 bg-indigo-500/10' : 'border-indigo-200 bg-indigo-50'
        }`}>
          <h2 className={`mb-2 text-2xl font-bold ${headingClass}`}>Uruchom konto ProfitOS</h2>
          <p className={`mb-5 text-sm ${mutedClass}`}>
            Podaj email, a wyślemy link aktywacyjny. Nie wysyłamy newslettera.
          </p>
          <MiniWaitlistForm isDark={isDark} />
        </div>
      </Section>

      <footer className={`border-t ${isDark ? 'border-slate-800' : 'border-slate-300'}`}>
        <div className={`mx-auto flex max-w-6xl flex-col gap-3 px-5 py-8 text-sm md:flex-row md:items-center md:justify-between ${softMutedClass}`}>
          <p>Copyright {productName()}</p>
          <div className="flex flex-wrap gap-4">
            <Link to="/security" className={isDark ? 'hover:text-white' : 'hover:text-slate-950'}>Bezpieczeństwo</Link>
            <Link to="/privacy" className={isDark ? 'hover:text-white' : 'hover:text-slate-950'}>Polityka prywatności</Link>
            <Link to="/terms" className={isDark ? 'hover:text-white' : 'hover:text-slate-950'}>Regulamin</Link>
            <Link to="/pobierz" className={isDark ? 'hover:text-white' : 'hover:text-slate-950'}>Aplikacja Android</Link>
            <a href={CRYPTO_REPO_URL} target="_blank" rel="noopener" className={isDark ? 'hover:text-white' : 'hover:text-slate-950'}>GitHub</a>
            <a href={SOURCE_REPO_URL} target="_blank" rel="noopener noreferrer" className={isDark ? 'hover:text-white' : 'hover:text-slate-950'}>Kod źródłowy (AGPL-3.0)</a>
            {supportEmail() && <a href={`mailto:${supportEmail()}`} className={isDark ? 'hover:text-white' : 'hover:text-slate-950'}>{supportEmail()}</a>}
          </div>
        </div>
      </footer>
    </div>
  )
}

function FaqList({ isDark }: { isDark: boolean }) {
  const [openIndex, setOpenIndex] = useState<number | null>(0)
  const panelClass = isDark ? 'border-slate-700 bg-slate-900' : 'border-slate-300 bg-white'
  const headingClass = isDark ? 'text-white' : 'text-slate-950'
  const mutedClass = isDark ? 'text-slate-300' : 'text-slate-700'

  return (
    <div className="grid gap-3">
      {faqItems.map(({ q, a }, index) => {
        const isOpen = openIndex === index
        return (
          <div key={q} className={`rounded-lg border shadow-sm ${panelClass}`}>
            <button
              type="button"
              onClick={() => setOpenIndex(isOpen ? null : index)}
              aria-expanded={isOpen}
              className={`flex min-h-12 w-full items-center justify-between gap-4 px-5 py-4 text-left text-base font-semibold ${headingClass}`}
            >
              <span>{q}</span>
              <ChevronDown
                size={20}
                className={`shrink-0 text-emerald-300 transition-transform ${isOpen ? 'rotate-180' : ''}`}
              />
            </button>
            {isOpen && <p className={`px-5 pb-5 text-sm leading-6 ${mutedClass}`}>{a}</p>}
          </div>
        )
      })}
    </div>
  )
}

function MaskedSku({ isDark, width = 'w-28' }: { isDark: boolean; width?: string }) {
  return (
    <span className={`inline-flex h-3 ${width} rounded-sm ${
      isDark ? 'bg-slate-600/80' : 'bg-slate-300'
    }`} aria-label="Nazwa produktu zamazana" />
  )
}

function ProductPreview({ isDark }: { isDark: boolean }) {
  const [showCosts, setShowCosts] = useState(false)
  const panelClass = isDark ? 'border-slate-700 bg-slate-900' : 'border-slate-300 bg-white'
  const innerPanelClass = isDark ? 'border-slate-800 bg-slate-950' : 'border-slate-200 bg-slate-50'
  const headingClass = isDark ? 'text-white' : 'text-slate-950'
  const mutedClass = isDark ? 'text-slate-400' : 'text-slate-600'
  const tableHeadClass = isDark ? 'bg-slate-950 text-slate-500' : 'bg-slate-100 text-slate-600'
  const rowDividerClass = isDark ? 'divide-slate-800 text-slate-200' : 'divide-slate-200 text-slate-800'
  const costBreakdown = [
    ['Towar', '19 078 PLN', '76,1%', '76.1%'],
    ['Prowizje Allegro', '4 029 PLN', '16,1%', '16.1%'],
    ['ADS', '771 PLN', '3,1%', '3.1%'],
    ['Smart / fulfillment', '902 PLN', '3,6%', '3.6%'],
    ['Pozostałe', '301 PLN', '1,2%', '1.2%'],
  ]

  return (
    <div className={`min-w-0 rounded-lg border p-5 shadow-2xl ${panelClass}`}>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <p className={`text-xs uppercase tracking-wide ${mutedClass}`}>Widok produktu</p>
          <h2 className={`text-lg font-semibold ${headingClass}`}>Realne dane sprzedaży i marży</h2>
        </div>
        <span className={`rounded border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-xs ${
          isDark ? 'text-emerald-200' : 'text-emerald-700'
        }`}>
          sejf odblokowany
        </span>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        {[
          ['Sprzedaż', '28 916,86 PLN', '394 zamówienia'],
          ['Zysk netto', '2 657,56 PLN', 'po kosztach Allegro'],
          ['Marża', '11,30%', 'koszty z sejfu'],
        ].map(([label, value, note]) => (
          <div key={label} className={`rounded border p-3 ${innerPanelClass}`}>
            <p className={`text-xs ${mutedClass}`}>{label}</p>
            <p className={`mt-2 text-xl font-bold ${headingClass}`}>{value}</p>
            <p className="mt-1 text-xs text-emerald-300">{note}</p>
          </div>
        ))}
      </div>
      <div className={`mt-4 overflow-x-auto rounded border ${isDark ? 'border-slate-700' : 'border-slate-300'}`}>
        <table className="w-full text-left text-xs">
          <thead className={tableHeadClass}>
            <tr>
              <th className="px-3 py-2">SKU</th>
              <th className="px-3 py-2 text-right">Sprzedaż</th>
              <th className="px-3 py-2 text-right">
                <button
                  type="button"
                  onClick={() => setShowCosts(current => !current)}
                  className={isDark ? 'underline decoration-slate-500 underline-offset-4 hover:text-white' : 'underline decoration-slate-400 underline-offset-4 hover:text-slate-950'}
                >
                  Koszty
                </button>
              </th>
              <th className="px-3 py-2 text-right">Zysk</th>
              <th className="px-3 py-2 text-right">Marża</th>
            </tr>
          </thead>
          <tbody className={`divide-y ${rowDividerClass}`}>
            {[
              ['sku-1', '3 356,14 PLN', '-2 987,81 PLN', '368,33 PLN', '13,50%', 'w-32'],
              ['sku-2', '4 063,01 PLN', '-3 693,54 PLN', '369,47 PLN', '11,18%', 'w-24'],
              ['sku-3', '2 230,49 PLN', '-1 764,04 PLN', '466,45 PLN', '22,59%', 'w-28'],
            ].map(row => (
              <tr key={row[0]}>
                <td className="px-3 py-2"><MaskedSku isDark={isDark} width={row[5]} /></td>
                <td className="px-3 py-2 text-right">{row[1]}</td>
                <td className="px-3 py-2 text-right text-red-300">{row[2]}</td>
                <td className="px-3 py-2 text-right text-emerald-300">{row[3]}</td>
                <td className="px-3 py-2 text-right text-emerald-300">{row[4]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {showCosts && (
        <div className={`mt-4 rounded border p-4 ${innerPanelClass}`}>
          <div className="mb-3 flex items-center justify-between gap-3">
            <h3 className={`text-sm font-semibold ${headingClass}`}>Struktura kosztów za aktywny miesiąc</h3>
            <span className={`text-xs ${mutedClass}`}>25 tys. PLN</span>
          </div>
          <div className="space-y-2">
            {costBreakdown.map(([label, value, percent, width], index) => (
              <div key={label} className="grid grid-cols-[7rem_1fr_4.5rem] items-center gap-3 text-xs">
                <span className={isDark ? 'text-slate-300' : 'text-slate-700'}>{label}</span>
                <div className={`h-2 overflow-hidden rounded ${isDark ? 'bg-slate-800' : 'bg-slate-200'}`}>
                  <div
                    className={`h-full ${['bg-amber-500', 'bg-red-500', 'bg-blue-500', 'bg-violet-500', 'bg-slate-500'][index]}`}
                    style={{ width }}
                  />
                </div>
                <span className={`text-right ${isDark ? 'text-slate-200' : 'text-slate-900'}`} title={percent}>{value}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function RevenueChart({ isDark }: { isDark: boolean }) {
  const points = [
    [0, 102], [34, 138], [68, 118], [102, 164], [136, 149],
    [170, 176], [204, 132], [238, 124], [272, 151], [306, 142],
    [340, 109], [374, 137], [408, 128],
  ]
  const bars = [
    [0, 92], [34, 128], [68, 106], [102, 154], [136, 139],
    [170, 165], [204, 121], [238, 112], [272, 139], [306, 131],
    [340, 98], [374, 127], [408, 118],
  ]
  const path = points.map(([x, y], index) => `${index === 0 ? 'M' : 'L'} ${x} ${210 - y}`).join(' ')
  return (
    <div className={`rounded-lg border p-6 shadow-sm ${
      isDark ? 'border-slate-700 bg-slate-900' : 'border-slate-300 bg-white'
    }`}>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="mb-2 text-sm font-semibold uppercase tracking-wide text-emerald-300">Trendy sprzedaży</p>
          <h2 className={isDark ? 'text-2xl font-bold text-white' : 'text-2xl font-bold text-slate-950'}>
            Ostatnie 30 dni sprzedaży i zysku
          </h2>
        </div>
        <div className={`flex gap-4 text-xs ${isDark ? 'text-slate-300' : 'text-slate-600'}`}>
          <span className="inline-flex items-center gap-1"><i className="h-2 w-2 rounded-full bg-blue-500" /> Sprzedaż</span>
          <span className="inline-flex items-center gap-1"><i className="h-2 w-2 rounded-full bg-emerald-500" /> Zysk</span>
        </div>
      </div>
      <div className="overflow-x-auto">
        <svg viewBox="0 0 440 240" className="min-w-[36rem]">
          {[55, 105, 155, 205].map(y => (
            <line key={y} x1="0" x2="430" y1={y} y2={y} stroke={isDark ? '#263747' : '#dbe3ea'} strokeWidth="1" />
          ))}
          {bars.map(([x, height]) => (
            <rect key={x} x={x + 5} y={210 - height} width="16" height={height} rx="4" fill="#10b981" opacity="0.78" />
          ))}
          <path d={path} fill="none" stroke="#2563eb" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
          {points.map(([x, y]) => (
            <circle key={`${x}-${y}`} cx={x} cy={210 - y} r="4" fill="#2563eb" />
          ))}
          <text x="0" y="232" fontSize="11" fill={isDark ? '#94a3b8' : '#64748b'}>30 dni temu</text>
          <text x="360" y="232" fontSize="11" fill={isDark ? '#94a3b8' : '#64748b'}>Dzisiaj</text>
        </svg>
      </div>
    </div>
  )
}
