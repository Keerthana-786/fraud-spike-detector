import { useState, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Eye, EyeOff, Lock, Mail, Shield, Lock as LockIcon } from 'lucide-react'
import { Toast } from '../components/ui'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'

export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [remember, setRemember] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await login(email, password, remember)
      navigate('/dashboard')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'We couldn\'t sign you in right now. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-container">
      {error && <Toast message={error} type="error" onClose={() => setError('')} />}
      
      <div className="auth-card">
        {/* Logo Section */}
        <div className="logo-wrapper">
          <div className="logo-icon">
            <Shield size={40} />
          </div>
          <div className="logo-text">SentinelPay</div>
        </div>

        {/* Title and Subtitle */}
        <h1 className="auth-title">Access Your Account</h1>
        <p className="auth-subtitle">Secure, encrypted connection to your risk management center</p>

        {/* Login Form */}
        <form onSubmit={handleSubmit} className="space-y-5">
          {/* Email Field */}
          <div className="form-group">
            <label className="form-label" htmlFor="email">Email Address</label>
            <div className="input-wrapper">
              <Mail size={18} className="input-icon" />
              <input
                id="email"
                className="auth-input"
                type="email"
                placeholder="your@email.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                disabled={busy}
              />
            </div>
          </div>

          {/* Password Field */}
          <div className="form-group">
            <label className="form-label" htmlFor="password">Password</label>
            <div className="input-wrapper">
              <LockIcon size={18} className="input-icon" />
              <input
                id="password"
                className="auth-input"
                type={showPassword ? 'text' : 'password'}
                placeholder="Enter your password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                disabled={busy}
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="input-eye-button"
                disabled={busy}
              >
                {showPassword ? (
                  <EyeOff size={18} className="input-icon-right" />
                ) : (
                  <Eye size={18} className="input-icon-right" />
                )}
              </button>
            </div>
          </div>

          {/* Remember and Forgot Password */}
          <div className="form-row">
            <label className="flex items-center gap-2 text-xs">
              <input
                type="checkbox"
                checked={remember}
                onChange={(e) => setRemember(e.target.checked)}
                disabled={busy}
                className="rounded border-gold/20 bg-charcoal-light accent-gold"
              />
              <span className="text-gray-400">Remember me</span>
            </label>
            <Link to="/forgot-password" className="forgot-password-link">
              Forgot password?
            </Link>
          </div>

          {/* Login Button */}
          <button
            type="submit"
            className="btn-login"
            disabled={busy}
          >
            {busy ? 'Signing in...' : 'Log In'}
          </button>
        </form>

        {/* Security Indicator */}
        <div className="security-indicator">
          <Lock size={16} className="security-icon" />
          <span>🔒 Secure encrypted connection</span>
        </div>

        {/* Loading Bar */}
        {busy && <div className="loading-bar mt-4" />}

        {/* Footer */}
        <div className="auth-footer">
          <p className="auth-footer-text">
            New here?{' '}
            <Link to="/signup" className="auth-footer-link">
              Create an account
            </Link>
          </p>
        </div>
      </div>
    </div>
  )
}

