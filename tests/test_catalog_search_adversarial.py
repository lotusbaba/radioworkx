"""SEARCH-02/03/04: adversarial modal behavior in isolated Chrome, no model calls."""
import os
import pytest
from tests.test_account_scenarios import qa_browser_page

pytestmark=pytest.mark.skipif(os.getenv('RWX_BROWSER_TESTS')!='1',reason='Set RWX_BROWSER_TESTS=1 for isolated Chrome')


def open_search(page):
    origin=page.url.split('/albums/')[0]
    page.goto(origin+'/')
    page.get_by_role('button',name='Search',exact=True).click()
    return page.get_by_role('dialog',name='Search the collection')


def test_search_markup_empty_and_type_boundaries(qa_browser_page):
    page,expect=qa_browser_page; dialog=open_search(page)
    field=dialog.get_by_label('Search text',exact=True)
    for text in ['   ', '%', '_', "' OR 1=1 --", '<svg onload="window.qaXss=1">']:
        field.fill(text)
        dialog.get_by_role('button',name='Search',exact=True).click()
        expect(dialog.locator('#catalog-search-status')).not_to_have_text('Searching…')
        expect(dialog.locator('.catalog-search-result')).to_have_count(0)
        assert page.evaluate('window.qaXss') is None
    field.fill('Artist A')
    expect(dialog.locator('.catalog-search-result')).to_have_count(1)
    dialog.get_by_label('Search by',exact=True).select_option('track')
    expect(dialog.locator('#catalog-search-status')).to_contain_text('No matches')
    expect(dialog.locator('.catalog-search-result')).to_have_count(0)


@pytest.mark.parametrize('change',['query','type','close'])
def test_late_search_response_cannot_restore_stale_cards(qa_browser_page,change):
    page,expect=qa_browser_page; dialog=open_search(page)
    # A response already resolving can escape AbortController; hold that boundary
    # explicitly so the request-version guard, not network cancellation, is tested.
    page.evaluate("""() => {
      const original=window.fetch;
      window.fetch=(url,options)=>String(url).includes('/api/library/search') && String(url).includes('q=old')
        ? new Promise(resolve=>{window.releaseOldSearch=()=>resolve(new Response(JSON.stringify({total:1,items:[
          {name:'STALE RESULT',kind:'artist',artists:[],url:'/artists/stale'}]}),{status:200}));})
        : original(url,options);
    }""")
    field=dialog.get_by_label('Search text',exact=True)
    field.fill('old');dialog.get_by_role('button',name='Search',exact=True).click()
    page.wait_for_function('typeof window.releaseOldSearch === "function"')
    if change=='close':
        dialog.get_by_role('button',name='Close search').click()
        page.get_by_role('button',name='Search',exact=True).click()
    else:
        if change=='type':dialog.get_by_label('Search by',exact=True).select_option('album')
        field.fill('Album A' if change=='type' else 'Artist A')
        expect(dialog.locator('.catalog-search-result')).to_have_count(1)
    page.evaluate('async () => { releaseOldSearch(); await new Promise(r=>setTimeout(r,50)); }')
    expect(dialog).not_to_contain_text('STALE RESULT')
    if change=='close':expect(dialog.locator('.catalog-search-result')).to_have_count(0)


def test_search_error_recovers(qa_browser_page):
    page,expect=qa_browser_page; dialog=open_search(page)
    page.route('**/api/library/search?*',lambda route:route.fulfill(status=503,json={'detail':'unavailable'}))
    field=dialog.get_by_label('Search text',exact=True)
    field.fill('Artist A')
    expect(dialog.locator('#catalog-search-status')).to_contain_text('unavailable')
    page.unroute('**/api/library/search?*')
    dialog.get_by_role('button',name='Search',exact=True).click()
    expect(dialog.locator('.catalog-search-result')).to_have_count(1)
