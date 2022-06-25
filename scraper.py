import string
from bs4 import BeautifulSoup, SoupStrainer
import cchardet
from datetime import datetime
from pprint import pprint
from re import findall, sub
from requests import Session
from thefuzz import fuzz
from unicodedata import normalize
from urllib.parse import parse_qs, quote_plus

# TODO: research parser types for BeautifulSoup; https://en.wikipedia.org/wiki/Beautiful_Soup_(HTML_parser)

session = Session()
home = "https://nutrition.sa.ucsc.edu/"
menu_table = "https://nutrition.sa.ucsc.edu/longmenu.aspx?sName=UC+Santa+Cruz+Dining&locationNum=40&locationName= College+Nine%2fJohn+R.+Lewis+Dining+Hall &naFlag=1&WeeksMenus=UCSC+-+This+Week%27s+Menus&dtdate=05%2f07%2f2022&mealName=Breakfast"
menu_table = "https://nutrition.sa.ucsc.edu/longmenu.aspx?sName=UC+Santa+Cruz+Dining&locationNum=05&locationName= Cowell%2fStevenson+Dining+Hall &naFlag=1&WeeksMenus=UCSC+-+This+Week%27s+Menus&dtdate= 05%2f07%2f 2022&mealName= Breakfast"
nutrition_label = "https://nutrition.sa.ucsc.edu/label.aspx?locationNum=40&locationName=College+Nine%2fJohn+R.+Lewis+Dining+Hall&dtdate=05%2f07%2f2022&RecNumAndPort=400387*3"

