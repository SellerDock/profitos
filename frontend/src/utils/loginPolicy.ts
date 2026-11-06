import type { DeploymentMode } from './deploymentRoutes'

export function rejectOperatorOnUserLogin(mode: DeploymentMode, isOperatorLogin: boolean, isOperator: boolean): boolean {
  return mode === 'hosted' && !isOperatorLogin && isOperator
}
