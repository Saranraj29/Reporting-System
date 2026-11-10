import AccountCircleIcon from '@mui/icons-material/AccountCircleOutlined'
import AddIcon from '@mui/icons-material/Add'
import AdminPanelSettingsIcon from '@mui/icons-material/AdminPanelSettingsOutlined'
import AssessmentIcon from '@mui/icons-material/AssessmentOutlined'
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesomeOutlined'
import BusinessIcon from '@mui/icons-material/BusinessCenterOutlined'
import DashboardIcon from '@mui/icons-material/SpaceDashboardOutlined'
import DomainIcon from '@mui/icons-material/DomainOutlined'
import FolderIcon from '@mui/icons-material/FolderOpenOutlined'
import GroupsIcon from '@mui/icons-material/GroupsOutlined'
import LogoutIcon from '@mui/icons-material/LogoutOutlined'
import MenuIcon from '@mui/icons-material/Menu'
import PeopleIcon from '@mui/icons-material/PeopleAltOutlined'
import SettingsIcon from '@mui/icons-material/SettingsOutlined'
import SmartToyIcon from '@mui/icons-material/SmartToyOutlined'
import TaskIcon from '@mui/icons-material/TaskAltOutlined'
import TimerIcon from '@mui/icons-material/TimerOutlined'
import TuneIcon from '@mui/icons-material/TuneOutlined'
import Diversity3Icon from '@mui/icons-material/Diversity3Outlined'
import { AppBar, Avatar, Box, ButtonBase, Divider, Drawer, Fab, GlobalStyles, IconButton, List, ListItemButton, ListItemIcon, ListItemText, ListSubheader, Menu, MenuItem, Stack, Toolbar, Tooltip, Typography, useMediaQuery, useTheme } from '@mui/material'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Navigate, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { canOpen } from '../access'
import { useAuth } from '../auth'
import { initials } from '../format'
import { HeaderTimer } from '../timer'
import { AssistantPanel, ASSISTANT_WIDTH } from './AssistantPanel'
import { DailyStatusDialog } from './DailyStatusDialog'

const WIDTH = 248

interface Item {
  to: string
  label: string
  icon: ReactNode
  show: boolean
}

/** "Priya Nair-Kumar Rao" -> "Priya Rao": only the first and the last name in the header. */
export function shortName(name: string): string {
  const parts = name.trim().split(/\s+/)
  return parts.length > 2 ? `${parts[0]} ${parts[parts.length - 1]}` : name.trim()
}

const read = (key: string, fallback: boolean) => {
  try {
    const v = localStorage.getItem(key)
    return v === null ? fallback : v === '1'
  } catch {
    return fallback
  }
}
const write = (key: string, v: boolean) => {
  try {
    localStorage.setItem(key, v ? '1' : '0')
  } catch {
    /* private mode: the choice just is not remembered */
  }
}

