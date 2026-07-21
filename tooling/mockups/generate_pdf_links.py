import os
import sys
import json
import asyncio
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
            font-size: 1.25rem;
            font-weight: 600;
            letter-spacing: 0.1em;
            text-transform: uppercase;
            color: #6366f1;
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
            background-color: #6366f1;
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
            background-color: #111827;
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
            background-color: #1f2937;
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
        <div class="shop-name">Digital Art Collective</div>
        <h1>Your Art is Ready!</h1>
        <div class="divider"></div>
        <p>
            Thank you so much for your purchase! Click the button below to access your high-resolution 300 DPI print files for <strong>{title}</strong>.
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
            Need help? Contact us via Etsy messages!
        </div>
    </div>
</body>
</html>
"""

async def generate_pdf(title, drive_link, output_pdf_path):
    """
    Generate PDF with links using Playwright.
    """
    html_content = HTML_TEMPLATE.format(title=title, drive_link=drive_link)
    
    # Save temp HTML file
    temp_html_path = output_pdf_path + ".temp.html"
    with open(temp_html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            
            # Open local temp html file
            abs_url = "file://" + os.path.abspath(temp_html_path).replace("\\", "/")
            await page.goto(abs_url)
            
            # Wait for fonts to load
            await page.evaluate("document.fonts.ready")
            
            # Print to PDF
            # A4 size, margins
            await page.pdf(
                path=output_pdf_path,
                format="A4",
                print_background=True,
                margin={"top": "0mm", "bottom": "0mm", "left": "0mm", "right": "0mm"}
            )
            await browser.close()
            
        print(f"Generated PDF download links -> {output_pdf_path}")
        return True
    except Exception as e:
        print(f"Error generating PDF: {e}")
        return False
    finally:
        # Cleanup temp HTML file
        if os.path.exists(temp_html_path):
            os.remove(temp_html_path)

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
    output_pdf = os.path.join(piece_dir, f"Download_Links_{meta.get('slug', 'art')}.pdf")
    
    ok = asyncio.run(generate_pdf(title, drive_link, output_pdf))
    if ok:
        meta["pdf_path"] = output_pdf.replace("\\", "/")
        meta["drive_link"] = drive_link
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        print("__PDF_RESULT__" + json.dumps({"success": True, "pdf_path": meta["pdf_path"]}))
        sys.exit(0)
    print("__PDF_RESULT__" + json.dumps({"success": False}))
    sys.exit(1)

if __name__ == "__main__":
    main()
