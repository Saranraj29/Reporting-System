import AddIcon from '@mui/icons-material/Add'
import AdminPanelSettingsIcon from '@mui/icons-material/AdminPanelSettingsOutlined'
import AssessmentIcon from '@mui/icons-material/AssessmentOutlined'
import BusinessIcon from '@mui/icons-material/BusinessCenterOutlined'
import DashboardIcon from '@mui/icons-material/SpaceDashboardOutlined'
import FolderIcon from '@mui/icons-material/FolderOpenOutlined'
import MenuIcon from '@mui/icons-material/Menu'
import SettingsIcon from '@mui/icons-material/SettingsOutlined'
import TaskIcon from '@mui/icons-material/TaskAltOutlined'
import TimerIcon from '@mui/icons-material/TimerOutlined'
import GroupsIcon from '@mui/icons-material/GroupsOutlined'
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesomeOutlined'
import { AppBar, Avatar, Box, Divider, Drawer, IconButton, List, ListItemButton, ListItemIcon, ListItemText, ListSubheader, Menu, MenuItem, Stack, Toolbar, Tooltip, Typography, useMediaQuery, useTheme } from '@mui/material'
import { useState, type ReactNode } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { initials } from '../format'
import { HeaderTimer } from '../timer'
import { DailyStatusDialog } from './DailyStatusDialog'

const WIDTH = 248

interface Item {
  to: string
  label: string
  icon: ReactNode
  show: boolean
}

export function Layout() {
  const { me, can, hasAny, logout } = useAuth()
  const theme = useTheme()
  const mobile = useMediaQuery(theme.breakpoints.down('md'))
  const [open, setOpen] = useState(false)
  const [statusOpen, setStatusOpen] = useState(false)
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const nav = useNavigate()

  const main: Item[] = [
    { to: '/', label: 'Dashboard', icon: <DashboardIcon />, show: hasAny('dashboard.view') },
    { to: '/tasks', label: 'Tasks', icon: <TaskIcon />, show: hasAny('task.view') },
    { to: '/my-day', label: 'My day', icon: <TimerIcon />, show: hasAny('task.view', 'status.view') },
    { to: '/check-ins', label: 'Check-ins', icon: <GroupsIcon />, show: can('status.view.team') || can('status.view.all') },
    { to: '/reports', label: 'Reports', icon: <AssessmentIcon />, show: hasAny('report.weekly.view', 'report.monthly.view', 'report.performance.view', 'report.visibility.view') },
    { to: '/client-reports', label: 'Client reports', icon: <AutoAwesomeIcon />, show: ['report.template.manage', 'report.ai.draft', 'report.approve', 'report.share.client'].some(can) },
  ]
  const admin: Item[] = [
    { to: '/admin/users', label: 'Users & roles', icon: <AdminPanelSettingsIcon />, show: can('user.manage') || can('role.manage') },
    { to: '/admin/projects', label: 'Projects & clients', icon: <FolderIcon />, show: can('project.manage') },
    { to: '/admin/settings', label: 'Settings', icon: <SettingsIcon />, show: can('settings.manage') },
  ]

  const link = (i: Item) =>
    i.show && (
      <ListItemButton
        key={i.to}
        component={NavLink}
        to={i.to}
        end={i.to === '/'}
        onClick={() => setOpen(false)}
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
      <List sx={{ flex: 1 }}>
        {main.map(link)}
        {admin.some((a) => a.show) && (
          <>
            <Divider sx={{ my: 1.5, mx: 2 }} />
            <ListSubheader sx={{ bgcolor: 'transparent', lineHeight: '28px', fontSize: 11, letterSpacing: '.08em', textTransform: 'uppercase' }}>Administration</ListSubheader>
            {admin.map(link)}
          </>
        )}
      </List>
      <Box sx={{ p: 2, color: 'text.secondary' }}>
        <Typography variant="caption">Release 1 · AI drafts, a person approves.</Typography>
      </Box>
    </Box>
  )

  return (
    <Box sx={{ display: 'flex', minHeight: '100vh' }}>
      <AppBar position="fixed" color="inherit" sx={{ width: { md: `calc(100% - ${WIDTH}px)` }, ml: { md: `${WIDTH}px` }, borderBottom: '1px solid', borderColor: 'divider', boxShadow: 'none' }}>
        <Toolbar>
          {mobile && (
            <IconButton edge="start" onClick={() => setOpen(true)} sx={{ mr: 1 }} aria-label="Open navigation">
              <MenuIcon />
            </IconButton>
          )}
          <Box sx={{ flex: 1 }} />
          <HeaderTimer />
          <Tooltip title="Add today's status">
            <IconButton color="primary" onClick={() => setStatusOpen(true)} aria-label="Add daily status" sx={{ bgcolor: 'primary.main', color: '#fff', mr: 2, '&:hover': { bgcolor: 'primary.dark' } }}>
              <AddIcon />
            </IconButton>
          </Tooltip>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ cursor: 'pointer' }} onClick={(e) => setAnchor(e.currentTarget)}>
            <Avatar sx={{ width: 34, height: 34, bgcolor: 'secondary.main', fontSize: 14 }}>{initials(me?.name ?? '?')}</Avatar>
            <Box sx={{ display: { xs: 'none', sm: 'block' } }}>
              <Typography variant="body2" sx={{ fontWeight: 600, lineHeight: 1.2 }}>
                {me?.name}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {me?.roles.map((r) => r.name).join(', ')}
              </Typography>
            </Box>
          </Stack>
          <Menu anchorEl={anchor} open={!!anchor} onClose={() => setAnchor(null)}>
            <MenuItem disabled>{me?.email}</MenuItem>
            <MenuItem
              onClick={async () => {
                setAnchor(null)
                await logout()
                nav('/login')
              }}
            >
              Sign out
            </MenuItem>
          </Menu>
        </Toolbar>
      </AppBar>
      <Box component="nav" sx={{ width: { md: WIDTH }, flexShrink: { md: 0 } }}>
        {mobile ? (
          <Drawer open={open} onClose={() => setOpen(false)} PaperProps={{ sx: { width: WIDTH } }}>
            {drawer}
          </Drawer>
        ) : (
          <Drawer variant="permanent" PaperProps={{ sx: { width: WIDTH, borderRight: '1px solid', borderColor: 'divider' } }} open>
            {drawer}
          </Drawer>
        )}
      </Box>
      <Box component="main" sx={{ flex: 1, minWidth: 0, p: { xs: 2, md: 3.5 }, pt: { xs: 10, md: 11 } }}>
        <Outlet />
      </Box>
      <DailyStatusDialog open={statusOpen} onClose={() => setStatusOpen(false)} />
    </Box>
  )
}
