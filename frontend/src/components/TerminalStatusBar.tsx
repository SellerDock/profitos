import { useEffect, useState } from 'react'
import { useFinancialVault } from '../context/FinancialVaultContext'
import { THEME_NAME, useTheme } from '../context/ThemeContext'

function useNowHHMMSS() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(id)
  }, [])
  return now.toLocaleTimeString('pl-PL', { hour12: false })
}

export default function TerminalStatusBar() {
  const vault = useFinancialVault()
  const { theme } = useTheme()
  const time = useNowHHMMSS()

  const vaultLabel = vault.unlocked
    ? 'sejf odblokowany'
    : vault.status?.configured
      ? 'sejf zablokowany'
      : 'sejf nieustawiony'
  const vaultDot = vault.unlocked
    ? 'bg-[#8aa05c]'
    : vault.status?.configured
      ? 'bg-[#d4a13b]'
      : 'bg-[#c66a3d]'

  return (
    <footer
      className="hidden border-t border-[rgba(255,240,210,0.08)] bg-[#1a1714] px-4 py-1.5 font-mono text-[11px] text-[#a89a86] lg:flex lg:items-center lg:gap-4"
      aria-label="terminal status"
      data-terminal-status
    >
      <span className="flex items-center gap-1.5">
        <span className={`inline-block h-1.5 w-1.5 rounded-full ${vaultDot}`} />
        {vaultLabel}
      </span>
      <span className="opacity-50">·</span>
      <span>motyw {THEME_NAME[theme]}</span>
      <span className="ml-auto tabular-nums">{time}</span>
    </footer>
  )
}