# this func is heavy so limit scrape calls to once a day
# FIXME: incorporate waitz process into another func, since this func can't be called frequently
def get_locations():
  unsplit = {}
  page = session.get("https://nutrition.sa.ucsc.edu/")
  soup = BeautifulSoup(page.text, "lxml")
  # initial return setup; parses only from menu page
  for i in soup.find_all("a"):
    if "location" in i["href"]:
      unsplit[int(parse_qs(i["href"])["locationNum"][0])] = {
        # nutrition.sa.ucsc.edu
        # "id": int(parse_qs(i["href"])["locationNum"][0]),
        "name": parse_qs(i["href"])["locationName"][0],
        # dining.ucsc.edu/eat
        "description": None,
        "phone": None,
        "address": None,
        # "hours": None, # selenium?
        # waitz
        "open": None, # include hours?
        "occupation": None
      }
  
  page = session.get("https://dining.ucsc.edu/eat/")
  soup = BeautifulSoup(page.text, "lxml-xml")
  # groups headers and child elements (location info page)
  temp, matches = soup.find_all(["h2", "li"]), {}
  for index, value in enumerate(temp):
    if (index + 1 < len(temp) and index - 1 >= 0):
      if temp[index - 1].name == "h2" and value.name == "li":
        matches[temp[index - 1]] = value
  
  # location matching
  for i in unsplit:
    ratio_list = {}
    isMultiple = [False, []]
    for j in matches:
      ratio = fuzz.ratio(unsplit[i]["name"].lower().replace("dining hall", ""), j.text.lower().replace("dining hall", ""))
      ratio_list[ratio] = j
      if unsplit[i]["name"].lower()[:-1] in j.text.lower() and "closed" not in j.text.lower():
        # FIXME: only serves perk coffee bars; go for global approach
        if ratio == 52: # detects for perk bar (phys sci building)
          isMultiple[0] = True
        isMultiple[1].append(j)
    max_ratio = max(list(ratio_list.keys()))
    li = matches[ratio_list[max_ratio]]
    
    # waitz api processing
    response = session.get("https://waitz.io/live/ucsc")
    data = response.json()
    response = session.get("https://waitz.io/compare/ucsc")
    comp_data = response.json()
    ratio_list = {}
    for j in data["data"]:
      # current compromise to get past the name - ratio problem
      if len(ratio_list) == 4:
        break
      ratio = fuzz.ratio(unsplit[i]["name"].lower().replace("dining hall", ""), j["name"].lower().replace("dining hall", ""))
      ratio_list[ratio] = [j, comp_data["data"][len(ratio_list)]]
    max_ratio = max(list(ratio_list.keys()))

    # location matching
    if isMultiple[0] is True:
      if not isinstance(unsplit[i]["description"], list):
        unsplit[i]["description"] = []
        unsplit[i]["phone"] = []
        unsplit[i]["address"] = []
      for j in isMultiple[1]:
        unsplit[i]["description"].append(sub(" +", " ", normalize("NFKD", matches[j].find("p").text.split("✆")[0].strip())))
        unsplit[i]["phone"].append(sub(" +", " ", normalize("NFKD", matches[j].find("p").text.split("✆")[1].strip())))
        # https://developers.google.com/maps/documentation/urls/get-started
        unsplit[i]["address"].append(f"https://www.google.com/maps/dir/?api=1&destination={quote_plus(j.text.strip())}")
    else:
      unsplit[i]["description"] = sub(" +", " ", normalize("NFKD", li.find("p").text.split("✆")[0].strip()))
      unsplit[i]["phone"] = sub(" +", " ", normalize("NFKD", li.find("p").text.split("✆")[1].strip()))
      unsplit[i]["address"] = f"https://www.google.com/maps/dir/?api=1&destination={quote_plus(unsplit[i]['name'])}"

    # waitz matching
    # compromise in matching c9/c10 to c9/john r. lewis; contacted waitz support to change name
    # c9/c10 => c9/john r. lewis gives a ratio of 46, whereas others are 90+
    if max_ratio == 46 or max_ratio > 90:
      if ratio_list[max_ratio][0]["isOpen"]:
        unsplit[i]["open"] = True
        trends = []
        for j in ratio_list[max_ratio][1]["comparison"]:
          if j["valid"]:
            soup = BeautifulSoup(j["string"], "lxml")
            text = soup.get_text()
            trends.append(text)
        unsplit[i]["occupation"] = {
          "people": ratio_list[max_ratio][0]["people"],
          "capacity": ratio_list[max_ratio][0]["capacity"],
          "busyness": ratio_list[max_ratio][0]["locHtml"]["summary"],
          "bestLocation": None,
          "subLocations": None,
          "trends": None
        }
        # TODO: very scuffed approach, try to repair
        if ratio_list[max_ratio][0]["bestLocations"]:
          if ratio_list[max_ratio][0]["subLocs"]:
            unsplit[i]["occupation"]["subLocations"] = []
            for j in ratio_list[max_ratio][0]["subLocs"]:
              if j["id"] == ratio_list[max_ratio][0]["bestLocations"][0]["id"]:
                unsplit[i]["occupation"]["bestLocation"] = j["name"]
              unsplit[i]["occupation"]["subLocations"].append({
                "name": j["name"],
                "abbreviation": j["abbreviation"],
                "people": j["people"],
                "capacity": j["capacity"],
                "busyness": j["subLocHtml"]["summary"]
              })
        trends = []
        for j in ratio_list[max_ratio][1]["comparison"]:
          if j["valid"]:
            soup = BeautifulSoup(j["string"], "lxml")
            trends.append(soup.get_text())
        unsplit[i]["occupation"]["trends"] = trends if trends else None
      else:
        unsplit[i]["open"] = False

  master = {"diningHalls": {}, "butteries": {}}
  for i in unsplit: master["diningHalls" if "dining hall" in unsplit[i]["name"].lower() else "butteries"][i] = unsplit[i]
  return master

# pprint(get_locations(), sort_dicts = False)

# process @ request (no loop)
# TODO: create function after implementing db
# def update_waitz():
#   master = get_locations()

# imported from parent function
def get_location(location_id: int):
  locations = get_locations()
  for i in locations:
    for j in locations[i]:
      print(j)
      if j["id"] == location_id:
        return j

