"""Static release contracts for the responsive LOIAL PWA and private dashboards.

These are regression checks, NOT substitutes for real iOS/Android testing.
"""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def source(name):
    return (ROOT/name).read_text(encoding="utf-8")


def test_black_metal_pwa_has_installable_manifest_and_offline_shell():
    data=json.loads(source("manifest.json"))
    assert data["display"]=="standalone"
    assert data["start_url"].startswith("/wallet")
    assert data["scope"]=="/"
    icons=data["icons"]
    assert {"192x192","512x512"}.issubset({x["sizes"] for x in icons})
    assert all(x["src"].startswith("/pwa-icon-") for x in icons)
    worker=source("sw.js")
    assert "url.pathname.startsWith('/api/')" in worker
    assert "request.method !== 'GET'" in worker
    assert "'/loial-offline.html'" in worker
    assert "const PUBLIC = new Set(SHELL)" in worker


def test_wallet_is_responsive_and_uses_private_token():
    for file in ("join.html","loial-wallet.html"):
        html=source(file)
        assert 'name="viewport"' in html
        assert 'href="/manifest.json"' in html
        assert "loial-pwa-install.js" in html
        assert "@media" in html
        assert "loial_wallet_inbox_token" in html
    assert "/wallet-recovery.html" in source("loial-wallet.html")


def test_ambassador_has_correct_referral_destinations_and_private_ledger():
    html=source("ambasador.html")
    assert 'name="viewport"' in html and "@media" in html
    assert "ambasador.html?ambref=" in html
    assert "join.html?ambref=" not in html
    assert "/api/loial-revenue/ambassador/me" in html
    assert "/api/ambassador/login" in html
    assert "ambWiseForm" in html
    assert "/api/loial-revenue/ambassador/wise-details" in html
    assert "sessionStorage" in html


def test_admin_dashboard_price_payment_and_export_are_consistent():
    html=source("platform.html")
    assert 'name="viewport"' in html and "@media" in html
    assert "67 EUR" in html
    assert "stripePayButton" in html
    assert "/api/loial-stripe/me" in html
    assert "/api/loial-stripe/checkout" not in html or "stripeLink('checkout')" in html
    assert "downloadCommissionXlsx" in html
    assert "adminActivity" in html
    assert "loadSuperAdmin()" in html
    assert "toggleProPlan(" not in html


def test_ai_workspace_has_six_distinct_views_and_preserves_all_tools():
    import re
    html=source("loial-ai.html")
    tabs=re.findall(r'data-workspace="([^"]+)"',html)
    views=re.findall(r'data-view="([^"]+)"',html)
    assert tabs==views==["chat","documents","sales","reports","customers","messages"]
    assert "workspace-view[hidden]{display:none!important}" in html
    assert "@media(max-width:1050px)" in html
    assert "@media(max-width:760px)" in html
    assert '<aside class="right">' not in html
    for element in ("chat","send","attachment","upload","documentPreview",
                    "expenseSave","issueReceipt","reportBtn","runBreakEven","showClients",
                    "sendCampaign","exportFeedback","chatFeedback","aiMode"):
        assert html.count('id="'+element+'"')==1
    assert 'data-export="customers.xlsx"' in html
    assert 'data-export="sales.xlsx"' in html
    assert 'document_id:selectedDocument' in html
    assert "api('/exports/summary')" in html


def test_favicon_is_public_and_valid_ico():
    from io import BytesIO
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from PIL import Image
    from loial_pwa import install_pwa

    app = FastAPI()
    install_pwa(app)
    with TestClient(app) as client:
        response = client.get("/favicon.ico")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/x-icon"
        assert response.headers["x-content-type-options"] == "nosniff"
        with Image.open(BytesIO(response.content)) as icon:
            assert icon.format == "ICO"
            assert {(16, 16), (32, 32), (48, 48)} <= icon.ico.sizes()


def test_management_hub_routes_and_private_tools():
    import re
    html=source("loial-ai.html")
    dashboard=source("platform.html")
    roles=re.findall(r'href="/loial-ai\.html\?specialist=([a-z]+)"',dashboard)
    assert set(roles)=={"general","performance","invoices","products","people",
                       "financing","campaign","customers","inventory","operations","risk","mentor"}
    assert len(roles)==12
    ids=re.findall(r'\bid="([\w-]+)"',html)
    assert len(ids)==len(set(ids))
    for element in ("managementRoles","roleFollowups","roleTools","managementOverview",
                    "healthGoals","healthResult","financeSimulator","teamOperations",
                    "decisionJournal","discussLoan","discussHealth","discussTeam"):
        assert element in ids
    for endpoint in ("management-overview","management-health","management-decisions"):
        assert "/"+endpoint in html
    role_selection=html.split("function chooseManagementRole(",1)[1].split("const roleFollowups=",1)[0]
    assert "input.value=draft" in role_selection
    assert "send()" not in role_selection and "api(" not in role_selection
    assert "data-no-translate" in html

def test_management_question_dictionary_covers_all_roles_and_starters():
    import re
    html=source("loial-ai.html")
    dictionary=source("loial-i18n.js")
    roles=html.split("const managementRoles=[",1)[1].split("];",1)[0]
    starts=re.findall(r"\['[a-z]+','([^']+)','[^']+','([^']+)'",roles)
    followups=html.split("const roleFollowups={",1)[1].split("};",1)[0]
    questions=re.findall(r"\['([^']+)','[^']+'\]",followups)
    assert len(starts)==12 and len(questions)==36
    for label,question in starts:
        assert label in dictionary and question in dictionary
    assert all(q in dictionary for q in questions)


def test_chat_profile_is_in_dashboard_and_attachment_controls_exist():
    html=source("loial-ai.html")
    dashboard=source("platform.html")
    assert 'id="aiBusinessProfile"' in dashboard
    assert 'id="aiProfileSave"' in dashboard
    assert '/platform.html#aiBusinessProfile' in html
    assert 'id="profileCard"' not in html
    assert html.index('id="managementRoles"') < html.index('id="questionSidebar"') < html.index('id="chat"')
    for element in ("attachChatImage","chatImageInput","chatImagePreview",
                    "deleteSelected","cancelSelection"):
        assert html.count('id="'+element+'"')==1
    assert "image_b64:pendingImage" in html
    assert "api('/history/delete'" in html
    assert "addEventListener('paste'" in html
