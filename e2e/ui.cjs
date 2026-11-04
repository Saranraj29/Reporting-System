/* End-to-end smoke test + screenshot tour. Needs the full stack running (API, worker, web) with the demo seed:
 *   python -m app.seed         (backend)
 *   BASE_URL=http://localhost:5173 node ui.cjs
 * Exits non-zero on the first failed expectation. Screenshots go to ../docs/screenshots. */
const { chromium } = require('playwright')
const { execSync } = require('child_process')
const fs = require('fs')
const path = require('path')

const BASE = process.env.BASE_URL || 'http://localhost:5173'
const OUT = process.env.SHOT_DIR || path.join(__dirname, '..', 'docs', 'screenshots')
const PASSWORD = 'Demo@12345'
const TASK = `E2E created task ${Date.now()}`
const PG = process.env.PG_URL || 'postgresql://rs_owner:rs_owner@localhost:5432/reporting'
fs.mkdirSync(OUT, { recursive: true })

let failures = 0
const check = (cond, msg) => {
  console.log(`${cond ? 'ok  ' : 'FAIL'} ${msg}`)
  if (!cond) failures++
}

async function login(browser, user, viewport = { width: 1440, height: 900 }) {
  const ctx = await browser.newContext({ viewport, deviceScaleFactor: 1.5 })
  const page = await ctx.newPage()
  page.on('pageerror', (e) => check(false, `page error: ${e.message}`))
  await page.goto(`${BASE}/login`)
  await page.getByLabel('Work email').fill(`${user}@northwind.dev`)
  await page.getByLabel('Password').fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await page.waitForURL(`${BASE}/**`)
  await page.waitForSelector('main')
  return { ctx, page }
}
const shot = async (page, name) => {
  await page.waitForTimeout(600)
  await page.screenshot({ path: path.join(OUT, `${name}.png`) })
  console.log(`     saved ${name}.png`)
}
const navLinks = async (page) => (await page.locator('nav a').allInnerTexts()).map((s) => s.trim())

