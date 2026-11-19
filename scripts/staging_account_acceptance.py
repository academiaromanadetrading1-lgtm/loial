import os, secrets, uuid
from playwright.sync_api import sync_playwright, expect
ORIGIN="https://loial-staging-staging.up.railway.app"
with sync_playwright() as p:
    browser=p.chromium.launch()
    for device in ["Desktop","Pixel 7","iPhone 13"]:
        ctx=browser.new_context(**({"viewport":{"width":1440,"height":900}} if device=="Desktop" else p.devices[device]))
        page=ctx.new_page()
        page.goto(ORIGIN+"/")
        menu=page.locator("#loialAccountMenu")
        expect(menu).to_be_visible()
        langs=page.locator("#langSelect")
        assert langs.locator("option").evaluate_all("els=>els.map(e=>e.value)") == ["en","de","fr","it","es","ro","nl","pl","hu"]
        langs.select_option("en")
        menu.locator("summary").click()
        expect(menu.get_by_text("Sign in",exact=True)).to_be_visible()
        menu.get_by_text("Change password",exact=True).click()
        expect(page.locator("#tabPwd")).to_be_visible()
        assert page.url.endswith("tab=password")
        page.goto(ORIGIN+"/")
        langs.select_option("ro")
        for role in ["merchant","administrator","ambassador","customer"]:
            page.evaluate("""role=>{
              localStorage.removeItem('token');sessionStorage.removeItem('loial_ambassador_token');localStorage.removeItem('loial_wallet_inbox_token');
              if(role==='merchant'||role==='administrator')localStorage.setItem('token','synthetic-browser-state');
              if(role==='ambassador')sessionStorage.setItem('loial_ambassador_token','synthetic-browser-state');
              if(role==='customer')localStorage.setItem('loial_wallet_inbox_token','synthetic-browser-state');
            }""",role)
            page.reload()
            menu.locator("summary").click()
            page.once("dialog",lambda d:d.accept())
            menu.get_by_text("Ieșire din cont",exact=True).click()
            page.wait_for_url(ORIGIN+"/")
            expect(menu.locator("summary")).to_be_visible()
            assert page.evaluate("!localStorage.getItem('token')&&!sessionStorage.getItem('loial_ambassador_token')&&!localStorage.getItem('loial_wallet_inbox_token')")
            assert page.evaluate("localStorage.getItem('loial_language')==='ro'")
            print("PASS shared menu synthetic role state, sign-out and locale preservation",device,role,flush=True)
        ctx.close()
    browser.close()
