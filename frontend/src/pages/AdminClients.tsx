import AddIcon from '@mui/icons-material/Add'
import DeleteIcon from '@mui/icons-material/DeleteOutline'
import { Button, IconButton, Paper, Stack, Table, TableBody, TableCell, TableHead, TableRow, TextField, Tooltip, Typography } from '@mui/material'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api'
import DeleteDialog from '../components/DeleteDialog'
import { Empty, ErrorAlert, PageHeader, SearchBox, clickable } from '../components/ui'
import { useSearch } from '../hooks'
import type { Client, Contact, Page } from '../types'

export default function AdminClients() {
  return (
    <>
      <PageHeader title="Clients" subtitle="Who your projects are for, and the contacts that approved reports can be shared with" />
      <Clients />
    </>
  )
}

function Clients() {
  const qc = useQueryClient()
  const search = useSearch()
  const clients = useQuery({ queryKey: ['clients', search.term], queryFn: () => api.get<Page<Client>>('/clients', { limit: 200, q: search.term }), placeholderData: keepPreviousData })
  const [sel, setSel] = useState<Client | null>(null)
  const [del, setDel] = useState<Client | null>(null)
  const [f, setF] = useState({ name: '', contact_name: '', contact_email: '' })
  const [creating, setCreating] = useState(false)
  const contacts = useQuery({ queryKey: ['contacts', sel?.id], queryFn: () => api.get<{ items: Contact[] }>(`/clients/${sel!.id}/contacts`), enabled: !!sel })
  const [c, setC] = useState({ name: '', email: '' })
  const create = useMutation({ mutationFn: () => api.post('/clients', { name: f.name, contact_name: f.contact_name || null, contact_email: f.contact_email || null }), onSuccess: () => { setCreating(false); setF({ name: '', contact_name: '', contact_email: '' }); qc.invalidateQueries({ queryKey: ['clients'] }) } })
  const addContact = useMutation({ mutationFn: () => api.post(`/clients/${sel!.id}/contacts`, c), onSuccess: () => { setC({ name: '', email: '' }); qc.invalidateQueries({ queryKey: ['contacts', sel?.id] }) } })
  const delContact = useMutation({ mutationFn: (id: string) => api.del(`/clients/${sel!.id}/contacts/${id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ['contacts', sel?.id] }) })
  return (
    <>
    <Stack direction={{ xs: 'column', md: 'row' }} spacing={2.5} alignItems="flex-start">
      <Paper sx={{ flex: 1, width: '100%', overflow: 'hidden' }}>
        <Stack sx={{ p: 2, pb: 1 }}><SearchBox value={search.input} onChange={search.setInput} placeholder="Search clients or contacts" /></Stack>
        <Table>
          <TableHead><TableRow><TableCell>Client</TableCell><TableCell>Primary contact</TableCell><TableCell align="right" sx={{ width: 56 }}><span style={{ position: 'absolute', left: -9999 }}>Delete</span></TableCell></TableRow></TableHead>
          <TableBody>
            {clients.data?.items.map((cl) => (
              <TableRow key={cl.id} hover selected={sel?.id === cl.id} sx={{ cursor: 'pointer' }} {...clickable(() => setSel(cl))} aria-label={`Show ${cl.name}`}>
                <TableCell sx={{ fontWeight: 600 }}>{cl.name}</TableCell>
                <TableCell>{cl.contact_name ? `${cl.contact_name} · ${cl.contact_email}` : '—'}</TableCell>
                <TableCell align="right" onClick={(e) => e.stopPropagation()}><Tooltip title="Delete"><IconButton size="small" aria-label={`Delete ${cl.name}`} onClick={() => setDel(cl)}><DeleteIcon fontSize="small" /></IconButton></Tooltip></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <Stack direction="row" spacing={1} sx={{ p: 2 }}>
          {creating ? (
            <>
              <TextField size="small" label="Name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
              <TextField size="small" label="Contact name" value={f.contact_name} onChange={(e) => setF({ ...f, contact_name: e.target.value })} />
              <TextField size="small" label="Contact email" value={f.contact_email} onChange={(e) => setF({ ...f, contact_email: e.target.value })} />
              <Button variant="contained" disabled={!f.name} onClick={() => create.mutate()}>Add</Button>
            </>
          ) : <Button startIcon={<AddIcon />} onClick={() => setCreating(true)}>New client</Button>}
        </Stack>
        <ErrorAlert error={create.error} />
      </Paper>
      <Paper sx={{ p: 2.5, width: { xs: '100%', md: 380 } }}>
        {sel ? (
          <>
            <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>{sel.name} · report recipients</Typography>
            <Typography variant="caption" color="text.secondary">Approved client reports can only be shared with these contacts.</Typography>
            {contacts.data?.items.map((ct) => <Stack key={ct.id} direction="row" justifyContent="space-between" alignItems="center" sx={{ py: 0.75, borderBottom: '1px solid', borderColor: 'divider' }}><Typography variant="body2">{ct.name} · {ct.email}</Typography><Button size="small" color="error" onClick={() => delContact.mutate(ct.id)}>Remove</Button></Stack>)}
            <Stack spacing={1} sx={{ mt: 2 }}>
              <TextField size="small" label="Name" value={c.name} onChange={(e) => setC({ ...c, name: e.target.value })} />
              <TextField size="small" label="Email" value={c.email} onChange={(e) => setC({ ...c, email: e.target.value })} />
              <Button variant="outlined" disabled={!c.name || !c.email} onClick={() => addContact.mutate()}>Add contact</Button>
              <ErrorAlert error={addContact.error} />
            </Stack>
          </>
        ) : <Empty>Select a client to manage its contacts.</Empty>}
      </Paper>
    </Stack>
    {del && <DeleteDialog title={`Delete ${del.name}?`} description="The client and its contacts are removed. Its projects are kept, without a client." path={`/clients/${del.id}`} onClose={() => setDel(null)} onDeleted={() => { if (sel?.id === del.id) setSel(null); qc.invalidateQueries({ queryKey: ['clients'] }); qc.invalidateQueries({ queryKey: ['projects'] }) }} />}
    </>
  )
}
