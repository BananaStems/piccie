# Piccie self-hosted event gallery

This Cloudflare Worker serves private, event-scoped galleries from your own R2
bucket. The booth receives a narrowly scoped upload credential; it does not
receive a Cloudflare API token or your R2 account keys.

## Deploy

[![Deploy to Cloudflare](https://deploy.workers.cloudflare.com/button)](https://deploy.workers.cloudflare.com/?url=https://github.com/BananaStems/piccie/tree/main/cloud)

1. Select **Deploy to Cloudflare** and sign in to your own Cloudflare account.
2. Create a unique setup key when prompted. Use at least 24 characters and keep
   it available until the booth is paired.
3. Wait for Cloudflare to create the private `photobooth` R2 bucket and deploy
   the Worker.
4. Copy the resulting `https://piccie-gallery.<account>.workers.dev` URL.
5. On Piccie's first-boot phone setup page, enter that Worker URL and the setup
   key, then select **Connect gallery**.

The Worker accepts the setup key from a private-network Piccie setup page only.
It atomically claims the key for one booth, returns a booth-only credential,
and stores only that credential's SHA-256 digest. Safe retries from the same
phone setup session return the same credential. A different booth cannot reuse
the key.

Piccie uploads and retrieves a temporary private test strip before onboarding
can complete. Keep the bucket private; public access is provided only through
random, revocable event and strip links validated by the Worker.

## Command-line deployment

For development or a customized Worker:

```bash
cd cloud
npm install
npx wrangler login
npx wrangler r2 bucket create photobooth
npx wrangler secret put PICCIE_SETUP_KEY
npm run deploy
```

The setup key must be at least 24 characters. Do not add `.dev.vars` or the key
itself to Git.

## Pair a replacement booth

The one-time claim deliberately prevents an old setup key from silently adding
another uploader. To replace the booth:

1. Delete `setup/claimed.json` from the Worker's `photobooth` R2 bucket in the
   Cloudflare dashboard.
2. Delete the previous booth object under `booths/` to revoke its credential.
   If you cannot identify it, delete all existing objects under `booths/`
   before pairing the replacement.
3. Rotate `PICCIE_SETUP_KEY` in **Workers & Pages → piccie-gallery → Settings →
   Variables and Secrets**.
4. Pair the replacement booth using the new key.

These reset steps are only needed when deliberately replacing or revoking a
booth. Normal image upgrades preserve the credential in Piccie's data
partition.
