import os
import requests
from fake_useragent import UserAgent
from stem import Signal
from stem.control import Controller, EventType
import json
import time
from tqdm import tqdm
import random
import re
from flask import Flask, request, jsonify, abort
import redis
from playwright.sync_api import sync_playwright


# Global variable to keep track of the last time we issued a NEWNYM signal
redis_client = redis.StrictRedis(
    host='localhost', port=6379, db=0, decode_responses=True)


def cache_data(key, data, expire=None):
    """
    Cache data in Redis under the specified key.

    :param key: The key under which to store the data.
    :param data: The data to store (must be JSON serializable).
    :param expire: The expiration time in seconds; if None, the data does not expire.
    """
    if expire is not None:
        redis_client.setex(key, expire, data)
    else:
        redis_client.set(key, json_data)


def get_cached_data(key):
    """
    Retrieve cached data from Redis for the given key.

    :param key: The key of the cached data.
    :return: The retrieved data or None if the key does not exist or an error occurred.
    """
    result = redis_client.get(key)
    if result:
        return result
    return None


def progress_wait(seconds, desc='Waiting...'):
    """
    Wait for a given amount of seconds, displaying a progress bar.

    :param seconds: Number of seconds to wait.
    :param desc: Description text to show next to the progress bar.
    """
    for _ in tqdm(range(seconds), desc=desc, ascii=True, ncols=75):
        time.sleep(1)


def generate_session():
    session = requests.session()
    session.proxies = {'http': 'socks5://127.0.0.1:9050',
                       'https': 'socks5://127.0.0.1:9050'}
    session.headers = {
        'User-Agent': UserAgent().random
    }
    new_tor_id()
    return session

# Log each request


def log_and_continue_request(request):
    print(f"Request: {request.method} {request.url}")

# Log each response


def log_response(response):
    print(f"Response: {response.status} {response.url}")

# Log console messages (e.g., console.log, errors, warnings)


def log_console(msg):
    print(f"Console message: {msg.type} - {msg.text}")

# Block images, CSS, and fonts


def block_resources(route, request):
    if request.resource_type in ["image", "stylesheet", "font"]:
        route.abort()
    else:
        route.continue_()


def get_data(url):
    websiteData = None
    browser = None

    try:
        with sync_playwright() as playwright:
            chromium = playwright.chromium
            browser = chromium.launch(headless=True, proxy={
                "server": "socks5://127.0.0.1:9050"
            })

            context = browser.new_context()

            page = context.new_page()

            # Define the pattern to match files we want to block
            block_pattern = re.compile(
                r"\.(png|jpg|jpeg|gif|woff2|pdf|docx|svg|ttf|css)$",
                re.IGNORECASE
            )

            # Abort requests that match the pattern
            page.route(block_pattern, lambda route: route.abort())

            # Add event listeners
            page.on("request", log_and_continue_request)
            page.on("response", log_response)
            page.on("console", log_console)

            page.goto(url, wait_until="networkidle", timeout=0)
            websiteData = page.content()

            page.remove_listener("request", log_and_continue_request)
            page.remove_listener("response", log_response)
            page.remove_listener("console", log_console)

            browser.close()
        return websiteData
    except Exception as e:
        print(f"An error occurred: {e}")
        if browser:
            browser.close()
        return None


def log_circuit(event):
    if event.status == 'BUILT':
        print(f"Circuit {event.id} has been built")
    elif event.status == 'EXTENDED':
        print(f"Circuit {event.id} has been extended")
    elif event.status == 'FAILED':
        print(f"Circuit {event.id} has failed: {event.reason}")
    elif event.status == 'CLOSED':
        print(f"Circuit {event.id} has been closed: {event.reason}")


def new_tor_id():
    # Connect to the Tor control port and issue a NEWNYM
    with Controller.from_port(port=9051) as controller:
        controller.authenticate()
        print("[+] Authenticated.")

        # Add the event listener for circuit events
        # controller.add_event_listener(log_circuit, EventType.CIRC)

        controller.signal(Signal.NEWNYM)
        print("[+] Sent change signal")
        progress_wait(random.randint(10, 15), desc='[+] Building new circuit')
        controller.close()

        # Optionally remove the event listener if we no longer wish to log events
        # controller.remove_event_listener(log_circuit)


def get_size_of_string_in_kb(input_string):
    """
    Calculate the size of a string in kilobytes (KB) when encoded in UTF-8.

    :param input_string: The string to measure.
    :return: The size of the string in kilobytes.
    """
    encoded_string = input_string.encode('utf-8')
    size_in_bytes = len(encoded_string)
    size_in_kb = size_in_bytes / 1024

    return size_in_kb


os.system('clear')

binDummyWebsite = 'http://httpbin.org/ip'

print(50*'-')


def getWebsiteData(url):
    cachedData = get_cached_data(url)

    if cachedData:
        print('Getting data from cache')
        print('Website data size: ' +
              str(get_size_of_string_in_kb(cachedData)) + ' KB\n\n')
        return {
            'data': cachedData,
            'url': url
        }

    retry = True
    websiteData = None
    while retry:
        torSession = generate_session()

        websiteData = get_data(url)
        if websiteData is not None:
            forbidden_match = re.search(
                r'403 forbidden', websiteData, re.IGNORECASE)
            if forbidden_match:
                print("403 Forbidden response received. Retrying...")
                torSession.close()  # Close the session before retrying
                # Wait a bit before retrying to not overwhelm the server
                time.sleep(1)
                continue  # Continue to the next iteration of the while loop to retry

            proxified_ip = get_data(binDummyWebsite)
            if proxified_ip:
                print('Proxified ip: ' + proxified_ip)
            print('Getting data from ', url)
            print('Website data size: ' +
                  str(get_size_of_string_in_kb(websiteData)) + ' KB\n\n')

            cache_data(url, websiteData, 48*60*60)  # Cache for 2 days
            retry = False  # Data received successfully, no need to retry
        else:
            print("Failed to get data from the website, retrying...")
            retry = True  # If there's an error, you may decide not to retry

        torSession.close()
    return {
        'data': websiteData,
        'url': url
    }
    print(50*'-')


app = Flask(__name__)

# Simple function to check the bearer token


def token_required(f):
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            token = request.headers['Authorization']
            # Check if the token is valid
            if not token or token.split(" ")[1] != 'abc':
                abort(401, 'Invalid token. Authentication failed!')
            return f(*args, **kwargs)
        else:
            abort(401, 'Token is missing.')
    return decorated


@app.route('/scrape', methods=['POST'])
@token_required
def scrape():
    data = request.json
    url = data.get('url')
    if not url:
        return jsonify({"error": "Missing URL in the request body"}), 400

    # Implement your scraping logic here
    # For example, you might fetch the URL and return the status code
    # For now, we'll just echo back the URL received
    response = getWebsiteData(url)
    return jsonify(response), 200


if __name__ == '__main__':
    app.run(debug=True, port=8987)
