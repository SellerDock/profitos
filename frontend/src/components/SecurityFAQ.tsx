import { useState } from 'react'
import { ChevronDown, HelpCircle } from 'lucide-react'
import { productName } from '../config/brand'

const questions = () => [
  {
    question: `Skąd mam wiedzieć, że ${productName()} naprawdę używa tego kodu z GitHuba?`,
    answer: 'Kliknij „Sprawdź teraz”. Przeglądarka pobierze plik używany przez panel, policzy jego odcisk i porówna go z publiczną wersją na GitHubie. Jeśli plik byłby inny, wynik się nie zgodzi.',
    badge: 'Wyjaśnienie',
  },
  {
    question: 'Co jeśli ktoś przejmie wasz serwer i podmieni kod?',
    answer: 'Dlatego pokazujemy publiczne odciski plików i dajemy narzędzie offline. To nie jest magiczna tarcza przed każdym atakiem, ale pozwala sprawdzić, czy plik szyfrujący zgadza się z publiczną wersją.',
    badge: 'Wyjaśnienie',
  },
  {
    question: 'Co się stanie jeśli zapomnę hasła sejfu finansowego?',
    answer: 'Nie będziemy mogli odzyskać kosztów zakupu. Nie znamy hasła sejfu i nie mamy klucza zapasowego. Najbezpieczniej zapisać hasło w menedżerze haseł.',
    badge: 'Ważne',
  },
  {
    question: 'Czy macie gdzieś moje koszty w jawnej formie?',
    answer: 'Nie. W bazie zapisujemy zaszyfrowane dane, a nie kwoty zakupu. Możesz pobrać pojedynczy rekord i odszyfrować go lokalnie, żeby zobaczyć, że jawna kwota pojawia się dopiero po podaniu hasła sejfu.',
    badge: 'Oświadczenie',
  },
  {
    question: 'Co dokładnie jest szyfrowane?',
    answer: 'Szyfrujemy koszty zakupu produktów. Nie szyfrujemy nazw produktów, cen sprzedaży, prowizji Allegro ani ustawień raportów, bo te dane są potrzebne do działania panelu i zwykle nie są tajnym kosztem zakupu.',
    badge: 'Wyjaśnienie',
  },
  {
    question: 'Czy mogę zmienić hasło sejfu finansowego?',
    answer: 'Tak. Przy zmianie hasła koszty są ponownie szyfrowane nowym kluczem w Twojej przeglądarce. Stare hasło przestaje działać, a my w żadnym momencie nie widzimy ani starego, ani nowego hasła.',
    badge: 'Wyjaśnienie',
  },
  {
    question: 'Czy moje koszty są zaszyfrowane też w kopiach zapasowych bazy?',
    answer: 'Tak. W bazie — a więc również w jej kopiach zapasowych — trzymamy wyłącznie zaszyfrowaną treść kosztów. Kopia zapasowa nie zawiera jawnych kwot ani klucza potrzebnego do ich odczytania.',
    badge: 'Oświadczenie',
  },
  {
    question: 'Na czym polega narzędzie offline?',
    answer: 'To pojedynczy plik HTML z publicznym odciskiem, który uruchamiasz na własnym komputerze bez połączenia z panelem. Wklejasz do niego zaszyfrowany rekord i swoje hasło, a odszyfrowanie następuje lokalnie — dzięki temu możesz potwierdzić, że jawna kwota pojawia się dopiero po podaniu hasła.',
    badge: 'Wyjaśnienie',
  },
  {
    question: 'Dlaczego nie używacie zewnętrznego audytu?',
    answer: 'To młody produkt, więc zaczynamy od jawnego kodu, publicznych odcisków plików i możliwości sprawdzenia rekordu offline. Zewnętrzny audyt jest naturalnym kolejnym krokiem, gdy produkt dojrzeje.',
    badge: 'Wyjaśnienie',
  },
]

function Badge({ kind }: { kind: string }) {
  const isImportant = kind === 'Ważne'
  const isDeclaration = kind === 'Oświadczenie'
  return (
    <span className={`rounded-full border px-2 py-0.5 text-xs font-medium ${
      isImportant
        ? 'border-amber-200 bg-amber-50 text-finance-amber'
        : isDeclaration
          ? 'border-slate-200 bg-slate-50 text-slate-600'
          : 'border-blue-200 bg-blue-50 text-finance-blue'
    }`}>
      {kind}
    </span>
  )
}

export function SecurityFAQ() {
  const [open, setOpen] = useState(0)

  return (
    <section className="apos-panel p-5">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <HelpCircle size={18} className="text-finance-blue" />
        <h2 className="text-lg font-semibold text-slate-950">Najczęstsze pytania</h2>
        <Badge kind="Wyjaśnienie" />
      </div>
      <div className="divide-y divide-slate-200 overflow-hidden rounded border border-slate-200">
        {questions().map((item, index) => {
          const isOpen = open === index
          return (
            <div key={item.question} className="bg-white">
              <button
                type="button"
                onClick={() => setOpen(isOpen ? -1 : index)}
                className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-slate-50"
                aria-expanded={isOpen}
              >
                <span className="min-w-0 text-sm font-medium text-slate-950">{item.question}</span>
                <span className="flex shrink-0 items-center gap-2">
                  <Badge kind={item.badge} />
                  <ChevronDown size={16} className={`text-slate-400 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
                </span>
              </button>
              {isOpen && (
                <p className="px-4 pb-4 text-sm leading-6 text-slate-600">{item.answer}</p>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}
