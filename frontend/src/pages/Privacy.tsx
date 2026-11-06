import { Link } from 'react-router-dom'
import type { ReactNode } from 'react'
import { PublicThemeToggle } from '../components/PublicThemeToggle'
import { productName, supportEmail } from '../config/brand'
import { BrandLogo } from '../components/BrandLogo'

const updatedAt = '7 maja 2026'

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold text-white">{title}</h2>
      <div className="space-y-3 text-sm leading-7 text-slate-300">{children}</div>
    </section>
  )
}

export default function Privacy() {
  return (
    <div className="public-theme min-h-screen bg-slate-900 px-5 py-10 text-slate-100">
      <main className="mx-auto max-w-3xl space-y-10">
        <header className="flex items-center justify-between gap-3">
          <Link to="/" className="text-white">
            <BrandLogo markClassName="h-8 w-8" textClassName="text-sm font-semibold" />
          </Link>
          <PublicThemeToggle />
        </header>

        <section className="space-y-4">
          <p className="text-sm font-medium uppercase text-emerald-300">Polityka prywatności</p>
          <h1 className="text-3xl font-bold leading-tight text-white">Jak dbamy o Twoje dane</h1>
          <p className="text-base leading-8 text-slate-300">
            Zbieramy tylko te informacje, które są potrzebne, żeby uruchomić konto w {productName()}.
            Poniżej opisujemy to prostym językiem:
            co zapisujemy, po co to robimy i jak możesz poprosić o zmianę albo usunięcie danych.
          </p>
          <p className="text-sm text-slate-400">Ostatnia aktualizacja: {updatedAt}</p>
        </section>

        <Section title="Administrator danych">
          <p>
            Administratorem danych jest {productName()}.{supportEmail() && <> W sprawach prywatności napisz do nas na{' '}
            <a href={`mailto:${supportEmail()}`} className="text-emerald-300 hover:text-emerald-200">
              {supportEmail()}
            </a>.</>}
          </p>
        </Section>

        <Section title="Cel przetwarzania">
          <p>
            Dane z formularza rejestracji wykorzystujemy, żeby utworzyć konto firmowe i wysłać
            link aktywacyjny. Po aktywacji konta używamy danych logowania do działania aplikacji.
          </p>
        </Section>

        <Section title="Podstawa prawna">
          <p>
            Gdy rejestrujesz lub aktywujesz konto, prosimy Cię o zgodę. Dodatkowo
            mamy uzasadniony interes w tym, żeby zabezpieczać usługę, prowadzić podstawowe logi
            techniczne i odpowiadać na Twoje wiadomości.
          </p>
        </Section>

        <Section title="Czas przechowywania">
          <p>
            Dane przechowujemy do momentu, w którym poprosisz o ich usunięcie. Konta,
            które pozostają nieaktywne przez 12 miesięcy, możemy usunąć także z własnej inicjatywy.
          </p>
        </Section>

        <Section title="Odbiorcy danych">
          <p>
            Nie sprzedajemy danych i nie przekazujemy ich zewnętrznym odbiorcom marketingowym.
            Dane z Allegro są pobierane i wysyłane do Allegro przez OAuth użytkownika, czyli za
            Twoją zgodą i w ramach połączenia, które sam uruchamiasz w aplikacji.
          </p>
        </Section>

        <Section title="Twoje prawa">
          <p>
            Masz prawa z art. 15-22 GDPR/RODO: dostęp do danych, sprostowanie, usunięcie,
            ograniczenie przetwarzania, sprzeciw oraz przenoszenie danych. W aplikacji możesz
            sprawdzić podstawowe dane przez <span className="font-mono text-slate-100">GET /me</span>,
            usunąć konto przez <span className="font-mono text-slate-100">DELETE /me</span> oraz
            pobrać zaszyfrowany envelope z danymi finansowymi.
          </p>
          <p>
            {supportEmail() && <>Jeśli wolisz załatwić sprawę mailowo, napisz na {supportEmail()}. </>}Odpowiemy bez
            zbędnego formalizmu, a gdy będziemy potrzebować potwierdzenia tożsamości, poprosimy
            tylko o informacje konieczne do bezpiecznej obsługi sprawy.
          </p>
        </Section>

        <Section title="Dane finansowe i szyfrowanie">
          <p>
            Koszty zakupu zapisane w {productName()} są szyfrowane w Twojej przeglądarce. Administrator
            widzi zaszyfrowany rekord, ale nie widzi kwoty ani hasła do sejfu finansowego. Więcej
            opisaliśmy na stronie <Link to="/security" className="text-emerald-300 hover:text-emerald-200">/security</Link>.
          </p>
        </Section>

        <Section title="Cookies">
          <p>
            Używamy tylko cookies sesyjnych potrzebnych do logowania i 2FA:{' '}
            <span className="font-mono text-slate-100">apos_session</span> oraz{' '}
            <span className="font-mono text-slate-100">apos_totp_enroll</span>. Są ustawione jako
            HttpOnly, SameSite=Strict i nie są cookies podmiotów trzecich.
          </p>
        </Section>

        <footer className="border-t border-slate-800 pt-6 text-sm text-slate-400">
          <div className="flex flex-wrap gap-4">
            <Link to="/" className="hover:text-white">Strona główna</Link>
            <Link to="/security" className="hover:text-white">Bezpieczeństwo</Link>
            {supportEmail() && <a href={`mailto:${supportEmail()}`} className="hover:text-white">{supportEmail()}</a>}
          </div>
        </footer>
      </main>
    </div>
  )
}
