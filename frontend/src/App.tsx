import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import Layout from './components/Layout'
import { PublicSecurityLayout } from './components/PublicSecurityLayout'
import { RequireAuth } from './components/RequireAuth'
import Dashboard from './pages/Dashboard'
import Import from './pages/Import'
import Products from './pages/Products'
import AdsImport from './pages/AdsImport'
import Stock from './pages/Stock'
import Orders from './pages/Orders'
import Settings from './pages/Settings'
import Subscription from './pages/Subscription'
import Security from './pages/Security'
import Landing from './pages/Landing'
import Login from './pages/Login'
import Waitlist from './pages/Waitlist'
import Activate from './pages/Activate'
import Privacy from './pages/Privacy'
import Terms from './pages/Terms'
import Pobierz from './pages/Pobierz'
import AdminLayout from './pages/admin/AdminLayout'
import AdminWaitlist from './pages/admin/AdminWaitlist'
import AdminTenants from './pages/admin/AdminTenants'
import AdminRevenue from './pages/admin/AdminRevenue'
import AdminSubscriptions from './pages/admin/AdminSubscriptions'
import AdminHealth from './pages/admin/AdminHealth'
import { AuthProvider, useAuth } from './context/AuthContext'
import { FinancialVaultProvider } from './context/FinancialVaultContext'
import { FullScreenSpinner } from './components/RequireAuth'
import { isAppHost } from './config/brand'
import { CookieNotice } from './components/CookieNotice'
import { useDeploymentMode } from './context/DeploymentContext'
import { isDeploymentRouteVisible } from './utils/deploymentRoutes'

function ProtectedApp() {
  return (
    <RequireAuth>
      <FinancialVaultProvider>
        <Layout />
      </FinancialVaultProvider>
    </RequireAuth>
  )
}

function OperatorApp() {
  return (
    <RequireAuth operator loginPath="/admiiii123">
      <FinancialVaultProvider>
        <Layout />
      </FinancialVaultProvider>
    </RequireAuth>
  )
}

function Home() {
  const { user, loading } = useAuth()
  if (loading) return <FullScreenSpinner />
  if (user) return <Navigate to="/dashboard" replace />
  if (isAppHost()) return <Navigate to="/login" replace />
  return <Landing />
}

function SecurityPage() {
  const { user, loading } = useAuth()
  if (loading) return <FullScreenSpinner />
  if (user) {
    return (
      <FinancialVaultProvider>
        <Layout>
          <Security />
        </Layout>
      </FinancialVaultProvider>
    )
  }
  return (
    <PublicSecurityLayout>
      <Security />
    </PublicSecurityLayout>
  )
}

export default function App() {
  const mode = useDeploymentMode()
  const { pathname } = useLocation()
  if (!isDeploymentRouteVisible(pathname, mode)) return <Navigate to="/" replace />

  return (
    <AuthProvider>
      <Routes>
        <Route index element={mode === 'selfhosted' ? <Navigate to="/dashboard" replace /> : <Home />} />
        <Route path="register" element={<Waitlist />} />
        <Route path="login" element={<Login />} />
        <Route path="admiiii123" element={<Login mode="operator" />} />
        <Route path="activate" element={<Activate />} />
        <Route path="security" element={<SecurityPage />} />
        <Route path="privacy" element={<Privacy />} />
        <Route path="terms" element={<Terms />} />
        <Route path="regulamin" element={<Navigate to="/terms" replace />} />
        <Route path="pobierz" element={<Pobierz />} />

        <Route element={<ProtectedApp />}>
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="import" element={<Import />} />
          <Route path="ads-import" element={<AdsImport />} />
          <Route path="sku-mapping" element={<Navigate to="/settings" replace />} />
          <Route path="products" element={<Products />} />
          <Route path="ads" element={<Navigate to="/ads-import" replace />} />
          <Route path="stock" element={<Stock />} />
          <Route path="orders" element={<Orders />} />
          <Route path="subscription" element={<Subscription />} />
          <Route path="settings" element={<Settings />} />
        </Route>

        <Route element={<OperatorApp />}>
          <Route path="admin" element={<AdminLayout />}>
            <Route index element={<Navigate to="/admin/waitlist" replace />} />
            <Route path="waitlist" element={<AdminWaitlist />} />
            <Route path="tenants" element={<AdminTenants />} />
            <Route path="revenue" element={<AdminRevenue />} />
            <Route path="subscriptions" element={<AdminSubscriptions />} />
            <Route path="health" element={<AdminHealth />} />
            <Route path="system-health" element={<Navigate to="/admin/health" replace />} />
          </Route>
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <CookieNotice />
    </AuthProvider>
  )
}
