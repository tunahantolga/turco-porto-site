# Turco Porto

Website for Turco Porto, Turkish home cooking popping up around Porto: https://turcoporto.com

## How it runs

- `public/`: the site itself (`index.html`, `images/`, `robots.txt`, `sitemap.xml`, `llms.txt`, icons).
- `server.py`: a small Python server (standard library only). It serves `public/` and handles the private dinner and catering form at `POST /api/request`, emailing each request.
- `Dockerfile`: Outplane builds this and deploys from `main`. The app listens on port 8080.

## Form email settings

Set these as environment variables (secrets) in Outplane, never in the repo:

| Variable | Example |
| --- | --- |
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `587` (or `465` for SSL) |
| `SMTP_USER` | `hey@techsalestr.com` |
| `SMTP_PASS` | an app password for that mailbox |
| `MAIL_TO` | `hey@techsalestr.com` (default) |

Without them the form still works: the server logs the request and the page falls back to opening the visitor's email app. Every request is also written to the app logs, so nothing is lost if sending fails. `GET /api/health` shows whether email is configured.

Spam protection: a hidden honeypot field and a limit of 5 requests per hour per visitor.
