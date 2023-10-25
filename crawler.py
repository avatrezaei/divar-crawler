import csv
import time
import os
import json
import concurrent.futures
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from urllib.parse import urlencode, quote_plus
import requests
import random
from tqdm import tqdm
from requests.exceptions import ReadTimeout


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3",
    "Mozilla/5.0 (Windows NT 6.1; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/64.0.3282.140 Safari/537.36 Edge/17.17134"
]

# Set the base URL
BASE_URL = "https://divar.ir/s/iran/car/peugeot/pars"
BRAND_MODEL = 'Peugeot Pars,Peugeot 206,Samand,Tiba'
PRODUCTION_YEAR = '1387-1395'
BUSINESS_TYPE = 'personal'
CITIES = '1722,1721,1739,1740,850,1751,2,1738,1720,1753,1752,774,1754,1709,1715,1714,29,1764,1707,1768,1760,1767,1766,781,1,1718,782,783,1765,1769,1763,1713,1717,1759,1712,1710,1716,1772,1770,1758,1761,1708,1719,1706,1771,784,1711,1762'
FROM_EMAIL = "you@gmail.com"
TO_EMAILS = "you@gmail.com,me@gmail.com"
EMAIL_PASSWORD = "--------"
SMTP_SERVER = "smtp.gmail.com"

# Extract parameters from environment variables
params = {
    'brand_model': BRAND_MODEL,
    'production-year': PRODUCTION_YEAR,
    'business-type': BUSINESS_TYPE,
    'cities': CITIES
}

# Convert parameters into URL encoded string
query_string = urlencode(params, quote_via=quote_plus)

# Build the complete URL
complete_url = f"{BASE_URL}?{query_string}"


MAX_RETRIES = 5
MAX_THREADS = 5


def fetch_single_page(args):
    page_number, last_post_date = args
    return get_api_data(page_number, last_post_date)


def get_api_data(page_number, last_post_date):

    try:
        url = "https://api.divar.ir/v8/web-search/1/light"

        # Extract the data from .env file
        brand_model = BRAND_MODEL.split(',')
        production_years = PRODUCTION_YEAR.split('-')
        business_type = BUSINESS_TYPE
        cities = CITIES.split(',')

        payload = {
            "page": page_number,
            "json_schema": {
                "cities": cities,
                "category": {
                    "value": "light"
                },
                "brand_model": {
                    "value": brand_model
                },
                "production-year": {
                    "max": int(production_years[1]),
                    "min": int(production_years[0])
                },
                "business-type": {
                    "value": business_type
                }
            },
            "last-post-date": last_post_date
        }

        headers = {"User-Agent": random.choice(USER_AGENTS)}
        response = requests.post(
            url, json=payload, headers=headers, timeout=30)

        if response.status_code == 200:
            return response.json()
        else:
            return None

    except ReadTimeout:
        print("ReadTimeout encountered. Retrying...")
        return get_api_data(page_number, last_post_date)
    except Exception as e:
        print(f"Error: {e}. Retrying...")
        return get_api_data(page_number, last_post_date)


