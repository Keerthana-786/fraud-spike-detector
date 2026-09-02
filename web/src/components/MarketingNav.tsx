import { Menu, X } from 'lucide-react'
import { useState } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { Logo } from './ui'

const links = [
  { to: '/', label: 'Home' },
  { to: '/#how-it-works', label: 'How It Works' },
  { to: '/#features', label: 'Features' },
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/#pricing', label: 'Pricing' },
]

export function MarketingNav() {
  const [open, setOpen] = useState(false)
  return (
    <header className="sticky top-0 z-40 border-b border-line bg-white/95 shadow-nav backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
        <Logo />
        <nav className="hidden items-center gap-6 md:flex">
          {links.map((l) => (
            <a key={l.label} href={l.to} className="text-sm font-medium text-mute hover:text-navy">
              {l.label}
            </a>
          ))}
        </nav>
        <div className="hidden items-center gap-3 md:flex">
          <NavLink to="/dashboard" className="btn-outline !py-2 !text-sm">
            Open Dashboard
          </NavLink>
          <Link to="/login" className="btn-primary !py-2 !text-sm">
            Login
          </Link>
        </div>
        <button type="button" className="md:hidden" onClick={() => setOpen((v) => !v)} aria-label="Menu">
          {open ? <X /> : <Menu />}
        </button>
      </div>
      {open && (
        <div className="space-y-2 border-t border-line px-4 py-3 md:hidden">
          {links.map((l) => (
            <a key={l.label} href={l.to} className="block py-1 text-sm" onClick={() => setOpen(false)}>
              {l.label}
            </a>
          ))}
          <Link to="/dashboard" className="block py-1 text-sm" onClick={() => setOpen(false)}>
            Open Dashboard
          </Link>
          <Link to="/login" className="btn-primary mt-2 w-full" onClick={() => setOpen(false)}>
            Login
          </Link>
        </div>
      )}
    </header>
  )
}

export function MarketingFooter() {
  return (
    <footer className="border-t border-line bg-paper">
      <div className="mx-auto grid max-w-6xl gap-8 px-4 py-12 md:grid-cols-4">
        <div>
          <Logo />
          <p className="mt-3 text-sm text-gray-500">© 2026 SentinelPay Inc. All rights reserved.</p>
          <p className="mt-2 text-sm text-gray-500">hello@sentinelpay.io</p>
        </div>
        {[
          {
            title: 'Product',
            items: [
              ['/#features', 'Features'],
              ['/#pricing', 'Pricing'],
              ['/docs', 'Docs'],
              ['/#how-it-works', 'Status'],
            ],
          },
          {
            title: 'Company',
            items: [
              ['/#use-cases', 'About'],
              ['/#social', 'Blog'],
              ['/#cta', 'Careers'],
              ['mailto:hello@sentinelpay.io', 'Contact'],
            ],
          },
          {
            title: 'Legal',
            items: [
              ['/docs', 'Terms of Service'],
              ['/docs', 'Privacy Policy'],
              ['/docs', 'Security'],
              ['/docs', 'Compliance'],
            ],
          },
        ].map((col) => (
          <div key={col.title}>
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">{col.title}</p>
            <ul className="mt-3 space-y-2">
              {col.items.map(([href, label]) => (
                <li key={label}>
                  <a href={href} className="text-sm text-mute hover:text-navy">
                    {label}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </footer>
  )
}
