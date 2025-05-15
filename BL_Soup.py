#import pandas as pd
#from selenium import webdriver
from bs4 import BeautifulSoup
import requests
#from requests_html import HTMLSession$
from datetime import datetime

print(datetime.today().strftime('%d.%m.'))

url = "https://www.predicd.com/de/football/league/4331/"

page = requests.get(url)
soup = BeautifulSoup(page.content, 'html.parser')


# Beispiel: Extrahiere alle Überschriften (Titel der Spiele)
titles = soup.find_all('h2') # x. Spieltag
for title in titles:
    texts = title.text.split()
    if texts[-1] == "Spieltag":
        print(texts)

scores = soup.find_all(class_="of-meta")
for score in scores:
    number_element = score.find('span')  
    if number_element:
        text = number_element.text.strip()
        print(text)

titles = soup.find_all('span')  
print_3 = False
count = 0
y = ""

#td class="inner-d align-middle text center">
#<div id="teamname"
#span id="predResult_2090393"

for title in titles:
    dates = title.text.split()
    if len(dates) > 0:
        if dates[0] in ["08.11.", "09.11.", "10.11."]:
            print_3 = True
            count = 0  # Reset the counter when the condition is met

        if print_3:
            texts = title.text.split()

            #if len(title) > 0:
            #    print(title)

            for text in texts:
                if len(text) > 0:
                    y += text
                    y += " "

            count += 1

            if count >= 2:
                print(y)
                y = ""
                print_3 = False  # Stop printing after 2 titles

#for title in titles:
 #   print(title.text)
