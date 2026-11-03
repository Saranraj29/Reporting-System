import { CircularProgress, Box } from '@mui/material'
import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { useAuth } from './auth'
import AdminProjects from './pages/AdminProjects'
import AdminSettings from './pages/AdminSettings'
import AdminUsers from './pages/AdminUsers'
import { ForgotPassword, Login, Register, ResetPassword, VerifyEmail } from './pages/Auth'
import ClientReports, { RunReview } from './pages/ClientReports'
import Dashboard from './pages/Dashboard'
import MyDay from './pages/MyDay'
import Reports, { ExportRun } from './pages/Reports'
import SharedReport from './pages/Shared'
import Tasks from './pages/Tasks'

function Home() {
  const { hasAny } = useAuth()
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
        <Route path="/reports" element={<Reports />} />
        <Route path="/reports/runs/:id" element={<ExportRun />} />
        <Route path="/client-reports" element={<ClientReports />} />
        <Route path="/client-reports/runs/:id" element={<RunReview />} />
        <Route path="/admin/users" element={<AdminUsers />} />
        <Route path="/admin/projects" element={<AdminProjects />} />
        <Route path="/admin/settings" element={<AdminSettings />} />
      </Route>
      <Route path="/login" element={<Navigate to="/" replace />} />
      <Route path="/register" element={<Navigate to="/" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