export function SignupPage() {
  const navigate = useNavigate()
  const [form, setForm] = useState({
    full_name: '',
    email: '',
    organization: '',
    role: 'Risk Analyst',
    password: '',
    confirm_password: '',
    terms_accepted: false,
  })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const set = (key: keyof typeof form, value: string | boolean) => setForm((f) => ({ ...f, [key]: value }))

  return (
    <AuthShell title="Create Your Account" subtitle="Start monitoring payment risk with AI-powered spike detection.">
      {error && <Toast message={error} type="error" onClose={() => setError('')} />}
      <form
        className="space-y-4"
        onSubmit={async (e) => {
          e.preventDefault()
          setBusy(true)
          setError('')
          try {
            const res = await api.register({
              full_name: form.full_name,
              email: form.email,
              organization: form.organization,
              role: form.role,
              password: form.password,
              confirm_password: form.confirm_password,
              terms_accepted: form.terms_accepted,
              agree_terms: form.terms_accepted,
            })
            navigate('/login', { state: { message: res.message } })
          } catch (err) {
            setError(err instanceof Error ? err.message : 'Signup failed.')
          } finally {
            setBusy(false)
          }
        }}
      >
        <div className="form-group">
          <label className="form-label" htmlFor="full_name">Full Name</label>
          <div className="input-wrapper">
            <Mail size={18} className="input-icon" />
            <input
              id="full_name"
              className="auth-input"
              placeholder="Your full name"
              value={form.full_name}
              onChange={(e) => set('full_name', e.target.value)}
              required
              disabled={busy}
            />
          </div>
        </div>

        <div className="form-group">
          <label className="form-label" htmlFor="role">What's your role at the company?</label>
          <select id="role" className="auth-input !px-3" value={form.role} onChange={(e) => set('role', e.target.value)} disabled={busy}>
            <option value="Risk Analyst">Risk Analyst</option>
            <option value="Finance Manager">Finance Manager</option>
            <option value="Operations Manager">Operations Manager</option>
          </select>
          <p className="mt-2 text-xs text-gray-400">Need administrator access? Ask an existing admin to promote your account after signup.</p>
        </div>

        <div className="form-group">
          <label className="form-label" htmlFor="email">Work Email</label>
          <div className="input-wrapper">
            <Mail size={18} className="input-icon" />
            <input
              id="email"
              className="auth-input"
              type="email"
              placeholder="your@company.com"
              value={form.email}
              onChange={(e) => set('email', e.target.value)}
              required
              disabled={busy}
            />
          </div>
        </div>

        <div className="form-group">
          <label className="form-label" htmlFor="organization">Organization</label>
          <div className="input-wrapper">
            <Mail size={18} className="input-icon" />
            <input
              id="organization"
              className="auth-input"
              placeholder="Company name"
              value={form.organization}
              onChange={(e) => set('organization', e.target.value)}
              required
              disabled={busy}
            />
          </div>
        </div>

        <div className="form-group">
          <label className="form-label" htmlFor="password">Password</label>
          <div className="input-wrapper">
            <LockIcon size={18} className="input-icon" />
            <input
              id="password"
              className="auth-input"
              type="password"
              placeholder="Min 8 characters"
              value={form.password}
              onChange={(e) => set('password', e.target.value)}
              required
              disabled={busy}
            />
          </div>
        </div>

        <div className="form-group">
          <label className="form-label" htmlFor="confirm_password">Confirm Password</label>
          <div className="input-wrapper">
            <LockIcon size={18} className="input-icon" />
            <input
              id="confirm_password"
              className="auth-input"
              type="password"
              placeholder="Confirm your password"
              value={form.confirm_password}
              onChange={(e) => set('confirm_password', e.target.value)}
              required
              disabled={busy}
            />
          </div>
        </div>

        <label className="flex items-start gap-2 text-xs">
          <input
            type="checkbox"
            className="mt-1 rounded border-gold/20 bg-charcoal-light accent-gold"
            checked={form.terms_accepted}
            onChange={(e) => set('terms_accepted', e.target.checked)}
            disabled={busy}
          />
          <span className="text-gray-400">
            I agree to the Terms of Service and Privacy Policy.
          </span>
        </label>

        <button className="btn-login" type="submit" disabled={busy}>
          {busy ? 'Creating account...' : 'Create Account'}
        </button>
      </form>

      <div className="auth-footer">
        <p className="auth-footer-text">
          Already have an account?{' '}
          <Link to="/login" className="auth-footer-link">
            Sign In
          </Link>
        </p>
      </div>
    </AuthShell>
  )
}

export function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  return (
    <AuthShell title="Reset Your Password" subtitle="Enter your email to receive recovery instructions.">
      {error && <Toast message={error} type="error" onClose={() => setError('')} />}
      {message && <Toast message={message} type="info" onClose={() => setMessage('')} />}
      <form
        className="space-y-5"
        onSubmit={async (e) => {
          e.preventDefault()
          setBusy(true)
          setError('')
          try {
            const res = await api.forgotPassword(email)
            setMessage(res.message)
          } catch (err) {
            setError(err instanceof Error ? err.message : 'Request failed.')
          } finally {
            setBusy(false)
          }
        }}
      >
        <div className="form-group">
          <label className="form-label" htmlFor="email">Email Address</label>
          <div className="input-wrapper">
            <Mail size={18} className="input-icon" />
            <input
              id="email"
              className="auth-input"
              type="email"
              placeholder="your@email.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              disabled={busy}
            />
          </div>
        </div>
        <button className="btn-login" type="submit" disabled={busy}>
          {busy ? 'Sending...' : 'Send Reset Link'}
        </button>
      </form>

      <div className="auth-footer">
        <p className="auth-footer-text">
          <Link to="/login" className="auth-footer-link">
            Back to Sign In
          </Link>
        </p>
      </div>
    </AuthShell>
  )
}

function AuthShell({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <div className="auth-container">
      <div className="auth-card">
        {/* Logo Section */}
        <div className="logo-wrapper">
          <div className="logo-icon">
            <Shield size={40} />
          </div>
          <div className="logo-text">SentinelPay</div>
        </div>

        {/* Title and Subtitle */}
        <h1 className="auth-title">{title}</h1>
        <p className="auth-subtitle">{subtitle}</p>

        {/* Content */}
        {children}

        {/* Security Indicator */}
        <div className="security-indicator mt-8">
          <Lock size={16} className="security-icon" />
          <span>🔒 Secure encrypted connection</span>
        </div>
      </div>
    </div>
  )
}
