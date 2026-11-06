import { Moon, Sun } from 'lucide-react'
import { useTheme } from '../context/ThemeContext'

export function PublicThemeToggle() {
  const { theme, setTheme } = useTheme()
  const isDarkBase = theme === 'dark'
  const nextTheme = isDarkBase ? 'light' : 'dark'
  return (
    <button
      type="button"
      onClick={() => setTheme(nextTheme)}
      className={`inline-flex items-center justify-center gap-2 rounded border px-3 py-1.5 text-sm font-medium transition ${
        isDarkBase
          ? 'border-slate-600 text-slate-200 hover:border-slate-400 hover:text-white'
          : 'border-slate-300 bg-white text-slate-700 hover:border-slate-500 hover:text-slate-950'
      }`}
      title={`Przełącz na ${isDarkBase ? 'tryb jasny' : 'tryb ciemny'}`}
    >
      {isDarkBase ? <Sun size={15} /> : <Moon size={15} />}
      <span>{isDarkBase ? 'Jasny' : 'Ciemny'}</span>
    </button>
  )
}
