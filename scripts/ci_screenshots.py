"""Open the freshly built site in a headless browser and save screenshots (used by the pipeline workflow).

    python scripts/rangeserve.py site 8000 &   # PMTiles needs HTTP range requests
    python scripts/ci_screenshots.py http://127.0.0.1:8000 shots/
"""
import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

BASE, OUT = sys.argv[1].rstrip("/"), Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)
data = Path("site/data")


def sample_well(prefixes):
    """A producing well from the first matching township shard, so the panel shows a chart."""
    for pre in prefixes:
        for f in sorted(data.glob(f"twp/{pre}*.json"))[:400]:
            wells = json.loads(f.read_text())["wells"]
            for w in wells.values():
                if w.get("pr") and w.get("b", 0) > 5:
                    return w["d"]
    return None


async def main():
    views = [("1_basin", "#@54.5,-113.5,4.6"), ("2_whitecourt_z11", "#@54.17,-115.70,11"),
             ("3_section_z14", "#@54.17,-115.70,14"), ("4_bc_montney", "#@56.3,-120.9,9.5"),
             ("5_sk_bakken", "#@49.2,-102.9,10"), ("6_mb_virden", "#@49.85,-100.95,10.5")]
    wells = [("7_well_ab", sample_well(["W5-060", "W5-05", "W4-04"])), ("8_well_bc", sample_well(["N094", "N093"])),
             ("9_well_sk", sample_well(["W2-00", "W3-0"]))]
    errors = []
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        ctx = await b.new_context(viewport={"width": 1280, "height": 820})
        pg = await ctx.new_page()
        pg.on("pageerror", lambda e: errors.append(str(e)))
        for name, h in views:
            await pg.goto(f"{BASE}/index.html{h}")
            await pg.reload()
            await pg.wait_for_timeout(7000)
            await pg.screenshot(path=str(OUT / f"{name}.png"))
        for name, uwi in wells:
            if not uwi:
                continue
            await pg.goto(f"{BASE}/index.html#well={uwi}")
            await pg.reload()
            await pg.wait_for_timeout(8000)
            await pg.screenshot(path=str(OUT / f"{name}.png"))
        await pg.goto(f"{BASE}/index.html")
        await pg.wait_for_timeout(3000)
        await pg.fill("#q", "tourmaline")
        await pg.wait_for_timeout(1500)
        await pg.screenshot(path=str(OUT / "10_search_operator.png"))
        for i, (tick, tab) in enumerate([("tou", "production"), ("cnq", "formations"), ("wcp", "activity"), ("aav", "production")]):
            await pg.goto(f"{BASE}/index.html#co={tick}")
            await pg.reload()
            await pg.wait_for_timeout(7000)
            btn = await pg.query_selector(f".tabs button[data-t={tab}]")
            if btn:
                await btn.click()
                await pg.wait_for_timeout(600)
            await pg.screenshot(path=str(OUT / f"11_company_{tick}_{tab}.png"))
        await pg.goto(f"{BASE}/index.html#@55.5,-117.5,6")
        await pg.reload()
        await pg.wait_for_timeout(5000)
        await pg.click("#layersBtn")
        await pg.check("#actT")
        await pg.wait_for_timeout(3000)
        await pg.screenshot(path=str(OUT / "12_activity_layer.png"))
        ph = await b.new_context(viewport={"width": 390, "height": 800}, is_mobile=True, has_touch=True)
        pp = await ph.new_page()
        if wells[0][1]:
            await pp.goto(f"{BASE}/index.html#well={wells[0][1]}")
            await pp.wait_for_timeout(8000)
            await pp.screenshot(path=str(OUT / "11_phone_well.png"))
        await b.close()
    (OUT / "errors.txt").write_text("\n".join(errors) or "no page errors")
    print("page errors:", errors or "none")


asyncio.run(main())
