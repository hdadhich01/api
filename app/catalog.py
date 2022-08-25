from datetime import datetime
from pprint import pprint
from re import sub
from unicodedata import normalize
from urllib.parse import quote_plus

from aiohttp import ClientSession
from bs4 import BeautifulSoup
from bs4 import SoupStrainer
from flask import abort
from flask import Blueprint
from flask import redirect
from flask import request
from flask import url_for
from orjson import loads
from requests import Session
from thefuzz.process import extractOne

catalog_bp = Blueprint("catalog", __name__)


@catalog_bp.route("/")
def home():
    return "<h1>Welcome to Catalog!</h1>"


# TODO: https://github.com/Nobelz/RateMyProfessorAPI has a ~2s slower implementation; push a PR
@catalog_bp.route("/teacher/<name>")
async def get_teacher(name):
    # session = Session()
    # sid possibly prone to change
    async with ClientSession() as session:
        page = await session.get(
            f"https://www.ratemyprofessors.com/search/teachers?query={quote_plus(name)}&sid=1078"
        )
        soup = BeautifulSoup(
            await page.text(), "lxml", parse_only=SoupStrainer("script")
        )
        content = {}

        for i in soup:
            if "_ = " in i.text:
                content = loads(i.text[: i.text.index(";")].split("_ = ")[1])
                # using first match at index 4 (relative to sid query parameter)
                # if pushing pr to api library, access reference IDs to make list of teachers
                content = content[list(content.keys())[4]]
                for i in content:
                    if isinstance(content[i], int) and content[i] <= 0:
                        content[i] = None
                break

        # __ref possibly prone to change
        return (
            {
                "name": f"{content['firstName']} {content['lastName']}",
                "department": content["department"],
                "rating": content["avgRating"],
                "ratings": content["numRatings"],
                "difficulty": content["avgDifficulty"],
                "wouldRetake": round(content["wouldTakeAgainPercent"])
                if content["wouldTakeAgainPercent"]
                else None,
                "page": f"https://www.ratemyprofessors.com/ShowRatings.jsp?tid={content['legacyId']}",
            }
            if "id" in content and content["school"]["__ref"] == "U2Nob29sLTEwNzg="
            else abort(404)
        )


@catalog_bp.route("/term", methods=["GET", "POST"])
def get_term():
    inbound = {}
    try:
        inbound = request.get_json(force=True)
    except:
        pass
    inbound.update(dict(request.args))
    year = int(datetime.now().strftime("%Y"))
    # TODO: fetch from calendar
    quarters, hold = {
        "winter": [datetime(year, 3, 24), 2],
        "spring": [datetime(year, 6, 15), 4],
        "summer": [datetime(year, 9, 1), 6],
        "fall": [datetime(year, 12, 9), 10],
    }, []
    if inbound.get("quarter"):
        if not quarters.get(inbound.get("quarter").lower()):
            abort(400)
        else:
            hold = [
                inbound.get("quarter").lower(),
                quarters[inbound.get("quarter").lower()][1],
            ]
    if inbound.get("year"):
        if (
            int(inbound.get("year")) <= year
        ):  # FIXME: pisa could list a year ahead, not sure
            year = int(inbound.get("year"))
    if not inbound.get("quarter"):
        for i in quarters:
            if datetime.today().replace(year=year) < quarters[i][0].replace(year=year):
                hold.append(i)
                hold.append(quarters[i][1])
                break
    # TODO: adjust the function to align with pisa (occ. a quarter ahead)?
    quarter, code = hold[0], 2048 + ((year % 100 - 5) * 10) + hold[1]
    code += 4  # temporary alignment with pisa
    return (
        {"code": code, "term": f"{year} {quarter.capitalize()} Quarter"}
        if code >= 2048
        else abort(400)
    )


# TODO: use https://ucsc.textbookx.com/institutional/index.php?action=browse#/books/3426324
@catalog_bp.route("/class/textbooks/<class_id>")
def get_textbooks(class_id):
    pass


@catalog_bp.route("/class")
def get_redirect():
    # TODO: point to cataog/class section
    return redirect("/")


@catalog_bp.route("/class/detail", methods=["GET", "POST"])
def get_course():
    inbound, session = {}, Session()
    try:
        inbound = request.get_json(force=True)
    except:
        pass
    inbound.update(dict(request.args))
    term = (
        inbound["term"]
        if inbound.get("term")
        else session.get(f"http://127.0.0.1:5000{url_for('catalog.get_term')}").json()[
            "code"
        ]
    )
    if inbound.get("number"):
        if isinstance(inbound.get("number"), (int, str)):
            number = str(inbound["number"])
        else:
            abort(400, "The inbound parameter 'number' is of an invalid data type.")
    else:
        abort(400, "The inbound parameter 'number' is required.")

    outbound = {
        "action": "detail",
        "class_data[:STRM]": term,
        "class_data[:CLASS_NBR]": number,
    }
    return outbound
    page = session.post("https://pisa.ucsc.edu/class_search/index.php", data=outbound)
    soup = BeautifulSoup(page.text, "lxml")
    print(soup)
    return {"success": True}


@catalog_bp.route("/class/search/template")
def get_search_template():
    with open("app/data/json/pisa/template.json", "r") as f:
        template = loads(f.read())
    return template if template else abort(503)


