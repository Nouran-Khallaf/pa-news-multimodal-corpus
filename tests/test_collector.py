from pathlib import Path
from bs4 import BeautifulSoup
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"src"))
from collect_pa_news import extract_listing_article_urls, max_pagination_number, parse_article

SITE={"base_url":"https://www.patrioticalternative.org.uk","article_hosts":["www.patrioticalternative.org.uk","patrioticalternative.org.uk"]}
SCOPE={"listing_path":"/news","excluded_path_prefixes":["/join","/donate"],"minimum_body_words":20}

def fixture(name): return BeautifulSoup((Path(__file__).parent/"fixtures"/name).read_text(),"html.parser")

def test_listing_discovery():
    soup=fixture("listing.html")
    urls=extract_listing_article_urls(soup,SITE,SCOPE)
    assert urls==["https://www.patrioticalternative.org.uk/first_story","https://www.patrioticalternative.org.uk/second_story"]
    assert max_pagination_number(soup)==181

def test_article_and_caption_extraction():
    rec=parse_article(fixture("article.html"),"https://www.patrioticalternative.org.uk/example",20)
    assert rec["title"]=="Example title"
    assert rec["author"]=="Example Author"
    assert len(rec["paragraphs"])==2
    assert "Do you like" not in rec["body"]
    assert rec["tags"]==["Research"]
    assert len(rec["image_candidates"])==1
    assert rec["image_candidates"][0]["figcaption"]=="Explicit picture caption."

def test_nationbuilder_sibling_heading_and_div_body():
    rec=parse_article(
        fixture("nationbuilder_article.html"),
        "https://www.patrioticalternative.org.uk/white_lives_matter_2026_save_the_date",
        20,
    )
    assert rec["title"]=="White Lives Matter 2026 - Save The Date"
    assert rec["author"]=="Patriotic Alternative"
    assert rec["tags"]==["Activism","Protest"]
    assert "On Saturday 8th August" in rec["body"]
    assert "Do you like" not in rec["body"]
    assert "Event announcement image" not in rec["body"]
    assert len(rec["image_candidates"])==1
    assert rec["image_candidates"][0]["figcaption"]=="Event announcement image."


def test_verified_nationbuilder_selector_hero_and_inline_caption():
    rec=parse_article(
        fixture("nationbuilder_verified_template.html"),
        "https://www.patrioticalternative.org.uk/verified_template_story",
        20,
    )
    assert rec["body_selector"]=="main#content #intro > .content"
    assert rec["author"]=="Example Author"
    assert rec["tags"]==["Activism"]
    assert "A plain-text image caption" not in rec["body"]
    assert "related story" not in rec["body"].lower()
    assert "Do you like" not in rec["body"]
    assert [x["image_role"] for x in rec["image_candidates"]]==["hero","inline"]
    inline=rec["image_candidates"][1]
    assert inline["figcaption"]=="A plain-text image caption"
    assert inline["caption_source"]=="inline_parent_text"
