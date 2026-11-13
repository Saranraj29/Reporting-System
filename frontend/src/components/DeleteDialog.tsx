import { Alert, Button, Dialog, DialogActions, DialogContent, DialogContentText } from '@mui/material'
import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, api, errorMessage } from '../api'
import { ModalTitle, keepOpen } from './ui'

/** One way to delete things. Asks first; if the server says the delete would take something along (code `in_use`), it says exactly what and
 *  asks once more ("Delete anyway"); if the thing cannot be deleted at all (code `has_history`), it says why and offers nothing further. */
export default function DeleteDialog({ title, description, path, confirmLabel = 'Delete', onClose, onDeleted }: {
  title: string
  description: string
  path: string  // e.g. /projects/<id>
  confirmLabel?: string
  onClose: () => void
  onDeleted: () => void
}) {
  const [needsConfirm, setNeedsConfirm] = useState('')  // what else would go, from the server
  const [blocked, setBlocked] = useState('')  // why it cannot be deleted
  const remove = useMutation({
    mutationFn: (force: boolean) => api.del(force ? `${path}${path.includes('?') ? '&' : '?'}force=true` : path),
    onSuccess: () => { onDeleted(); onClose() },
    onError: (e) => {
      if (e instanceof ApiError && e.code === 'in_use') setNeedsConfirm(e.message)
      else if (e instanceof ApiError && e.code === 'has_history') setBlocked(e.message)
    },
  })
  const failed = remove.error && !(remove.error instanceof ApiError && ['in_use', 'has_history'].includes(remove.error.code))
  return (
    <Dialog open onClose={keepOpen(onClose)} maxWidth="xs" fullWidth>
      <ModalTitle onClose={onClose}>{title}</ModalTitle>
      <DialogContent>
        <DialogContentText>{description}</DialogContentText>
        {needsConfirm && <Alert severity="warning" sx={{ mt: 2 }}>{needsConfirm}</Alert>}
        {blocked && <Alert severity="info" sx={{ mt: 2 }}>{blocked}</Alert>}
        {failed && <Alert severity="error" sx={{ mt: 2 }}>{errorMessage(remove.error)}</Alert>}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{blocked ? 'Close' : 'Cancel'}</Button>
        {!blocked && <Button color="error" variant="contained" disabled={remove.isPending} onClick={() => remove.mutate(!!needsConfirm)}>{needsConfirm ? 'Delete anyway' : confirmLabel}</Button>}
      </DialogActions>
    </Dialog>
  )
}
