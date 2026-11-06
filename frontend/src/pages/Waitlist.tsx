import { FormEvent, useState } from 'react'
import { Link } from 'react-router-dom'
import { authApi, type WaitlistPayload } from '../api/client'
import { PublicThemeToggle } from '../components/PublicThemeToggle'
import { useTheme } from '../context/ThemeContext'
import { productName, supportEmail } from '../config/brand'
import { trackRegistrationConversion } from '../utils/gtag'

const orderBuckets = ['<100', '100-1000', '1000-10000', '>10000', 'nie wiem']

export default function Waitlist() {
  const { theme } = useTheme()
  const isDarkBase = theme === 'dark'
  const [form, setForm] = useState<WaitlistPayload>({
    email: '',
    company: '',
    monthly_orders: 'nie wiem',
    message: '',
    website: '',
  })
  const [status, setStatus] = useState<'idle' | 'sending' | 'ok' | 'rate' | 'error'>('idle')
  const [activationEmailSent, setActivationEmailSent] = useState<boolean | null>(null)
  const [privacyAccepted, setPrivacyAccepted] = useState(false)

  function update<K extends keyof WaitlistPayload>(key: K, value: WaitlistPayload[K]) {
    setForm(current => ({ ...current, [key]: value }))
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (status === 'sending') return
    setStatus('sending')
    try {
      const result = await authApi.waitlist({ ...form, privacy_accepted: privacyAccepted })
      setActivationEmailSent(Boolean(result.activation_email_sent))
      setStatus('ok')
      trackRegistrationConversion()
    } catch (error: any) {
      setStatus(error?.response?.status === 429 ? 'rate' : 'error')
    }
  }

  const labelClass = isDarkBase ? 'text-slate-300' : 'text-slate-700'
  const inputClass = isDarkBase
    ? 'border-slate-600 bg-slate-950 text-white focus:border-indigo-500'
    : 'border-slate-300 bg-white text-slate-950 focus:border-blue-500'
  const mutedText = isDarkBase ? 'text-slate-300' : 'text-slate-600'

  return (
    <div className={`public-theme min-h-screen px-5 py-10 ${
      isDarkBase ? 'bg-slate-900 text-slate-100' : 'bg-[#f6f4ed] text-slate-950'
    }`}>
      <div className="mx-auto max-w-2xl">
        <div className="mb-8 flex items-center justify-between gap-3">
          <Link to="/" className={`inline-block text-sm ${
            isDarkBase ? 'text-slate-400 hover:text-white' : 'text-slate-600 hover:text-slate-950'
          }`}>{productName()}</Link>
          <PublicThemeToggle />
        </div>
        <div className={`rounded-lg border p-6 ${
          isDarkBase ? 'border-slate-700 bg-slate-800' : 'border-slate-300 bg-white shadow-sm'
        }`}>
          <h1 className={`mb-2 text-2xl font-bold ${isDarkBase ? 'text-white' : 'text-slate-950'}`}>Uruchom konto ProfitOS</h1>
          <p className={`mb-6 text-sm leading-6 ${mutedText}`}>
            Podaj email, utwórz konto i rozpocznij 30 dni bezpłatnego korzystania z ProfitOS.pl.
          </p>

          {status === 'ok' ? (
            <div className="rounded border border-emerald-300 bg-emerald-50 p-4 text-sm font-medium text-emerald-900">
              {activationEmailSent
                ? `Wysłaliśmy link aktywacyjny na ${form.email}. Otwórz wiadomość, ustaw hasło i uruchom konto.`
                : `Konto zostało przygotowane, ale nie udało się automatycznie wysłać maila.${supportEmail() ? ` Napisz na ${supportEmail()}.` : ""}`}
            </div>
          ) : (
            <form onSubmit={submit} className="space-y-4">
              <label className="block">
                <span className={`mb-1 block text-sm ${labelClass}`}>Email</span>
                <input
                  type="email"
                  required
                  value={form.email}
                  onChange={event => update('email', event.target.value)}
                  className={`w-full rounded border px-3 py-2 text-sm outline-none ${inputClass}`}
                />
              </label>
              <div className="grid gap-4 md:grid-cols-2">
                <label className="block">
                  <span className={`mb-1 block text-sm ${labelClass}`}>Firma</span>
                  <input
                    value={form.company}
                    onChange={event => update('company', event.target.value)}
                    className={`w-full rounded border px-3 py-2 text-sm outline-none ${inputClass}`}
                  />
                </label>
                <label className="block">
                  <span className={`mb-1 block text-sm ${labelClass}`}>Miesięczna liczba zamówień</span>
                  <select
                    value={form.monthly_orders}
                    onChange={event => update('monthly_orders', event.target.value)}
                    className={`w-full rounded border px-3 py-2 text-sm outline-none ${inputClass}`}
                  >
                    {orderBuckets.map(bucket => <option key={bucket} value={bucket}>{bucket}</option>)}
                  </select>
                </label>
              </div>
              <label className="block">
                <span className={`mb-1 block text-sm ${labelClass}`}>Wiadomość</span>
                <textarea
                  value={form.message}
                  maxLength={2000}
                  onChange={event => update('message', event.target.value)}
                  rows={4}
                  className={`w-full rounded border px-3 py-2 text-sm outline-none ${inputClass}`}
                />
              </label>
              <label className="absolute -left-[10000px]" aria-hidden="true">
                Website
                <input
                  name="website"
                  tabIndex={-1}
                  autoComplete="off"
                  value={form.website}
                  onChange={event => update('website', event.target.value)}
                />
              </label>
              <label className={`flex cursor-pointer items-start gap-3 rounded border p-3 text-sm leading-6 ${
                isDarkBase ? 'border-slate-700 bg-slate-900/60 text-slate-300' : 'border-slate-200 bg-slate-50 text-slate-700'
              }`}>
                <input
                  type="checkbox"
                  required
                  checked={privacyAccepted}
                  onChange={event => setPrivacyAccepted(event.target.checked)}
                  className="mt-1 h-4 w-4 rounded border-slate-600 text-indigo-500 focus:ring-indigo-500"
                />
                <span>
                  Zapoznałem się z{' '}
                  <Link to="/privacy" className={isDarkBase ? 'text-emerald-300 hover:text-emerald-200' : 'text-emerald-700 hover:text-emerald-900'}>
                    Polityką prywatności
                  </Link>{' '}
                  i zgadzam się na przetwarzanie moich danych osobowych w celu uruchomienia konta w {productName()}.
                </span>
              </label>
              {status === 'rate' && <p className="text-sm text-amber-600">Za dużo prób. Spróbuj ponownie za godzinę.</p>}
              {status === 'error' && <p className="text-sm text-red-500">Coś poszło nie tak.{supportEmail() && <> Napisz na {supportEmail()}.</>}</p>}
              <button
                type="submit"
                disabled={status === 'sending' || !privacyAccepted}
                className="w-full rounded bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-500 disabled:opacity-60"
              >
                {status === 'sending' ? 'Tworzenie konta...' : 'Utwórz konto'}
              </button>
            </form>
          )}

          <p className={`mt-5 text-xs leading-5 ${isDarkBase ? 'text-slate-400' : 'text-slate-600'}`}>
            Twój email zostanie użyty wyłącznie do kontaktu w sprawie uruchomienia konta.
            Nie wysyłamy newslettera.{' '}
            <Link to="/privacy" className={isDarkBase ? 'text-slate-300 hover:text-white' : 'text-slate-800 hover:text-slate-950'}>Polityka prywatności</Link>
          </p>
        </div>
      </div>
    </div>
  )
}