def navigate_and_load_all_posts():
    page_number = 0
    last_post_date = None

    all_posts = []

    total_pages = 1000
    for _ in tqdm(range(total_pages), desc="Fetching Posts"):

        data = get_api_data(page_number, last_post_date)

        if not data:
            break  # exit the loop if no data is received

        # Extract required information from data
        posts = data.get('web_widgets', {}).get('post_list', [])
        for post in posts:
            if not post.get('data', {}).get('token'):
                continue  # skip if the post doesn't have a token

            if post.get('data', {}).get('image_url'):
                image_url = post.get('data', {}).get('image_url')[1]['src']
            else:
                image_url = ''

            post_data = {
                "Id": post.get('data', {}).get('token'),
                "Title": post.get('data', {}).get('title'),
                "Old Price": None,
                "Price": post.get('data', {}).get('middle_description_text'),
                "Time & Location": post.get('data', {}).get('bottom_description_text'),
                "Image URL": image_url,
                "Post URL": "https://divar.ir/v/" + post.get('data', {}).get('token'),
                "Created At": time.strftime("%Y-%m-%d %H:%M:%S"),
                "Updated At": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            all_posts.append(post_data)

        # Update last_post_date for the next API call
        last_post_date = data.get('last_post_date')

        # If there are no more posts, break out of the loop
        if not posts:
            break

        # Random sleep between 1 to 3 seconds.
        time.sleep(random.uniform(1, 3))

    return all_posts


def safe_request(url, driver):
    retries = 0
    while retries < MAX_RETRIES:
        try:
            driver.get(url)
            if "429 too many requests" not in driver.page_source.lower():
                return driver
            else:
                print("429 encountered. Waiting and retrying...")
                retries += 1
                time.sleep(10)  # sleep for 10 seconds
        except Exception as e:
            print(f"Error: {e}. Retrying...")
            retries += 1
            time.sleep(2)  # Sleep for 2 seconds

    print("Max retries reached. Exiting...")
    return None


def screenshot_urls_with_ids(posts, append_suffix=None):
    urls = [post['Post URL'] for post in posts]
    ids = [post['Id'] for post in posts]
    total_posts = len(posts)

    if append_suffix:
        filenames = [
            f"screen_{post_id}_{append_suffix}.png" for post_id in ids]
    else:
        filenames = [f"screen_{post_id}.png" for post_id in ids]

    # Limit the number of drivers and threads to MAX_THREADS
    drivers = [setup_driver() for _ in range(min(len(urls), MAX_THREADS))]

    # Process the URLs in chunks of MAX_THREADS
    for i in range(0, len(urls), MAX_THREADS):
        chunked_urls = urls[i:i+MAX_THREADS]
        chunked_filenames = filenames[i:i+MAX_THREADS]
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
            for idx, _ in enumerate(executor.map(take_screenshot, drivers, chunked_urls, chunked_filenames)):
                print(
                    f"Screenshot taken for post {i + idx + 1}/{total_posts}...")

    for driver in drivers:
        driver.quit()

    return filenames


def format_updated_posts(updated_posts):
    formatted_posts = ""
    for post in updated_posts:
        formatted_posts += f"""
        <hr>
        <table class="table table-bordered">
            <tbody>
                <tr>
                    <th scope="row"><i class="fas fa-heading"></i> Title</th>
                    <td>{post['Title']}</td>
                </tr>
                <tr>
                    <th scope="row"><i class="fas fa-tag"></i> Old Price</th>
                    <td>{post['Old Price']}</td>
                </tr>
                <tr>
                    <th scope="row"><i class="fas fa-dollar-sign"></i> New Price</th>
                    <td>{post['Price']}</td>
                </tr>
                <tr>
                    <th scope="row"><i class="fas fa-link"></i> Link</th>
                    <td><a href="{post['Post URL']}">View Post</a></td>
                </tr>
            </tbody>
        </table>
        """
    return formatted_posts


def take_screenshot(driver, url, filename):
    log(f"Taking a screenshot for {url}...")

    try:
        driver = safe_request(url, driver)

        # Maximize the browser window
        driver.maximize_window()

        # Ensure the 'screenshots' folder exists
        if not os.path.exists("screenshots"):
            os.makedirs("screenshots")

        # Save the screenshot in the 'screenshots' folder
        filepath = os.path.join("screenshots", filename)
        full_page_screenshot(driver, filepath)

    except Exception as e:
        print(f"Failed to take screenshot for {url}. Error: {e}")


def setup_driver():
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument("--log-level=3")
    return webdriver.Chrome(options=options)


def log(message, level="INFO"):
    print(f"[{level}] - {message}")


def StartupTest(driver):
    log("Running StartupTest...")

    try:
        driver.get(complete_url)
    except:
        time.sleep(1)
        StartupTest(driver)
    return driver


def NavigateToDivarAndSearch(driver, searchterm):
    log(f"Navigating and searching for term: {searchterm}...")

    try:
        search_box = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.XPATH, "//*[@id='app']/header/nav/div/div[2]/div/div/div[1]/form/input"))
        )
        search_box.send_keys(searchterm)
        search_box.send_keys(Keys.RETURN)
    except:
        print("Error during navigation and search")
    return driver


