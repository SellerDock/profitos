import { Link, Outlet, NavLink } from 'react-router-dom'
import { FormEvent, useState } from 'react'
import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Bell,
  ChevronsUpDown,
  LayoutDashboard,
  Upload,
  Package,
  Warehouse,
  Receipt,
  CreditCard,
  Settings,
  FileBarChart,
  ShieldCheck,
  Smartphone,
  Lock,
  Unlock,
  LogOut,
  Fingerprint,
  Users,
  Menu,
  X,
  MessageSquare,
  Paperclip,
  Send,
} from 'lucide-react'
import { adminApi, supportApi } from '../api/client'
import { useFinancialVault } from '../context/FinancialVaultContext'
import { useAuth } from '../context/AuthContext'
import { useDeploymentMode } from '../context/DeploymentContext'
import { isDeploymentRouteVisible } from '../utils/deploymentRoutes'
import { THEME_NAME, useTheme } from '../context/ThemeContext'
import { FINANCIAL_DISPLAY_LABEL, useFinancialDisplayMode } from '../context/FinancialDisplayModeContext'
import TerminalStatusBar from './TerminalStatusBar'
import AppUpdateBanner from './AppUpdateBanner'
import { productName } from '../config/brand'
import { BrandMark } from './BrandLogo'

const navItems = [
  { to: '/dashboard', icon: LayoutDashboard, label: 'Panel' },
  { to: '/import', icon: Upload, label: 'Import' },
  { to: '/ads-import', icon: FileBarChart, label: 'Reklamy' },
  { to: '/products', icon: Package, label: 'Produkty' },
  { to: '/stock', icon: Warehouse, label: 'Magazyn' },
  { to: '/orders', icon: Receipt, label: 'Zamówienia' },
  { to: '/subscription', icon: CreditCard, label: 'Rozliczenia' },
  { to: '/security', icon: ShieldCheck, label: 'Bezpieczeństwo' },
  { to: '/pobierz', icon: Smartphone, label: 'Aplikacja' },
  { to: '/settings', icon: Settings, label: 'Ustawienia' },
]

const BOTTOM_NAV_PATHS = ['/dashboard', '/products', '/orders', '/stock', '/settings']
const bottomNavItems = BOTTOM_NAV_PATHS
  .map(path => navItems.find(item => item.to === path))
  .filter((item): item is typeof navItems[number] => Boolean(item))

