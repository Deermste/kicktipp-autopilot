from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as ec
from selenium.common.exceptions import TimeoutException

url = "https://www.predicd.com/de/football/league/4331/"

driver = webdriver.Chrome()  

try:
    driver.get(url)

    WebDriverWait(driver, 10).until(ec.presence_of_element_located((By.ID, "reloadArea")))

    WebDriverWait(driver, 30).until(ec.presence_of_element_located((By.TAG_NAME, "body")))

    '''
    # Wait for cookie notice and accept it
    try:
        cookie_notice = WebDriverWait(driver, 20).until(
            ec.presence_of_element_located((By.CSS_SELECTOR, ".cookie-notice"))
        )

        cookie_accept_button = cookie_notice.find_element(By.CSS_SELECTOR, ".cookie-notice__accept")
        cookie_accept_button.click()

        print("Cookie notice accepted successfully")
    except TimeoutException:
        print("No cookie notice found")
    '''

    titles = driver.find_elements(By.TAG_NAME, 'h2')

    for title in titles:
        try:
            title = title.text.split()
            if title[-1] == "SPIELTAG":
                print(title)
                break
        except:
            print("fuck")

    scores = driver.find_elements(By.CLASS_NAME, "of-meta")
    for score in scores:
        try:
            score_value = score.text
            score_html = score.get_attribute("outerHTML")
            score_html = score_html.split()
            print(score_value)
            print(score_html)

        except Exception as e:
            print(f"Error processing score: {str(e)}")

    '''
    # Adapted from the original script
    titles = driver.find_elements(By.TAG_NAME, 'span')
    print_3 = False
    count = 0
    y = ""

    for title in titles:
        dates = title.text.split()
        if len(dates) > 0:
            if any(date in dates[0] for date in ["08.11.", "09.11.", "10.11."]):
                print_3 = True
                count = 0  # Reset the counter when condition is met

            if print_3:
                texts = title.text.split()

                for text in texts:
                    if len(text) > 0:
                        y += text + " "

                count += 1

                if count >= 2:
                    print(y)
                    y = ""
                    print_3 = False  # Stop printing after 2 titles
                    
                    '''

except TimeoutException:
    print("Timed out waiting for page to load")

finally:
    driver.quit()



