import { Shield } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

export function Logo({ to = '/', light = false }: { to?: string; light?: boolean }) {
  return (
    <Link to={to} className="flex items-center gap-2">
      <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-navy text-white">
        <Shield size={18} />
      </span>
      <span className={`font-display text-lg font-extrabold tracking-tight ${light ? 'text-white' : 'text-navy'}`}>
        SentinelPay
      </span>
    </Link>
  )
}

export function Badge({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <span className={`inline-flex rounded px-2 py-1 text-xs font-medium ${className}`}>{children}</span>
  )
}

export function Toast({
  message,
  type,
  onClose,
}: {
  message: string
  type: 'success' | 'error' | 'warning' | 'info'
  onClose: () => void
}) {
  const color =
    type === 'success'
      ? 'bg-emerald-600'
      : type === 'error'
        ? 'bg-red-600'
        : type === 'warning'
          ? 'bg-amber-500'
          : 'bg-blue-600'
  return (
    <div className={`fixed right-4 top-4 z-50 rounded-md px-4 py-3 text-sm text-white shadow-lift ${color}`}>
      <div className="flex items-start gap-3">
        <p>{message}</p>
        <button type="button" onClick={onClose} className="opacity-80 hover:opacity-100">
          ×
        </button>
      </div>
    </div>
  )
}

export function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-lg border border-dashed border-line p-8 text-center">
      <p className="font-display text-lg font-semibold">{title}</p>
      <p className="mt-1 text-sm text-gray-500">{body}</p>
    </div>
  )
}
