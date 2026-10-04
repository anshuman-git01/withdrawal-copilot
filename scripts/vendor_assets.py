"""Download HTMX and Alpine into app/static/vendor for a fully offline demo.

Run once while online:  python scripts/vendor_assets.py
The app then serves them locally automatically (restart the server).
"""
import pathlib
import urllib.request

FILES = {
    "htmx.min.js": "https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js",
    "alpine.min.js": "https://cdn.jsdelivr.net/npm/alpinejs@3.14.8/dist/cdn.min.js",
}
out = pathlib.Path(__file__).resolve().parent.parent / "app" / "static" / "vendor"
out.mkdir(parents=True, exist_ok=True)
for name, url in FILES.items():
    print("Downloading", url)
    urllib.request.urlretrieve(url, out / name)
print("Saved to", out)
