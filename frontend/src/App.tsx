import { CircularProgress, Box } from '@mui/material'
import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { useAuth } from './auth'
import AdminClients from './pages/AdminClients'
import AdminProjects from './pages/AdminProjects'
import AdminRoles from './pages/AdminRoles'
import AdminSettings from './pages/AdminSettings'
import AdminTeams from './pages/AdminTeams'
import AdminUsers from './pages/AdminUsers'
import { ForgotPassword, Login, Register, ResetPassword, VerifyEmail } from './pages/Auth'
import CheckIns from './pages/CheckIns'
import AiReports, { AiReportPage } from './pages/AiReports'
import Dashboard from './pages/Dashboard'
import MyDay from './pages/MyDay'
import Preferences from './pages/Preferences'
import Profile from './pages/Profile'
import Reports, { ExportRun } from './pages/Reports'
import SharedReport from './pages/Shared'
import Tasks from './pages/Tasks'

function Home() {
  const { hasAny, me } = useAuth()
  const start = me?.prefs.start_page
  // the page the person chose to land on (only the first time in a browser session, so the Dashboard link still works)
  if (start && start !== '/' && !sessionStorage.getItem('start-page-used')) {
    sessionStorage.setItem('start-page-used', '1')
    return <Navigate to={start} replace />
  }
  if (hasAny('dashboard.view')) return <Dashboard />
  if (hasAny('task.view')) return <Navigate to="/tasks" replace />
  return <Navigate to="/my-day" replace />
}

export default function App() {
  const { me, loading } = useAuth()
  const publicRoutes = (
    <>
      <Route path="/shared/:token" element={<SharedReport />} />
      <Route path="/verify-email" element={<VerifyEmail />} />
      <Route path="/reset-password" element={<ResetPassword />} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
    </>
  )
  if (loading) return <Box sx={{ display: 'grid', placeItems: 'center', height: '100vh' }}><CircularProgress /></Box>
  if (!me) {
    return (
      <Routes>
        {publicRoutes}
        <Route path="/register" element={<Register />} />
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    )
  }
  return (
    <Routes>
      {publicRoutes}
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="/tasks" element={<Tasks />} />
        <Route path="/my-day" element={<MyDay />} />
        <Route path="/check-ins" element={<CheckIns />} />
        <Route path="/reports" element={<Reports />} />
        <Route path="/reports/runs/:id" element={<ExportRun />} />
        <Route path="/ai-reports" element={<AiReports />} />
        <Route path="/ai-reports/:id" element={<AiReportPage />} />
        <Route path="/client-reports/*" element={<Navigate to="/ai-reports" replace />} />
        <Route path="/profile" element={<Profile />} />
        <Route path="/preferences" element={<Preferences />} />
        <Route path="/admin/users" element={<AdminUsers />} />
        <Route path="/admin/roles" element={<AdminRoles />} />
        <Route path="/admin/projects" element={<AdminProjects />} />
        <Route path="/admin/clients" element={<AdminClients />} />
        <Route path="/admin/teams" element={<AdminTeams />} />
        <Route path="/admin/settings" element={<AdminSettings />} />
      </Route>
      <Route path="/login" element={<Navigate to="/" replace />} />
      <Route path="/register" element={<Navigate to="/" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
