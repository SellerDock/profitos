import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Smartphone, X } from 'lucide-react'
import { appDownloadApi } from '../api/client'
import { useTheme } from '../context/ThemeContext'
import { APP_VERSION, IS_APP } from '../utils/isApp'
import { isNewerVersion } from '../utils/semver'

// Discreet banner shown only inside the Android WebView when the published
// manifest advertises a semantically newer app version than the one in the UA.
// Fails silent: any manifest error (404, network) means no banner.
export default function AppUpdateBanner() {
  const { theme } = useTheme()
  const [dismissed, setDismissed] = useState(false)

  const enabled = IS_APP && APP_VERSION !== null
  const { data: manifest } = useQuery({
    queryKey: ['app', 'manifest'],
    queryFn: appDownloadApi.manifest,
    enabled,
    retry: false,
    staleTime: 10 * 60 * 1000,
  })

  if (!IS_APP || !APP_VERSION || dismissed || !manifest) return null
  if (!isNewerVersion(manifest.version, APP_VERSION)) return null

  const isDarkBase = theme === 'dark'

  return (
    <div className={`mb-4 flex items-center gap-2 rounded-lg border px-3 py-2 text-xs ${
      isDarkBase ? 'border-white/10 bg-white/[0.04] text-slate-300' : 'border-slate-200 bg-slate-50 text-slate-700'
    }`}>
      <Smartphone size={14} className="shrink-0 text-emerald-500" />
      <p className="min-w-0 flex-1 leading-snug">
        Dostępna nowa wersja aplikacji{' '}
        <Link
          to="/pobierz"
          className="font-semibold text-emerald-500 underline underline-offset-2 hover:text-emerald-400"
        >
          Pobierz
        </Link>
      </p>
      <button
        type="button"
        onClick={() => setDismissed(true)}
        aria-label="Zamknij powiadomienie"
        className={`shrink-0 rounded-md p-1 ${
          isDarkBase ? 'text-slate-400 hover:bg-white/10 hover:text-white' : 'text-slate-500 hover:bg-slate-100 hover:text-slate-950'
        }`}
      >
        <X size={14} />
      </button>
    </div>
  )
}
