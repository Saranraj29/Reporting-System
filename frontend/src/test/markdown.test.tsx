import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Markdown } from '../components/Markdown'

describe('Markdown', () => {
  it('renders bold, italic, strikethrough and inline code', () => {
    const { container } = render(<Markdown text={'**bold** _it_ ~~gone~~ `code`'} />)
    expect(container.querySelector('strong')?.textContent).toBe('bold')
    expect(container.querySelector('em')?.textContent).toBe('it')
    expect(container.querySelector('s')?.textContent).toBe('gone')
    expect(container.querySelector('code')?.textContent).toBe('code')
  })

  it('renders lists, checklists, quotes and fenced code', () => {
    const { container } = render(<Markdown text={'- one\n- two\n\n1. first\n2. second\n\n- [ ] todo\n- [x] done\n\n> quoted\n\n```\nlet a = 1\n```'} />)
    expect(container.querySelectorAll('ul').length).toBe(2)
    expect(container.querySelectorAll('ol li').length).toBe(2)
    const boxes = container.querySelectorAll('input[type=checkbox]')
    expect(boxes.length).toBe(2)
    expect((boxes[0] as HTMLInputElement).checked).toBe(false)
    expect((boxes[1] as HTMLInputElement).checked).toBe(true)
    expect(container.querySelector('pre')?.textContent).toBe('let a = 1')
    expect(screen.getByText('quoted')).toBeInTheDocument()
  })

  it('only links http(s) URLs, with rel=noopener, and never injects HTML', () => {
    const { container } = render(<Markdown text={'[ok](https://example.com) [bad](javascript:alert(1)) <img src=x onerror=alert(1)> <script>alert(1)</script>'} />)
    const links = container.querySelectorAll('a')
    expect(links.length).toBe(1)
    expect(links[0].getAttribute('href')).toBe('https://example.com')
    expect(links[0].getAttribute('rel')).toContain('noopener')
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('script')).toBeNull()
    expect(container.textContent).toContain('<script>alert(1)</script>') // shown as text, not executed
  })

  it('keeps single line breaks inside a paragraph', () => {
    const { container } = render(<Markdown text={'line one\nline two'} />)
    expect(container.querySelectorAll('br').length).toBe(1)
  })
})
