import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './lib/auth'
import { LoginPage, SignupPage, ForgotPasswordPage } from './pages/Auth'
import { DashboardLayout } from './components/DashboardLayout'
import {
  DashboardHome,
  TransactionsPage,
  TransactionDetailPage,
  IncidentsPage,
  AlertDetailPage,
  FinancialImpactPage,
  ModelHealthPage,
  SimulatorPage,
  RazorpayIntegrationPage,
  NotificationsPage,
  UsersPage,
  SettingsPage,
  AuditLogsPage,
  SystemHealthPage,
  DocsPage,
} from './pages/Dashboard'

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/signup" element={<SignupPage />} />
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />
          
          <Route path="/dashboard" element={<DashboardLayout />}>
            <Route index element={<DashboardHome />} />
            
            {/* Monitor */}
            <Route path="transactions" element={<TransactionsPage />} />
            <Route path="transactions/:txId" element={<TransactionDetailPage />} />
            <Route path="incidents" element={<IncidentsPage />} />
            <Route path="alerts" element={<IncidentsPage />} />
            <Route path="incidents/:alertId" element={<AlertDetailPage />} />
            <Route path="alerts/:alertId" element={<AlertDetailPage />} />
            <Route path="investigation/:alertId" element={<AlertDetailPage />} />

            {/* Investigate */}
            <Route path="financial" element={<FinancialImpactPage />} />
            <Route path="reports" element={<FinancialImpactPage />} />

            {/* Configure */}
            <Route path="simulator" element={<SimulatorPage />} />
            <Route path="razorpay" element={<RazorpayIntegrationPage />} />
            <Route path="model-health" element={<ModelHealthPage />} />

            {/* Manage */}
            <Route path="notifications" element={<NotificationsPage />} />
            <Route path="audit-logs" element={<AuditLogsPage />} />
            <Route path="system-health" element={<SystemHealthPage />} />
            <Route path="users" element={<UsersPage />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="docs" element={<DocsPage />} />
          </Route>

          <Route path="/" element={<Navigate to="/login" replace />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}

export default App
