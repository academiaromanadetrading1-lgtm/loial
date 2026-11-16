"""Installable Loial Black Metal PWA, without Apple or Google Wallet.

Public endpoints only serve static app shell and icons. Customer data is always
fetched with the private wallet token and NEVER cached by the service worker.
"""
from functools import lru_cache
from io import BytesIO

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from PIL import Image, ImageDraw, ImageFont


def _font(px, bold=False):
    try:
        return ImageFont.truetype(
            "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf", px)
    except OSError:
        return ImageFont.load_default()


@lru_cache(maxsize=4)
def metal_icon(size: int, maskable: bool = False) -> bytes:
    if size not in (192, 512):
        raise ValueError("Unsupported PWA icon size")
    im = Image.new("RGB", (size, size), (10, 11, 15))
    p = im.load()
    # Brushed metallic gradient with restrained gold accents.
    for y in range(size):
        for x in range(size):
            beam = max(0.0, 1.0 - abs((x / size) - .32) * 3.1)
            v = int(9 + 28 * beam + ((y // max(1, size // 115)) % 3))
            p[x, y] = (v, v + 1, v + 3)
    d = ImageDraw.Draw(im)
    margin = int(size * (.13 if not maskable else .18))
    d.rounded_rectangle((margin, margin, size - margin, size - margin),
                        radius=int(size * .17),
                        outline=(207, 178, 113), width=max(3, size // 115))
    # Emblem represents loyalty / membership, NOT a bank or payment card.
    mx, my = size // 2, int(size * .43)
    r = int(size * .16)
    d.ellipse((mx-r, my-r, mx+r, my+r), outline=(222, 193, 123),
              width=max(4, size // 80))
    d.line((mx-int(r*.55), my, mx-int(r*.13), my+int(r*.4),
            mx+int(r*.62), my-int(r*.48)),
           fill=(245, 225, 171), width=max(4, size // 55), joint="curve")
    name = "LOIAL"
    font = _font(max(18, int(size * .105)), True)
    bbox = d.textbbox((0, 0), name, font=font)
    width = bbox[2] - bbox[0]
    d.text(((size-width)/2, int(size*.64)), name,
           font=font, fill=(242, 222, 174))
    output = BytesIO()
    im.save(output, format="PNG", optimize=True)
    return output.getvalue()


def install_pwa(app):
    router = APIRouter(tags=["Loial installable app"])

    @router.get("/wallet", include_in_schema=False)
    def wallet_launcher():
        return FileResponse("loial-wallet.html", media_type="text/html",
            headers={"Cache-Control":"no-store"})

    @router.get("/loial-offline.html", include_in_schema=False)
    def offline_page():
        return FileResponse("loial-offline.html", media_type="text/html",
            headers={"Cache-Control":"public, max-age=3600"})

    @router.get("/sw.js", include_in_schema=False)
    def service_worker():
        return FileResponse("sw.js", media_type="text/javascript",
            headers={"Cache-Control":"no-cache",
                     "Service-Worker-Allowed":"/"})

    @router.get("/pwa-icon-{size}.png", include_in_schema=False)
    def icon(size: int):
        if size not in (192, 512):
            raise HTTPException(status_code=404, detail="Icon unavailable")
        return Response(metal_icon(size), media_type="image/png",
                        headers={"Cache-Control":"public, max-age=86400",
                                 "X-Content-Type-Options":"nosniff"})

    app.include_router(router)
