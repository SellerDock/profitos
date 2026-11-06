import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import { DeploymentProvider } from './context/DeploymentContext'
import './index.css'
import { CRYPTO_BUNDLE_SHA256, CRYPTO_VERSION } from './crypto/CRYPTO_PIN'
import { ThemeProvider } from './context/ThemeContext'
import { FinancialDisplayModeProvider } from './context/FinancialDisplayModeContext'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 10 * 60 * 1000,
      refetchOnWindowFocus: false,
    },
  },
})

if (!window.ProfitOSCrypto) {
  document.body.innerHTML = `
    <div style="font-family:sans-serif;padding:2rem;max-width:48rem;margin:auto">
      <h1>Moduł szyfrujący nie załadował się</h1>
      <p>Najczęstsza przyczyna: integralność (SRI) skryptu nie pasuje
      do oczekiwanego SHA-384. To zabezpieczenie — przeglądarka odmówiła
      uruchomienia zmodyfikowanego pliku.</p>
      <p>Spróbuj odświeżyć stronę.</p>
      <p><small>Oczekiwana wersja: ${CRYPTO_VERSION} · SHA-256: ${CRYPTO_BUNDLE_SHA256}</small></p>
    </div>`
  throw new Error('ProfitOSCrypto missing')
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ThemeProvider>
          <FinancialDisplayModeProvider>
            <DeploymentProvider>
              <App />
            </DeploymentProvider>
          </FinancialDisplayModeProvider>
        </ThemeProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
)
