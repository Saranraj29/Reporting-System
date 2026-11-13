import { createContext, useContext, useEffect, useRef, type MutableRefObject } from 'react'

export interface FabRegistration {
  label: string
  run: MutableRefObject<() => void>
}

export const FabContext = createContext<(r: FabRegistration | null) => void>(() => {})

/** A page asks for the floating "+" button to do its own thing ("New task"); when the page goes away it goes back to "Add today's status". Pass null to leave it alone. */
export function useFab(label: string | null, onClick: () => void) {
  const set = useContext(FabContext)
  const run = useRef(onClick)
  run.current = onClick
  useEffect(() => {
    if (!label) return
    set({ label, run })
    return () => set(null)
  }, [label, set])
}
