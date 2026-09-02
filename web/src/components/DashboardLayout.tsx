import {
  BarChart3,
  Bell,
  Cpu,
  CreditCard,
  DollarSign,
  FileText,
  LayoutDashboard,
  LifeBuoy,
  LogOut,
  Menu,
  Radio,
  Search,
  Settings,
  ShieldAlert,
  ShieldCheck,
  Users,
  X,
  Zap,
} from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { Link, Navigate, NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import { api, type Alert } from '../lib/api'
import { Logo } from './ui'

interface NavItem {
  to: string
  label: string
  icon: any
  end?: boolean
  adminOnly?: boolean
}

interface NavGroup {
  group: string
  items: NavItem[]
}

const navGroups: NavGroup[] = [
  {
    group: 'Monitor',
    items: [
      { to: '/dashboard', label: 'Overview', icon: LayoutDashboard, end: true },
      { to: '/dashboard/transactions', label: 'Live Transactions', icon: CreditCard },
      { to: '/dashboard/incidents', label: 'Incidents & Alerts', icon: ShieldAlert },
    ],
  },
  {
    group: 'Investigate',
    items: [
      { to: '/dashboard/financial', label: 'Financial Impact', icon: DollarSign },
    ],
  },
  {
    group: 'Configure',
    items: [
      { to: '/dashboard/simulator', label: 'Pipeline Simulator', icon: Zap },
      { to: '/dashboard/razorpay', label: 'Razorpay Test Mode', icon: Radio },
      { to: '/dashboard/model-performance', label: 'Model Performance', icon: BarChart3 },
      { to: '/dashboard/model-health', label: 'Model Health', icon: Cpu },
    ],
  },
  {
    group: 'Manage',
    items: [
      { to: '/dashboard/notifications', label: 'Notifications', icon: Bell },
      { to: '/dashboard/audit-logs', label: 'Audit Logs', icon: FileText },
      { to: '/dashboard/system-health', label: 'System Health', icon: ShieldCheck },
      { to: '/dashboard/users', label: 'Users', icon: Users, adminOnly: true },
      { to: '/dashboard/settings', label: 'Settings', icon: Settings, adminOnly: true },
      { to: '/dashboard/docs', label: 'Documentation', icon: LifeBuoy },
    ],
  },
]

export function DashboardLayout() {
  const { user, loading, logout } = useAuth()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [bell, setBell] = useState(false)
  const [query, setQuery] = useState('')
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [notifications, setNotifications] = useState<Array<{ id: number; alert_id: string; recipient: string; channel: string; status: string; sent_at: string }>>([])

  useEffect(() => {
    api
      .alerts()
      .then((rows) => setAlerts(rows.filter((a) => a.status === 'INVESTIGATING' || a.status === 'CONFIRMED_FRAUD' || a.status === 'ACTIVE')))
      .catch(() => setAlerts([]))
    api
      .notifications(10)
      .then(setNotifications)
      .catch(() => setNotifications([]))
  }, [bell])

  if (loading) return <div className="min-h-svh bg-[#0A0F1E]" aria-busy="true" />
  if (!user) return <Navigate to="/login" replace />

  const isAdmin = user.role === 'Merchant Admin' || user.role === 'ADMIN' || user.role === 'admin'
  const isFinance = user.role === 'Finance Manager'
  const count = alerts.length

  return (
    <div className="min-h-svh bg-[#0A0F1E] text-[#E2E8F0] font-sans antialiased">
      {/* Enterprise Top Navigation Bar */}
      <header className="sticky top-0 z-30 flex items-center justify-between border-b border-[#1E293B] bg-[#0F172A]/90 backdrop-blur-md px-4 py-2.5">
        <div className="flex items-center gap-3">
          <button type="button" className="lg:hidden text-gray-400 hover:text-white" onClick={() => setOpen((v) => !v)}>
            {open ? <X size={20} /> : <Menu size={20} />}
          </button>
          <Logo to="/dashboard" />
          
          {/* Always-Visible TEST MODE Badge */}
          <div className="hidden sm:flex items-center gap-1.5 rounded-full border border-amber-500/40 bg-amber-500/10 px-2.5 py-0.5 text-[11px] font-mono font-bold uppercase tracking-wider text-amber-400">
            <span className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-pulse" />
            TEST MODE
          </div>
        </div>

        {/* Global Trace & Search Bar */}
        <div className="hidden max-w-md flex-1 px-6 md:block">
          <label className="relative block">
            <Search className="absolute left-3 top-2.5 text-gray-400" size={15} />
            <input
              className="input !py-1.5 !pl-9 text-xs w-full bg-[#141B2E] border-[#1E293B] focus:border-[#3B82F6]"
              placeholder="Search by Transaction ID (e.g. pay_...) or Incident ID..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && query.trim()) {
                  navigate(`/dashboard/incidents?q=${encodeURIComponent(query.trim())}`)
                }
              }}
            />
          </label>
        </div>

        {/* Right Chrome: Notifications & Profile */}
        <div className="flex items-center gap-3">
          <button
            type="button"
            className="relative rounded-md p-2 hover:bg-[#141B2E] text-gray-300 hover:text-white transition"
            onClick={() => setBell((v) => !v)}
            title="Notification Center"
          >
            <Bell size={18} />
            {count > 0 && (
              <span className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-[#EF4444] px-1 text-[10px] font-bold text-white">
                {count}
              </span>
            )}
          </button>

          <div className="hidden text-right text-xs sm:block border-l border-[#1E293B] pl-3">
            <strong className="block text-[#F1F5F9] font-medium">{user.name}</strong>
            <span className="text-gray-400 text-[11px]">{user.role}</span>
          </div>
        </div>
      </header>

      {/* Notification Center Dropdown */}
      {bell && (
        <div className="absolute right-4 top-14 z-50 w-96 rounded-xl border border-[#1E293B] bg-[#0F172A] p-4 shadow-2xl">
          <div className="mb-3 flex items-center justify-between border-b border-[#1E293B] pb-2">
            <p className="text-xs font-bold uppercase tracking-wider text-gray-300">Notification Center</p>
            <span className="badge-info text-[11px]">{count} Active</span>
          </div>

          <p className="text-[11px] font-semibold uppercase tracking-wider text-gray-400 mb-1.5">Spike Anomaly Incidents</p>
          <div className="space-y-1.5 mb-3">
            {alerts.slice(0, 3).map((a) => (
              <Link
                key={a.alert_id}
                to={`/dashboard/incidents/${a.alert_id}`}
                className="flex items-center justify-between rounded-lg bg-[#141B2E] p-2 text-xs hover:border hover:border-teal transition"
                onClick={() => setBell(false)}
              >
                <div>
                  <span className="font-mono font-bold text-critical">{a.alert_id}</span>
                  <span className="block text-[11px] text-gray-400">
                    {(a.current_rate * 100).toFixed(1)}% density · {a.affected_transactions} txns
                  </span>
                </div>
                <span className="badge-critical !text-[10px]">{a.severity}</span>
              </Link>
            ))}
            {!alerts.length && <p className="text-xs text-gray-500 py-1">No active incidents.</p>}
          </div>

          <p className="text-[11px] font-semibold uppercase tracking-wider text-gray-400 mb-1.5">Dispatch History</p>
          <div className="space-y-1.5 max-h-40 overflow-y-auto">
            {notifications.slice(0, 3).map((n) => (
              <div key={n.id} className="rounded-lg bg-[#141B2E] p-2 text-xs">
                <div className="flex justify-between items-center">
                  <span className="font-medium text-gray-300 truncate max-w-[180px]">{n.recipient}</span>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${n.status === 'SENT' ? 'bg-success/20 text-success' : 'bg-gray-700 text-gray-300'}`}>
                    {n.status}
                  </span>
                </div>
                <p className="text-[10px] text-gray-500 mt-0.5">Alert: {n.alert_id} · Channel: {n.channel}</p>
              </div>
            ))}
            {!notifications.length && <p className="text-xs text-gray-500 py-1">No dispatches logged.</p>}
          </div>
        </div>
      )}

      {/* Main Layout Grid */}
      <div className="mx-auto flex max-w-[1536px]">
        {/* Persistent Enterprise Sidebar */}
        <aside
          className={`${open ? 'block fixed inset-y-0 left-0 z-40' : 'hidden'} w-64 shrink-0 border-r border-[#1E293B] bg-[#0F172A] lg:block`}
        >
          <nav className="flex h-[calc(100svh-53px)] flex-col p-3 overflow-y-auto">
            {navGroups.map((grp) => {
              const visibleItems = grp.items.filter((item) => {
                if (item.adminOnly && !isAdmin) return false
                if (isFinance && (item.label === 'Simulator' || item.label === 'Users')) return false
                return true
              })

              if (!visibleItems.length) return null

              return (
                <div key={grp.group} className="mb-4">
                  <p className="px-3 text-[10px] font-bold uppercase tracking-wider text-gray-400 mb-1">
                    {grp.group}
                  </p>
                  <div className="space-y-0.5">
                    {visibleItems.map((item) => (
                      <NavLink
                        key={item.to}
                        to={item.to}
                        end={item.end}
                        className={({ isActive }) =>
                          `flex items-center gap-2.5 rounded-lg px-3 py-2 text-xs font-medium transition ${
                            isActive
                              ? 'bg-[#3B82F6]/15 text-[#3B82F6] font-semibold border border-[#3B82F6]/30'
                              : 'text-gray-400 hover:bg-[#141B2E] hover:text-white'
                          }`
                        }
                        onClick={() => setOpen(false)}
                      >
                        <item.icon size={15} />
                        <span>{item.label}</span>
                        {item.label.includes('Incidents') && count > 0 && (
                          <span className="ml-auto rounded-full bg-[#EF4444] px-1.5 py-0.2 text-[10px] font-bold text-white">
                            {count}
                          </span>
                        )}
                      </NavLink>
                    ))}
                  </div>
                </div>
              )
            })}

            {/* Bottom User & Workspace Footer */}
            <div className="mt-auto border-t border-[#1E293B] pt-3">
              <div className="rounded-lg bg-[#141B2E] p-2.5 text-xs">
                <p className="font-semibold text-white truncate">{user.organization || 'Merchant Workspace'}</p>
                <span className="inline-block mt-1 text-[10px] text-gray-400 bg-gray-800 px-1.5 py-0.5 rounded font-mono">
                  {user.role}
                </span>
              </div>
              <button
                type="button"
                className="mt-2 flex w-full items-center gap-2 rounded-lg px-3 py-2 text-xs text-gray-400 hover:bg-[#141B2E] hover:text-critical transition"
                onClick={() => {
                  logout()
                  navigate('/login')
                }}
              >
                <LogOut size={14} /> Sign out
              </button>
            </div>
          </nav>
        </aside>

        {/* Main Content Area */}
        <main className="min-w-0 flex-1 p-4 md:p-6 lg:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

export function PageHeader({
  title,
  subtitle,
  children,
}: {
  title: string
  subtitle?: string
  children?: ReactNode
}) {
  return (
    <div className="mb-6 flex flex-wrap items-center justify-between gap-3 border-b border-[#1E293B] pb-4">
      <div>
        <h1 className="text-xl md:text-2xl font-bold tracking-tight text-white">{title}</h1>
        {subtitle && <p className="mt-1 text-xs text-gray-400">{subtitle}</p>}
      </div>
      {children}
    </div>
  )
}
