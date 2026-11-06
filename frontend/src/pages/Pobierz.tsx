import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import { Link } from 'react-router-dom'
import {
  Boxes,
  Download,
  KeyRound,
  LayoutDashboard,
  Loader2,
  ShieldCheck,
  ShoppingCart,
  Smartphone,
} from 'lucide-react'
import { PublicThemeToggle } from '../components/PublicThemeToggle'
import { BrandLogo } from '../components/BrandLogo'
import { productName, supportEmail } from '../config/brand'
import { appDownloadApi } from '../api/client'
import { useDeploymentMode } from '../context/DeploymentContext'

const FEATURES = [
  { icon: LayoutDashboard, text: 'Podgląd pulpitu sprzedaży i wyników za wybrany okres' },
  { icon: ShoppingCart, text: 'Rentowność produktów i ostatnie zamówienia' },
  { icon: Boxes, text: 'Stany magazynowe SKU' },
  { icon: KeyRound, text: 'Sejf kosztów szyfrowany lokalnie, na urządzeniu' },
  { icon: ShieldCheck, text: 'Logowanie z kodem TOTP' },
  { icon: Smartphone, text: 'Zapamiętane urządzenie oznacza rzadsze logowanie' },
]

function formatSize(bytes: number): string {
  const mb = bytes / (1024 * 1024)
  return `${mb.toFixed(1)} MB`
}

export default function Pobierz() {
  const mode = useDeploymentMode()
  const { data, isLoading, error } = useQuery({
    queryKey: ['app', 'manifest'],
    queryFn: appDownloadApi.manifest,
    retry: false,
  })

  const notPublished = axios.isAxiosError(error) && error.response?.status === 404

  return (
    <div className="public-theme min-h-screen bg-slate-900 px-5 py-10 text-slate-100">
      <main className="mx-auto max-w-3xl space-y-8">
        <header className="flex items-center justify-between gap-3">
          <Link to="/" className="text-white">
            <BrandLogo markClassName="h-8 w-8" textClassName="text-sm font-semibold" />
          </Link>
          <PublicThemeToggle />
        </header>

        <section className="space-y-4">
          <p className="text-sm font-medium uppercase text-emerald-300">Aplikacja Android</p>
          <h1 className="text-3xl font-bold leading-tight text-white">Pobierz aplikację {productName()}</h1>
          <p className="text-base leading-8 text-slate-300">
            Aplikacja na Androida do podglądu danych {productName()} — pulpitu, produktów,
            rentowności, zamówień i stanów magazynowych — bezpośrednio z telefonu.
          </p>
        </section>

        <section className="apos-panel p-5">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <Smartphone size={18} className="text-finance-blue" />
            <h2 className="text-lg font-semibold text-slate-950">Co potrafi aplikacja</h2>
          </div>
          <ul className="space-y-3">
            {FEATURES.map(({ icon: Icon, text }) => (
              <li key={text} className="flex items-start gap-3 text-sm leading-6 text-slate-600">
                <Icon size={16} className="mt-0.5 shrink-0 text-finance-blue" />
                <span>{text}</span>
              </li>
            ))}
          </ul>
        </section>

        <section className="apos-panel p-5">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <Download size={18} className="text-finance-blue" />
            <h2 className="text-lg font-semibold text-slate-950">Pobieranie</h2>
          </div>

          {isLoading ? (
            <p className="flex items-center gap-2 text-sm text-slate-600">
              <Loader2 size={16} className="animate-spin" />
              Sprawdzanie dostępnej wersji...
            </p>
          ) : notPublished ? (
            <div className="space-y-3">
              <p className="text-sm text-slate-600">Wersja wkrótce — aplikacja jest jeszcze przygotowywana.</p>
              <button
                type="button"
                disabled
                className="inline-flex cursor-not-allowed items-center gap-2 rounded bg-slate-300 px-4 py-2 text-sm font-semibold text-slate-500"
              >
                <Download size={16} />
                Pobierz aplikację (.apk)
              </button>
            </div>
          ) : data ? (
            <div className="space-y-3">
              <a
                href={appDownloadApi.downloadUrl()}
                className="inline-flex items-center gap-2 rounded bg-finance-blue px-4 py-2 text-sm font-semibold text-white hover:opacity-90"
              >
                <Download size={16} />
                Pobierz aplikację (.apk)
              </a>
              <p className="text-sm text-slate-600">
                Wersja {data.version} · {formatSize(data.size_bytes)} · wymaga Android {data.min_android}
              </p>
              {data.notes && <p className="text-sm text-slate-500">{data.notes}</p>}
            </div>
          ) : (
            <p className="text-sm text-red-600">Nie udało się sprawdzić dostępnej wersji aplikacji.</p>
          )}
        </section>

        <section className="apos-panel p-5">
          <h2 className="mb-2 text-base font-semibold text-slate-950">Jak zainstalować</h2>
          <p className="text-sm leading-6 text-slate-600">
            To plik .apk do samodzielnej instalacji (sideload), aplikacja nie jest jeszcze
            publikowana w Google Play. Po pobraniu otwórz plik na telefonie i włącz instalację
            z nieznanych źródeł, gdy system o to poprosi — zgoda jest wymagana tylko przy
            pierwszej instalacji.
          </p>
        </section>

        <footer className="border-t border-slate-800 pt-6 text-sm text-slate-400">
          <div className="flex flex-wrap gap-4">
            <Link to="/" className="hover:text-white">Strona główna</Link>
            <Link to="/security" className="hover:text-white">Bezpieczeństwo</Link>
            {mode === 'hosted' && <>
              <Link to="/privacy" className="hover:text-white">Polityka prywatności</Link>
              <Link to="/terms" className="hover:text-white">Regulamin</Link>
            </>}
            {supportEmail() && <a href={`mailto:${supportEmail()}`} className="hover:text-white">{supportEmail()}</a>}
          </div>
        </footer>
      </main>
    </div>
  )
}
