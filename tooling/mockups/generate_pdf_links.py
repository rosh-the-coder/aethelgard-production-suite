import os
import sys
import json
import asyncio

# Pin browsers to the suite cache before Playwright imports resolve paths.
_HERE = os.path.dirname(os.path.abspath(__file__))
_BROWSERS = os.path.abspath(os.path.join(_HERE, "..", "ad-creatives", ".playwright-browsers"))
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _BROWSERS

from playwright.async_api import async_playwright

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Download Your Art - {title}</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;800&family=Plus+Jakarta+Sans:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        body {{
            font-family: 'Plus Jakarta Sans', sans-serif;
            background-color: #fafafa;
            color: #1f2937;
            margin: 0;
            padding: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            -webkit-print-color-adjust: exact;
        }}
        .container {{
            background-color: #ffffff;
            width: 100%;
            max-width: 650px;
            padding: 50px;
            border-radius: 16px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.05);
            border: 1px solid #f3f4f6;
            box-sizing: border-box;
            text-align: center;
        }}
        .shop-name {{
            font-family: 'Outfit', sans-serif;
            font-size: 1.15rem;
            font-weight: 600;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            color: #3d4a3f;
            margin-bottom: 25px;
        }}
        h1 {{
            font-family: 'Outfit', sans-serif;
            font-size: 2.25rem;
            font-weight: 800;
            color: #111827;
            margin-bottom: 15px;
            line-height: 1.2;
        }}
        .divider {{
            height: 2px;
            width: 60px;
            background-color: #8b7355;
            margin: 20px auto 25px auto;
        }}
        p {{
            font-size: 1.05rem;
            line-height: 1.6;
            color: #4b5563;
            margin-bottom: 30px;
        }}
        .btn {{
            display: inline-block;
            background-color: #1f2937;
            color: #ffffff !important;
            text-decoration: none;
            padding: 16px 32px;
            border-radius: 12px;
            font-weight: 600;
            font-size: 1.1rem;
            margin: 10px 0 25px 0;
            transition: background-color 0.2s ease;
            box-shadow: 0 4px 12px rgba(17, 24, 39, 0.15);
        }}
        .btn:hover {{
            background-color: #111827;
        }}
        .instructions {{
            text-align: left;
            background-color: #f9fafb;
            border: 1px solid #f3f4f6;
            border-radius: 12px;
            padding: 24px;
            margin-top: 35px;
        }}
        .instructions h3 {{
            font-family: 'Outfit', sans-serif;
            font-size: 1.1rem;
            font-weight: 600;
            margin-top: 0;
            margin-bottom: 12px;
            color: #111827;
        }}
        .instructions ol {{
            margin: 0;
            padding-left: 20px;
            color: #4b5563;
            font-size: 0.95rem;
        }}
        .instructions li {{
            margin-bottom: 10px;
            line-height: 1.5;
        }}
        .footer {{
            margin-top: 40px;
            font-size: 0.85rem;
            color: #9ca3af;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="shop-name">Aethelgard Art Co.</div>
        <h1>Your Art is Ready!</h1>
        <div class="divider"></div>
        <p>
            Thank you for supporting Aethelgard Art Co.! Click the button below to access your high-resolution 300 DPI print files for <strong>{title}</strong>.
        </p>
        
        <a href="{drive_link}" class="btn" target="_blank">Download Art Files</a>
        
        <div class="instructions">
            <h3>How to print your art:</h3>
            <ol>
                <li>Click the download button above to access the Google Drive folder containing all print sizes.</li>
                <li>Download the aspect ratio file that matches your frame size (refer to the file names for size options).</li>
                <li>Print at home, upload to an online printing service (like Shutterfly, Printful, Mpix), or visit a local print shop (Staples, Walgreens, Costco).</li>
            </ol>
        </div>
        
        <div class="footer">
            Need help? Message Aethelgard Art Co. on Etsy.
        </div>
    </div>
</body>
</html>
"""

async def generate_pdf(title, drive_link, output_pdf_path):
    """
    Generate PDF with links using Playwright.
    Uses set_content (not file://) so long Windows paths still work.
    Writes via a short temp path first — Acrobat/Etsy choke on 260+ char paths.
    """
    import tempfile
    import shutil

    html_content = HTML_TEMPLATE.format(title=title, drive_link=drive_link)
    out_abs = os.path.abspath(output_pdf_path)
    os.makedirs(os.path.dirname(out_abs), exist_ok=True)

    try:
        with tempfile.TemporaryDirectory(prefix="aethelgard_pdf_") as tmp:
            tmp_pdf = os.path.join(tmp, "Download_Links.pdf")
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                page = await browser.new_page()
                await page.set_content(html_content, wait_until="load")
                try:
                    await page.evaluate("document.fonts.ready")
                except Exception:
                    pass
                await page.pdf(
                    path=tmp_pdf,
                    format="A4",
                    print_background=True,
                    margin={"top": "0mm", "bottom": "0mm", "left": "0mm", "right": "0mm"}
                )
                await browser.close()

            # Extended-length path copy for deep artwork-runs folders on Windows
            dest = out_abs
            if os.name == "nt" and not dest.startswith("\\\\?\\"):
                dest = "\\\\?\\" + dest
            src = tmp_pdf
            if os.name == "nt" and not src.startswith("\\\\?\\"):
                src = "\\\\?\\" + os.path.abspath(tmp_pdf)
            shutil.copy2(src, dest)

        print(f"Generated PDF download links -> {output_pdf_path}")
        return True
    except Exception as e:
        print(f"Error generating PDF: {e}")
        return False


def main():
    if len(sys.argv) < 3:
        print("Usage: python generate_pdf_links.py <piece_directory_path> <google_drive_folder_link>")
        sys.exit(1)

    piece_dir = sys.argv[1]
    drive_link = sys.argv[2]

    meta_path = os.path.join(piece_dir, "meta.json")
    if not os.path.exists(meta_path):
        print(f"Error: meta.json not found in {piece_dir}")
        sys.exit(1)

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    title = meta.get("title", "Digital Art Print")
    # Short fixed name — long slug filenames blow past Windows MAX_PATH / Acrobat.
    output_pdf = os.path.join(piece_dir, "Download_Links.pdf")

    # Also keep a short-path copy for easy opening during dry-runs.
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    delivery_dir = os.path.join(root, "_delivery")
    os.makedirs(delivery_dir, exist_ok=True)
    slug = (meta.get("slug") or "art").replace(" ", "-")[:40]
    short_pdf = os.path.join(delivery_dir, f"{slug}-Download_Links.pdf")

    ok = asyncio.run(generate_pdf(title, drive_link, output_pdf))
    if ok:
        try:
            import shutil
            shutil.copy2(output_pdf, short_pdf)
        except Exception as e:
            print(f"Warning: could not write short delivery copy: {e}")
            short_pdf = None
        meta["pdf_path"] = output_pdf.replace("\\", "/")
        if short_pdf:
            meta["pdf_path_short"] = short_pdf.replace("\\", "/")
        meta["drive_link"] = drive_link
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        print("__PDF_RESULT__" + json.dumps({
            "success": True,
            "pdf_path": meta["pdf_path"],
            "pdf_path_short": meta.get("pdf_path_short"),
        }))
        sys.exit(0)
    print("__PDF_RESULT__" + json.dumps({"success": False}))
    sys.exit(1)


if __name__ == "__main__":
    main()