# loop @ 1 day
def get_menus(date = datetime.now().strftime("%m-%d-%Y")):
  locations = get_locations()
  master = {}
  for i in locations:
    master[i] = {}
    for j in locations[i]:
      menu = {"short": {}, "long": {}}
      # short scraping
      new = session.get("https://nutrition.sa.ucsc.edu/")
      new = session.get(f"{home}shortmenu.aspx?locationNum={j:02d}&locationName={quote_plus(locations[i][j]['name'])}&naFlag=1&dtdate={date}")
      if new.status_code == 500:
        return None
      short_soup = BeautifulSoup(new.text, "lxml")
      # TODO: no data available or empty meal containers, develop conditional for latter
      status = short_soup.find("div", {"class": "shortmenuinstructs"})
      if status.text == "No Data Available":
        master[i][j] = None
        continue
      
      # TODO: could run two loops concurrently with multiprocessing, attempt later
      # long scraping
      item_list = {}
      for k in short_soup.find_all("a"):
        # TODO: do a faster check
        if k["href"].startswith("longmenu"):
          new = session.get(home + k["href"])
          long_soup = BeautifulSoup(new.text, "lxml")
          meal = parse_qs(k["href"])["mealName"][0]
          menu["long"][meal] = {}
          for l in long_soup.find_all("div", {"class": ["longmenucolmenucat", "longmenucoldispname", "longmenucolprice"]}):
            if l["class"][0] == "longmenucolmenucat":
              menu["long"][meal][l.text.split("--")[1].strip()] = {}
            elif l["class"][0] == "longmenucoldispname":
              course = list(menu["long"][meal].keys())[-1]
              item_id = l.find("input").attrs["value"]
              menu["long"][meal][course][normalize("NFKD", l.text).strip()] = item_id
              item_list[normalize("NFKD", l.text).strip()] = item_id
            elif l.text.strip() != "": # else doesn't account for course row price whitespace
              course = list(menu["long"][meal].keys())[-1]
              item = list(menu["long"][meal][course].keys())[-1]
              item_price = {"id": menu["long"][meal][course][item], "price": l.text}
              menu["long"][meal][course][item] = item_price
              item_list[item] = item_price
      
      # short scraping
      for k in short_soup.find_all("div", {"class": ["shortmenumeals", "shortmenucats", ["shortmenurecipes"]]}): # meal(s), course(s), item(s)
        if k["class"][0] == "shortmenumeals":
          menu["short"][k.text] = {}
        elif k["class"][0] == "shortmenucats":
          menu["short"][list(menu["short"].keys())[-1]][k.text.split("--")[1].strip()] = {}
        else:
          meal = list(menu["short"].keys())[-1]
          course = list(menu["short"][meal].keys())[-1]
          # FIXME: cheese pizza issue; current fix is just a error bypass
          # normalize() just removes the "\xa0" that comes at the end of each j.text
          try:
            menu["short"][meal][course][normalize("NFKD", k.text).strip()] = item_list[normalize("NFKD", k.text).strip()]
          except:
            pass
      # short and long dict attachment
      master[i][j] = None if all(not menu["short"][m] for m in menu["short"]) else menu
  # remove submenus; short == long
  # parsing diningHalls and butteries separately not practical
  for i in master["butteries"]:
    if master["butteries"][i]:
      master["butteries"][i] = master["butteries"][i]["short"] 
  return master

# imported from parent function
def get_menu(location_id: int, date):
  menus = get_locations()
  if location_id in list(menus.keys()):
    return menus[location_id]
  return -1

