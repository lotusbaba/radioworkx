import os
import pytest
from tests.test_account_scenarios import qa_browser_page

pytestmark=pytest.mark.skipif(os.getenv('RWX_BROWSER_TESTS')!='1',reason='Set RWX_BROWSER_TESTS=1 for Chrome + test PostgreSQL')


@pytest.mark.parametrize('viewport', [{'width':1280,'height':900},{'width':390,'height':844}])
def test_home_modal_search(qa_browser_page,viewport):
    page,expect=qa_browser_page
    origin=page.url.split('/albums/')[0]
    page.set_viewport_size(viewport)
    page.goto(origin+'/')
    # Keep a real media clock running to detect modal-induced playback changes.
    if not page.evaluate('tuned'):
        page.locator('#listen').click()
    page.wait_for_function('!document.querySelector("#audio").paused && document.querySelector("#audio").currentTime > .1')
    before=page.locator('#audio').evaluate('(a)=>a.currentTime')
    page.get_by_role('button',name='Search',exact=True).click()
    dialog=page.get_by_role('dialog',name='Search the collection')
    expect(dialog).to_be_visible()
    expect(dialog.locator('.catalog-search-result')).to_have_count(0)
    dialog.get_by_label('Search text',exact=True).fill('Artst A')
    expect(dialog.locator('.catalog-search-result')).to_have_count(1)
    expect(dialog.locator('.catalog-search-result')).to_contain_text('Artist A')
    dialog.get_by_label('Search by',exact=True).select_option('album')
    dialog.get_by_label('Search text',exact=True).fill('Albm A')
    expect(dialog.locator('.catalog-search-result')).to_contain_text('Album A')
    dialog.get_by_label('Search by',exact=True).select_option('track')
    dialog.get_by_label('Search text',exact=True).fill('Trak A')
    expect(dialog.locator('.catalog-search-result')).to_contain_text('Track A')
    if os.getenv('RWX_TEST_ARTIFACTS'):
        page.screenshot(path=os.environ['RWX_TEST_ARTIFACTS']+f'/search-{viewport["width"]}.png')
    dialog.get_by_label('Search text',exact=True).fill('')
    expect(dialog.locator('.catalog-search-result')).to_have_count(0)
    assert page.url==origin+'/'
    assert page.locator('#audio').evaluate('(a)=>!a.paused && a.currentTime')>before
    page.keyboard.press('Escape')
    expect(dialog).not_to_be_visible()
    expect(page.locator('#open-catalog-search')).to_be_focused()
