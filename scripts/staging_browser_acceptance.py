import os, secrets, uuid
from playwright.sync_api import sync_playwright, expect
ORIGIN="https://loial-staging-staging.up.railway.app"
with sync_playwright() as p:
    browser=p.chromium.launch()
    desktop=browser.new_context()
    page=desktop.new_page()
    page.goto(ORIGIN+"/login.html")
    page.locator("#login-email").fill("ciprianpop@academiadetrading.llc")
    page.locator("#login-password").fill(os.environ["LOIAL_QA_ADMIN_PASSWORD"])
    with page.expect_response(lambda r: r.url==ORIGIN+"/auth/login") as login:
        page.locator("#loginBtn").click()
    assert login.value.status==200
    page.wait_for_url("**/platform.html")
    expect(page.locator("#superAdminSection")).to_be_visible(timeout=20000)
    print("PASS superadmin browser login and visible dashboard",flush=True)
    expect(page.locator("#adminOverviewStatus")).to_contain_text("Actualizat la",timeout=20000)
    expect(page.locator("#foundersAdmin")).to_be_visible()
    page.evaluate("logout()")
    page.wait_for_url(ORIGIN+"/")
    expect(page.locator("#walletCard")).to_be_visible()
    print("PASS administrator overview, founder management and logout to homepage",flush=True)
    desktop.close()
    api=browser.new_context()
    tag=uuid.uuid4().hex[:12]
    r=api.request.post(ORIGIN+"/api/register",data={"email":f"qa-mobile-{tag}@example.invalid","password":secrets.token_urlsafe(24),"business_name":"QA mobile "+tag})
    assert r.ok
    bid=r.json()["business_id"]
    api.close()
    for device in ["Desktop","Pixel 7","iPhone 13"]:
        viewport={"viewport":{"width":1440,"height":900}} if device=="Desktop" else p.devices[device]
        context=browser.new_context(**viewport,reduced_motion="reduce")
        page=context.new_page()
        page.goto(ORIGIN+"/")
        expect(page.locator("h1")).to_contain_text("Afacerile cresc")
        expect(page.locator("#walletCard")).to_be_visible()
        page.locator("#bizName").fill("QA Card")
        expect(page.locator("#previewName")).to_have_text("QA Card")
        page.locator("#addStamp").click()
        expect(page.locator("#stampCount")).to_have_text("6/6")
        expect(page.locator("[data-founder-count]")).to_contain_text("500",timeout=20000)
        expect(page.locator("#pentru-cine")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 2"),device
        page.goto(ORIGIN+"/fondatori")
        expect(page.locator("[data-founder-count]")).to_contain_text("500",timeout=20000)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 2"),device
        print("PASS homepage, interactive simulator, gallery and width:",device,flush=True)
        context.close()
    for device in ["Pixel 7","iPhone 13"]:
        context=browser.new_context(**p.devices[device])
        page=context.new_page()
        page.goto(ORIGIN+"/join/"+str(bid))
        expect(page.locator("#nameInput")).to_be_visible()
        page.locator("#nameInput").fill("QA Mobile")
        page.locator("#enrollForm button[type=submit]").click()
        expect(page.locator("#cardView")).to_be_visible(timeout=20000)
        expect(page.locator("#pwaInstallBtn")).to_be_visible()
        expect(page.locator("#qrImg")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 2")
        manifest=page.request.get(ORIGIN+"/manifest.json")
        assert manifest.ok and manifest.json()["display"]=="standalone"
        page.locator("#tabBtnInbox").click()
        expect(page.locator("#panelInbox")).to_be_visible()
        print("PASS mobile viewport, enrollment, card, install control, inbox:",device,flush=True)
        context.close()
    browser.close()
