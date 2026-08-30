# Email Notifications

Configured in Presets & Settings. Password **only** from env:

```
AETHELGARD_SMTP_PASSWORD
```

Optional env overrides: `AETHELGARD_SMTP_HOST`, `AETHELGARD_SMTP_PORT`, `AETHELGARD_SMTP_USERNAME`, `AETHELGARD_SMTP_SENDER`, `AETHELGARD_SMTP_RECIPIENT`.

Completion email sends when a batch reaches a terminal state. Email failure is recorded separately and does **not** fail production.
