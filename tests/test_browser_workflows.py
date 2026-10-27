"""Optional real-browser regressions with mocked API data and no user database."""
import copy
import json
import threading
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import pytest

playwright=pytest.importorskip('playwright.sync_api')

@pytest.fixture
def browser_page():
    root=Path(__file__).resolve().parents[1]/'src'/'musicharbor'
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(SimpleHTTPRequestHandler,directory=str(root)))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    p=dict(id='a',name='Project A',storefront='us',tracks=[],recordings={},releases={},local_files=[],exports=[],price_history=[],library_folders=[])
    with playwright.sync_playwright() as tool:
        browser=tool.chromium.launch();page=browser.new_page();errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        def respond(route):
            path=route.request.url.split('/api/',1)[1]
            if path=='projects': data=[dict(id='a',name='Project A',updated='2026-10-12'),dict(id='b',name='Project B',updated='2026-10-12')]
            elif path=='settings': data=dict(spotify_id='',storefront='us',preferences={},performance={},listening={'running':False},retention={})
            elif path=='desktop': data={'folder_picker':False}
            elif path.endswith('/jobs') or path=='jobs': data=[]
            elif '/library?' in path: data=dict(files=[],recordings={},total=0,offset=0,next_offset=None)
            elif '/export-preview?' in path: data=dict(count=0,skipped=0,omissions=[],text='#EXTM3U\n')
            elif path.endswith('/owned-collection'): data=dict(count=0,percent=0,value=0,currency='USD',total=0,unpriced=0,groups=[],releases={})
            else:
                data=copy.deepcopy(p);data.update(id=path.split('/')[1],name='Project '+path.split('/')[1].upper())
            route.fulfill(json=data)
        page.route('**/api/**',respond)
        page.goto(f'http://127.0.0.1:{server.server_port}/static/ui.html')
        page.locator('#breadcrumb').filter(has_text='Project A').wait_for()
        yield page,errors
        browser.close()
    server.shutdown();server.server_close();thread.join()

def test_navigation_and_specific_export_controls(browser_page):
    page,errors=browser_page
    page.locator('a[href="#export"]').first.click()
    page.locator('#export-advanced > summary').click()
    page.locator('#export-preferred-format').select_option('flac')
    page.locator('#export-preferred-folder').fill('/Music/Lossless')
    page.locator('a[href="#owned"]').first.click()
    page.locator('a[href="#library"]').first.click()
    page.get_by_text('Showing 0 of 0 library files.').wait_for()
    page.locator('#project-picker').select_option('b')
    page.locator('#breadcrumb').filter(has_text='Project B').wait_for()
    assert errors==[]

def test_dirty_settings_survive_background_refresh(browser_page):
    page,errors=browser_page
    page.locator('a[href="#settings"]').first.click()
    page.locator('#client-id').fill('unsaved-client')
    page.evaluate('reload({preserveDrafts:true})')
    assert page.locator('#client-id').input_value()=='unsaved-client'
    assert errors==[]


def test_all_strategies_are_directly_accessible(browser_page):
    page,errors=browser_page
    page.locator('.sidebar a[href="#plan"]').click()
    assert page.locator('#strategy').is_visible()
    assert page.locator('#strategy option').count()==6
    page.locator('#strategy').select_option('best-value')
    assert page.locator('#budget').is_visible()
    assert page.locator('#strategy').input_value()=='best-value'
    page.locator('#strategy').select_option('artist')
    assert page.locator('#artist').is_visible()
    assert page.locator('#strategy').input_value()=='artist'
    page.locator('#strategy').select_option('fewest')
    assert not page.locator('#artist').is_visible()
    assert not page.locator('#budget').is_visible()
    assert errors==[]


def test_import_choices_do_not_navigate_away(browser_page):
    page,errors=browser_page
    page.locator('.topbar a[href="#import"]').click()
    page.locator('[data-action="choose-import"][data-id="spotify-import"]').click()
    assert page.url.endswith('#import')
    assert page.locator('#import-form input[name="url"]').is_visible()
    page.locator('[data-action="choose-import"][data-id="playlist-file"]').click()
    assert page.locator('#playlist-csv').is_visible()
    assert errors==[]


def test_folder_picker_and_browser_fallback(browser_page):
    page,errors=browser_page
    page.locator('.sidebar a[href="#owned"]').click()
    page.locator('.subnav a[href="#library"]').click()
    page.locator('[data-action="choose-folder"]').click()
    assert page.locator('#folder').is_visible()
    page.route('**/api/desktop',lambda route:route.fulfill(json={'folder_picker':True}))
    page.route('**/api/desktop/folder',lambda route:route.fulfill(json={'path':'/Music/My collection'}))
    page.locator('[data-action="choose-folder"]').click()
    page.locator('#selected-folder').filter(has_text='/Music/My collection').wait_for()
    assert page.locator('#folder').input_value()=='/Music/My collection'
    page.evaluate('reload({preserveDrafts:true})')
    assert page.locator('#folder').input_value()=='/Music/My collection'
    assert errors==[]


def test_empty_export_is_disabled_and_device_options_are_visible(browser_page):
    page,errors=browser_page
    page.locator('.sidebar a[href="#export"]').click()
    page.get_by_text('0 playlist entries ready',exact=True).wait_for()
    assert page.locator('[data-action="export"]').is_disabled()
    page.locator('[name="export-preset"][value="device"]').check()
    assert page.locator('#device-folder').is_visible()
    assert page.locator('#device-folder').input_value()==''
    assert page.locator('[data-action="export"]').is_disabled()
    page.locator('[name="export-preset"][value="mac"]').check()
    assert not page.locator('#export-custom').is_checked()
    assert page.locator('#export-slashes').input_value()=='macos'
    assert errors==[]
