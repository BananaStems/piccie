# Troubleshooting

Find the message you see, or the problem you have, and follow the fix.

## Wi-Fi and setup

**"No Wi-Fi networks found."**
Move the booth closer to the router and select refresh. For a network that
doesn't show its name, use **Join a hidden network**.

**"Wi-Fi connected, but cloud access failed."**
The network has no internet, or it needs a sign-in page (common in hotels and
venues). Use a different network or a phone hotspot.

**The setup page won't open on my phone.**
Check that your phone is on the same Wi-Fi as the booth, not on mobile data. If
scanning doesn't work, type the address shown on the booth into the browser.
The setup code stops working once setup finishes or the booth restarts; open
a new one from **Settings → Operator access**.

**"Test and save" fails for cloud storage.**
Check the four values against [Cloudflare storage](cloudflare.md): Account ID,
Access Key ID, Secret Access Key and bucket name. The token needs **Object Read
& Write** on that bucket. Leave **Jurisdiction** on **Default** unless you chose
otherwise when creating the bucket.

**"Test and save" fails for the custom domain.**
In Cloudflare, the domain must be connected to `piccie-links` (not
`piccie-photos`) and show **Active**. New domains can take a few minutes. The
API token must also include `piccie-links`.

## During an event

**"Guest delivery is not ready" when I press Launch.**
Cloud storage isn't set up or can't be reached. Check Wi-Fi, then open
**Settings → Operator access → Open on phone or computer** and select **Test
and save** under cloud storage.

**"Upload pending" or "Guest download is temporarily unavailable."**
The booth is offline. Photos are safe on the booth and upload by themselves
when the connection returns. The guest's QR code works after that.

**"Upload failed."**
Piccie retries on its own. If it keeps failing, check Wi-Fi and the cloud
settings.

**Phones struggle to scan the QR code.**
Turn up the screen brightness and avoid glare. Without a custom domain, codes
are dense because the links are long. A
[custom domain](cloudflare.md#optional-short-links-with-your-own-domain) makes
the code much simpler.

**"Camera unavailable" or "Camera preview lost."**
Shut the booth down, check that the camera ribbon cable is pushed fully into
both connectors, then start it again.

**I can't get out of guest mode.**
Tap the bottom-right corner five times within two seconds, then enter your PIN.

**The event says "Concluded" and Launch is greyed out.**
Its end time has passed. Edit the event, set a later **Event ends**, and launch
again.

## After the event

**The share link stopped working.**
Links without a custom domain last seven days. Open the event's **Gallery →
Download all event strips** and select **New link**.

**"Storage low."**
The microSD card is nearly full. Delete old events you've already shared.

**"Storage fault. Photos and events will be lost after power-off."**
The booth can't write to its card safely. Share any photos you need, shut down,
and replace the card with a new high-endurance one. Card problems are the most
common cause.

## Still stuck?

Open an [issue](https://github.com/BananaStems/piccie/issues) with what you see
on the screen and what you tried. If you have SSH access, include the output of
`journalctl -u piccie-engine -n 200`.
