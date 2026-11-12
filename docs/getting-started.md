# Getting started

This guide takes you from a blank microSD card to your first photo strip. It
takes about 30 minutes, most of it waiting for downloads.

## What you need

- The booth, or at least a Raspberry Pi 4 with the touchscreen, camera and fan
  connected. See [Hardware](hardware.md).
- A **32 GB high-endurance microSD card** rated A2/U3. Ordinary cards wear out
  quickly when a booth writes photos all night.
- A computer with [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
  and a card reader.
- **Wi-Fi with internet access.** Networks with a sign-in page, like many
  hotels and venues, won't work. A phone hotspot does.
- A phone or computer on the same Wi-Fi as the booth, to finish setup.
- A Cloudflare storage bucket and key. You can make them now with
  [Cloudflare storage](cloudflare.md), or during step 4.

## 1. Download the image

Open the [latest release](https://github.com/BananaStems/piccie/releases/latest)
and download the file ending in `-arm64.img.xz`. Don't unzip it; Raspberry Pi
Imager reads it as it is.

Want to build the image yourself instead? See [Advanced](advanced.md#build-the-image-yourself).

## 2. Flash the card

1. Put the microSD card in your computer and open Raspberry Pi Imager.
2. For **Device**, choose **Raspberry Pi 4**.
3. For **Operating system**, scroll down, choose **Use custom**, and pick the
   file you downloaded.
4. For **Storage**, choose your microSD card. Check it carefully: everything on
   it will be erased.
5. Select **Next**. When Imager offers to customise the operating system,
   choose **No**. Piccie asks for Wi-Fi on its own screen.
6. Wait until Imager says the card is verified, then remove it.

## 3. Turn it on and pick Wi-Fi

1. Put the card in the Raspberry Pi and plug in the power.
2. Wait. On the very first start, Piccie prepares the card and **restarts once
   by itself**. Don't unplug it during this restart.
3. Choose your Wi-Fi network on the touchscreen and type its password. This is
   the only thing you ever type on the booth.

## 4. Finish setup on your phone

The booth now shows a QR code, a web address such as
`http://192.168.1.145:8080/setup.html`, and an eight-character setup code.

1. Scan the QR code with your phone. On a computer, type the address into a
   browser and enter the code. Your phone or computer must be on the same
   Wi-Fi as the booth. Do this on a Wi-Fi you trust, such as your home
   network: the setup page sends your storage keys to the booth unencrypted.
2. **Cloud storage.** Paste the Account ID, Access Key ID, Secret Access Key
   and bucket name from [Cloudflare storage](cloudflare.md). Select **Test and
   save**. Piccie uploads a test strip and downloads it again before it saves
   anything.
3. **Custom domain** (optional). If you set up your own domain for short links,
   enter it and the public bucket name, then select **Test and save**. You can
   skip this and add it later.
4. **Operator PIN.** Choose four digits. You'll need them to leave guest mode
   and to change settings.
5. **SSH public key** (optional). Only needed if you want to update the booth
   from a computer. See [Advanced](advanced.md#update-over-wi-fi).
6. Select **Finish setup**. The booth runs a last check and opens its main
   menu.

The setup page talks to the booth over your local network without encryption,
so do this on a network you trust, like your home Wi-Fi. The code stops working
once setup finishes or the booth restarts.

## 5. Take a test strip

1. Select **Create a new event**, name it "Test" and select **Create**. Pick
   today's date and an end time later today, then select **Create** again.
2. Select **Launch**, tap the screen, and take a strip.
3. Turn Wi-Fi off on your phone and scan the QR code using mobile data. The
   strip should download. If it does, guests at any venue can get their photos.
4. To get back to the menu, tap the **bottom-right corner five times quickly**
   and enter your PIN.

That's it: your booth is ready. Next, read [Running an event](running-an-event.md).

Before the first real event, also run the eight-hour
[soak test](advanced.md#run-the-soak-test). It catches overheating, a weak power
supply or a flaky card while there's still time to fix them.

## Changing settings later

To replace the cloud keys, add or remove the custom domain, or change the SSH
key:

1. On the booth, open **Settings → Operator access**.
2. Select **Open on phone or computer** and scan the code.
3. Make the change on your phone. The link stops working when you close the
   code on the booth.

Change the PIN on the booth itself, in the same section. Change Wi-Fi from the
Wi-Fi button on the main menu.
