import { CheckCircle2, CircleAlert, Shield, TrendingUp, Zap } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { MarketingFooter, MarketingNav } from '../components/MarketingNav'

const spike = [
  { t: '10a', rate: 0.5 },
  { t: '11a', rate: 0.48 },
  { t: '12p', rate: 0.52 },
  { t: '1p', rate: 0.5 },
  { t: '2p', rate: 0.55 },
  { t: '3p', rate: 7.5 },
  { t: '4p', rate: 6.1 },
]

const features = [
  ['Real-Time Fraud Spike Detection', 'Monitor fraud rate continuously. Get alerts within seconds of abnormal activity.'],
  ['AI-Powered Transaction Risk Scoring', 'Machine learning scores each transaction for fraud risk from 0–100%.'],
  ['Financial Impact Analysis', 'See potential exposure, confirmed loss, and false-positive review cost in rupees.'],
  ['Historical Baseline Comparison', 'Automatically learns your normal fraud rate and compares current activity against it.'],
  ['Human-in-the-Loop Investigation', 'Alerts go to your risk team. No auto-blocking. Analysts make the final decision.'],
  ['Audit Trail & Compliance', 'Every alert, investigation, and decision is logged with a timestamp.'],
  ['Razorpay Integration', 'Ingest transaction data from Razorpay Test Mode. No manual data entry.'],
  ['Advanced Analytics & Reporting', 'Daily, weekly, and monthly fraud reports. Export data for deeper analysis.'],
  ['Configurable Thresholds', 'Tune spike multiplier and Z-score sensitivity to match your business.'],
  ['Multi-Channel Notifications', 'Email, dashboard badges, and webhook delivery for your ops stack.'],
]

const faqs = [
  ['How quickly does SentinelPay detect fraud spikes?', 'Within 60–120 seconds of abnormal activity. Alerts appear on the dashboard immediately.'],
  ['Does SentinelPay automatically block payments?', 'No. It is defense-only. Alerts go to your team for investigation. You make the final decision.'],
  ['What data does SentinelPay need?', 'Connect Razorpay Test Mode or use the controlled simulator. We ingest events via API and webhooks.'],
  ['Is my data secure?', 'Data is encrypted in transit. This local deployment stores records in your own SQLite database.'],
  ['Can I export data for my own analysis?', 'Yes. Export alerts and transactions as CSV from the dashboard.'],
  ['Can I integrate with existing systems?', 'Yes. The REST API supports custom integrations with CRM, SIEM, or data warehouse tools.'],
  ['What is the uptime target?', 'The hosted product targets 99.9% uptime. This repo also runs fully offline for demos.'],
  ['What if I have questions about an alert?', 'Use investigation notes and the audit trail, or email hello@sentinelpay.io.'],
]

