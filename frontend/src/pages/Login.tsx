import { FormEvent, useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowRight, LockKeyhole } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { useDeploymentMode } from '../context/DeploymentContext'
import { PublicThemeToggle } from '../components/PublicThemeToggle'
import { productName, publicSiteUrl } from '../config/brand'
import { BrandLogo } from '../components/BrandLogo'
import { IS_APP } from '../utils/isApp'
import { rejectOperatorOnUserLogin } from '../utils/loginPolicy'

type LoginMode = 'user' | 'operator'
type EnrollData = {
  qr_svg: string
  secret: string
  provisioning_uri: string
}

export default function Login({ mode = 'user' }: { mode?: LoginMode }) {
  const { login, enrollTotp, logout } = useAuth()
  const modeDeployment = useDeploymentMode()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [totp, setTotp] = useState('')
  const [rememberDevice, setRememberDevice] = useState(true)
  const [requiresTotp, setRequiresTotp] = useState(false)
  const [enrollData, setEnrollData] = useState<EnrollData | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const next = params.get('next') || '/dashboard'
  const isOperatorLogin = mode === 'operator'

  useEffect(() => {
    if (!isOperatorLogin) return
    const previousTitle = document.title
    const meta = document.querySelector<HTMLMetaElement>('meta[name="robots"]') || document.createElement('meta')
    const previousContent = meta.getAttribute('content')
    const wasConnected = meta.isConnected
    meta.setAttribute('name', 'robots')
    meta.setAttribute('content', 'noindex,nofollow,noarchive')
    if (!wasConnected) document.head.appendChild(meta)
    document.title = `Dostęp operatora - ${productName()}`

    return () => {
      document.title = previousTitle
      if (wasConnected) {
        if (previousContent === null) meta.removeAttribute('content')
        else meta.setAttribute('content', previousContent)
      } else {
        meta.remove()
      }
    }
  }, [isOperatorLogin])

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (enrollData) {
        await enrollTotp(totp)
        navigate(next, { replace: true })
        return
      }
      const response = await login(email, password, requiresTotp ? totp : undefined, rememberDevice)
      if (response.status === 'ok') {
        if (isOperatorLogin && !response.user.is_operator) {
          await logout()
          setError('To wejście jest tylko dla operatora.')
          return
        }
        if (rejectOperatorOnUserLogin(modeDeployment, isOperatorLogin, response.user.is_operator)) {
          await logout()
          setError('Konto operatora loguje się osobnym wejściem.')
          return
        }
        navigate(next, { replace: true })
      } else if (response.status === 'totp_required') {
        setRequiresTotp(true)
        setTotp('')
      } else if (response.status === 'totp_enroll_required') {
        setEnrollData({
          qr_svg: response.qr_svg,
          secret: response.secret,
          provisioning_uri: response.provisioning_uri,
        })
        setRequiresTotp(false)
        setTotp('')
      } else {
        setError('Ten sposób logowania jest już wyłączony. Odśwież stronę i spróbuj ponownie.')
      }
    } catch (err: any) {
      const status = err?.response?.status
      if (status === 429 || status === 423) {
        setError('Konto tymczasowo zablokowane po zbyt wielu próbach. Spróbuj później.')
      } else {
        setError('Nieprawidłowe dane logowania.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="public-theme min-h-screen bg-zinc-950 text-zinc-100">
      <div className="mx-auto grid min-h-screen w-full max-w-6xl px-5 py-8 lg:grid-cols-[0.9fr_1.1fr] lg:items-center lg:gap-14">
        {!IS_APP && (
          <section className="hidden lg:block">
            <div className="flex items-center justify-between gap-3">
              <a href={publicSiteUrl()} className="inline-flex items-center gap-2 text-sm font-semibold text-white">
                <BrandLogo markClassName="h-8 w-8" textClassName="text-sm font-semibold" />
              </a>
              <PublicThemeToggle />
            </div>
            <h1 className="mt-10 max-w-xl text-4xl font-semibold leading-tight text-white">
              {isOperatorLogin ? 'Wejście operatora' : 'Panel sprzedaży Allegro'}
            </h1>
            <p className="mt-5 max-w-lg text-base leading-7 text-zinc-400">
              {isOperatorLogin
                ? 'Dostęp administracyjny do kont, zgłoszeń i operacji systemowych.'
                : 'Zaloguj się do panelu swojej firmy. Koszty zakupu pozostają chronione w Twoim sejfie.'}
            </p>
            <div className="mt-8 grid max-w-lg grid-cols-2 gap-3 text-sm">
              <div className="rounded border border-zinc-800 bg-zinc-900/70 p-4">
                <p className="text-zinc-500">Zakres</p>
                <p className="mt-1 font-medium text-white">{isOperatorLogin ? 'Operator' : 'Firma'}</p>
              </div>
              <div className="rounded border border-zinc-800 bg-zinc-900/70 p-4">
                <p className="text-zinc-500">Bezpieczeństwo</p>
                <p className="mt-1 font-medium text-white">{isOperatorLogin ? 'noindex' : 'sejf gotowy'}</p>
              </div>
            </div>
          </section>
        )}

        <section className="mx-auto w-full max-w-md rounded border border-zinc-800 bg-zinc-900 p-6 shadow-2xl shadow-black/30">
          <div className="mb-6 flex items-center justify-between gap-3 lg:hidden">
            <a href={publicSiteUrl()} className="inline-flex items-center gap-2 text-sm font-semibold text-white">
              <BrandLogo markClassName="h-8 w-8" textClassName="text-sm font-semibold" />
            </a>
            <PublicThemeToggle />
          </div>
          <div className="mb-6 flex items-start justify-between gap-4">
            <div>
              <p className="text-xs font-medium uppercase text-cyan-300">
                {isOperatorLogin ? 'Dostęp operatora' : 'Dostęp użytkownika'}
              </p>
              <h1 className="mt-2 text-2xl font-semibold text-white">
                {isOperatorLogin ? 'Logowanie operatora' : 'Logowanie użytkownika'}
              </h1>
            </div>
            <div className="rounded border border-zinc-700 bg-zinc-950 p-2 text-zinc-300">
              <LockKeyhole size={18} />
            </div>
          </div>
          <p className="mb-6 text-sm leading-6 text-zinc-400">
            {isOperatorLogin
              ? 'Ten adres jest ukryty przed indeksowaniem i wymaga 2FA dla konta operatora.'
              : modeDeployment === 'hosted'
                ? 'Użyj emaila aktywowanego po zgłoszeniu. Operator loguje się osobnym wejściem.'
                : 'Zaloguj się do panelu swojej firmy.'}
          </p>

        <form onSubmit={submit} className="space-y-4">
          <label className="block">
            <span className="mb-1 block text-sm text-zinc-300">Email</span>
            <input
              type="email"
              required
              value={email}
              disabled={requiresTotp || !!enrollData}
              onChange={event => setEmail(event.target.value)}
              autoComplete="username"
              className="w-full rounded border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-white outline-none focus:border-cyan-500 disabled:opacity-70"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm text-zinc-300">Hasło</span>
            <input
              type="password"
              required
              minLength={8}
              value={password}
              disabled={requiresTotp || !!enrollData}
              onChange={event => setPassword(event.target.value)}
              autoComplete="current-password"
              className="w-full rounded border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-white outline-none focus:border-cyan-500 disabled:opacity-70"
            />
          </label>

          {!enrollData && (
            <label className="flex items-center gap-2 text-sm text-zinc-300">
              <input
                type="checkbox"
                checked={rememberDevice}
                onChange={event => setRememberDevice(event.target.checked)}
                className="h-4 w-4 rounded border-zinc-700 bg-zinc-950 text-cyan-500 focus:ring-cyan-500"
              />
              Zapamiętaj to urządzenie — rzadsze logowanie
            </label>
          )}

          {enrollData && (
            <div className="rounded border border-cyan-500/30 bg-cyan-500/10 p-4">
              <p className="text-sm font-semibold text-cyan-100">Aktywuj 2FA</p>
              <p className="mt-1 text-xs leading-5 text-zinc-300">
                Zeskanuj QR w aplikacji TOTP i wpisz pierwszy 6-cyfrowy kod.
              </p>
              <div
                className="mt-3 inline-block rounded bg-white p-3"
                dangerouslySetInnerHTML={{ __html: enrollData.qr_svg }}
              />
              <p className="mt-3 break-all rounded bg-zinc-950 p-2 font-mono text-xs text-zinc-200">
                {enrollData.secret}
              </p>
            </div>
          )}

          {(requiresTotp || enrollData) && (
            <label className="block">
              <span className="mb-1 block text-sm text-zinc-300">Kod 2FA</span>
              <input
                required
                inputMode="numeric"
                pattern="[0-9]{6}"
                maxLength={6}
                value={totp}
                onChange={event => setTotp(event.target.value.replace(/\D/g, '').slice(0, 6))}
                autoComplete="one-time-code"
                className="w-full rounded border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-white outline-none focus:border-cyan-500"
              />
            </label>
          )}

          {error && <p className="rounded border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">{error}</p>}
          <button
            type="submit"
            disabled={busy}
            className="inline-flex w-full items-center justify-center gap-2 rounded bg-cyan-500 px-4 py-2.5 text-sm font-semibold text-zinc-950 hover:bg-cyan-400 disabled:opacity-60"
          >
            {busy ? 'Sprawdzanie...' : enrollData ? 'Aktywuj 2FA' : requiresTotp ? 'Potwierdź kod' : 'Zaloguj'}
            {!busy && <ArrowRight size={16} />}
          </button>
        </form>

        {!IS_APP && (
          <div className="mt-5 flex flex-wrap gap-4 text-sm text-zinc-400">
            {modeDeployment === 'hosted' && !isOperatorLogin && <a href={`${publicSiteUrl()}/register`} className="hover:text-white">Nie mam jeszcze konta</a>}
            <Link to="/security" className="hover:text-white">Bezpieczeństwo</Link>
            {modeDeployment === 'hosted' && <Link to="/privacy" className="hover:text-white">Polityka prywatności</Link>}
          </div>
        )}
        </section>
      </div>
    </div>
  )
}