def extract_post_details(article, driver, timeout=10):
    print("Extracting post details...")

    wait = WebDriverWait(driver, timeout)

    def safe_find(element_method, error_message):
        try:
            return element_method()
        except Exception as e:
            print(error_message, e)
            return None

    title = safe_find(lambda: article.find_element(
        By.TAG_NAME, 'h2').text, "Error in extracting title:")

    # Extracting the price from the second occurrence of kt-post-card__description
    descriptions = safe_find(lambda: article.find_elements(
        By.CLASS_NAME, 'kt-post-card__description'), "Error finding descriptions:")
    price = descriptions[1].text if descriptions and len(
        descriptions) > 1 else None

    time_location = safe_find(lambda: article.find_element(
        By.CLASS_NAME, 'kt-post-card__bottom-description').text, "Error in extracting time/location:")

    post_url = safe_find(lambda: article.find_element(
        By.XPATH, '..').get_attribute('href'), "Error retrieving post URL")

    post_id = post_url.split(
        "/")[-1] if post_url else "Error retrieving post ID"

    return post_id, title, price, time_location, "", post_url


def send_search_summary_notification(all_posts_count, new_posts_count, updated_posts_count):

    from_email = FROM_EMAIL
    # Split the string by comma to get a list of emails
    to_emails = TO_EMAILS.split(",")
    email_password = EMAIL_PASSWORD
    smtp_server = SMTP_SERVER

    subject = "Search Summary Alert"

    # HTML Email Body
    body = f"""
    <html>
        <head>
            <style type="text/css">
                .summary-table {{
                    width: 100%;
                    border-collapse: collapse;
                }}
                .summary-table th, .summary-table td {{
                    border: 1px solid #ddd;
                    padding: 8px;
                    text-align: left;
                }}
                .summary-table th {{
                    background-color: #4CAF50;
                    color: white;
                }}
            </style>
        </head>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2 style="color: #2e7d32;">Search Summary</h2>
            <table class="summary-table">
                <tr>
                    <th>Metric</th>
                    <th>Count</th>
                </tr>
                <tr>
                    <td>Total Posts Found</td>
                    <td><strong>{all_posts_count}</strong></td>
                </tr>
                <tr>
                    <td>New Posts Found</td>
                    <td><strong>{new_posts_count}</strong></td>
                </tr>
                <tr>
                    <td>Updated Posts Found</td>
                    <td><strong>{updated_posts_count}</strong></td>
                </tr>
            </table>
        </body>
    </html>
    """

    # Setting up the SMTP server
    with smtplib.SMTP(smtp_server, 587) as smtp:
        smtp.starttls()
        smtp.login(from_email, email_password)

        for to_email in to_emails:
            msg = MIMEMultipart()
            msg["From"] = from_email
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.attach(MIMEText(body, 'html'))
            text = msg.as_string()
            smtp.sendmail(from_email, to_email, text)


def load_old_posts():
    try:
        with open('posts.json', 'r', encoding='utf-8') as json_file:
            return json.load(json_file)
    except (FileNotFoundError, json.decoder.JSONDecodeError):
        return {}


def save_posts_to_file(posts_dict):
    with open('posts.json', 'w', encoding='utf-8') as json_file:
        json.dump(posts_dict, json_file, ensure_ascii=False, indent=4)


def extract_new_posts(all_posts, old_posts):
    return [post for post in all_posts if not any(old_post["Id"] == post["Id"] for old_post in old_posts)]


