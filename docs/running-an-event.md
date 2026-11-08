# Running an event

Each party is an **event** on the booth. An event keeps its own strips, its own
gallery and its own share link.

## Before the day

- Find a power socket where the booth will stand. It runs on mains power, not
  a battery.
- Check the venue's Wi-Fi. If it has a sign-in page, bring a phone hotspot
  instead. Without internet, the booth still takes photos and uploads them
  later, but guests can't download until it's back online.
- Run the [soak test](advanced.md#run-the-soak-test) if the booth is new or
  has changed.

## 1. Create the event

1. On the main menu, select **Create a new event**, type a name and select
   **Create**.
2. Fill in what prints on the strip:
   - **Heading** and **Subheading**, for example "Sarah & James" and "Our
     wedding".
   - **Event date**, and turn on **Date on strip** if you want it printed.
3. Set **Event ends**. At that time the booth leaves guest mode by itself, so
   it can't be left running.
4. Choose a **Template**. To make your own, see [Templates](templates.md).
5. Select **Create**.

## 2. Choose the look

Open **Settings** on the main menu. Under **Photo**, pick a look (Clean, Soft,
Warm, Mono or Bold) and set its strength. The live preview shows the result.
**Camera** and **Focus** fine-tune exposure, white balance and focus if the
light is tricky.

## 3. Launch

Select **Launch** on the event. The booth shows "Tap to start" and is ready for
guests.

What guests do:

1. Tap the screen.
2. Smile for three photos. A ring counts down before each one.
3. Scan the QR code to download the strip to their phone, or tap to start
   again.

If the Wi-Fi drops, guests see that their photo is safe. It uploads by itself
when the connection returns, and the same QR code then works.

## 4. Get back to the menu

Tap the **bottom-right corner of the screen five times quickly**, then enter
your PIN. Guests can't leave guest mode without it.

## 5. Share all the photos

1. On the event, select **Gallery**. Every strip is there.
2. Select **Download all event strips**.
3. Scan the QR code or select **Copy link**. Anyone with the link can download
   one ZIP with every strip and every original photo.

Without a custom domain, this link lasts seven days. To share it again later,
open the same screen and select **New link**. Select **Disable** to stop the
link working.

## 6. Tidy up

- **Delete a strip:** open it in the gallery and select **Delete strip**.
- **Clear photos:** in the event's settings, **Clear photos** removes every
  strip but keeps the event.
- **Delete the event:** removes the event and its photos from the booth and
  from your cloud storage.

To reuse an event after its end time, edit **Event ends** and launch it again.

## 7. Shut down safely

Select **Power** on the main menu, then **Shut down**. Wait until the screen is
black and the green light on the Raspberry Pi has stopped flashing before you
unplug it.

The booth is built to survive a pulled plug, but a proper shutdown is always
safer for the photos still being saved.
