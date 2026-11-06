import { FormEvent, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ShieldCheck } from 'lucide-react'
import { authApi, type ActivationStatus } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { PublicThemeToggle } from '../components/PublicThemeToggle'
import { productName, supportEmail } from '../config/brand'

type State = 'loading' | 'ready' | 'activating' | 'ok' | 'invalid' | 'error'

function strongEnough(password: string) {
  return password.length >= 8
}

export default function Activate() {
  const [params] = useSearchParams()
  const token = params.get('token') || ''
  const navigate = useNavigate()
  const { refresh } = useAuth()
  const [state, setState] = useState<State>('loading')
  const [activation, setActivation] = useState<ActivationStatus | null>(null)
  const [password, setPassword] = useState('')
  const [passwordConfirm, setPasswordConfirm] = useState('')
  const [enableTotp, setEnableTotp] = useState(false)
  const [totp, setTotp] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [privacyAccepted, setPrivacyAccepted] = useState(false)

  const passwordIssue = useMemo(() => {
    if (!password) return null
    if (!strongEnough(password)) return 'Hasło musi mieć min. 8 znaków.'
    if (passwordConfirm && password !== passwordConfirm) return 'Hasła nie są identyczne.'
    return null
  }, [password, passwordConfirm])

  useEffect(() => {
    let alive = true
    async function load() {
      if (!token) {
        setState('invalid')
        return
      }
      try {
        const result = await authApi.activationStatus(token)
        if (!alive) return
        setActivation(result)
        setState('ready')
      } catch {
        if (alive) setState('invalid')
      }
    }
    void load()
    return () => { alive = false }
  }, [token])

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!activation || passwordIssue || password !== passwordConfirm || !privacyAccepted) return
    if (enableTotp && totp.length !== 6) {
      setError('Wpisz 6-cyfrowy kod 2FA.')
      return
    }
    setState('activating')
    setError(null)
    try {
      await authApi.activate({ token, password, privacy_accepted: true, ...(enableTotp ? { totp } : {}) })
      await refresh()
      setState('ok')
      navigate('/dashboard', { replace: true })
    } catch (err: any) {
      const code = err?.response?.data?.detail?.code
      setState(code === 'invalid_token' ? 'invalid' : 'ready')
      setError(code === 'invalid_token'
        ? 'Link aktywacyjny jest nieważny, wygasł albo został już użyty.'
        : 'Nie udało się aktywować konta. Sprawdź dane i spróbuj ponownie.')
    }
  }

  return (
    <div className="public-theme min-h-screen bg-slate-900 px-5 py-10 text-slate-100">
      <div className="mx-auto max-w-2xl">
        <div className="mb-8 flex items-center justify-between gap-3">
          <Link to="/" className="inline-flex items-center gap-2 text-sm font-semibold text-white">
            <ShieldCheck size={18} className="text-emerald-300" />
            {productName()}
          </Link>
          <PublicThemeToggle />
        </div>
        <div className="rounded-lg border border-slate-700 bg-slate-800 p-6">
          <h1 className="mb-2 text-2xl font-bold text-white">Aktywacja konta</h1>
          {state === 'loading' && <p className="text-sm text-slate-300">Sprawdzanie linku aktywacyjnego...</p>}
          {state === 'invalid' && (
            <div className="rounded border border-red-500/40 bg-red-500/10 p-4 text-sm leading-6 text-red-100">
              Link aktywacyjny jest nieważny, wygasł albo został już użyty.
              {supportEmail() && <> Skontaktuj się z {supportEmail()}, jeśli potrzebujesz nowego linku.</>}
            </div>
          )}
          {activation && state !== 'loading' && state !== 'invalid' && (
            <>
              <p className="mb-6 text-sm leading-6 text-slate-300">
                Aktywujesz konto dla <span className="font-semibold text-white">{activation.email}</span>
                {' '}na koncie <span className="font-semibold text-white">{activation.tenant_name}</span>.
                Ustaw hasło, żeby wejść do {productName()}.
              </p>
              <form onSubmit={submit} className="space-y-4">
                <label className="block">
                  <span className="mb-1 block text-sm text-slate-300">Hasło</span>
                  <input
                    type="password"
                    required
                    minLength={8}
                    value={password}
                    onChange={event => setPassword(event.target.value)}
                    autoComplete="new-password"
                    className="w-full rounded border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-white outline-none focus:border-indigo-500"
                  />
                </label>
                <label className="block">
                  <span className="mb-1 block text-sm text-slate-300">Powtórz hasło</span>
                  <input
                    type="password"
                    required
                    value={passwordConfirm}
                    onChange={event => setPasswordConfirm(event.target.value)}
                    autoComplete="new-password"
                    className="w-full rounded border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-white outline-none focus:border-indigo-500"
                  />
                </label>
                {passwordIssue && <p className="text-sm text-amber-300">{passwordIssue}</p>}

                <label className="flex cursor-pointer items-start gap-3 rounded border border-slate-700 bg-slate-900/60 p-3">
                  <input
                    type="checkbox"
                    checked={enableTotp}
                    onChange={event => setEnableTotp(event.target.checked)}
                    className="mt-0.5 h-4 w-4 rounded border-slate-600 text-indigo-500 focus:ring-indigo-500"
                  />
                  <div>
                    <p className="text-sm font-medium text-white">Włącz 2FA (zalecane)</p>
                    <p className="mt-0.5 text-xs leading-5 text-slate-400">
                      Logowanie będzie wymagało kodu z aplikacji TOTP.
                    </p>
                  </div>
                </label>

                {enableTotp && activation.qr_svg && activation.secret && (
                  <div className="rounded border border-indigo-500/30 bg-indigo-500/10 p-4">
                    <p className="text-sm font-semibold text-indigo-100">Skonfiguruj aplikację TOTP</p>
                    <div
                      className="mt-3 inline-block rounded bg-white p-3"
                      dangerouslySetInnerHTML={{ __html: activation.qr_svg }}
                    />
                    <p className="mt-3 break-all rounded bg-slate-950 p-2 font-mono text-xs text-slate-200">
                      {activation.secret}
                    </p>
                    <label className="mt-3 block">
                      <span className="mb-1 block text-sm text-slate-300">Kod 2FA</span>
                      <input
                        required={enableTotp}
                        inputMode="numeric"
                        pattern="[0-9]{6}"
                        maxLength={6}
                        value={totp}
                        onChange={event => setTotp(event.target.value.replace(/\D/g, '').slice(0, 6))}
                        autoComplete="one-time-code"
                        className="w-full rounded border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-white outline-none focus:border-indigo-500"
                      />
                    </label>
                  </div>
                )}

                <label className="flex cursor-pointer items-start gap-3 rounded border border-slate-700 bg-slate-900/60 p-3 text-sm leading-6 text-slate-300">
                  <input
                    type="checkbox"
                    required
                    checked={privacyAccepted}
                    onChange={event => setPrivacyAccepted(event.target.checked)}
                    className="mt-1 h-4 w-4 rounded border-slate-600 text-indigo-500 focus:ring-indigo-500"
                  />
                  <span>
                    Zapoznałem się z{' '}
                    <Link to="/privacy" className="text-emerald-300 hover:text-emerald-200">
                      Polityką prywatności
                    </Link>{' '}
                    i zgadzam się na przetwarzanie moich danych osobowych w celu uruchomienia konta w {productName()}.
                  </span>
                </label>

                {error && <p className="text-sm text-red-300">{error}</p>}
                <button
                  type="submit"
                  disabled={state === 'activating' || !!passwordIssue || password !== passwordConfirm || !privacyAccepted || (enableTotp && totp.length !== 6)}
                  className="w-full rounded bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {state === 'activating' ? 'Aktywowanie...' : 'Aktywuj konto'}
                </button>
              </form>
            </>
          )}
        </div>
        <div className="mt-5 flex flex-wrap gap-4 text-sm text-slate-500">
          <Link to="/privacy" className="hover:text-white">Polityka prywatności</Link>
          <Link to="/security" className="hover:text-white">Bezpieczeństwo</Link>
        </div>
      </div>
    </div>
  )
}
