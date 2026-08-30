# Google Drive delivery setup

Automatic packaging under your [Etsy 2026 Drive folder](https://drive.google.com/drive/u/4/folders/1owjKwkil2H-7jli52jbkIhexxXclhkQk):

```text
Etsy 2026/
  00_Mockups_Private/          ← owner-only (never shared)
    {listing-slug}/
      mockup_*.jpg
  01_Customer_Delivery/        ← shareable listings
    {listing-slug}/            ← anyone-with-link (reader)
      prints / pack files      ← single: size JPGs; bundle: all pack images + sized prints
```

The customer folder share link is embedded into `Download_Links.pdf` (same PDF buyers get on Etsy).

## One-time Google Cloud setup

1. Open [Google Cloud Console](https://console.cloud.google.com/) → create or pick a project.
2. Enable **Google Drive API**.
3. **APIs & Services → Credentials → Create credentials → OAuth client ID**.
4. Application type: **Desktop app** (or Web with redirect below).
5. Add authorized redirect URI:
   `http://localhost:8080/api/drive/oauth/callback`
6. Download the JSON and save it as:
   `roshwillberich/tooling/upload/gdrive_client.json`

   Or put in `~/.config/ai-images/env`:

   ```text
   GOOGLE_DRIVE_CLIENT_ID=....apps.googleusercontent.com
   GOOGLE_DRIVE_CLIENT_SECRET=...
   GOOGLE_DRIVE_ROOT_FOLDER_ID=1owjKwkil2H-7jli52jbkIhexxXclhkQk
   ```

7. Restart the Production Suite.
8. Click **Connect Google Drive** and sign in with the Google account that owns the Etsy 2026 folder (the `u/4` account).

## Daily use

1. Open a listing in **Catalog & Listings**.
2. Click **Package to Drive & PDF**.
3. Suite creates/updates folders, uploads files, shares the customer folder, compiles the PDF with the link.
4. Then **Upload Draft (API)** as usual.

Manual paste fallback remains: **Paste link → PDF**.
