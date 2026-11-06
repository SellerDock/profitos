import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { billingApi } from '../api/client'
import { useDeploymentMode } from '../context/DeploymentContext'
import { subscriptionBanner } from '../utils/subscription'

export default function SubscriptionBanner() {
  const mode = useDeploymentMode()
  const [closed, setClosed] = useState(() => { try { return sessionStorage.getItem('subscription-banner-closed') === '1' } catch { return false } })
  const { data } = useQuery({ queryKey: ['billing-subscription'], queryFn: billingApi.subscription, enabled: mode === 'hosted' && !closed })
  const message = data?.billing_scheme === 'pool_v2' ? subscriptionBanner(data.usage) : null
  if (!message || closed) return null
  return <div className="mb-4 flex flex-wrap items-center gap-3 rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
    <span className="min-w-0 flex-1">{message} <Link className="font-semibold underline" to="/subscription">Pakiety</Link></span>
    <button type="button" aria-label="Zamknij komunikat" onClick={() => { setClosed(true); try { sessionStorage.setItem('subscription-banner-closed', '1') } catch { /* niedostępna pamięć sesji */ } }}>✕</button>
  </div>
}
