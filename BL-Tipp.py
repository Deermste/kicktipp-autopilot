import base64
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException
import time

options = [Options(), Options()]
options[0].add_argument("--headless")
options[0].add_experimental_option('excludeSwitches', ['enable-logging']) 
options[1].add_argument("--blink-settings=imagesEnabled=false")
options[1].add_experimental_option('excludeSwitches', ['enable-logging']) 
options[1].add_argument("--start-maximized")

name_map = {
    "FC Bayern München": "FC Bayern München",
    "RB Leipzig": "RB Leipzig",
    "1. FC Heidenheim": "1. FC Heidenheim 1846",
    "VfL Wolfsburg": "VfL Wolfsburg",
    "1. FC Union Berlin": "1. FC Union Berlin",
    "VfB Stuttgart": "VfB Stuttgart",
    "Bayer Leverkusen": "Bayer 04 Leverkusen",
    "TSG Hoffenheim": "1899 Hoffenheim",
    "Eintracht Frankfurt": "Eintracht Frankfurt",
    "Werder Bremen": "Werder Bremen",
    "SC Freiburg": "SC Freiburg",
    "FC Augsburg": "FC Augsburg",
    "FC St. Pauli": "FC St. Pauli",
    "Borussia Dortmund": "Borussia Dortmund",
    "1. FSV Mainz 05": "FSV Mainz 05",
    "1. FC Köln": "1. FC Köln",
    "Borussia M'Gladbach": "Bor. Mönchengladbach",
    "Hamburger SV": "Hamburger SV",
}

spieltag = ""

def translate_club_name(name):
    return name_map.get(name, name)  

all_hometeams_and_scores = [[0 for _ in range(3)] for _ in range(9)]

url = "https://www.predicd.com/de/football/league/4331/"
driver = webdriver.Chrome(service=Service(), options=options[0])

try:
    driver.get(url)

    try:
        cookie_accept_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".fc-button.fc-cta-consent.fc-primary-button"))
        )
        cookie_accept_button.click()
    except TimeoutException:
        print("Kein Cookie-Banner gefunden oder bereits akzeptiert.")


    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "span[id^='predResult_']"))
    )

    spieltag = driver.find_element(By.ID, "matchdayNumber").text.strip()

    print("Predictions ", spieltag)

    match_rows = driver.find_elements(By.CSS_SELECTOR, "tr.tr-body")

    index = 0

    for row in match_rows:
        try:
            teams = row.find_elements(By.CSS_SELECTOR, "div#teamname")
            if len(teams) < 2:
                continue
            home_team = teams[0].text.strip()
            away_team = teams[1].text.strip()

            score_parts = row.find_elements(By.CSS_SELECTOR, "span[id^='predResult_'] .of-meta")

            decoded_score_parts = []
            for part in score_parts:
                meta_info = part.get_attribute("meta-info")
                decoded = ""
                if meta_info:
                    decoded_bytes = base64.b64decode(meta_info)
                    decoded_text = decoded_bytes.decode("utf-16-be")
                    for ch in decoded_text:
                        cp = ord(ch)
                        decoded += str(cp)
                decoded = str(int((int(decoded[-4:]) - 1760) / 256))
                decoded_score_parts.append(decoded)

            decoded_score = ":".join(decoded_score_parts)

            if len(home_team) > 0 and len(away_team) > 0:
                print(f"{home_team} vs {away_team} → {decoded_score}")
                all_hometeams_and_scores[index][0] = translate_club_name(home_team)
                all_hometeams_and_scores[index][1] = decoded_score[0]
                all_hometeams_and_scores[index][2] = decoded_score[2]
                index += 1

        except Exception as e:
            print(f"Error processing row: {e}")

finally:
    driver.quit()

url2 = "https://www.kicktipp.de/sfsdfvsd/tippabgabe"
driver2 = webdriver.Chrome(service=Service(), options=options[1])

try:
    driver2.get(url2)

    anmelden_button = WebDriverWait(driver2, 10).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[name="submitbutton"][type="submit"]'))
    )

    try:
        e_mail = driver2.find_element(By.CSS_SELECTOR, 'input#kennung[type="email"]')
        e_mail.send_keys("pse1812@web.de")
    except NoSuchElementException:
        print("Fehler: E-Mail-Eingabefeld nicht gefunden.")

    try:
        passwort = driver2.find_element(By.CSS_SELECTOR, "#passwort")
        passwort.send_keys("Ermisch00")
    except NoSuchElementException:
        print("Fehler: Passwort-Eingabefeld nicht gefunden.")

    try:
        anmelden_button.click()
    except ElementClickInterceptedException:
        print("Fehler: Anmelden-Button konnte nicht geklickt werden.")

    try:
        iframe = WebDriverWait(driver2, 10).until(
            EC.frame_to_be_available_and_switch_to_it((By.ID, "sp_message_iframe_1230027"))
        )

        cookie_accept_button = WebDriverWait(driver2, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".message-component.message-button.no-children.focusable.action_button.sp_choice_type_11"))
        )

        cookie_accept_button.click()

        driver2.switch_to.default_content()

    except TimeoutException:
        print("Kein Cookie-Banner gefunden oder bereits akzeptiert.")
            
    WebDriverWait(driver2, 20).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "tr.datarow"))
    )

    match_rows = driver2.find_elements(By.CSS_SELECTOR, "tr.datarow")

    if spieltag[1:2] == driver2.find_element(By.CSS_SELECTOR, "div.prevnextTitle").text.strip()[1:2]:
        for row in match_rows:
            try:
                home_team_div = row.find_element(By.CSS_SELECTOR, "td.nw.cell.col1")

                for team_and_score in all_hometeams_and_scores:
                    if team_and_score[0] == home_team_div.text.strip():
                        tipps = row.find_elements(By.CSS_SELECTOR, "input[id^='spieltippForms'][type='text']")
                        tipps[0].clear()  
                        tipps[1].clear()  
                        tipps[0].send_keys(team_and_score[1])
                        tipps[1].send_keys(team_and_score[2])
                        time.sleep(0.5)  
                    
            except NoSuchElementException as e:
                continue
    else:
        print("Spieltag stimmt nicht überein, Tipps werden nicht eingetragen.")

    try:
        submit_button = WebDriverWait(driver2, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[name="submitbutton"][type="submit"]'))
        )

        submit_button.click()
        time.sleep(5) 
    except TimeoutException:
        print("Tipps konnten nicht eingetragen werden, da der Submit-Button nicht gefunden wurde.")
    
except TimeoutException:
    print("Timeout: Anmelden-Button nicht in Zeit gefunden oder nicht klickbar.")
except Exception as e:
    print(f"Unbekannter Fehler: {e}")

finally:
    driver2.quit()
    print("Erfolgreicher Eintrag der Tipps in Kicktipp")
    time.sleep(5) 