def BeginSearchParsing():
    log("Beginning search parsing...")

    old_posts_dict = load_old_posts()
    post_details_dict = old_posts_dict.copy()  # shallow copy is sufficient

    fresh_posts = navigate_and_load_all_posts()
    # Create a dict for easy comparison
    fresh_post_ids = {post_dict['Id']: post_dict for post_dict in fresh_posts}

    # Removing deleted posts
    for post_id in set(old_posts_dict.keys()) - set(fresh_post_ids.keys()):
        del post_details_dict[post_id]

    for post_dict in fresh_posts:
        post_id = post_dict["Id"]
        post_exists = post_details_dict.get(post_id)
        if post_exists:
            # delete last month post
            if post_exists["Created At"] < time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 2592000)):
                post_details_dict.remove(post_exists)
                continue

            thePost = post_details_dict[post_id]
            thePost["Old Price"] = thePost["Price"]
            thePost["Price"] = post_dict["Price"]
            thePost["Time & Location"] = post_dict["Time & Location"]
            thePost["Image URL"] = post_dict["Image URL"]
            thePost["Post URL"] = post_dict["Post URL"]
            thePost["Title"] = post_dict["Title"]
            thePost["Id"] = post_dict["Id"]
            thePost["Updated At"] = time.strftime("%Y-%m-%d %H:%M:%S")

            post_details_dict[post_id] = thePost
        else:
            post_details_dict[post_id] = post_dict

    save_posts_to_file(post_details_dict)

    # Extracting new posts and updated posts
    new_posts = [post for post_id, post in post_details_dict.items()
                 if post_id not in old_posts_dict]
    updated_posts = [post for post_id, post in post_details_dict.items(
    ) if post_id in old_posts_dict and post["Price"] != post["Old Price"] and post["Old Price"] != None]
    return post_details_dict, new_posts, updated_posts


def send_notification(all_posts, new_posts, updated_posts):
    try:
        log("Sending notification for search summary and updated posts...")

        from_email = FROM_EMAIL
        # Split the string by comma to get a list of emails
        to_emails = TO_EMAILS.split(",")
        email_password = EMAIL_PASSWORD
        smtp_server = SMTP_SERVER

        subject = "Search Summary and Price Alert"

        # Format the updated posts
        formatted_posts = format_updated_posts(updated_posts)

        # HTML Email Body
        body = f"""
        <html>
            <head>
                <link rel="stylesheet" href="https://stackpath.bootstrapcdn.com/bootstrap/4.3.1/css/bootstrap.min.css">
            </head>
            <body style="font-family: Arial, sans-serif;">
                <div class="container">
                    <h2 class="text-success">Search Summary</h2>
                    <table class="table table-bordered">
                        <tr>
                            <th>Metric</th>
                            <th>Count</th>
                        </tr>
                        <tr>
                            <td>Total Posts Found</td>
                            <td><strong>{len(all_posts)}</strong></td>
                        </tr>
                        <tr>
                            <td>New Posts Found</td>
                            <td><strong>{len(new_posts)}</strong></td>
                        </tr>
                        <tr>
                            <td>Updated Posts Found</td>
                            <td><strong>{len(updated_posts)}</strong></td>
                        </tr>
                    </table>
                    <hr>
                    <h2 class="text-success">Price Alert!</h2>
                    <p>Here is a list of updated posts:</p>
                    {formatted_posts}
                </div>
            </body>
        </html>
        """

        with smtplib.SMTP(smtp_server, 587) as smtp:
            smtp.starttls()
            smtp.login(from_email, email_password)

            for to_email in to_emails:
                msg = MIMEMultipart()
                msg["From"] = from_email
                msg["To"] = to_email
                msg["Subject"] = subject
                msg.attach(MIMEText(body, 'html'))

                text = msg.as_string()
                smtp.sendmail(from_email, to_email, text)

    except Exception as e:
        # Assuming log is a function you've defined
        log(f"Failed to send notification. Error: {e}")


def main():

    all_posts, new_posts, updated_posts = BeginSearchParsing()

    send_notification(all_posts, new_posts, updated_posts)


if __name__ == "__main__":
    while True:
        # clear the console
        os.system('cls' if os.name == 'nt' else 'clear')
        print("Restarting...")
        main()
        print("Sleeping for 60 seconds...")
        time.sleep(60)