export default function Layout({ children }: { children?: ReactNode }) {
  const { user, logout } = useAuth()
  const mode = useDeploymentMode()
  const vault = useFinancialVault()
  const { theme, cycleTheme } = useTheme()
  const financialDisplay = useFinancialDisplayMode()
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const [vaultSheetOpen, setVaultSheetOpen] = useState(false)
  const visibleNavItems = (user?.is_operator
    ? [...navItems, { to: '/admin/waitlist', icon: Users, label: 'Administracja' }]
    : navItems).filter(item => isDeploymentRouteVisible(item.to, mode))
  const isDarkBase = theme === 'dark'

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-finance-canvas text-slate-900">
      {mobileNavOpen && (
        <button
          type="button"
          aria-label="Zamknij menu"
          onClick={() => setMobileNavOpen(false)}
          className="fixed inset-0 z-30 bg-slate-950/45 lg:hidden"
        />
      )}
      {vaultSheetOpen && (
        <div className="fixed inset-0 z-[80] p-3">
          <button
            type="button"
            className="absolute inset-0 bg-slate-950/60 backdrop-blur-sm"
            onClick={() => setVaultSheetOpen(false)}
            aria-label="Zamknij Sejf"
          />
          <div className={`relative z-10 ml-auto flex h-full w-full max-w-sm flex-col overflow-y-auto rounded-lg border shadow-2xl ${
            isDarkBase ? 'border-white/10 bg-ink-950 text-slate-100' : 'border-slate-200 bg-white text-slate-950'
          }`}>
            <div className={`flex items-center justify-between border-b px-4 py-3 ${
              isDarkBase ? 'border-white/10' : 'border-slate-200'
            }`}>
              <div className="flex items-center gap-2 text-sm font-semibold">
                {vault.unlocked ? <Unlock size={16} className="text-emerald-300" /> : <Lock size={16} className="text-amber-300" />}
                <span>Sejf finansowy</span>
              </div>
              <button
                type="button"
                className={`rounded-md p-2 ${
                  isDarkBase ? 'text-slate-400 hover:bg-white/10 hover:text-white' : 'text-slate-500 hover:bg-slate-100 hover:text-slate-950'
                }`}
                onClick={() => setVaultSheetOpen(false)}
                aria-label="Zamknij Sejf"
              >
                <X size={18} />
              </button>
            </div>
            <div className="p-3">
              <FinancialVaultPanel mobile onDone={() => setVaultSheetOpen(false)} />
            </div>
          </div>
        </div>
      )}
      <aside className={`fixed inset-y-0 left-0 z-40 flex w-72 max-w-[86vw] flex-col overflow-y-auto overscroll-contain shadow-2xl transition-transform duration-200 lg:static lg:z-auto lg:w-60 lg:max-w-none lg:translate-x-0 ${
        mobileNavOpen ? 'translate-x-0' : '-translate-x-full'
      } ${
        isDarkBase
          ? 'bg-ink-950 text-slate-300'
          : 'border-r border-slate-200 bg-white text-slate-700'
      }`}>
        <div className={`flex h-16 items-center justify-between border-b px-4 ${
          isDarkBase ? 'border-white/10' : 'border-slate-200'
        }`}>
          <div className="flex min-w-0 items-center">
            <BrandMark className="h-9 w-9 shrink-0" />
            <div className="ml-3 min-w-0">
              <h1 className={`truncate text-sm font-semibold tracking-tight ${isDarkBase ? 'text-white' : 'text-slate-950'}`}>
                {productName()}
              </h1>
              <p className="text-[11px] text-slate-500">
                {isDarkBase ? 'tryb ciemny' : 'tryb jasny'}
              </p>
            </div>
          </div>
          <button
            type="button"
            aria-label="Zamknij menu"
            onClick={() => setMobileNavOpen(false)}
            className={`rounded-md p-2 lg:hidden ${
              isDarkBase ? 'text-slate-400 hover:bg-white/10 hover:text-white' : 'text-slate-500 hover:bg-slate-100 hover:text-slate-950'
            }`}
          >
            <X size={18} />
          </button>
        </div>
        <nav className="flex-1 space-y-1 px-3 py-4">
          {visibleNavItems.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              onClick={() => setMobileNavOpen(false)}
              className={({ isActive }) =>
                `group flex items-center justify-start gap-3 rounded-lg px-3 py-2.5 text-xs font-medium transition-colors ${
                  isActive
                    ? isDarkBase
                      ? 'bg-white/10 text-white shadow-inner'
                      : 'bg-slate-950 text-white shadow-sm'
                    : isDarkBase
                      ? 'text-slate-400 hover:bg-white/5 hover:text-white'
                      : 'text-slate-500 hover:bg-slate-100 hover:text-slate-950'
                }`
              }
            >
              <Icon size={17} className="shrink-0" />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className={`space-y-3 border-t px-3 py-3 ${isDarkBase ? 'border-white/10' : 'border-slate-200'}`}>
          <SupportReportPanel />
          <button
            type="button"
            onClick={() => {
              setMobileNavOpen(false)
              void logout()
            }}
            className={`group flex w-full items-center justify-start gap-3 rounded-lg px-3 py-2.5 text-xs font-medium transition-colors ${
              isDarkBase ? 'text-slate-400 hover:bg-white/5 hover:text-white' : 'text-slate-500 hover:bg-slate-100 hover:text-slate-950'
            }`}
          >
            <LogOut size={17} className="shrink-0" />
            <span>Wyloguj</span>
          </button>
        </div>
        <div className="hidden lg:block">
          <FinancialVaultPanel />
        </div>
      </aside>
      <section className="flex min-w-0 flex-1 flex-col">
        <header className={`flex h-16 items-center justify-between gap-2 border-b px-3 shadow-sm backdrop-blur sm:px-6 ${
          isDarkBase ? 'border-slate-800 bg-slate-950/90' : 'border-slate-200 bg-white/90'
        }`}>
          <div className="flex min-w-0 items-center gap-2">
            <button
              type="button"
              className="apos-button h-9 px-2.5 lg:hidden"
              onClick={() => setMobileNavOpen(true)}
              aria-label="Otwórz menu"
            >
              <Menu size={16} />
            </button>
            <div className="hidden min-w-0 sm:block">
            <p className="hidden text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400 md:block">System finansów operacyjnych</p>
            <p className={`text-sm font-semibold ${isDarkBase ? 'text-white' : 'text-slate-900'}`}>
              Panel rentowności Allegro
            </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {user?.is_operator && <SystemHealthBadge />}
            <button
              className="apos-button h-9 px-2.5"
              type="button"
              onClick={cycleTheme}
              title={`Motyw: ${THEME_NAME[theme]} — kliknij aby przełączyć`}
            >
              <span className="text-xs">{THEME_NAME[theme]}</span>
            </button>
            <button
              className="apos-button h-9 px-2.5"
              type="button"
              onClick={financialDisplay.toggleMode}
              title={`Widok finansów: ${FINANCIAL_DISPLAY_LABEL[financialDisplay.mode]} — kliknij aby przełączyć netto/brutto`}
            >
              <span className="text-xs">{FINANCIAL_DISPLAY_LABEL[financialDisplay.mode]}</span>
            </button>
            <button
              className="apos-button h-9 gap-1.5 px-2.5"
              type="button"
              onClick={() => {
                setMobileNavOpen(false)
                setVaultSheetOpen(true)
              }}
              title={vault.unlocked ? 'Sejf finansowy jest odblokowany' : 'Otwórz Sejf finansowy, aby używać kosztów zakupu'}
              aria-label="Otwórz Sejf finansowy"
            >
              {vault.unlocked ? <Unlock size={15} className="text-emerald-400" /> : <Lock size={15} className="text-amber-400" />}
              <span className="text-xs">Sejf</span>
            </button>
            <button className="apos-button hidden h-9 px-2.5 sm:inline-flex" type="button" title="Powiadomienia">
              <Bell size={15} />
            </button>
            <button className="apos-button hidden h-9 sm:inline-flex" type="button">
              <span className="hidden text-left sm:block">
                <span className="block text-xs font-semibold leading-none text-slate-900">
                  {user?.email || productName()}
                </span>
                <span className="block text-[10px] leading-none text-slate-500">
                  {user?.is_operator ? 'konto operatora' : 'konto użytkownika'}
                </span>
              </span>
              <ChevronsUpDown size={14} className="text-slate-400" />
            </button>
          </div>
        </header>
        <main className="min-w-0 flex-1 overflow-auto px-5 pt-5 pb-24 lg:px-7 lg:pb-5">
          <AppUpdateBanner />
          {children ?? <Outlet />}
        </main>
        {theme === 'dark' && <TerminalStatusBar />}
      </section>
      <nav
        className={`fixed inset-x-0 bottom-0 z-40 flex items-stretch justify-around border-t lg:hidden ${
          isDarkBase ? 'border-white/10 bg-ink-950' : 'border-slate-200 bg-white'
        }`}
        style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
      >
        {bottomNavItems.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `flex flex-1 flex-col items-center justify-center gap-0.5 py-2 text-[11px] font-medium transition-colors ${
                isActive
                  ? isDarkBase ? 'text-white' : 'text-slate-950'
                  : isDarkBase ? 'text-slate-500 hover:text-slate-300' : 'text-slate-500 hover:text-slate-700'
              }`
            }
          >
            <Icon size={20} className="shrink-0" />
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>
    </div>
  )
}

