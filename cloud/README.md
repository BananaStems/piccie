# Piccie self-hosted event gallery

This Worker serves private, event-scoped galleries from your own R2 bucket. It
does not use a database, email provider, custom domain, or project-operated
service.

## Deploy

1. Install Node.js 20 or newer, then sign in to Cloudflare:

   ```bash
   cd cloud
   npm install
   npx wrangler login
   ```

2. Create the bucket named in `wrangler.toml`:

   ```bash
   npx wrangler r2 bucket create piccie-photos
   ```

3. Deploy the Worker:

   ```bash
   npm run deploy
   ```

   Keep the resulting `https://piccie-gallery.<account>.workers.dev` URL.

4. In Cloudflare R2, create an Object Read & Write API token restricted to the
   `piccie-photos` bucket. Enter its S3 credentials and the Worker URL during
   booth onboarding.

Keep the bucket private. The Worker only exposes objects after validating a
random share token created by the booth. Disable or regenerate a link from the
booth gallery when access should change.
