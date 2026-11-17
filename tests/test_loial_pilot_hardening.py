from html.parser import HTMLParser
import pytest
from loial_seo_locales import COPY, landing, path_for
from loial_growth import sitemap_xml
from loial_acquisition import normalize_source
from loial_multilocation import available_slot, month_range

class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links=[]
    def handle_starttag(self,tag,attrs):
        if tag=="link":self.links.append(dict(attrs))

@pytest.mark.parametrize("lang",list(COPY))
def test_locale_links(lang):
    parser=Links()
    parser.feed(landing(lang))
    alternates={a["hreflang"]:a["href"] for a in parser.links if a.get("rel")=="alternate"}
    assert alternates=={**{k:"https://loial.space"+path_for(k) for k in COPY},"x-default":"https://loial.space/"}
    assert any(a.get("rel")=="canonical" and a["href"]=="https://loial.space"+path_for(lang) for a in parser.links)

@pytest.mark.parametrize("source,expected",[("CARD","card"),(" receipt ","receipt"),("unknown","direct"),(None,"direct"),("<script>","direct")])
def test_attribution(source,expected):
    assert normalize_source(source)==expected

def test_location_cap():
    assert available_slot(set())==2
    assert available_slot({2,3,4})==5
    assert available_slot({2,3,4,5}) is None

def test_month_range():
    assert month_range("2026-12")==("2026-12-01","2027-01-01")
    with pytest.raises(Exception):month_range("2026-13")
