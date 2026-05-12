# LSuite — authusers Update

## What's added

- **Social Links** — users can add/edit/delete links (LinkedIn, GitHub, portfolio, etc.) from their profile page via a new tab.
- **Password Reset** — email-based reset flow for logged-out users. Change password (while logged in) was already there and is unchanged.

## Files

```
apps/authusers/
├── models.py                        # SocialLink model
├── views.py                         # All views incl. social links + reset
├── urls.py                          # Updated URL patterns
└── migrations/0001_initial.py       # Creates social_link table

templates/auth/
├── profile.html                     # Now has Account Info + Social Links tabs
├── password_reset.html              # Email form
├── password_reset_done.html         # "Check your inbox"
├── password_reset_confirm.html      # Set new password form
├── password_reset_complete.html     # Success page
└── email/password_reset.txt         # Email body (plain text)
```

## Setup

```bash
python manage.py migrate
```

Add to your `settings.py` for email to work:

```python
EMAIL_BACKEND   = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST      = 'smtp.gmail.com'        # or your provider
EMAIL_PORT      = 587
EMAIL_USE_TLS   = True
EMAIL_HOST_USER = 'you@example.com'
EMAIL_HOST_PASSWORD = 'your-app-password'
DEFAULT_FROM_EMAIL  = 'LSuite <you@example.com>'
```

For local dev/testing use the console backend instead:

```python
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
```

## Login template — add reset link

In `templates/auth/login.html`, add under the login button:

```html
<p class="text-center mt-2">
  <a href="{% url 'authusers:password_reset' %}" class="small text-muted">Forgot password?</a>
</p>
```
