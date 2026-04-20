# Phase 8 – Sub-Agent Prompt Index

> Each prompt is a self-contained file in `prompts/`. Paste into a fresh Cascade session.  
> **Execution order matters** — each prompt may depend on the one before it.

---

## Prompts

| # | File | Scope | Depends on |
|---|------|-------|------------|
| 1 | `prompts/PROMPT_1_ACCOUNTS_OVERHAUL.md` | Backend + frontend: password column, type filter, CSV template, edit/delete, auto-downgrade | None |
| 2 | `prompts/PROMPT_2_CAPTCHA_CHALLENGE.md` | Backend + frontend: Challenge model, detection in stream worker, Telegram alert, dashboard page | Prompt 1 |
| 3 | `prompts/PROMPT_3_TEMPMAIL_REGISTRATION.md` | Backend + frontend: mail.tm integration, registration service, register endpoint | Prompt 1 |
| 4 | `prompts/PROMPT_4_PROXY_PROVIDER.md` | Backend + frontend: Webshare.io integration, auto-provision/burn, lifecycle wiring | Prompt 1 |

## Workflow

1. **Paste prompt** into a fresh Cascade session
2. Sub-agent implements all parts
3. **Return to lead session** (this one) — paste results or report issues
4. Lead audits, fixes bugs, approves
5. Move to next prompt

## Testing Checklist

- [ ] Accounts page: password column, eye toggle, type filter, edit dialog, CSV template download
- [ ] Auto-downgrade: premium → free on shuffle miss
- [ ] Challenges: model, detection, Telegram alert, dashboard page, resolve flow
- [ ] TempMail: mailbox creation, message polling, OTP/link extraction, registration flow
- [ ] Proxy: auto-provision on account create/import, burn on delete/ban, replace endpoint