# process at request; consider making a db for all items (not efficient)
# sync with db and implement checks
def get_item(item_id: string):
  url = session.get("https://nutrition.sa.ucsc.edu/")
  # location set to lowest int:02d; labels don't show up without locationNum query
  url = session.get(f"https://nutrition.sa.ucsc.edu/label.aspx?locationNum=05&RecNumAndPort={item_id}")
  soup = BeautifulSoup(url.text, "lxml")
  if soup.find("div", {"class": "labelnotavailable"}):
    return None
  master = {
    "name": None,
    "ingredients": None,
    "labels": {
      "eggs": False,
      "vegan": False,
      "fish": False,
      "veggie": False,
      "gluten": False,
      "pork": False,
      "milk": False,
      "beef": False,
      "nuts": False,
      "halal": False,
      "soy": False,
      "shellfish": False,
      "treenut": False
    },
    "nutrition": {
      "amountPerServing": {
        "servingSize": None,
        "calories": None,
        "totalFat": None,
        "saturatedFat": None,
        "transFat": None,
        "cholesterol": None,
        "sodium": None,
        "totalCarbohydrate": None,
        "dietaryFiber": None,
        "totalSugars": None,
        "protein": None
      },
      "percentDailyValue": {
        "totalFat": None,
        "saturatedFat": None,
        "cholesterol": None,
        "sodium": None,
        "totalCarbohydrate": None,
        "dietaryFiber": None,
        "vitaminD": None,
        "calcium": None,
        "iron": None,
        "potassium": None
      }
    }
  }
  master["name"] = soup.find("div", {"class": "labelrecipe"}).text
  master["ingredients"] = soup.find("span", {"class": "labelingredientsvalue"}).text
  
  # labels
  # img_tags = SoupStrainer("img")
  # soup = BeautifulSoup(url.text, "lxml", parse_only = img_tags)
  for i in soup.find_all("img"):
    if i["src"].startswith("LegendImages"):
      master["labels"][i["src"].split("/", 1)[1][:-4]] = True

  # nutrition
  # scuffed approach; make an efficient one
  complete = ""
  soup = BeautifulSoup(url.text, "lxml", parse_only = SoupStrainer("tr"))
  for i in soup.find("td"):
    complete += sub(" +", " ", normalize("NFKD", i.text).replace("\n", "").strip())
  
  # hardcoded for now; maybe try to fetch keywords from scraped; might be a stretch
  keywords = ["Serving Size", "Calories", "Total Fat", "Sat. Fat", "Trans Fat", "Cholesterol", "Sodium ", "Tot. Carb.", "Dietary Fiber", "Sugars", "Protein", "Vitamin D - mcg", "Calcium", "Iron", "Potassium"]
  for k in keywords:
    complete = sub(k, f"'{k}'", complete)
      
  pattern  = rf"'({'|'.join(keywords)})'\s*([^'*]+)"
  # pattern = rf"'({'|'.join(keywords)})'\s*(\d+\.?\d*\s*\w+\s*\w*(?:\s*\d*%)?)"
  # pattern = rf"'({'|'.join(keywords)})'\s*(\d+\.?\d*\s*(?:oz|g|%|mg|)(?:\s*\d*%)?)"
  matches = dict(findall(pattern, complete))
  matches = {k:v.strip() for k, v in matches.items()}
  # FIXME: current bypass for potassium error
  copy = {}
  for item in keywords:
    try:
      copy[item] = "0%" if not matches[item] else matches[item]
    except:
      copy[item] = "0%"
  matches = copy
  # pprint(matches, sort_dicts = False)
  # matches["Serving Size"] = search("ize (.*?)Cal", original).group(1).replace("%", "/")

  for index, key in enumerate(master["nutrition"]["amountPerServing"]):
    temp = matches[list(matches.keys())[index]]
    temp = temp if any(i.isdigit() for i in temp) else f"0{temp.split()[-1]}"
    master["nutrition"]["amountPerServing"][key] = temp if key != "calories" else int(temp)

  for index, key in enumerate(master["nutrition"]["percentDailyValue"]):
    if index < 6: # exclude vitaminD, calcium, iron, and potassium
      temp = master["nutrition"]["amountPerServing"][key]
      # FIXME: "- - - g" issue (/400387*2*01)
      temp = temp[temp.index("g") + 1:len(temp) - 1]
      # master["nutrition"]["percentDailyValue"][key] = int(temp) if temp else None
    else:
      temp = matches[list(matches.keys())[index + 5]][:-1]
    master["nutrition"]["percentDailyValue"][key] = int(temp) if temp else 0

  for i in master["nutrition"]["amountPerServing"]:
    temp = master["nutrition"]["amountPerServing"][i]
    master["nutrition"]["amountPerServing"][i] = temp[0:temp.index("g") + 1] if str(temp).endswith("%") else temp

  # (.*?) as opposed to (.*); non-greedy expression; https://blog.finxter.com/python-regex-greedy-vs-non-greedy-quantifiers/
  # master["nutrition"]["amountPerServing"]["servingSize"] = search("ize (.*?)Cal", string).group(1).replace("%", "/")
  # master["nutrition"]["amountPerServing"]["calories"] = search(r"ies (.*)*Per", string).group(1)
  
  return master