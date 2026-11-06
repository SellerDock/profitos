import { Link } from 'react-router-dom'
import { ArrowRight, BarChart3, LockKeyhole, RefreshCw } from 'lucide-react'
import type { ReactNode } from 'react'
import { productName } from '../config/brand'

export function EmptyDashboard() {
  return (
    <div className="mx-auto max-w-4xl space-y-8 py-10">
      <div>
        <p className="text-sm font-medium text-indigo-300">Pierwsze kroki</p>
        <h1 className="mt-2 text-3xl font-bold text-white">Witaj w {productName()}</h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300">
          Ten panel jest pusty, bo konto nie ma jeszcze podpiętego konta Allegro.
          Zacznij od połączenia konta, uruchom synchronizację, a potem skonfiguruj sejf finansowy.
        </p>
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        <Step
          icon={<ArrowRight size={18} />}
          title="Dodaj konto Allegro"
          text="Przejdź do ustawień i rozpocznij OAuth dla pierwszego konta sprzedażowego."
          to="/settings"
          cta="Przejdź do ustawień"
        />
        <Step
          icon={<RefreshCw size={18} />}
          title="Zsynchronizuj dane"
          text="Po połączeniu konta uruchom import zamówień, rozliczeń, zwrotów i ofert."
          to="/import"
          cta="Synchronizuj"
        />
        <Step
          icon={<LockKeyhole size={18} />}
          title="Skonfiguruj sejf"
          text="Koszty zakupu wpiszesz dopiero po utworzeniu lokalnie szyfrowanego sejfu."
          to="/security"
          cta="Zobacz bezpieczeństwo"
        />
      </div>
      <div className="rounded-lg border border-slate-700 bg-slate-800 p-5">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-100">
          <BarChart3 size={18} className="text-emerald-300" />
          Co zobaczysz po pierwszej synchronizacji
        </div>
        <p className="mt-2 text-sm leading-6 text-slate-300">
          Pojawią się kafle wyników, tabela SKU, koszty Allegro, reklamy, zwroty i link do ustawienia kosztów zakupu
          w sejfie finansowym. Dane są izolowane między kontami.
        </p>
      </div>
    </div>
  )
}

function Step({ icon, title, text, to, cta }: { icon: ReactNode; title: string; text: string; to: string; cta: string }) {
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800 p-5">
      <div className="mb-3 inline-flex rounded bg-indigo-500/15 p-2 text-indigo-200">{icon}</div>
      <h2 className="text-base font-semibold text-white">{title}</h2>
      <p className="mt-2 min-h-20 text-sm leading-6 text-slate-300">{text}</p>
      <Link to={to} className="mt-4 inline-flex items-center gap-2 text-sm font-medium text-indigo-300 hover:text-indigo-200">
        {cta}
        <ArrowRight size={14} />
      </Link>
    </div>
  )
}