export function LandingPage() {
  const [openFaq, setOpenFaq] = useState<number | null>(0)
  return (
    <div>
      <MarketingNav />
      <section className="bg-[#0B1020] text-white">
        <div className="mx-auto grid max-w-6xl items-center gap-10 px-4 py-16 md:grid-cols-2 md:py-24">
          <div>
            <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-[#3B82F6]/30 bg-[#3B82F6]/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.2em] text-[#93C5FD]">
              <Shield size={14} /> AI Finance Controller
            </div>
            <h1 className="text-4xl font-extrabold leading-tight md:text-6xl">Take Control of Your Financial Risk with AI</h1>
            <p className="mt-5 max-w-xl text-lg text-slate-300 md:text-xl">
              AI Finance Controller continuously monitors transactions, identifies suspicious financial activity,
              calculates risk scores, and delivers actionable insights to help businesses make safer decisions.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link to="/dashboard" className="btn-primary">
                Open Dashboard
              </Link>
              <Link to="/dashboard/simulator" className="btn-outline !border-slate-600 !text-slate-100 hover:bg-slate-800/80">
                View Demo Data
              </Link>
            </div>
            <div className="mt-6 flex flex-wrap gap-4 text-sm text-slate-300">
              <span>• Real-time transaction monitoring</span>
              <span>• Risk scoring and anomaly detection</span>
              <span>• Actionable recommendations</span>
            </div>
          </div>
          <div className="rounded-2xl border border-slate-700 bg-slate-950/80 p-5 shadow-2xl shadow-slate-950/30">
            <div className="mb-4 flex items-center justify-between">
              <p className="text-sm font-medium text-slate-300">Risk Overview</p>
              <span className="rounded-full border border-rose-500/30 bg-rose-500/10 px-2 py-1 text-[10px] font-bold uppercase tracking-[0.2em] text-rose-300">
                Critical
              </span>
            </div>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={spike}>
                  <XAxis dataKey="t" stroke="#94A3B8" />
                  <YAxis unit="%" stroke="#94A3B8" />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#0F172A',
                      border: '1px solid #334155',
                      borderRadius: '12px',
                      color: '#E2E8F0',
                    }}
                  />
                  <Area type="monotone" dataKey="rate" stroke="#F87171" fill="#FECACA" fillOpacity={0.35} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-3 flex items-center justify-between rounded-xl border border-slate-800 bg-slate-900/80 p-3 text-sm">
              <span className="text-slate-300">Fraud baseline</span>
              <span className="font-semibold text-slate-100">0.5%</span>
              <span className="text-rose-300">→ 7.5% spike</span>
            </div>
          </div>
        </div>
      </section>

      <section id="how-it-works" className="mx-auto max-w-6xl px-4 py-16">
        <div className="mb-8 text-center">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-sky-400">Workflow</p>
          <h2 className="mt-3 text-3xl font-bold text-slate-900 md:text-4xl">From transaction data to confident action</h2>
        </div>
        <div className="grid gap-4 md:grid-cols-5">
          {[
            'Transaction Data',
            'AI Risk Analysis',
            'Risk Score & Detection',
            'Alerts & Insights',
            'Recommended Action',
          ].map((item, index) => (
            <div key={item} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="mb-3 flex h-8 w-8 items-center justify-center rounded-full bg-sky-100 text-sm font-bold text-sky-700">
                {index + 1}
              </div>
              <p className="text-sm font-semibold text-slate-800">{item}</p>
            </div>
          ))}
        </div>
        <div className="mt-6 flex items-center justify-center text-slate-500">
          <span className="mx-2">↓</span>
        </div>
      </section>

      <section id="problem" className="mx-auto max-w-6xl px-4 py-16">
        <h2 className="text-3xl font-bold md:text-4xl">The Problem</h2>
        <div className="mt-8 grid gap-8 md:grid-cols-2">
          <div>
            <p className="text-lg text-gray-700">Traditional fraud detection asks: “Is THIS transaction suspicious?”</p>
            <ul className="mt-4 space-y-2 text-gray-600">
              <li>Misses coordinated fraud attacks</li>
              <li>Only scores individual transactions</li>
              <li>Doesn’t detect sudden rate changes</li>
              <li>Leaves merchants blind to spikes</li>
            </ul>
            <p className="mt-6 text-lg font-semibold">Merchants actually need: “Has MY FRAUD RATE suddenly changed?”</p>
          </div>
          <div className="grid gap-4">
            <div className="card border-red-200">
              <p className="text-sm text-gray-500">Average loss per spike</p>
              <p className="text-2xl font-bold text-critical">₹2.4 lakh</p>
            </div>
            <div className="card">
              <p className="text-sm text-gray-500">Coordinated attacks can lift fraud rate</p>
              <p className="text-2xl font-bold">15× in minutes</p>
            </div>
            <div className="card">
              <p className="text-sm text-gray-500">Traditional detection lag</p>
              <p className="text-2xl font-bold">4–6 hours</p>
            </div>
          </div>
        </div>
      </section>

      <section id="how-it-works" className="bg-paper py-16">
        <div className="mx-auto max-w-6xl px-4">
          <h2 className="text-3xl font-bold md:text-4xl">How SentinelPay Works</h2>
          <div className="mt-8 grid gap-4 md:grid-cols-5">
            {[
              ['1', 'Transactions flow in', 'Razorpay webhooks or the simulator, 1–2s latency'],
              ['2', 'ML scores each one', 'Fraud probability and LOW–CRITICAL risk'],
              ['3', 'Hourly aggregation', 'Fraud % vs your historical baseline'],
              ['4', 'Anomaly detection', 'Z-score and multiplier vs threshold'],
              ['5', 'Human decision', 'Confirm, false positive, or resolve — then audit'],
            ].map(([n, t, d]) => (
              <div key={n} className="card">
                <p className="text-sm font-bold text-teal">{n}</p>
                <p className="mt-2 font-semibold">{t}</p>
                <p className="mt-1 text-sm text-gray-600">{d}</p>
              </div>
            ))}
          </div>
          <div className="card mt-8">
            <p className="font-semibold">Example timeline</p>
            <p className="mt-2 text-sm text-gray-600">10 AM–2 PM: 0.5% fraud, 10,000 txns — status normal.</p>
            <p className="mt-1 text-sm text-gray-600">
              3 PM: 7.5% fraud, 750 suspicious, 15× multiplier, Z=4.2, exposure ₹18,75,000 — alert generated.
            </p>
            <p className="mt-1 text-sm text-gray-600">
              Analyst reviews for ~10 minutes and confirms fraud. Time to detect: 2 minutes. Defense-only: no
              automatic blocks.
            </p>
          </div>
        </div>
      </section>

      <section id="features" className="mx-auto max-w-6xl px-4 py-16">
        <h2 className="text-3xl font-bold md:text-4xl">Key Features</h2>
        <div className="mt-8 grid gap-4 md:grid-cols-3">
          {features.map(([title, body]) => (
            <div key={title} className="card transition hover:shadow-lift">
              <Zap className="text-teal" size={20} />
              <h3 className="mt-3 text-lg font-semibold">{title}</h3>
              <p className="mt-2 text-sm text-gray-600">{body}</p>
            </div>
          ))}
        </div>
      </section>

      <section id="use-cases" className="bg-paper py-16">
        <div className="mx-auto max-w-6xl px-4">
          <h2 className="text-3xl font-bold">Who Uses SentinelPay?</h2>
          <div className="mt-8 grid gap-4 md:grid-cols-3">
            {[
              ['E-Commerce Merchants', 'Prevent coordinated attacks during peak shopping seasons.'],
              ['Payment Processors', 'Monitor merchant fraud rates across the platform.'],
              ['Digital Banks', 'Detect sudden UPI payment fraud spikes.'],
              ['Subscription Services', 'Catch coordinated card-testing fraud.'],
              ['Ticketing Platforms', 'Stop bot-driven fraudulent bulk purchases.'],
            ].map(([t, d]) => (
              <div key={t} className="card">
                <TrendingUp className="text-navy" size={18} />
                <p className="mt-2 font-semibold">{t}</p>
                <p className="text-sm text-gray-600">{d}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="social" className="mx-auto max-w-6xl px-4 py-16 text-center">
        <h2 className="text-3xl font-bold">Trusted by leading risk teams</h2>
        <p className="mt-6 text-lg text-gray-700">
          “SentinelPay helped us see fraud-rate spikes the same afternoon they started — before chargebacks piled
          up.”
        </p>
        <p className="mt-2 text-sm text-gray-500">Head of Risk, demo merchant</p>
        <p className="mt-4 font-medium">4.8/5 from 120+ reviews</p>
      </section>

      <section id="pricing" className="bg-paper py-16">
        <div className="mx-auto max-w-6xl px-4">
          <h2 className="text-3xl font-bold">Pricing</h2>
          <div className="mt-8 grid gap-4 md:grid-cols-3">
            {[
              ['Starter', '₹29,999', '1M txns, email alerts, 30-day retention, 1 user'],
              ['Professional', '₹99,999', '10M txns, Slack + email, 90-day retention, 5 users'],
              ['Enterprise', 'Custom', 'Unlimited txns, 24/7 support, custom retention, API'],
            ].map(([name, price, body]) => (
              <div key={name} className="card">
                <p className="text-sm font-semibold text-teal">{name}</p>
                <p className="mt-2 font-display text-3xl font-bold">{price}</p>
                <p className="text-sm text-gray-500">per month</p>
                <p className="mt-4 text-sm text-gray-600">{body}</p>
                <Link to="/signup" className="btn-primary mt-6 w-full">
                  {name === 'Enterprise' ? 'Contact Us' : 'Get Started'}
                </Link>
              </div>
            ))}
          </div>
          <p className="mt-6 text-sm text-gray-600">
            All plans include Razorpay integration, historical baseline, audit trail, reporting, API access, and
            custom thresholds.
          </p>
        </div>
      </section>

      <section id="faq" className="mx-auto max-w-3xl px-4 py-16">
        <h2 className="text-3xl font-bold">FAQ</h2>
        <div className="mt-6 space-y-2">
          {faqs.map(([q, a], i) => (
            <button
              key={q}
              type="button"
              className="w-full rounded-lg border border-line bg-white p-4 text-left"
              onClick={() => setOpenFaq(openFaq === i ? null : i)}
            >
              <p className="font-medium">{q}</p>
              {openFaq === i && <p className="mt-2 text-sm text-gray-600">{a}</p>}
            </button>
          ))}
        </div>
      </section>

      <section id="cta" className="bg-navy py-16 text-center text-white">
        <Shield className="mx-auto mb-4" />
        <h2 className="text-3xl font-bold text-white">Ready to stop losing money to fraud?</h2>
        <p className="mt-3 text-sky-100">Start monitoring in 15 minutes. No credit card. 14-day free trial.</p>
        <div className="mt-6 flex justify-center gap-3">
          <Link to="/signup" className="btn-primary">
            Get Started Free
          </Link>
          <a href="mailto:hello@sentinelpay.io" className="btn-outline !border-white !text-white">
            Talk to Sales
          </a>
        </div>
      </section>
      <MarketingFooter />
    </div>
  )
}

export function DocsPage() {
  return (
    <div>
      <MarketingNav />
      <div className="mx-auto max-w-3xl px-4 py-16">
        <h1 className="text-4xl font-bold">Documentation</h1>
        <p className="mt-4 text-gray-600">
          SentinelPay is defense-only: detect, alert, investigate, decide, audit. It never blocks payments, freezes
          accounts, issues refunds, or moves money.
        </p>
        <h2 className="mt-10 text-2xl font-bold">Local run</h2>
        <ol className="mt-4 list-decimal space-y-2 pl-5 text-gray-700">
          <li>
            API: <code className="rounded bg-paper px-1">uvicorn api.main:app --reload --port 8000</code>
          </li>
          <li>
            Website: <code className="rounded bg-paper px-1">cd web && npm run dev</code>
          </li>
          <li>Open http://localhost:5173, create an account, then inject a spike from Settings.</li>
        </ol>
        <h2 className="mt-10 text-2xl font-bold">API</h2>
        <p className="mt-3 text-gray-700">
          Auth, dashboard metrics, alerts, transactions, settings, simulator, and Razorpay test webhooks live on
          the FastAPI server at port 8000. Vite proxies <code>/api</code> in development.
        </p>
        <div className="mt-6 flex items-start gap-2 rounded-lg bg-amber-50 p-4 text-sm">
          <CircleAlert className="mt-0.5 text-amber-600" size={16} />
          Terms, privacy, and security policies for the commercial product are summarized here for the demo. Production
          deployments should attach legal copies.
        </div>
        <div className="mt-6 flex items-center gap-2 text-sm text-teal">
          <CheckCircle2 size={16} /> SOC 2 posture, encryption in transit, and audit logging are first-class product
          requirements.
        </div>
      </div>
      <MarketingFooter />
    </div>
  )
}
