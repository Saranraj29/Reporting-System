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
  await page.getByLabel(/^Password/).fill(PASSWORD)
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
    await page.getByLabel(/^Password/).fill('wrong-password')
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
    check(['Dashboard', 'Tasks', 'Reports', 'AI reports'].every((l) => links.includes(l)), `manager nav: ${links.join(', ')}`)
    check(!links.includes('Settings'), 'manager has no admin links')
    await shot(page, '02-dashboard')

    await page.getByRole('link', { name: 'Tasks' }).click()
    await page.waitForSelector('tbody tr')
    check((await page.locator('tbody tr').count()) >= 10, 'tasks list shows seeded tasks')
    await shot(page, '03-tasks')
    await page.getByPlaceholder('Search tasks').fill('Offline mode')  // the list is date-ordered, so search instead of relying on its first page
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
    check((await page.getByRole('tab').count()) === 4, 'manager sees weekly, monthly, performance and project visibility reports')
    await shot(page, '06-report-weekly')
    await page.getByRole('tab', { name: /Performance/ }).click()
    await page.waitForTimeout(800)
    await shot(page, '07-report-performance')

    // --- AI report in the employer's own format: request -> structure preview -> change -> OK -> report
    await page.getByRole('link', { name: 'AI reports' }).click()
    await page.getByRole('heading', { name: 'AI reports' }).waitFor()
    await page.getByLabel('What is this report for').fill('Update for the CTO, highlight delays')
    await page.getByRole('combobox', { name: 'People' }).click()
    const who = await page.getByRole('option').allInnerTexts()
    check(who[0] === 'Everyone' && who.length > 3, `People filter offers Everyone and the team: ${who.slice(0, 4).join(', ')}…`)
    await page.keyboard.press('Escape') // close the list
    await page.getByRole('radio', { name: /Own format/ }).click()
    await page.getByLabel('Report format').fill('1. Executive summary\n2. Progress per project\n3. Risks\n4. Next steps')
    await shot(page, '08-ai-report-request')
    await page.getByRole('button', { name: 'Show me the structure' }).click()
    await page.getByText('Here is how your report will look').waitFor({ timeout: 60000 })
    const rows = await page.getByRole('list', { name: 'Report structure' }).getByRole('listitem').allInnerTexts()
    check(rows.length === 4 && /Executive summary/.test(rows[0]) && /Next steps/.test(rows[3]), `structure preview follows the requested sections: ${rows.map((r) => r.split('\n')[0]).join(' | ')}`)
    check((await page.getByRole('button', { name: /^Looks good/ }).count()) === 1, 'preview offers an explicit OK before anything is written')
    await shot(page, '09-ai-report-structure')
    await page.getByRole('button', { name: 'Change something' }).click()
    await page.getByLabel('What should change').fill('Add a budget section at the end')
    await page.getByRole('button', { name: 'Update the structure' }).click()
    await page.getByText('Preparing the structure').waitFor()
    await page.getByText('Here is how your report will look').waitFor({ timeout: 60000 })
    await page.getByRole('button', { name: /^Looks good/ }).click()
    await page.getByText('Your report is ready').waitFor({ timeout: 90000 })
    const doc = await page.frameLocator('iframe').locator('body').innerText()
    check(doc.includes('Executive summary') && doc.includes('Mobile App') && doc.includes('Website Revamp'), 'finished report has the requested sections and every project')
    await shot(page, '10-ai-report-ready')
    const href = await page.getByRole('link', { name: /Markdown/ }).getAttribute('href')
    const md = await (await page.request.get(new URL(href, BASE).toString())).text()
    check(md.startsWith('# ') && md.includes('Mobile App'), 'Markdown download works')
    check((await page.getByRole('link', { name: /Word/ }).count()) === 1 && (await page.getByRole('link', { name: /Excel/ }).count()) === 1, 'Word and Excel downloads are offered')

    // --- no format given: industry-standard structure; Project Visibility Report layout
    await page.getByRole('link', { name: 'AI reports' }).click()
    await page.getByRole('button', { name: 'Show me the structure' }).click()
    await page.getByText('Here is how your report will look').waitFor({ timeout: 60000 })
    const std = await page.getByRole('list', { name: 'Report structure' }).getByRole('listitem').allInnerTexts()
    check(std.length >= 8 && /Executive summary/.test(std[0]), 'without a format the AI proposes an industry-standard structure')
    await page.getByRole('button', { name: 'Start over' }).click()
    await page.getByRole('heading', { name: 'AI reports' }).waitFor()
    await page.getByRole('radio', { name: /Project Visibility Report/ }).click()
    await page.getByRole('button', { name: 'Show me the structure' }).click()
    await page.getByText('Here is how your report will look').waitFor({ timeout: 60000 })
    check(/Sprint Goal/.test(await page.getByRole('list', { name: 'Report structure' }).innerText()), 'visibility format gives the Project Visibility layout')
    await page.getByRole('button', { name: /^Looks good/ }).click()
    await page.getByText('Your report is ready').waitFor({ timeout: 90000 })
    const vtext = await page.frameLocator('iframe').locator('body').innerText()
    check(vtext.includes('Sprint Goal') && vtext.includes('Combined Sprint Health Dashboard'), 'visibility AI report renders in the agreed layout')
    check((await page.frameLocator('iframe').locator('svg').count()) >= 3, 'charts are drawn (SVG), not mermaid source')
    await shot(page, '11-ai-report-visibility')
    await ctx.close()
  }

  // ---------------------------------------------------------------- team member
  {
    const { ctx, page } = await login(browser, 'divya')
    const links = await navLinks(page)
    check(!links.includes('Reports') && !links.includes('AI reports'), `member nav hides reports: ${links.join(', ')}`)
    check(!links.some((l) => /Users|Settings|Projects/.test(l)), 'member sees no admin links')
    await page.waitForSelector('svg.recharts-surface')
    await shot(page, '12-member-dashboard')
    await page.getByRole('link', { name: 'My day' }).click()
    await page.getByText('Morning check-in').waitFor()
    await page.getByLabel('What will you work on today?').fill('Finish the SEO audit and pair on the nav bug.')
    await page.getByRole('button', { name: /morning plan/i }).click()
    await page.getByText('Saved. You can keep editing until midnight.').first().waitFor()
    await page.getByLabel('What did you do today?').fill('Reviewed SEO audit findings and paired on the nav bug.')
    await page.getByRole('button', { name: /end-of-day/i }).first().click()
    await page.getByText(/Posted \d\d:\d\d/).nth(1).waitFor()
    check(true, 'morning plan and end-of-day update both save and are timestamped')
    await shot(page, '13-my-day')
    await page.getByRole('button', { name: 'Add daily status' }).click()
    await page.getByRole('dialog').getByText('One entry per day with two check-ins').waitFor()
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
    check(links.includes('Reports') && links.includes('AI reports'), `lead (a project owner) nav: ${links.join(', ')}`)
    await page.getByRole('link', { name: 'Reports', exact: true }).click()
    await page.waitForSelector('iframe')
    check((await page.getByRole('tab').count()) === 4, 'lead sees weekly, monthly, performance and visibility (team scope)')
    await ctx.close()
  }

  // ---------------------------------------------------------------- admin
  {
    const { ctx, page } = await login(browser, 'asha')
    const links = await navLinks(page)
    check(['Users', 'Roles & permissions', 'Projects', 'Clients', 'Teams', 'Settings'].every((l) => links.includes(l)), `admin nav has separate pages: ${links.join(', ')}`)
    check(links.indexOf('Settings') > links.indexOf('Teams'), 'Settings sits at the bottom of the sidebar')
    check(await page.getByRole('button', { name: 'Log out' }).isVisible(), 'sidebar has a Log out button next to Settings')
    await page.getByRole('link', { name: 'Users', exact: true }).click()
    await page.getByText('Priya Nair').waitFor()
    await shot(page, '15-admin-users')
    // search fires only from 3 characters
    const searches = []
    page.on('request', (r) => { if (/\/api\/v1\/users\?/.test(r.url()) && /[?&]q=/.test(r.url())) searches.push(new URL(r.url()).searchParams.get('q')) })
    const box = page.getByRole('searchbox', { name: /Search users/ })
    await box.fill('pr')
    await page.getByText('Type at least 3 characters to search').waitFor()
    await page.waitForTimeout(700)
    check(searches.length === 0, 'typing 2 characters sends no search request')
    await box.fill('pri')
    await page.waitForTimeout(900)
    check(searches.length === 1 && searches[0] === 'pri', `3 characters send one search: ${searches.join(',')}`)
    check(!(await page.getByText('Rohan Mehta').count()) && (await page.getByText('Priya Nair').count()) > 0, 'the list is narrowed to the match')
    await box.fill('')
    await page.getByText('Rohan Mehta').waitFor()
    await page.getByRole('link', { name: 'Roles & permissions' }).click()
    await page.getByText('task.view.team').waitFor()
    await shot(page, '16-admin-roles')
    await page.getByRole('link', { name: 'Projects', exact: true }).click()
    await page.getByText('Website Revamp').waitFor()
    await shot(page, '17-admin-projects')
    await page.getByRole('link', { name: 'Clients', exact: true }).click()
    await page.getByRole('heading', { name: 'Clients' }).waitFor()
    await page.getByRole('link', { name: 'Teams', exact: true }).click()
    await page.getByRole('heading', { name: 'Teams' }).waitFor()
    await page.getByRole('button', { name: 'New team' }).click()
    await page.getByLabel('Team name').fill('Design')
    await page.getByLabel('What does this team do?').fill('UI, brand and product design')
    await page.getByRole('dialog').getByRole('button', { name: 'Save' }).click()
    await page.getByText('UI, brand and product design').waitFor()
    check(true, 'a team (department) can be created with a description')
    await shot(page, '33-admin-teams')
    // a team is chosen when a project is created; the project's tasks inherit it
    await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Projects', exact: true }).click()
    await page.getByRole('button', { name: 'New project' }).click()
    const pd = page.getByRole('dialog')
    await pd.getByLabel(/^Name/).fill('Design portal')
    await pd.getByRole('combobox', { name: /^Team/ }).click()
    await page.getByRole('option', { name: 'Design' }).click()
    await pd.getByRole('button', { name: 'Save' }).click()
    await page.getByRole('row', { name: /Design portal/ }).getByText('Design', { exact: true }).waitFor()
    check(true, 'a project is created with its team and the list shows it')
    await page.getByRole('combobox', { name: /^Team/ }).click()
    await page.getByRole('option', { name: 'Design' }).click()
    await page.getByRole('row', { name: /Website Revamp/ }).waitFor({ state: 'hidden' })
    check((await page.getByRole('row').filter({ hasText: 'Design portal' }).count()) === 1, 'the Projects list filters by team')
    await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Tasks', exact: true }).click()
    await page.getByRole('button', { name: 'New task' }).click()
    check((await page.getByRole('dialog').getByLabel('Team (department)').count()) === 0, 'tasks have no team field of their own')
    await page.getByRole('dialog').getByRole('button', { name: 'Cancel' }).click()
    check((await page.getByRole('combobox', { name: /^Team/ }).count()) === 1, 'the Tasks list can still be filtered by team')
    await page.getByRole('link', { name: 'Settings' }).click()
    await page.getByLabel('Company name').waitFor()
    await shot(page, '18-admin-settings')
    await page.getByText('Email delivery').waitFor()
    await page.getByRole('button', { name: 'Send a test email to me' }).click()
    await page.getByText(/Development mode: the email was written to the server log/).waitFor()
    check(true, 'Settings shows how email is sent and a test email can be sent from there')
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
    await page.getByRole('link', { name: 'Projects', exact: true }).click()
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
    // owners can also ask for AI reports, but only about their own projects
    check((await navLinks(page)).includes('AI reports'), 'project owner gets the AI reports page')
    await page.getByRole('link', { name: 'AI reports' }).click()
    await page.getByRole('heading', { name: 'AI reports' }).waitFor()
    await page.getByRole('combobox', { name: 'Projects' }).click()
    await page.getByRole('option', { name: 'Mobile App' }).waitFor()  // the options load asynchronously; read the list only once they are in
    const opts = await page.getByRole('option').allInnerTexts()
    check(opts.length === 2 && opts[0] === 'All my projects' && opts[1] === 'Mobile App', `owner can only pick the owned project: ${opts.join(', ')}`)
    await ctx.close()
  }

  // ---------------------------------------------------------------- AI assistant (read-only): quick actions, scope, accessibility
  {
    const { ctx, page } = await login(browser, 'priya')
    await page.waitForSelector('svg.recharts-surface')
    await page.getByRole('button', { name: 'AI assistant' }).click()
    const panel = page.getByRole('complementary', { name: 'AI assistant' })
    await panel.waitFor()
    await panel.getByText('Draft this week\'s brief').waitFor()  // the cards arrive with the status request
    check(await panel.getByText('Draft this week\'s brief').isVisible() && await panel.getByText('Coming soon').first().isVisible(), 'assistant shows three page cards; later-phase cards are greyed "Coming soon"')
    check((await panel.getByRole('button', { name: /What is overdue/ }).isEnabled()) && !(await panel.getByRole('button', { name: /Draft this week/ }).isEnabled()), 'only phase-1 cards are clickable')
    check(await panel.getByLabel('Ask your assistant anything').isDisabled(), 'free-text input is disabled while the AI service is not connected, quick actions still work')
    await panel.getByRole('button', { name: /What is overdue/ }).click()
    await panel.getByText(/overdue or blocked\./).waitFor({ timeout: 30000 })
    await panel.getByText('Where this comes from').waitFor()
    const answer = await panel.getByLabel('Conversation').innerText()
    check(/Payment gateway sandbox access/.test(answer) && /not record the reason/.test(answer), 'answer lists real overdue tasks and says the reason is not recorded')
    await panel.getByRole('button', { name: 'Show' }).first().click()
    check(await panel.getByText(/as of/).first().isVisible(), 'the sources card shows row counts and an as-of time')
    await shot(page, '32-assistant-panel')
    const axe = await new (require('@axe-core/playwright').default)({ page }).include('aside[aria-label="AI assistant"]').analyze()
    const bad = axe.violations.filter((v) => ['serious', 'critical'].includes(v.impact))
    check(bad.length === 0, `assistant panel has no serious accessibility violations${bad.length ? ': ' + bad.map((v) => v.id + ' ' + v.nodes.map((n) => n.target.join(' ') + ' ' + (n.any[0] ? n.any[0].message : '')).join(' | ')).join('; ') : ''}`)
    await page.keyboard.press('Escape')
    await panel.waitFor({ state: 'hidden' })
    check(await page.getByRole('button', { name: 'AI assistant' }).evaluate((el) => el === document.activeElement), 'Esc closes the panel and focus returns to the trigger')
    await page.getByRole('link', { name: 'AI reports' }).click()
    await page.getByRole('heading', { name: 'AI reports' }).waitFor()
    check((await page.getByRole('button', { name: 'AI assistant' }).count()) === 0, 'AI reports keeps its own flow: no assistant button there')
    await ctx.close()
    // a plain Team Member does not get the AI assistant at all
    const m = await login(browser, 'divya')
    check((await m.page.getByRole('button', { name: 'AI assistant' }).count()) === 0, 'a Team Member has no AI assistant button')
    await m.ctx.close()
  }

  // ---------------------------------------------------------------- account chrome: password eye, header menu, profile, preferences, sidebar toggle, floating add button
  {
    const anon = await browser.newContext({ viewport: { width: 1280, height: 800 } })
    const lp = await anon.newPage()
    await lp.goto(`${BASE}/login`)
    const pwd = lp.getByLabel(/^Password/)
    await pwd.fill('secret-value')
    check((await pwd.getAttribute('type')) === 'password', 'password is hidden by default')
    await lp.getByRole('button', { name: 'Show password' }).click()
    check((await pwd.getAttribute('type')) === 'text', 'the eye button shows the password')
    await lp.getByRole('button', { name: 'Hide password' }).click()
    check((await pwd.getAttribute('type')) === 'password', 'and hides it again')
    await lp.goto(`${BASE}/register`)
    check(await lp.getByRole('button', { name: 'Show password' }).isVisible(), 'the register page has the eye button too')
    await anon.close()

    const { ctx, page } = await login(browser, 'priya')
    check((await page.locator('header button:has(svg[data-testid="AddIcon"])').count()) === 0, 'no plus button in the header')
    check(await page.getByRole('button', { name: 'Add daily status' }).isVisible(), 'the add-status button floats at the bottom right')
    const hdr = await page.locator('header').innerText()
    check(hdr.includes('Priya Nair') && !/Manager/.test(hdr), `header shows only the name, not the role: ${hdr.replace(/\n/g, ' ')}`)
    // sidebar toggle
    await page.getByRole('button', { name: 'Hide navigation' }).click()
    await page.getByRole('link', { name: 'Tasks' }).waitFor({ state: 'hidden' })
    check(true, 'the sidebar can be hidden on a laptop screen')
    await page.getByRole('button', { name: 'Show navigation' }).click()
    await page.getByRole('link', { name: 'Tasks' }).waitFor()
    // user menu
    await page.getByRole('button', { name: 'Account menu' }).click()
    const items = await page.getByRole('menuitem').allInnerTexts()
    check(['Profile', 'Preferences', 'Log out'].every((i) => items.some((t) => t.includes(i))), `user menu: ${items.join(' | ')}`)
    await page.getByRole('menuitem', { name: 'Profile' }).click()
    await page.getByRole('heading', { name: 'My profile' }).waitFor()
    await page.getByLabel('Job title').fill('Delivery manager')
    await page.getByLabel('Phone').fill('+91 90000 11111')
    await page.getByLabel('About me').fill('Keeps projects on track.')
    await page.getByRole('button', { name: 'Save profile' }).click()
    await page.getByText('Profile saved.').waitFor()
    await shot(page, '34-profile')
    await page.reload()
    await page.locator('input[value="Delivery manager"]').waitFor({ timeout: 10000 })  // the form fills in once /me has loaded
    check((await page.getByLabel('Job title').inputValue()) === 'Delivery manager', 'profile details are kept after a reload')
    await page.getByRole('button', { name: 'Account menu' }).click()
    await page.getByRole('menuitem', { name: 'Preferences' }).click()
    await page.getByRole('heading', { name: 'Preferences' }).waitFor()
    await page.getByLabel('Compact tables').check()
    await page.getByText('Saved.').waitFor()
    await shot(page, '35-preferences')
    await page.getByLabel('Compact tables').uncheck()
    // sidebar log out
    await page.getByRole('button', { name: 'Log out' }).click()
    await page.getByRole('button', { name: 'Sign in' }).waitFor()
    check(true, 'Log out in the sidebar returns to the sign-in page')
    await ctx.close()
    // phone: the sidebar opens over the page from the same button
    const ph = await login(browser, 'priya', { width: 390, height: 844 })
    await ph.page.getByRole('button', { name: 'Show navigation' }).click()
    await ph.page.getByRole('link', { name: 'Tasks' }).waitFor()
    check(true, 'the sidebar toggle works on a phone')
    await ph.ctx.close()
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

    // 4) person filter on Reports
    await page.getByRole('link', { name: 'Reports', exact: true }).click()
    await page.waitForSelector('iframe')
    await page.getByRole('combobox', { name: /^Person/ }).click()
    await page.getByRole('option', { name: 'Divya Iyer' }).click()
    await page.waitForTimeout(1200)
    const rep = await page.frameLocator('iframe').locator('body').innerText()
    check(rep.includes('Divya Iyer') && !rep.includes('Arjun Das'), 'Reports person filter narrows the report to one person')
    await shot(page, '24-report-person-filter')
    await ctx.close()
  }

  // ---------------------------------------------------------------- the LLM is environment-only: nothing in the UI
  {
    const { ctx, page } = await login(browser, 'asha')
    await page.getByRole('link', { name: 'Settings' }).click()
    await page.getByLabel('Company name').waitFor()
    for (const tab of ['Company', 'Task fields', 'Notification log']) {
      await page.getByRole('tab', { name: tab }).click()
      const text = await page.locator('main').innerText()
      check(!/anthropic|openai|gemini|claude|api key|llm/i.test(text), `Settings → ${tab} does not expose an LLM provider or key`)
    }
    await ctx.close()
  }

  // ---------------------------------------------------------------- GitLab-style task panel, Testing status, check-ins
  {
    const { ctx, page } = await login(browser, 'priya')
    await page.getByRole('link', { name: 'Tasks' }).click()
    await page.waitForSelector('tbody tr')
    await page.getByPlaceholder('Search tasks').fill('Cart discount')
    await page.getByText('Cart discount rules').click()
    await page.getByRole('heading', { name: 'Activity' }).waitFor()
    // status menu has Testing
    await page.getByRole('combobox', { name: 'Status' }).click()
    const statuses = await page.getByRole('option').allInnerTexts()
    check(['To do', 'In progress', 'In review', 'Testing', 'Blocked', 'Done'].every((n) => statuses.some((o) => o.includes(n))), `status menu: ${statuses.join(' | ')}`)
    await page.getByRole('option', { name: 'Testing' }).click()
    await page.getByText('changed status from').first().waitFor()
    check((await page.locator('.MuiDrawer-paperAnchorRight').innerText()).includes('Testing'), 'moving a task to Testing is recorded in the activity feed')
    // rich comment editor: toolbar + preview + internal note
    await page.getByLabel('Comment', { exact: true }).fill('Ready for QA: ')
    await page.getByRole('button', { name: 'Bold' }).click()
    await page.keyboard.type('please check checkout')
    await page.getByRole('tab', { name: 'Preview' }).click()
    const bold = page.locator('.MuiDrawer-paperAnchorRight strong').filter({ hasText: 'please check checkout' })
    await bold.first().waitFor({ timeout: 8000 }).catch(() => undefined)  // the preview renders a moment after the tab switch (slower on CI)
    check((await bold.count()) >= 1, 'toolbar inserts markdown and Preview renders it')
    await page.getByRole('tab', { name: 'Write' }).click()
    await page.getByLabel('Make this an internal note').check()
    await shot(page, '27-task-panel')
    await page.getByRole('button', { name: 'Add internal note' }).click()
    await page.getByText('Internal note', { exact: true }).waitFor()
    check(true, 'internal notes are marked in the feed')
    await page.getByLabel('Filter activity').click()
    await page.getByRole('option', { name: 'History only' }).click()
    check((await page.getByText('Internal note', { exact: true }).count()) === 0, 'History-only filter hides comments')
    await page.getByLabel('Filter activity').click()
    await page.getByRole('option', { name: 'All activity' }).click()
    await page.getByRole('button', { name: 'Close issue' }).click()
    await page.getByRole('button', { name: 'Reopen issue' }).waitFor()
    check(true, 'Close issue marks the task done and offers Reopen')
    await page.getByRole('button', { name: 'Reopen issue' }).click()
    await page.getByRole('button', { name: 'Close issue' }).waitFor()
    await page.getByLabel('Close').click()

    // team check-ins page + report section
    await page.getByRole('link', { name: 'Check-ins' }).click()
    await page.getByText('Morning plans').first().waitFor()
    await page.getByText('Check-in log').waitFor()
    await page.getByRole('cell', { name: 'Karthik Rao' }).first().waitFor() // rows loaded
    check((await page.locator('tbody tr').count()) >= 5, 'Check-ins page lists the team log')
    check((await page.locator('tbody').innerText()).includes('Waiting on payment sandbox credentials.'), 'blockers show in the check-in log')
    await shot(page, '28-check-ins')
    await page.getByRole('link', { name: 'Reports', exact: true }).click()
    await page.waitForSelector('iframe')
    await page.waitForTimeout(1200)
    const rep = await page.frameLocator('iframe').locator('body').innerText()
    check(rep.includes('Daily check-ins') && rep.includes('Karthik Rao'), 'weekly report tracks morning and end-of-day check-ins')
    await ctx.close()
  }

  // ---------------------------------------------------------------- project visibility report + Markdown downloads
  {
    const { ctx, page } = await login(browser, 'priya')
    await page.getByRole('link', { name: 'Reports', exact: true }).click()
    await page.waitForSelector('iframe')
    await page.getByRole('tab', { name: /Project visibility/ }).click()
    await page.waitForTimeout(1500)
    const frame = page.frameLocator('iframe')
    const text = await frame.locator('body').innerText()
    check(text.includes('Project Visibility Report') && text.includes('Sprint Goal & Objectives') && text.includes('Combined Sprint Health Dashboard'), 'visibility report renders in the agreed layout')
    check((await frame.locator('svg').count()) >= 3 && (await frame.locator('.flow .node').count()) >= 3, 'charts and the workflow are drawn (SVG), not mermaid source')
    await shot(page, '29-visibility-report')
    // download as Markdown
    await page.getByRole('button', { name: 'Markdown' }).click()
    const link = page.getByRole('link', { name: 'Download' })
    await link.waitFor({ timeout: 60000 })
    const md = await (await page.request.get(await link.getAttribute('href').then((h) => new URL(h, BASE).toString()))).text()
    check(md.includes('# 📊 Project Visibility Report —') && md.includes('```mermaid') && md.includes('| 🎯 Planned Tasks | ✅ Completed |'), 'the .md export contains the visibility layout with mermaid charts')

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
