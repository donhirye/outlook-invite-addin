# Learning safety checklist

- [x] Separate folder from `whatsapp-hello-bot/`
- [x] Separate virtualenv (`learning/.venv`)
- [x] Separate `requirements.txt`
- [x] Mock FAQ data only by default
- [x] Private CSV gitignored
- [x] No Cloud Run deploy scripts in learning modules
- [x] Exercises do not import production GCS helpers by default

Never set learning env vars to production GCS buckets or live WhatsApp tokens unless you intentionally create a read-only experiment — and even then, prefer mocks.