function SystemHealthBadge() {
  const { data } = useQuery({
    queryKey: ['admin-system-health'],
    queryFn: adminApi.systemHealth,
    refetchInterval: 30_000,
  })

  if (!data) return null

  return (
    <Link
      to="/admin/health"
      className={`hidden rounded border px-2.5 py-1.5 text-xs font-medium lg:inline-flex ${
        data.db_ok
          ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200'
          : 'border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-200'
      }`}
      title="Zdrowie systemu"
    >
      {data.users_count} użytk. · {data.active_sessions} aktywni
    </Link>
  )
}

function SupportReportPanel() {
  const { theme } = useTheme()
  const [message, setMessage] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<'idle' | 'sent' | 'error'>('idle')
  const [error, setError] = useState<string | null>(null)
  const expanded = message.trim().length > 0 || Boolean(file) || status !== 'idle' || Boolean(error)
  const isDarkBase = theme === 'dark'

  function pickFile(nextFile: File | null) {
    setError(null)
    setStatus('idle')
    if (nextFile && nextFile.size > 5 * 1024 * 1024) {
      setFile(null)
      setError('Plik może mieć maksymalnie 5 MB.')
      return
    }
    setFile(nextFile)
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    const body = message.trim()
    if (!body || busy) return
    setBusy(true)
    setError(null)
    setStatus('idle')
    try {
      await supportApi.createTicket({ message: body, attachment: file })
      setMessage('')
      setFile(null)
      setStatus('sent')
    } catch {
      setStatus('error')
      setError('Nie udało się wysłać zgłoszenia.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form
      onSubmit={submit}
      className={`rounded-lg border p-2.5 transition-all ${
        isDarkBase ? 'border-white/10 bg-white/[0.04]' : 'border-slate-200 bg-slate-50'
      }`}
    >
      <div className={`mb-2 flex items-center gap-2 text-xs font-medium ${
        isDarkBase ? 'text-slate-300' : 'text-slate-700'
      }`}>
        <MessageSquare size={14} />
        <span>Zgłoś błąd</span>
      </div>
      <textarea
        value={message}
        onChange={event => {
          setMessage(event.target.value)
          setStatus('idle')
          setError(null)
        }}
        maxLength={5000}
        rows={expanded ? 3 : 1}
        placeholder="Napisz krótko, co nie działa..."
        className={`w-full resize-none rounded-md border px-2 py-1.5 text-xs outline-none transition-all placeholder:text-slate-500 focus:border-emerald-400 ${
          isDarkBase
            ? 'border-white/10 bg-ink-900 text-white'
            : 'border-slate-300 bg-white text-slate-950'
        }`}
      />
      {expanded && (
        <div className="mt-2 space-y-2">
          <label className={`flex cursor-pointer items-center gap-2 rounded-md border px-2 py-1.5 text-[11px] transition ${
            isDarkBase
              ? 'border-white/10 text-slate-400 hover:bg-white/5 hover:text-white'
              : 'border-slate-200 text-slate-600 hover:bg-white hover:text-slate-950'
          }`}>
            <Paperclip size={13} />
            <span className="truncate">{file ? file.name : 'Załącz plik do 5 MB'}</span>
            <input
              type="file"
              className="sr-only"
              onChange={event => pickFile(event.target.files?.[0] ?? null)}
            />
          </label>
          {status === 'sent' && <p className="text-[11px] text-emerald-500">Wysłane, dzięki.</p>}
          {error && <p className="text-[11px] text-red-400">{error}</p>}
          <button
            type="submit"
            disabled={busy || message.trim().length === 0}
            className={`flex w-full items-center justify-center gap-2 rounded-md px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50 ${
              isDarkBase ? 'bg-emerald-400 text-ink-950 hover:bg-emerald-300' : 'bg-ink-950 text-white hover:bg-ink-800'
            }`}
          >
            <Send size={13} />
            {busy ? 'Wysyłanie...' : 'Wyślij'}
          </button>
        </div>
      )}
    </form>
  )
}

function nativeErrorMessage(err: unknown): string {
  const code = err instanceof Error ? err.message : ''
  switch (code) {
    case 'cancelled':
      return 'Anulowano odblokowanie odciskiem'
    case 'key_invalidated':
      return 'Zmieniono biometrię w systemie — włącz odblokowanie odciskiem ponownie'
    case 'lockout':
      return 'Zbyt wiele nieudanych prób — spróbuj ponownie za chwilę'
    case 'no_biometric':
    case 'no_stored_key':
      return 'Biometria niedostępna na tym urządzeniu'
    default:
      return 'Nie udało się odblokować sejfu odciskiem'
  }
}

function FinancialVaultPanel({ mobile = false, onDone }: { mobile?: boolean; onDone?: () => void }) {
  const vault = useFinancialVault()
  const { theme } = useTheme()
  const [password, setPassword] = useState('')
  const [persist, setPersist] = useState(false)
  const [enableNative, setEnableNative] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Mostek + biometria (checkbox opt-in); vault.nativeAvailable dodatkowo wymaga
  // zapisanego blobu klucza (przycisk „Odblokuj odciskiem").
  const nativeSupported = vault.nativeSupported

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!password || busy) return
    setBusy(true)
    setError(null)
    try {
      // Gdy user włącza biometrię, klucz musi być extractable (do eksportu do
      // natywnego magazynu) — stąd persist || enableNative.
      const keepExtractable = persist || (nativeSupported && enableNative)
      const vaultKey = vault.status?.configured
        ? await vault.unlock(password, keepExtractable)
        : await vault.setup(password, keepExtractable)
      if (nativeSupported && enableNative) {
        const enabled = await vault.enableNativeUnlock(vaultKey)
        if (!enabled) throw new Error('Nie udało się włączyć odblokowania odciskiem')
      }
      setPassword('')
      onDone?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Nie udało się odblokować sejfu')
    } finally {
      setBusy(false)
    }
  }

  async function submitNative() {
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      await vault.unlockWithNative()
      onDone?.()
    } catch (err) {
      setError(nativeErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const isDarkBase = theme === 'dark'

  const explainer = vault.unlocked
    ? 'Sejf jest odblokowany w tej sesji. Koszty zakupu mogą być odszyfrowane i użyte w marży.'
    : 'Odblokuj Sejf, żeby importować i widzieć koszty zakupu. Hasło zostaje w przeglądarce, serwer go nie zna.'

  return (
    <div className={`${mobile ? '' : 'border-t'} p-2 lg:p-3 ${isDarkBase ? 'border-white/10' : 'border-slate-200'}`}>
      <div className={`rounded-lg border p-2.5 ${
        isDarkBase ? 'border-white/10 bg-white/[0.04]' : 'border-slate-200 bg-slate-50'
      }`}>
      <div className="mb-2 flex items-center justify-center gap-2 lg:justify-between">
        <span className={`${mobile ? 'inline' : 'hidden lg:inline'} text-xs font-medium ${isDarkBase ? 'text-slate-300' : 'text-slate-600'}`}>
          Sejf finansowy
        </span>
        {vault.unlocked ? <Unlock size={15} className="text-emerald-300" /> : <Lock size={15} className="text-amber-300" />}
      </div>
      <p className={`mb-2 text-[11px] leading-snug ${isDarkBase ? 'text-slate-500' : 'text-slate-600'}`}>
        {explainer}
      </p>
      {vault.unlocked ? (
        <div className="space-y-2">
          <button
            type="button"
            onClick={() => {
              vault.lock()
              onDone?.()
            }}
            className="w-full rounded-md bg-emerald-400/15 px-3 py-2 text-xs font-medium text-emerald-200 hover:bg-emerald-400/20"
          >
            Zablokuj Sejf
          </button>
          {vault.nativeAvailable && (
            <div className={`flex items-center justify-between gap-2 text-[11px] leading-snug ${
              isDarkBase ? 'text-slate-500' : 'text-slate-600'
            }`}>
              <span className="flex items-center gap-1.5">
                <Fingerprint size={12} className="shrink-0 text-emerald-400" />
                Odblokowanie odciskiem włączone na tym urządzeniu
              </span>
              <button
                type="button"
                onClick={() => void vault.disableNativeUnlock()}
                className={`shrink-0 underline ${isDarkBase ? 'hover:text-slate-300' : 'hover:text-slate-950'}`}
              >
                Usuń zapamiętany klucz
              </button>
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          {vault.nativeAvailable && (
            <button
              type="button"
              onClick={submitNative}
              disabled={busy}
              className={`flex w-full items-center justify-center gap-2 rounded-md px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50 ${
                isDarkBase ? 'bg-emerald-400 text-ink-950' : 'bg-ink-950 text-white'
              }`}
            >
              <Fingerprint size={14} />
              {busy ? 'Pracuję...' : 'Odblokuj odciskiem'}
            </button>
          )}
          <form onSubmit={submit} className="space-y-2">
          <input
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            placeholder={vault.status?.configured ? 'Hasło finansowe' : 'Utwórz hasło finansowe'}
            autoComplete="current-password"
            className={`${mobile ? 'block' : 'hidden lg:block'} w-full rounded-md border px-2 py-1.5 text-xs outline-none placeholder:text-slate-500 focus:border-emerald-400 ${
              isDarkBase
                ? 'border-white/10 bg-ink-900 text-white'
                : 'border-slate-300 bg-white text-slate-950'
            }`}
          />
          <label className={`${mobile ? 'flex' : 'hidden lg:flex'} items-start gap-2 text-[11px] leading-snug ${
            isDarkBase ? 'text-slate-500' : 'text-slate-600'
          }`}>
            <input
              type="checkbox"
              checked={persist}
              onChange={e => setPersist(e.target.checked)}
              className="mt-0.5"
            />
            <span>Tryb wygodny: zapamiętaj po F5 przez 30 min</span>
          </label>
          {nativeSupported && (
            <label className={`${mobile ? 'flex' : 'hidden lg:flex'} items-start gap-2 text-[11px] leading-snug ${
              isDarkBase ? 'text-slate-500' : 'text-slate-600'
            }`}>
              <input
                type="checkbox"
                checked={enableNative}
                onChange={e => setEnableNative(e.target.checked)}
                className="mt-0.5"
              />
              <span>Odblokowuj odciskiem na tym urządzeniu</span>
            </label>
          )}
          {error && <p className="text-[11px] text-red-300">{error}</p>}
          <button
            type="submit"
            disabled={busy || !password}
            className={`w-full rounded-md px-3 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50 ${
              isDarkBase ? 'bg-emerald-400 text-ink-950' : 'bg-ink-950 text-white'
            }`}
          >
            {busy ? 'Pracuję...' : vault.status?.configured ? 'Odblokuj Sejf' : 'Utwórz Sejf'}
          </button>
          </form>
        </div>
      )}
      </div>
    </div>
  )
}
