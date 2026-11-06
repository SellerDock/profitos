import { Link } from 'react-router-dom'
import type { ReactNode } from 'react'
import { PublicThemeToggle } from '../components/PublicThemeToggle'
import { BrandLogo } from '../components/BrandLogo'
import { productName, supportEmail } from '../config/brand'

const updatedAt = '7 listopada 2026'

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold text-white">{title}</h2>
      <div className="space-y-3 text-sm leading-7 text-slate-300">{children}</div>
    </section>
  )
}

export default function Terms() {
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
          <p className="text-sm font-medium uppercase text-emerald-300">Regulamin</p>
          <h1 className="text-3xl font-bold leading-tight text-white">Regulamin świadczenia usługi ProfitOS.pl</h1>
          <p className="text-base leading-8 text-slate-300">
            Ten regulamin opisuje zasady korzystania z {productName()}: konto, okres próbny,
            pakiety płatne, rozliczenia, integrację z Allegro, Sejf Finansowy, reklamacje
            oraz odpowiedzialność za dane i decyzje biznesowe.
          </p>
          <p className="text-sm text-slate-400">Wersja: 2026-11-07 · ostatnia aktualizacja: {updatedAt}</p>
        </section>

        <Section title="1. Usługodawca i kontakt">
          <p>
            Usługą jest aplikacja {productName()} dostępna pod adresem profitos.pl oraz app.profitos.pl
            i świadczona przez operatora serwisu ProfitOS.pl. W sprawach technicznych,
            rozliczeniowych, organizacyjnych i reklamacyjnych{supportEmail() && <> napisz na{' '}
            <a href={`mailto:${supportEmail()}`} className="text-emerald-300 hover:text-emerald-200">{supportEmail()}</a></>}.
          </p>
          <p>
            Dane identyfikacyjne potrzebne do wystawienia faktury i obsługi rozliczeń są
            przekazywane klientowi w dokumentach rozliczeniowych lub w korespondencji z operatorem.
          </p>
        </Section>

        <Section title="2. Definicje">
          <p>
            <strong>Usługa</strong> oznacza dostęp do aplikacji {productName()}, jej paneli,
            importów, raportów i funkcji pomocniczych. <strong>Konto</strong> oznacza przestrzeń
            użytkownika zabezpieczoną logowaniem. <strong>Użytkownik</strong> oznacza firmę,
            organizację albo osobę działającą zawodowo, która korzysta z Usługi.
          </p>
          <p>
            <strong>Dane Allegro</strong> oznaczają dane pobierane przez oficjalne integracje,
            w szczególności zamówienia, pozycje zamówień, rozliczenia, oferty, zwroty, refundy,
            stany magazynowe i dane reklamowe. <strong>Sejf Finansowy</strong> oznacza mechanizm,
            w którym koszty zakupu są szyfrowane po stronie przeglądarki użytkownika.
          </p>
          <p>
            <strong>Pula startowa</strong> oznacza 1000 zamówień, które nowe konto może przetworzyć
            bez opłaty, bez limitu czasu. <strong>Pakiet płatny</strong> oznacza roczny dostęp
            z wyższym miesięcznym limitem zamówień zgodnie z cennikiem.
          </p>
        </Section>

        <Section title="3. Dla kogo jest usługa">
          <p>
            {productName()} jest usługą B2B dla sprzedawców Allegro. Korzystając z aplikacji potwierdzasz,
            że działasz w ramach firmy albo organizacji, a konto służy do analizy sprzedaży i kosztów.
          </p>
          <p>
            Usługa nie jest kierowana do konsumentów. Jeżeli zakładasz konto w imieniu firmy,
            potwierdzasz, że masz prawo działać w jej imieniu albo zostałeś do tego upoważniony.
          </p>
        </Section>

        <Section title="4. Zakres usługi">
          <p>
            Aplikacja pobiera Dane Allegro po połączeniu konta przez OAuth, pokazuje przychody,
            opłaty, prowizje, reklamy, zwroty, refundy, VAT, stany magazynowe i koszty zakupu
            w ujęciu per konto, okres i SKU.
          </p>
          <p>
            Wyniki w panelu są narzędziem analitycznym i decyzyjnym. Nie zastępują ksiąg
            rachunkowych, deklaracji podatkowych, ewidencji magazynowej ani indywidualnej porady
            księgowej, podatkowej lub prawnej.
          </p>
        </Section>

        <Section title="5. Warunki techniczne">
          <p>
            Do korzystania z usługi potrzebujesz aktualnej przeglądarki internetowej, dostępu do internetu
            i konta Allegro, które możesz połączyć z ProfitOS.pl. Dla bezpieczeństwa wymagamy logowania
            i możemy wymagać 2FA.
          </p>
          <p>
            Część funkcji zależy od dostępności zewnętrznych API, w szczególności Allegro, bramek
            płatności, usług pocztowych i systemów fakturowych. Przerwa lub błąd po stronie
            dostawcy zewnętrznego może czasowo ograniczyć działanie wybranych funkcji.
          </p>
        </Section>

        <Section title="6. Konto, Allegro i bezpieczeństwo">
          <p>
            Użytkownik odpowiada za poufność hasła, kodów 2FA i hasła do sejfu finansowego.
            Nie wolno dostarczać treści bezprawnych, próbować obchodzić zabezpieczeń ani korzystać
            z cudzych kont Allegro bez uprawnienia.
          </p>
          <p>
            Łącząc konto Allegro, potwierdzasz, że jesteś właścicielem konta albo masz zgodę
            właściciela na podłączenie go do {productName()}. Możemy odmówić ponownego podłączenia
            tego samego konta Allegro do innego klienta, jeżeli system wykryje ryzyko pomyłki,
            nadużycia lub naruszenia izolacji danych.
          </p>
          <p>
            Użytkownik odpowiada za poprawność danych wprowadzanych ręcznie, w szczególności
            kosztów zakupu, stawek VAT, mapowań SKU, stanów magazynowych i danych do faktury.
          </p>
        </Section>

        <Section title="7. Sejf Finansowy i koszty zakupu">
          <p>
            Koszty zakupu mogą być szyfrowane w przeglądarce przed wysłaniem na serwer.
            W takim wariancie serwer przechowuje zaszyfrowany zapis kosztu, nonce, wersję klucza
            i kontekst AAD, ale nie otrzymuje jawnego kosztu ani hasła do Sejfu Finansowego.
          </p>
          <p>
            Hasło do Sejfu Finansowego, klucz szyfrujący i możliwość odszyfrowania kosztów są
            po stronie użytkownika. Operator {productName()} nie ma technicznej możliwości
            odtworzenia jawnych kosztów zakupu, jeśli użytkownik utraci hasło albo klucz.
          </p>
          <p>
            Użytkownik powinien samodzielnie weryfikować poprawność importowanych kosztów,
            stawek VAT i wyników marżowych przed podjęciem decyzji zakupowych, cenowych lub
            reklamowych.
          </p>
        </Section>

        <Section title="8. Pula startowa, darmowy limit i pakiety">
          <p>
            Każde konto założone od dnia wejścia w życie tej wersji regulaminu otrzymuje pulę startową
            1000 zamówień. Do puli liczą się zamówienia złożone od dnia założenia konta; zamówienia
            historyczne pobrane przy pierwszym imporcie nie zmniejszają puli.
          </p>
          <p>
            Po wykorzystaniu puli konto korzysta bez opłat z limitu 200 zamówień w miesiącu kalendarzowym.
            Wyższe limity dają pakiety roczne (ceny netto): do 1000 zamówień miesięcznie 99 zł rocznie,
            do 5000 – 299 zł rocznie, do 25 000 – 499 zł rocznie, powyżej 25 000 – wycena indywidualna
            po kontakcie.
          </p>
          <p>
            Przekroczenie limitu nie wstrzymuje działania aplikacji ani pobierania danych. Wysyłamy wtedy
            przypomnienie w aplikacji i e-mailem, nie częściej niż raz w miesiącu. Jeżeli limit jest
            przekraczany stale, możemy zaproponować pakiet odpowiadający liczbie zamówień.
          </p>
          <p>
            Konta założone przed wejściem w życie tej wersji regulaminu zachowują dotychczasowe warunki
            (30 dni okresu próbnego i akceptacja pakietu płatnego w zakładce Rozliczenia), chyba że wybiorą
            pakiet roczny. Jeżeli takie konto po okresie próbnym nie zaakceptuje pakietu płatnego, możemy
            wstrzymać nowe automatyczne synchronizacje; dane historyczne pozostają widoczne, chyba że
            poprosisz o usunięcie konta lub danych.
          </p>
        </Section>

        <Section title="9. Faktury i płatności">
          <p>
            Pakiet roczny zamawiasz w zakładce Rozliczenia po zaakceptowaniu regulaminu. Na podstawie danych
            rozliczeniowych z ustawień wystawiamy fakturę z terminem płatności 7 dni. Pakiet obowiązuje
            12 miesięcy od dnia zaksięgowania płatności.
          </p>
          <p>
            Odnowienie zamówione w ostatnich 30 dniach pakietu zaczyna się w dniu następującym po jego końcu.
            Zmiana na wyższy pakiet obowiązuje od dnia opłacenia faktury za nowy pakiet. Po wygaśnięciu
            pakietu konto wraca do darmowego limitu 200 zamówień miesięcznie.
          </p>
          <p>
            Status opłacenia oznacza operator po otrzymaniu przelewu. Ceny są kwotami netto, do faktury
            doliczamy VAT zgodnie z przepisami. Odpowiadasz za aktualność NIP, nazwy firmy, adresu
            i adresu e-mail do faktur.
          </p>
        </Section>

        <Section title="10. Zawieszenie, rezygnacja i usunięcie danych">
          <p>
            Możesz zrezygnować z usługi, pisząc na adres kontaktowy. Po rezygnacji wstrzymujemy nowe
            synchronizacje. Dane możemy usunąć na Twoją prośbę, z zachowaniem obowiązków prawnych
            dotyczących dokumentów rozliczeniowych.
          </p>
          <p>
            Możemy czasowo zawiesić konto lub wybrane funkcje, jeżeli występuje zaległość płatnicza,
            ryzyko naruszenia bezpieczeństwa, podejrzenie nieuprawnionego dostępu do cudzego konta
            Allegro, próby obejścia zabezpieczeń albo korzystanie z Usługi w sposób zakłócający jej
            działanie.
          </p>
          <p>
            Usunięcie konta może być nieodwracalne. Po usunięciu konta nie gwarantujemy możliwości
            przywrócenia danych analitycznych, mapowań, historii kosztów ani zaszyfrowanych rekordów
            Sejfu Finansowego.
          </p>
        </Section>

        <Section title="11. Reklamacje">
          <p>
            {supportEmail() && <>Reklamacje przyjmujemy mailowo na {supportEmail()}. </>}Opisz problem, konto, którego dotyczy,
            moment wystąpienia problemu, oczekiwany sposób rozwiązania i dane kontaktowe. Odpowiemy
            w ciągu 14 dni roboczych, chyba że sprawa wymaga dodatkowych informacji od użytkownika
            albo dostawcy zewnętrznego.
          </p>
          <p>
            Reklamacje dotyczące faktury powinny wskazywać numer faktury, kwestionowaną pozycję
            i uzasadnienie. Bezsporna część należności powinna zostać opłacona w standardowym terminie.
          </p>
        </Section>

        <Section title="12. Odpowiedzialność">
          <p>
            Dokładamy staranności, żeby dane i obliczenia były poprawne, ale użytkownik powinien sam
            weryfikować wyniki przed decyzjami finansowymi, księgowymi lub podatkowymi. Nie odpowiadamy
            za błędy wynikające z niepełnych danych Allegro, błędnych importów, błędnych kosztów zakupu
            lub zmian wprowadzonych przez użytkownika.
          </p>
          <p>
            W zakresie dopuszczalnym przez prawo nie odpowiadamy za utracone korzyści, szkody pośrednie,
            decyzje cenowe, reklamowe lub zakupowe podjęte wyłącznie na podstawie raportów, ani za
            skutki awarii, zmian lub ograniczeń po stronie Allegro i innych dostawców zewnętrznych.
          </p>
          <p>
            Użytkownik odpowiada za własne rozliczenia podatkowe, księgowe i prawne oraz za weryfikację,
            czy dane z {productName()} są zgodne z dokumentami źródłowymi i polityką rachunkową firmy.
          </p>
        </Section>

        <Section title="13. Dane, prywatność i bezpieczeństwo">
          <p>
            Zasady przetwarzania danych opisuje <Link to="/privacy" className="text-emerald-300 hover:text-emerald-200">Polityka prywatności</Link>.
            Zasady szyfrowania kosztów opisuje strona <Link to="/security" className="text-emerald-300 hover:text-emerald-200">Bezpieczeństwo</Link>.
          </p>
          <p>
            Dane operacyjne są przetwarzane w celu świadczenia Usługi, synchronizacji danych,
            prezentowania raportów, obsługi rozliczeń, bezpieczeństwa, wsparcia technicznego
            i dochodzenia lub obrony roszczeń.
          </p>
        </Section>

        <Section title="14. Zmiany regulaminu">
          <p>
            O istotnych zmianach regulaminu poinformujemy w aplikacji lub mailowo. Dalsze korzystanie
            z pakietu płatnego może wymagać zaakceptowania nowej wersji regulaminu.
          </p>
          <p>
            Jeżeli nie akceptujesz zmian, możesz zrezygnować z Usługi przed wejściem nowej wersji
            regulaminu w życie. Korzystanie z Usługi po dacie wejścia zmian w życie oznacza akceptację
            aktualnej wersji regulaminu.
          </p>
        </Section>

        <Section title="15. Postanowienia końcowe">
          <p>
            Regulamin podlega prawu polskiemu. Jeżeli którekolwiek postanowienie okaże się nieważne
            lub nieskuteczne, pozostałe postanowienia pozostają w mocy, a strony będą dążyć do
            zastąpienia go postanowieniem możliwie najbliższym pierwotnemu celowi.
          </p>
          <p>
            Spory będą w pierwszej kolejności rozwiązywane polubownie przez kontakt mailowy. Jeżeli
            nie uda się ich rozwiązać polubownie, właściwy będzie sąd powszechny zgodnie z przepisami
            prawa.
          </p>
        </Section>

        <footer className="border-t border-slate-800 pt-6 text-sm text-slate-400">
          <div className="flex flex-wrap gap-4">
            <Link to="/" className="hover:text-white">Strona główna</Link>
            <Link to="/privacy" className="hover:text-white">Polityka prywatności</Link>
            <Link to="/security" className="hover:text-white">Bezpieczeństwo</Link>
          </div>
        </footer>
      </main>
    </div>
  )
}