export function Layout() {
  const { me, can, hasAny, logout } = useAuth()
  const theme = useTheme()
  const mobile = useMediaQuery(theme.breakpoints.down('md'))
  const nav = useNavigate()
  const { pathname } = useLocation()
  const trigger = useRef<HTMLButtonElement>(null)
  const [statusOpen, setStatusOpen] = useState(false)
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)

  // sidebar: one toggle for every screen. On a laptop it slides away and the page widens (remembered); on a phone it opens over the page.
  const navKey = `sidebar-open:${me?.id}`
  const [deskOpen, setDeskOpen] = useState(() => read(navKey, true))
  const [phoneOpen, setPhoneOpen] = useState(false)
  const navOpen = mobile ? phoneOpen : deskOpen
  const toggleNav = () => (mobile ? setPhoneOpen((o) => !o) : (setDeskOpen((o) => { write(navKey, !o); return !o })))
  useEffect(() => setPhoneOpen(false), [pathname])

  const storeKey = `assistant-open:${me?.id}`
  const [assistOpen, setAssistOpen] = useState(() => read(storeKey, false))
  const setAssist = (v: boolean) => { setAssistOpen(v); write(storeKey, v) }
  const hasAssistant = can('assistant.use') && !pathname.startsWith('/ai-reports') // AI reports keeps its own three-step flow
  const docked = hasAssistant && assistOpen && !mobile  // below md the panel opens full screen instead of docking
  const left = !mobile && navOpen ? WIDTH : 0
  const right = docked ? ASSISTANT_WIDTH : 0

  const who = { can, hasAny, me }
  const main: Item[] = [
    { to: '/', label: 'Dashboard', icon: <DashboardIcon />, show: hasAny('dashboard.view') },
    { to: '/tasks', label: 'Tasks', icon: <TaskIcon />, show: canOpen('/tasks', who) },
    { to: '/my-day', label: 'My day', icon: <TimerIcon />, show: canOpen('/my-day', who) },
    { to: '/check-ins', label: 'Check-ins', icon: <GroupsIcon />, show: canOpen('/check-ins', who) },
    { to: '/reports', label: 'Reports', icon: <AssessmentIcon />, show: canOpen('/reports', who) },
    { to: '/ai-reports', label: 'AI reports', icon: <AutoAwesomeIcon />, show: canOpen('/ai-reports', who) },
  ]
  const admin: Item[] = [
    { to: '/admin/users', label: 'Users', icon: <PeopleIcon />, show: canOpen('/admin/users', who) },
    { to: '/admin/roles', label: 'Roles & permissions', icon: <AdminPanelSettingsIcon />, show: canOpen('/admin/roles', who) },
    { to: '/admin/projects', label: 'Projects', icon: <FolderIcon />, show: canOpen('/admin/projects', who) },
    { to: '/admin/clients', label: 'Clients', icon: <DomainIcon />, show: canOpen('/admin/clients', who) },
    { to: '/admin/teams', label: 'Teams', icon: <Diversity3Icon />, show: canOpen('/admin/teams', who) },
  ]
  const settings: Item = { to: '/admin/settings', label: 'Settings', icon: <SettingsIcon />, show: canOpen('/admin/settings', who) }

  const signOut = async () => {
    setAnchor(null)
    try { sessionStorage.removeItem('start-page-used') } catch { /* ignore */ }
    await logout()
    nav('/login')
  }

  const link = (i: Item) =>
    i.show && (
      <ListItemButton
        key={i.to}
        component={NavLink}
        to={i.to}
        end={i.to === '/'}
        sx={{
          mx: 1.5, mb: 0.5, borderRadius: 2, color: 'text.secondary',
          '&.active': { bgcolor: 'primary.main', color: '#fff', '& .MuiListItemIcon-root': { color: '#fff' } },
          '&.active:hover': { bgcolor: 'primary.dark' },
        }}
      >
        <ListItemIcon sx={{ minWidth: 38, color: 'inherit' }}>{i.icon}</ListItemIcon>
        <ListItemText primary={i.label} primaryTypographyProps={{ fontWeight: 600, fontSize: 14 }} />
      </ListItemButton>
    )

  const drawer = (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column', bgcolor: 'background.paper' }}>
      <Stack direction="row" spacing={1.5} alignItems="center" sx={{ px: 2.5, py: 2.5 }}>
        <Avatar variant="rounded" sx={{ bgcolor: 'primary.main', width: 36, height: 36 }}>
          <BusinessIcon fontSize="small" />
        </Avatar>
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 700, lineHeight: 1.2 }}>
            Transparency
          </Typography>
          <Typography variant="caption" color="text.secondary" noWrap component="div">
            {me?.company.name}
          </Typography>
        </Box>
      </Stack>
      <List component="nav" aria-label="Main" sx={{ flex: 1, overflowY: 'auto' }}>
        {main.map(link)}
        {admin.some((a) => a.show) && (
          <>
            <Divider sx={{ my: 1.5, mx: 2 }} />
            <ListSubheader sx={{ bgcolor: 'transparent', lineHeight: '28px', fontSize: 11, letterSpacing: '.08em', textTransform: 'uppercase' }}>Administration</ListSubheader>
            {admin.map(link)}
          </>
        )}
      </List>
      <Box component="nav" aria-label="Account" sx={{ pb: 1 }}>
        <Divider sx={{ mb: 1, mx: 2 }} />
        {link(settings)}
        <ListItemButton onClick={signOut} sx={{ mx: 1.5, borderRadius: 2, color: 'text.secondary' }}>
          <ListItemIcon sx={{ minWidth: 38, color: 'inherit' }}><LogoutIcon /></ListItemIcon>
          <ListItemText primary="Log out" primaryTypographyProps={{ fontWeight: 600, fontSize: 14 }} />
        </ListItemButton>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', px: 3, pt: 1 }}>Release 1</Typography>
      </Box>
    </Box>
  )

  const slide = theme.transitions.create(['margin', 'width'], { duration: theme.transitions.duration.shorter })
  return (
    <Box sx={{ display: 'flex', minHeight: '100vh' }}>
      {me?.prefs.compact_tables && <GlobalStyles styles={{ '.MuiTableCell-root': { paddingTop: '6px', paddingBottom: '6px' } }} />}
      <AppBar position="fixed" color="inherit" sx={{ width: `calc(100% - ${left + right}px)`, ml: `${left}px`, transition: slide, borderBottom: '1px solid', borderColor: 'divider', boxShadow: 'none' }}>
        <Toolbar>
          <Tooltip title={navOpen ? 'Hide the sidebar' : 'Show the sidebar'}>
            <IconButton edge="start" onClick={toggleNav} sx={{ mr: 1 }} aria-label={navOpen ? 'Hide navigation' : 'Show navigation'} aria-expanded={navOpen}>
              <MenuIcon />
            </IconButton>
          </Tooltip>
          <Box sx={{ flex: 1 }} />
          <HeaderTimer />
          {hasAssistant && (
            <Tooltip title="AI assistant">
              <IconButton ref={trigger} onClick={() => setAssist(!assistOpen)} aria-label="AI assistant" aria-pressed={assistOpen} sx={{ mr: 1 }} color={assistOpen ? 'primary' : 'default'}>
                <SmartToyIcon />
              </IconButton>
            </Tooltip>
          )}
          <ButtonBase onClick={(e) => setAnchor(e.currentTarget)} aria-label="Account menu" aria-haspopup="menu" aria-expanded={!!anchor} sx={{ borderRadius: 2, px: 0.75, py: 0.5, gap: 1 }}>
            <Avatar sx={{ width: 34, height: 34, bgcolor: 'secondary.main', fontSize: 14 }}>{initials(me?.name ?? '?')}</Avatar>
            <Typography variant="body2" sx={{ fontWeight: 600, display: { xs: 'none', sm: 'block' } }}>{shortName(me?.name ?? '')}</Typography>
          </ButtonBase>
          <Menu anchorEl={anchor} open={!!anchor} onClose={() => setAnchor(null)} anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }} transformOrigin={{ vertical: 'top', horizontal: 'right' }}>
            <MenuItem disabled sx={{ opacity: '1 !important' }}>
              <Box>
                <Typography variant="body2" sx={{ fontWeight: 700 }}>{me?.name}</Typography>
                <Typography variant="caption" color="text.secondary">{me?.email}</Typography>
              </Box>
            </MenuItem>
            <Divider />
            <MenuItem onClick={() => { setAnchor(null); nav('/profile') }}><ListItemIcon><AccountCircleIcon fontSize="small" /></ListItemIcon>Profile</MenuItem>
            <MenuItem onClick={() => { setAnchor(null); nav('/preferences') }}><ListItemIcon><TuneIcon fontSize="small" /></ListItemIcon>Preferences</MenuItem>
            <Divider />
            <MenuItem onClick={signOut}><ListItemIcon><LogoutIcon fontSize="small" /></ListItemIcon>Log out</MenuItem>
          </Menu>
        </Toolbar>
      </AppBar>
      <Drawer
        variant={mobile ? 'temporary' : 'persistent'}
        open={navOpen}
        onClose={() => setPhoneOpen(false)}
        ModalProps={{ keepMounted: false }}
        PaperProps={{ sx: { width: WIDTH, borderRight: '1px solid', borderColor: 'divider' } }}
        sx={{ width: mobile ? 0 : left, flexShrink: 0, transition: slide }}
      >
        {drawer}
      </Drawer>
      <Box component="main" sx={{ flex: 1, minWidth: 0, p: { xs: 2, md: 3.5 }, pt: { xs: 10, md: 11 }, pb: { xs: 11, md: 11 }, transition: slide, mr: `${right}px` }}>
        {canOpen(pathname, who) ? <Outlet /> : <Navigate to="/" replace />}  {/* a page the person has no access to cannot be opened by typing its address */}
      </Box>
      <Tooltip title="Add today's status" placement="left">
        <Fab color="primary" aria-label="Add daily status" onClick={() => setStatusOpen(true)} sx={{ position: 'fixed', bottom: 24, right: 24 + right, transition: slide, zIndex: 1050 }}>
          <AddIcon />
        </Fab>
      </Tooltip>
      {hasAssistant && <AssistantPanel open={assistOpen} onClose={() => setAssist(false)} returnFocus={() => trigger.current?.focus()} />}
      <DailyStatusDialog open={statusOpen} onClose={() => setStatusOpen(false)} />
    </Box>
  )
}
