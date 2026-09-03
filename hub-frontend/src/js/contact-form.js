// EVOSHUB — Contact Form
const submit = document.querySelector('.form-submit')
const form   = document.querySelector('.contact-form')

submit?.addEventListener('click', async () => {
  const name     = form.querySelector('[name="name"]').value.trim()
  const email    = form.querySelector('[name="email"]').value.trim()
  const message  = form.querySelector('[name="message"]').value.trim()
  const honeypot = form.querySelector('[name="website"]').value

  if (honeypot) return // silently do nothing — bot filled the trap field

  if (!name || !email || !message) { alert('Please fill in all fields.'); return }

  submit.textContent = 'Sending…'
  submit.disabled = true

  try {
    const apiBase = import.meta.env.VITE_API_BASE_URL
    const res = await fetch(`${apiBase}/api/contact`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, email, message, website: honeypot || null }),
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data.detail || `request_failed_${res.status}`)

    submit.textContent = '✓ Message Sent!'
    submit.style.background = 'var(--green)'
    form.reset()
  } catch (err) {
    console.error('[contact-form] submit failed', err)
    const msg = String(err.message || '')
    submit.textContent = msg.includes('429') ? 'Too many messages — try later' : 'Failed — try again'
    submit.style.background = '#c0392b'
  } finally {
    setTimeout(() => {
      submit.textContent = 'Send Message'
      submit.disabled = false
      submit.style.background = ''
    }, 3000)
  }
})
