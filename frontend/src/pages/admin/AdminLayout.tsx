import { NavLink, Outlet } from 'react-router-dom'
import { Activity, Building2, ClipboardList, Coins } from 'lucide-react'
import { useDeploymentMode } from '../../context/DeploymentContext'
import { isDeploymentRouteVisible } from '../../utils/deploymentRoutes'

const tabs = [
  { to: '/admin/waitlist', label: 'Zgłoszenia', icon: ClipboardList },
  { to: '/admin/tenants', label: 'Konta', icon: Building2 },
  { to: '/admin/revenue', label: 'Przychody', icon: Coins },
  { to: '/admin/health', label: 'System', icon: Activity },
]

export default function AdminLayout() {
  const mode = useDeploymentMode()
  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div>
        <p className="text-sm font-medium text-indigo-300">Panel operatora</p>
        <h1 className="mt-1 text-2xl font-bold text-white">Administracja</h1>
      </div>
      <div className="flex flex-wrap gap-2 border-b border-slate-700 pb-3">
        {tabs.filter(tab => isDeploymentRouteVisible(tab.to, mode)).map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `inline-flex items-center gap-2 rounded px-3 py-2 text-sm ${
                isActive ? 'bg-indigo-600 text-white' : 'text-slate-300 hover:bg-slate-800 hover:text-white'
              }`
            }
          >
            <Icon size={16} />
            {label}
          </NavLink>
        ))}
      </div>
      <Outlet />
    </div>
  )
}
