import { createContext, useContext, useEffect } from 'react'
import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { buildApiUrl } from '../api/client'
import { setBrandConfig } from '../config/brand'
import type { BrandConfig } from '../config/brand'
import { loadAnalytics } from '../utils/analytics'
import type { AnalyticsConfig } from '../utils/analytics'
import type { DeploymentMode } from '../utils/deploymentRoutes'

export interface AppConfig {
  deployment_mode: DeploymentMode
  brand: BrandConfig
  analytics: AnalyticsConfig
}

const defaultConfig: AppConfig = {
  deployment_mode: 'selfhosted',
  brand: { product_name: 'ProfitOS', support_email: null, public_site_url: null, app_url: null },
  analytics: { ga_id: null, ahrefs_key: null },
}
const DeploymentContext = createContext<AppConfig>(defaultConfig)

export function DeploymentProvider({ children }: { children: ReactNode }) {
  const { data, isPending } = useQuery({
    queryKey: ['public-config'],
    queryFn: async (): Promise<AppConfig> => {
      const response = await fetch(buildApiUrl('/public/config'))
      if (!response.ok) throw new Error('Unable to load deployment configuration')
      const config = await response.json()
      if (config.deployment_mode !== 'hosted' && config.deployment_mode !== 'selfhosted') {
        throw new Error('Invalid deployment mode')
      }
      return config
    },
    staleTime: Infinity,
    retry: 2,
  })
  useEffect(() => { if (data) loadAnalytics(data.analytics) }, [data])
  if (isPending) return null
  const config = data ?? defaultConfig
  setBrandConfig(config.brand)
  return <DeploymentContext.Provider value={config}>{children}</DeploymentContext.Provider>
}

export function useAppConfig(): AppConfig { return useContext(DeploymentContext) }
export function useDeploymentMode(): DeploymentMode { return useAppConfig().deployment_mode }
