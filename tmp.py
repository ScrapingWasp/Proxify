from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    for browser_type in [p.chromium]:
        browser = browser_type.launch(headless=True)
        page = browser.new_page()
        page.goto(
            'https://www.pnp.co.za/c/pnpbase?query=:relevance:allCategories:pnpbase:category:personal-care-and-health-423144840', wait_until="networkidle")

        print(page.content())

        browser.close()