@catalog_bp.route("/class/search", methods=["GET", "POST"])
def search_course():
    inbound = {}
    try:
        inbound = request.get_json(force=True)
    except:
        pass
    inbound.update(dict(request.args))
    # [curr year relative calendar, increment value]
    with open("app/data/json/pisa/template.json", "r") as f:
        template = loads(f.read())
    template = template if template else abort(503)
    with open("app/data/json/pisa/outbound.json", "r") as f:
        outbound = loads(f.read())
    c, keys = 0, list(outbound.keys())
    # TODO: abort with 500 for invalid types, or use default?
    # TODO: adjust ratio threshold for fuzzy matching
    # FIXME: operation keys not getting fuzzy matches properly
    # TODO: add debug option to view outbound headers
    # TODO: incorporate way to check type of courseNumber and courseUnits value
    # if it works, it works
    for i in template:
        if isinstance(template[i], dict):
            # compromise
            hasSubLevels = False
            for j in template[i]:
                if isinstance(template[i][j], dict):
                    hasSubLevels = True
                    break
            if hasSubLevels:
                for j in template[i]:
                    if isinstance(template[i][j], dict):
                        if inbound.get(i, {}).get(j):
                            extract = extractOne(
                                str(inbound[i][j]), list(template[i][j].keys())
                            )
                            print(extract)
                            if (
                                isinstance(inbound[i][j], (int, str))
                                and extract[1] > 85
                            ):
                                outbound[keys[c]] = extract[0]
                        c += 1
                    else:
                        if inbound.get(i, {}).get(j) and isinstance(
                            inbound[i][j], (int, str)
                        ):
                            outbound[keys[c]] = inbound[i][j]
                        c += 1
                continue  # debugging for a solid hour got me to add this line
            else:
                # special cases
                if isinstance(inbound.get(i), dict):
                    if i == "instructionModes":
                        for j in inbound[i]:
                            if not inbound[i][j]:
                                outbound[keys[c]] = ""
                    else:
                        # TODO: regulate # of results
                        if (
                            inbound[i].get("results")
                            and str(inbound[i]["results"]).isnumeric()
                        ):
                            outbound["rec_dur"] = inbound[i]["results"]
                        # TODO: regulate page #
                        if (
                            inbound[i].get("number")
                            and str(inbound[i]["number"]).isnumeric()
                            and int(inbound[i]["number"]) > 1
                        ):
                            outbound["action"] = "next"
                            outbound["rec_start"] = (
                                int(inbound[i]["number"]) - 2
                            ) * int(outbound["rec_dur"])
                elif inbound.get(i):
                    extract = extractOne(str(inbound[i]), list(template[i].keys()))
                    print(extract)
                    if isinstance(inbound[i], (int, str)) and extract[1] > 85:
                        outbound[keys[c]] = extract[0]
            c += 1
        elif isinstance(template[i], list):
            if inbound.get(i):
                extract = extractOne(str(inbound[i]), template[i])
                print(extract)
                if isinstance(inbound[i], (int, str)) and extract[1] > 85:
                    outbound[keys[c]] = extract[0]
            c += 1
        else:
            if i in inbound:  # .get() issue
                # FIXME: type() is slower than isinstance()
                if isinstance(inbound[i], (int, str)):
                    outbound[keys[c]] = inbound[i]
            c += 1
    session, classes = Session(), {}
    page = session.post("https://pisa.ucsc.edu/class_search/index.php", data=outbound)
    soup = BeautifulSoup(
        page.text,
        "lxml",
        parse_only=SoupStrainer(
            "div", attrs={"class": ["panel panel-default row", "row hide-print"]}
        ),
    )
    for i in soup.find_all("div", attrs={"class": "panel panel-default row"}):
        head = sub(
            " +",
            " ",
            normalize(
                "NFKD",
                i.find("div", attrs={"class": "panel-heading panel-heading-custom"})
                .find("h2")
                .find("a")
                .text,
            ),
        )
        body = i.find("div", attrs={"class": "panel-body"}).find("div")
        number = body.find("div", attrs={"class": "col-xs-6 col-sm-3"})
        instructor = (
            body.find_all("div", attrs={"class": "col-xs-6 col-sm-3"})[1]
            .get_text(separator="\n")
            .replace(",", ", ")
            .split("\n")
        )
        instructor = [i.strip() for i in instructor]
        mode = body.find_all("div", attrs={"class": "col-xs-6 col-sm-3 hide-print"})[
            2
        ].text.split(":")[1]
        classes[int(number.find("a").text)] = {
            "detail": number.find("a")["href"],
            "subject": head.split(" ")[0],
            "number": head.split(" ")[1],
            "section": head.split(" ")[3],
            "name": " ".join(head.split(" ")[4:]).replace(":", ": ").replace(",", ", "),
            "instructor": instructor[1:]
            if len(instructor) > 2
            else instructor[1],  # can be array
            "mode": mode,  # mode
            # "location": "", # can be array
            # "time": "", # can be array, can be cancelled
            # "seats": { # TODO: maybe change name
            #     "taken": 0,
            #     "capacity": 20
            # },
            # "textbooks": "", # link
        }
    number = (
        1
        if int(outbound["rec_start"]) == 0
        else int(int(outbound["rec_start"]) / int(outbound["rec_dur"]) + 2)
    )
    total = int(
        soup.find("div", attrs={"class": "row hide-print"}).find_all("b")[2].text
    )
    left = total - int(outbound["rec_dur"]) * number
    display = left if left < int(outbound["rec_dur"]) else int(outbound["rec_dur"])
    return {
        "page": {
            "number": number,
            "results": {"display": display, "total": total},
        },
        "classes": classes,
    }


# @catalog_bp.route("/calendar") # make calendar endpoint
# @catalog_bp.route("/classrooms") # make classroom endpoint