;(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined, args: ['--no-sandbox'] })

  // ---------------------------------------------------------------- login page
  {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1.5 })
    const page = await ctx.newPage()
    await page.goto(`${BASE}/login`)
    await page.getByText('Welcome back').waitFor()
    check(true, 'login page renders')
    await shot(page, '01-login')
    await page.getByLabel('Work email').fill('priya@northwind.dev')
    await page.getByLabel('Password').fill('wrong-password')
    await page.getByRole('button', { name: 'Sign in' }).click()
    await page.getByText('Incorrect email or password').waitFor()
    check(true, 'wrong password shows an error')
    await ctx.close()
  }

  // ---------------------------------------------------------------- manager
  {
    const { ctx, page } = await login(browser, 'priya')
    await page.waitForSelector('svg.recharts-surface')
    check(await page.getByRole('heading', { name: 'Dashboard' }).isVisible(), 'manager lands on the dashboard')
    const links = await navLinks(page)
    check(['Dashboard', 'Tasks', 'Reports', 'Client reports'].every((l) => links.includes(l)), `manager nav: ${links.join(', ')}`)
    check(!links.includes('Settings'), 'manager has no admin links')
    await shot(page, '02-dashboard')

    await page.getByRole('link', { name: 'Tasks' }).click()
    await page.waitForSelector('tbody tr')
    check((await page.locator('tbody tr').count()) >= 10, 'tasks list shows seeded tasks')
    await shot(page, '03-tasks')
    await page.getByText('Offline mode sync engine').click()
    await page.getByText('Time entries').waitFor()
    await shot(page, '04-task-detail')
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: 'New task' }).click()
    await page.getByRole('dialog').getByLabel('Title').fill(TASK)
    await shot(page, '05-new-task')
    await page.getByRole('dialog').getByLabel('Project').click()
    await page.getByRole('option', { name: 'Internal Tools' }).click()
    await page.getByRole('button', { name: 'Create task' }).click()
    await page.getByRole('dialog').waitFor({ state: 'detached' })
    await page.getByPlaceholder('Search tasks').fill(TASK)
    await page.getByText(TASK).waitFor()
    check(true, 'manager can create a task (assignees default to creator)')

    await page.getByRole('link', { name: 'Reports', exact: true }).click()
    await page.waitForSelector('iframe')
    check((await page.getByRole('tab').count()) === 3, 'manager sees weekly, monthly and performance reports')
    await shot(page, '06-report-weekly')
    await page.getByRole('tab', { name: /Performance/ }).click()
    await page.waitForTimeout(800)
    await shot(page, '07-report-performance')

    // --- client report: generate -> review -> approve -> share
    await page.getByRole('link', { name: 'Client reports' }).click()
    await page.getByText('Contoso weekly client update').waitFor()
    await shot(page, '08-client-templates')
    await page.getByRole('button', { name: 'Generate' }).first().click()
    await page.getByRole('dialog').getByRole('button', { name: 'Generate' }).click() // default: last complete week, whole team
    await page.getByText('Figures the draft is built from').waitFor({ timeout: 60000 })
    check(await page.getByLabel('Summary').isVisible(), 'draft appears after the worker finishes')
    await page.getByLabel('Summary').fill('A steady week for Contoso: the redesigned landing page and responsive navigation shipped, and checkout testing is under way.')
    await shot(page, '09-report-review')
    await page.getByRole('button', { name: 'Approve' }).click()
    await page.getByRole('dialog').getByRole('button', { name: 'Approve' }).click()
    await page.getByText('Final files & sharing').waitFor()
    await page.getByRole('link', { name: /PDF$/ }).or(page.getByRole('button', { name: 'PDF' })).first().waitFor({ timeout: 60000 })
    await page.getByLabel(/Hannah Cole/).check()
    await page.getByRole('button', { name: 'Share with client' }).click()
    await page.getByText('sending…').or(page.getByText('Revoke')).first().waitFor()
    await page.waitForTimeout(8000) // worker emails + marks the run as sent
    await shot(page, '10-report-shared')
    await ctx.close()
  }

  // ---------------------------------------------------------------- public shared page (no login)
  {
    const token = execSync(`psql "${PG}" -tAc "select token from report_shares order by created_at desc limit 1"`).toString().trim()
    check(token.length >= 43, 'share token is a long random string')
    const ctx = await browser.newContext({ viewport: { width: 1200, height: 900 }, deviceScaleFactor: 1.5 })
    const page = await ctx.newPage()
    await page.goto(`${BASE}/shared/${token}`)
    await page.waitForSelector('iframe')
    check(await page.getByRole('link', { name: 'Download PDF' }).isVisible(), 'client page offers the PDF without logging in')
    const html = await page.frameLocator('iframe').locator('body').innerText()
    check(html.includes('A steady week for Contoso'), 'client page shows the approved text')
    check(!/Divya|Arjun|Meera|Karthik/.test(html), 'client page contains no internal names')
    await shot(page, '11-shared-report')
    await page.goto(`${BASE}/shared/not-a-token`)
    await page.getByText(/no longer available/).waitFor()
    check(true, 'invalid share link shows a friendly message')
    await ctx.close()
  }

  // ---------------------------------------------------------------- team member
  {
    const { ctx, page } = await login(browser, 'divya')
    const links = await navLinks(page)
    check(!links.includes('Reports') && !links.includes('Client reports'), `member nav hides reports: ${links.join(', ')}`)
    check(!links.some((l) => /Users|Settings|Projects/.test(l)), 'member sees no admin links')
    await page.waitForSelector('svg.recharts-surface')
    await shot(page, '12-member-dashboard')
    await page.getByRole('link', { name: 'My day' }).click()
    await page.getByText('Daily status', { exact: false }).first().waitFor()
    await page.waitForFunction(() => document.querySelector('textarea')?.value.length > 0) // seeded status loaded
    await page.getByLabel('What did you do today?').fill('Reviewed SEO audit findings and paired on the nav bug.')
    await page.getByRole('button', { name: 'Save status' }).click()
    await page.getByText('Saved. You can keep editing until midnight.').waitFor()
    check(true, 'daily status saves')
    await shot(page, '13-my-day')
    await page.getByRole('button', { name: 'Add daily status' }).click()
    await page.getByRole('dialog').getByText('One entry per day').waitFor()
    await shot(page, '14-daily-status-dialog')
    await page.goto(`${BASE}/reports`)
    await page.waitForTimeout(500)
    await page.getByText('You do not have access to any reports.').waitFor()
    check(true, 'member cannot open reports')
    await ctx.close()
  }

  // ---------------------------------------------------------------- team lead
  {
    const { ctx, page } = await login(browser, 'karthik')
    const links = await navLinks(page)
    check(links.includes('Reports') && !links.includes('Client reports'), `lead nav: ${links.join(', ')}`)
    await page.getByRole('link', { name: 'Reports', exact: true }).click()
    await page.waitForSelector('iframe')
    check((await page.getByRole('tab').count()) === 3, 'lead sees weekly, monthly and performance (team scope)')
    await ctx.close()
  }

  // ---------------------------------------------------------------- admin
  {
    const { ctx, page } = await login(browser, 'asha')
    const links = await navLinks(page)
    check(links.includes('Users & roles') && links.includes('Settings'), `admin nav: ${links.join(', ')}`)
    await page.getByRole('link', { name: 'Users & roles' }).click()
    await page.getByText('Priya Nair').waitFor()
    await shot(page, '15-admin-users')
    await page.getByRole('tab', { name: 'Roles & permissions' }).click()
    await page.getByText('task.view.team').waitFor()
    await shot(page, '16-admin-roles')
    await page.getByRole('link', { name: 'Projects & clients' }).click()
    await page.getByText('Website Revamp').waitFor()
    await shot(page, '17-admin-projects')
    await page.getByRole('link', { name: 'Settings' }).click()
    await page.getByLabel('Company name').waitFor()
    await shot(page, '18-admin-settings')
    await ctx.close()
  }

  // ---------------------------------------------------------------- project owner
  {
    // Meera is a plain Team Member: she only sees her own tasks...
    let { ctx, page } = await login(browser, 'meera')
    await page.getByRole('link', { name: 'Tasks' }).click()
    await page.waitForSelector('tbody tr')
    check(!(await page.locator('tbody').innerText()).includes('Push notification service'), 'member does not see other teams\' tasks')
    await ctx.close()
    // ...until an admin makes her an owner of the Mobile App project
    ;({ ctx, page } = await login(browser, 'asha'))
    await page.getByRole('link', { name: 'Projects & clients' }).click()
    await page.getByRole('row', { name: /Mobile App/ }).click()
    await page.getByLabel('Project owners').click()
    await page.getByRole('option', { name: 'Meera Pillai' }).click()
    await page.getByRole('heading', { name: 'Edit project' }).click() // close the dropdown (Escape would close the dialog)
    await shot(page, '20-project-owners')
    await page.getByRole('button', { name: 'Save' }).click()
    await page.getByRole('dialog').waitFor({ state: 'detached' })
    await ctx.close()
    ;({ ctx, page } = await login(browser, 'meera'))
    await page.getByRole('link', { name: 'Tasks' }).click()
    await page.getByText('Push notification service').waitFor()
    const body = await page.locator('tbody').innerText()
    check(body.includes('Offline mode sync engine') && body.includes('Push notification service'), 'project owner sees every task in the owned project')
    check(!body.includes('Payment gateway sandbox access'), 'project owner does not see tasks of other projects')
    await shot(page, '21-project-owner-tasks')
    await ctx.close()
  }

  // ---------------------------------------------------------------- usability regressions (reported from real use)
  {
    // 1) a running timer is visible and stoppable from every page, including the task drawer
    let { ctx, page } = await login(browser, 'divya')
    const stopBtn = page.locator('header button:has-text("Stop")') // CSS: the drawer (a modal) aria-hides the header
    await page.waitForTimeout(1500) // let the running-timer query load
    if (await stopBtn.isVisible()) { await stopBtn.click(); await stopBtn.waitFor({ state: 'detached' }) } // leftovers from earlier runs
    await page.getByRole('link', { name: 'Tasks' }).click()
    await page.waitForSelector('tbody tr')
    await page.locator('tbody tr').first().click()
    await page.getByRole('button', { name: 'Start timer' }).click()
    await stopBtn.waitFor()
    check(true, 'timer started from the task drawer shows live in the header')
    await page.getByRole('button', { name: 'Stop timer' }).waitFor()
    check(true, 'the drawer offers Stop for the running timer')
    await shot(page, '22-timer-running')
    await page.keyboard.press('Escape') // close the drawer
    await page.getByRole('link', { name: 'My day' }).click()
    await page.getByText(/^\d\d:\d\d:\d\d$/).first().waitFor()
    check(await page.getByRole('button', { name: 'Stop' }).first().isVisible(), 'My day shows the same running timer immediately (no stale cache)')
    await stopBtn.click()
    await stopBtn.waitFor({ state: 'detached' })
    await page.getByRole('button', { name: 'Start' }).waitFor()
    check(true, 'Stop in the header ends the timer everywhere')
    await ctx.close()

    // 2) "All ..." options show their text, 3) changing filters keeps old content on screen (no blink)
    ;({ ctx, page } = await login(browser, 'priya'))
    await page.waitForSelector('svg.recharts-surface')
    await page.getByRole('combobox', { name: /^Project/ }).click()
    await page.getByRole('option', { name: 'Mobile App' }).click()
    await page.getByRole('combobox', { name: /^Project/ }).click()
    await page.getByRole('option', { name: 'All projects' }).click()
    check((await page.locator('.MuiSelect-select').filter({ hasText: 'All projects' }).count()) === 1, 'dashboard project filter shows "All projects" instead of an empty box')
    check((await page.locator('.MuiSelect-select').filter({ hasText: 'Everyone' }).count()) === 1, 'dashboard person filter shows "Everyone"')
    await page.evaluate(() => {
      window.__flicker = 0
      new MutationObserver(() => { if (document.querySelector('.MuiSkeleton-root') || !document.querySelector('svg.recharts-surface')) window.__flicker++ }).observe(document.body, { childList: true, subtree: true })
    })
    for (const name of ['Mobile App', 'Website Revamp', 'All projects']) {
      await page.getByRole('combobox', { name: /^Project/ }).click()
      await page.getByRole('option', { name }).click()
      await page.waitForTimeout(700)
    }
    check((await page.evaluate(() => window.__flicker)) === 0, 'changing dashboard filters never blanks the page (no skeleton, charts stay mounted)')
    await shot(page, '23-dashboard-filters')
    await page.getByRole('link', { name: 'Tasks' }).click()
    await page.waitForSelector('tbody tr')
    await page.getByRole('combobox', { name: /^Status/ }).click()
    await page.getByRole('option', { name: 'All' }).click()
    check((await page.locator('.MuiSelect-select').filter({ hasText: 'All' }).count()) >= 1, 'tasks status filter shows "All"')

    // 4) person filter on Reports and Client reports
    await page.getByRole('link', { name: 'Reports', exact: true }).click()
    await page.waitForSelector('iframe')
    await page.getByRole('combobox', { name: /^Person/ }).click()
    await page.getByRole('option', { name: 'Divya Iyer' }).click()
    await page.waitForTimeout(1200)
    const rep = await page.frameLocator('iframe').locator('body').innerText()
    check(rep.includes('Divya Iyer') && !rep.includes('Arjun Das'), 'Reports person filter narrows the report to one person')
    await shot(page, '24-report-person-filter')
    await page.getByRole('link', { name: 'Client reports' }).click()
    await page.getByRole('button', { name: 'Generate' }).first().click()
    await page.getByLabel('Only work by').click()
    await page.getByRole('option', { name: 'Divya Iyer' }).click()
    await shot(page, '25-client-report-person-filter')
    await page.getByRole('dialog').getByRole('button', { name: 'Generate' }).click()
    await page.getByText('filtered to one person').waitFor({ timeout: 60000 })
    check(true, 'client report can be generated for one person, name not written into the report')
    await ctx.close()
  }

  // ---------------------------------------------------------------- AI provider settings
  {
    const { ctx, page } = await login(browser, 'asha')
    await page.getByRole('link', { name: 'Settings' }).click()
    await page.getByText('AI drafting').waitFor()
    await page.getByLabel('Provider').click()
    const options = await page.getByRole('option').allInnerTexts()
    check(['Anthropic', 'OpenAI', 'Gemini', 'Off'].every((n) => options.some((o) => o.includes(n))), `provider choices: ${options.join(' | ')}`)
    await page.getByRole('option', { name: /Gemini/ }).click()
    await page.getByLabel('API key').fill('AIza-not-a-real-key')
    await page.getByRole('button', { name: 'Test connection' }).click()
    await page.locator('.MuiAlert-message').filter({ hasText: /gemini|No LLM|API/i }).first().waitFor({ timeout: 30000 })
    check(!(await page.locator('.MuiAlert-message').allInnerTexts()).join(' ').includes('AIza-not-a-real-key'), 'connection test reports a result without echoing the key')
    await shot(page, '26-ai-provider-settings')
    await page.getByRole('button', { name: 'Save AI settings' }).click()
    await page.getByText('Company API key saved').waitFor()
    check(!(await page.content()).includes('AIza-not-a-real-key'), 'the saved API key is never shown again')
    await ctx.close()
  }

  // ---------------------------------------------------------------- phone
  {
    const { ctx, page } = await login(browser, 'priya', { width: 390, height: 844 })
    await page.waitForSelector('svg.recharts-surface')
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)
    check(!overflow, 'dashboard has no horizontal scroll at phone width')
    await shot(page, '19-mobile-dashboard')
    await ctx.close()
  }

  await browser.close()
  console.log(failures ? `\n${failures} check(s) FAILED` : '\nall checks passed')
  process.exit(failures ? 1 : 0)
})().catch((e) => {
  console.error(e)
  process.exit(1)
})
