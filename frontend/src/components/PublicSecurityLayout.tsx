import { Outlet, Link } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useAuth } from '../context/AuthContext'
import { useDeploymentMode } from '../context/DeploymentContext'
import { PublicThemeToggle } from './PublicThemeToggle'
import { productName, supportEmail, appUrl, SOURCE_REPO_URL } from '../config/brand'
import { BrandLogo } from './BrandLogo'
import { IS_APP } from '../utils/isApp'

export function PublicSecurityLayout({ children }: { children?: ReactNode }) {
  const { user, logout } = useAuth()
  const mode = useDeploymentMode()

  return (
    <div className="public-theme min-h-screen bg-slate-900 text-slate-100">
      {!IS_APP && (
        <header className="border-b border-slate-800 bg-slate-950/70">
          <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-5 py-4">
            <Link to="/" className="flex items-center gap-2 text-sm font-semibold text-white">
              <BrandLogo markClassName="h-8 w-8" textClassName="text-sm font-semibold" label={`${productName()} – bezpieczeństwo`} />
            </Link>
            <nav className="flex flex-wrap items-center justify-end gap-x-3 gap-y-2 text-sm text-slate-300">
              <PublicThemeToggle />
              <Link to="/pobierz" className="hover:text-white">Aplikacja</Link>
              {mode === 'hosted' && <Link to="/register" className="hover:text-white">Rozpocznij</Link>}
              {user ? (
                <>
                  <a href={appUrl('/dashboard')} className="hover:text-white">Panel</a>
                  <button type="button" onClick={() => void logout()} className="hover:text-white">
                    Wyloguj
                  </button>
                </>
              ) : (
                <a href={appUrl('/login')} className="rounded bg-indigo-600 px-3 py-1.5 text-white hover:bg-indigo-500">
                  Zaloguj
                </a>
              )}
            </nav>
          </div>
        </header>
      )}
      <main className="mx-auto max-w-5xl px-5 py-10">
        {children ?? <Outlet />}
      </main>
      {!IS_APP && (
        <footer className="border-t border-slate-800">
          <div className="mx-auto flex max-w-5xl flex-wrap gap-4 px-5 py-6 text-sm text-slate-400">
            {mode === 'hosted' && <><Link to="/privacy" className="hover:text-white">Polityka prywatności</Link>
            <Link to="/terms" className="hover:text-white">Regulamin</Link></>}
            <Link to="/security" className="hover:text-white">Bezpieczeństwo</Link>
            <Link to="/pobierz" className="hover:text-white">Aplikacja Android</Link>
            <a href={SOURCE_REPO_URL} target="_blank" rel="noopener noreferrer" className="hover:text-white">Kod źródłowy (AGPL-3.0)</a>
            {supportEmail() && <a href={`mailto:${supportEmail()}`} className="hover:text-white">{supportEmail()}</a>}
          </div>
        </footer>
      )}
    </div>
  )
}
