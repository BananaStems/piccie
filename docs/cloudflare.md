# Cloudflare storage

Piccie sends every finished strip to storage in **your own** Cloudflare
account, using a service called R2. Guests download their strip from there, so
their phones never need to connect to the booth.

You need two things: a **bucket** (a folder in the cloud) and an **API token**
(a key that lets the booth upload to it). This takes about five minutes.

R2's free tier includes 10 GB of storage, which is plenty for most parties.
Cloudflare asks for a payment method before it turns R2 on, even on the free
tier.

## 1. Create the bucket

1. Sign in to the [Cloudflare dashboard](https://dash.cloudflare.com/), or
   create a free account.
2. Open **Storage & databases → R2** and create a bucket named
   `piccie-photos`. Leave it **private**.
3. Planning to use your own domain (see below)? Create a second bucket named
   `piccie-links` now as well, so one token covers both.

## 2. Create the API token

1. On the R2 **Overview** page, find **Account Details → API Tokens** and select
   **Manage**.
2. Create an **Account API token** with **Object Read & Write** permission.
3. Under bucket access, choose **only** the bucket(s) you just created.
4. Copy these into a note:
   - Account ID
   - Access Key ID
   - Secret Access Key (Cloudflare shows it only once)

Leave **Jurisdiction** set to **Default** in Piccie unless you created the
bucket in the EU or FedRAMP jurisdiction.

You'll paste these on the booth's setup page in
[Getting started](getting-started.md#4-finish-setup-on-your-phone).

## How guest links work

Without a domain, Piccie makes **signed links**: long, private links that work
for seven days, which is the longest Cloudflare allows. They work well, but the
QR code is dense (73 × 73 squares). If an older event needs sharing again, make
a new link from the event gallery on the booth.

## Optional: short links with your own domain

With your own domain, links look like `https://piccie.link/a1b2c3/d4e5f6g7h8`.
They never expire and fit in a small 29 × 29 QR code that scans easily from a
distance. A domain costs a few dollars a year.

1. **Buy a domain** in the same Cloudflare account: **Domain Registration →
   Register Domains**. Cloudflare charges cost price. A domain bought elsewhere
   also works once its DNS is moved to Cloudflare. Avoid spam-heavy endings
   such as `.bid`, `.win` or `.loan`, which phones and venue networks often
   block.
2. **Connect it to `piccie-links`:** open **R2 → piccie-links → Settings →
   Custom Domains**, select **Add**, and enter the domain (or a subdomain such
   as `photos.example.com`). Wait until it shows **Active**.
3. **Make sure the token covers `piccie-links`.** If you made the token before
   this bucket existed, edit it and add the bucket.
4. **Tell the booth.** Open **Settings → Operator access → Open on phone or
   computer**, enter the domain and `piccie-links` under **Custom domain**, and
   select **Test and save**.

> [!WARNING]
> Never connect a domain to `piccie-photos`. A domain makes a bucket public,
> and `piccie-photos` uses readable names that anyone could guess. Piccie
> refuses a domain that shows anything from `piccie-photos`.

With a domain on, Piccie copies each finished strip, event gallery and event
ZIP into `piccie-links` under random names that can't be guessed or listed.
Anyone with the link can open it. When you delete a strip or an event on the
booth, the public copies go too.

## Where your photos are stored

Everything is organised by event, so it's easy to browse in the Cloudflare
dashboard. An event called "Sarah & James" on 14 June 2026 looks like this:

```text
sarah-james-2026-06-14/
├── strips/
│   ├── sarah-james-strip-00001.jpg
│   └── sarah-james-strip-00002.jpg
├── photos/
│   ├── sarah-james-strip-00001-photo-01.jpg
│   ├── sarah-james-strip-00001-photo-02.jpg
│   └── sarah-james-strip-00001-photo-03.jpg
└── download-all.zip
```

- `strips/` holds the finished strips; `photos/` holds the three original
  photos behind each one.
- Strip numbers start at `00001` and are never reused, even after a deletion.
- If two events would get the same folder name, Piccie adds `-2`, `-3` and so
  on.
