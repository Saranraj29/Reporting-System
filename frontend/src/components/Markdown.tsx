import { Box, Checkbox, Link, Typography } from '@mui/material'
import type { ReactNode } from 'react'

// Small, safe markdown renderer for comments and descriptions: everything becomes React nodes, never raw HTML.
// Supports bold, italic, strikethrough, inline code, https links, quotes, bullet/numbered lists, checklists,
// fenced code blocks and headings.
const INLINE = /(`[^`]+`|\*\*[^*]+\*\*|~~[^~]+~~|\[[^\]]+\]\(https?:\/\/[^)\s]+\)|\*[^*\s][^*]*\*|_[^_\s][^_]*_)/g

function inline(text: string, keyBase: string): ReactNode[] {
  return text.split(INLINE).map((part, i) => {
    const key = `${keyBase}-${i}`
    if (!part) return null
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2)
      return <Box key={key} component="code" sx={{ px: 0.6, py: 0.1, borderRadius: 0.75, bgcolor: '#eef1f6', fontSize: '0.9em', fontFamily: 'ui-monospace, Menlo, Consolas, monospace' }}>{part.slice(1, -1)}</Box>
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) return <strong key={key}>{inline(part.slice(2, -2), key)}</strong>
    if (part.startsWith('~~') && part.endsWith('~~') && part.length > 4) return <s key={key}>{inline(part.slice(2, -2), key)}</s>
    const link = /^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/.exec(part)
    if (link) return <Link key={key} href={link[2]} target="_blank" rel="noopener noreferrer">{link[1]}</Link>
    if ((part.startsWith('*') && part.endsWith('*') && part.length > 2) || (part.startsWith('_') && part.endsWith('_') && part.length > 2))
      return <em key={key}>{inline(part.slice(1, -1), key)}</em>
    return part
  })
}

export function Markdown({ text, dense }: { text: string; dense?: boolean }) {
  const lines = text.replace(/\r/g, '').split('\n')
  const out: ReactNode[] = []
  let i = 0
  let n = 0
  const k = () => `b${n++}`
  while (i < lines.length) {
    const line = lines[i]
    if (line.trim() === '') { i++; continue }
    if (line.startsWith('```')) {
      const buf: string[] = []
      i++
      while (i < lines.length && !lines[i].startsWith('```')) buf.push(lines[i++])
      i++
      out.push(<Box key={k()} component="pre" sx={{ m: '8px 0', p: 1.5, borderRadius: 1.5, bgcolor: '#f3f5f9', border: '1px solid #e4e8f0', overflowX: 'auto', fontSize: 13, fontFamily: 'ui-monospace, Menlo, Consolas, monospace' }}>{buf.join('\n')}</Box>)
      continue
    }
    const heading = /^(#{1,3})\s+(.*)$/.exec(line)
    if (heading) {
      out.push(<Typography key={k()} variant={heading[1].length === 1 ? 'h6' : 'subtitle1'} sx={{ fontWeight: 700, mt: 1 }}>{inline(heading[2], `h${n}`)}</Typography>)
      i++
      continue
    }
    if (line.startsWith('>')) {
      const buf: string[] = []
      while (i < lines.length && lines[i].startsWith('>')) buf.push(lines[i++].replace(/^>\s?/, ''))
      out.push(<Box key={k()} sx={{ my: 1, pl: 1.5, borderLeft: '3px solid #cfd6e4', color: 'text.secondary' }}>{buf.map((b, j) => <div key={j}>{inline(b, `q${n}-${j}`)}</div>)}</Box>)
      continue
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line)
      const items: string[] = []
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*([-*]|\d+\.)\s+/, ''))
      const Tag = ordered ? 'ol' : 'ul'
      out.push(
        <Box key={k()} component={Tag} sx={{ my: 0.75, pl: 3, listStyle: items.every((x) => /^\[( |x)\]/.test(x)) ? 'none' : undefined, ml: items.every((x) => /^\[( |x)\]/.test(x)) ? -1.5 : 0 }}>
          {items.map((it, j) => {
            const task = /^\[( |x)\]\s*(.*)$/.exec(it)
            return (
              <li key={j}>
                {task ? <><Checkbox size="small" checked={task[1] === 'x'} disabled sx={{ p: 0.25, mr: 0.5 }} />{inline(task[2], `l${n}-${j}`)}</> : inline(it, `l${n}-${j}`)}
              </li>
            )
          })}
        </Box>,
      )
      continue
    }
    const buf: string[] = []
    while (i < lines.length && lines[i].trim() !== '' && !/^(```|>|#{1,3}\s|\s*([-*]|\d+\.)\s+)/.test(lines[i])) buf.push(lines[i++])
    out.push(<Typography key={k()} variant="body2" sx={{ my: dense ? 0.25 : 0.75, lineHeight: 1.6 }}>{buf.map((b, j) => <span key={j}>{j > 0 && <br />}{inline(b, `p${n}-${j}`)}</span>)}</Typography>)
  }
  return <Box sx={{ wordBreak: 'break-word' }}>{out}</Box>
}
