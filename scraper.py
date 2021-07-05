# This module scrapes rottentomatoes.com for the desired data.

import requests
import sys
import json
import logging
logger = logging.getLogger(__name__)
print_logger = logging.getLogger('print_logger')

from datetime import date
from dataclasses import dataclass
from bs4 import BeautifulSoup

HEADERS = {
    'Host': 'www.rottentomatoes.com',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:89.0) Gecko/20100101 Firefox/89.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br',
    'DNT': '1',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-GPC': '1',
}

def rt_url(movieid):
    return "https://www.rottentomatoes.com/" + movieid

def url_contents(url):
    logger.debug("Scraping %s", url)
    r = requests.get(url, headers=HEADERS)
    if r.status_code != 200:
        r.raise_for_status()
    return r.text

def find_substring(s, indicator, terminator):
    """
    Given a string, returns the substring
    strictly between the indicator and terminator strings, if they exist.
    Otherwise returns None.
    It is possible that an empty string is returned
    if the indicator and terminator are adjacent.
    """
    i = s.find(indicator)
    if i == -1:
        return None
    j = s.find(terminator, i + len(indicator))
    if j == -1:
        return None
        
    return s[i + len(indicator) : j]

@dataclass
class RTMovie:
    short_url: str
    url: str = None
    title: str = None
    year: str = None
    rtid: str = None
    access_date: str = None
    synopsis: str = None
    rating: str = None
    genre: str = None
    original_language: str = None
    director: list[str] = None
    producer: list[str] = None
    writer: list[str] = None
    release_date_theaters: str = None
    release_date_streaming: str = None
    box_office_gross_usa: str = None
    runtime: str = None
    production_co: list[str] = None
    sound_mix: list[str] = None
    aspect_ratio: str = None
    view_the_collection: str = None

    tomatometer_score: tuple[str, str, str] = None

    def __post_init__(self):
        try:
            html = url_contents(rt_url(self.short_url))
        except requests.exceptions.HTTPError as x:
            if x.response.status_code == 403:
                self.blocked.acquire(blocking=False)
                logger.exception("Probably blocked by rottentomatoes.com. Exiting thread")
                sys.exit()
            elif x.response.status_code == 404:
                logger.debug("404 Client Error", exc_info=True)
            elif x.response.status_code == 500:
                logger.debug("500 Server Error", exc_info=True)
            elif x.response.status_code == 504:
                logger.debug("504 Server Error", exc_info=True)
            else:
                logger.exception("An unknown HTTPError occured for short url %s", self.short_url)
            raise
        except requests.exceptions.TooManyRedirects as x:
            logger.exception("Too many redirects for short url %s", self.short_url)
            raise

        soup = BeautifulSoup(html, "html.parser")
        self.url = soup.find('link', rel='canonical')['href']
        j = r.text.find(') - Rotten Tomatoes</title>')
        self.year = r.text[j-4 :j]
        self.access_date = date.today().strftime("%B %d, %Y")

        indicator = 'root.RottenTomatoes.context.movieDetails = '
        terminator = ';'
        d = json.loads(find_substring(r.text, indicator, terminator))
        self.short_url = d["movieDetailsURL"]
        self.title = d["movieTitle"]
        self.rtid = d["id"]
        self.synopsis = soup.find('div', id="movieSynopsis").string.strip()

        for x in soup.find_all('li', attrs={'data-qa': "movie-info-item"}):
            item = x.div.string
            attr = item.lower().translate(str.maketrans(' ', '_', ':()'))
            setattr(self, attr, 'HELLO')

            if item in ['Genre:', 'Production Co:', 'Sound Mix:', 'Aspect Ratio:']:
                setattr(self, attr, [s.strip() for s in x('div')[1].string.split(',')])
            elif item in ['Writer:', 'Director:', 'Producer:']:
                setattr(self, attr, [a.string for a in x('a')])
            elif item == 'Release Date (Theaters):':
                setattr(self, attr, f"{x.find('time').string} {x.find('span').string.strip().capitalize()}")
            else:
                setattr(self, attr, x('div')[1].get_text(strip=True))

        consensus = str(soup.find('span', attrs={'data-qa': "critics-consensus"}))
        consensus = consensus[consensus.find('>')+1 : consensus.rfind('<')]
        consensus = consensus.replace('<em>',"''").replace('</em>',"''")
        if "'''" in consensus:
            consensus = consensus.replace("'''", r"''{{'}}")
        self.consensus = consensus

        sd = str(soup.find('script', id='score-details-json'))
        self.score_data = json.loads(sd[sd.find('>')+1 : sd.rfind('<')])["modal"]
        if self.score_data["hasTomatometerScoreAll"]:
            if sd := self.score_data["tomatometerScoreAll"]:
                average = sd["averageRating"]
                count = str(sd["ratingCount"])
                score = sd["score"]
                self.tomatometer_score = (score, count, average)

# def get_rt_rating(movieid):
#     """
#     Given the url of a movie page from Rotten tomatoes,
#     returns a dictionary containing the score, average rating, review count,
#     and also the current date.
#     All the values are strings.
#     """
#     url = rt_url(movieid)
#     try:
#         contents = url_contents(url)
#     except requests.exceptions.HTTPError as x:
#         if x.response.status_code == 403:
#             self.blocked.acquire(blocking=False)
#             logger.exception("Probably blocked by rottentomatoes.com. Exiting thread")
#             sys.exit()
#         elif x.response.status_code == 404:
#             logger.debug("404 Client Error", exc_info=True)
#         elif x.response.status_code == 500:
#             logger.debug("500 Server Error", exc_info=True)
#         elif x.response.status_code == 504:
#             logger.debug("504 Server Error", exc_info=True)
#         else:
#             logger.exception("An unknown HTTPError occured for [[%s]] with id %s", title, movieid)
#         raise
#     except requests.exceptions.TooManyRedirects as x:
#         logger.exception("Too many redirects for [[%s]] with id %s", title, movieid)
#         raise

#     indicator = '<script id="score-details-json" type="application/json">'
#     terminator = '</script>'
#     score_data = find_substring(contents, indicator, terminator)
#     if not score_data:
#         raise ValueError(f"Could not find score data for {movieid}.")

#     sd = json.loads(score_data)['modal']
#     if sd['hasTomatometerScoreAll'] == False:
#         logger.debug("Tomatometer not yet available for %s", movieid)
#         return None

#     sd = sd['tomatometerScoreAll']

#     # When this occurs even though sd['hasTomatometerScoreAll'] == True,
#     # it means that Rotten Tomatoes isn't loading the rating for whatever reason.
#     # Not sure why this happens. Usually it loads if you try again later.
#     if not sd:
#         logger.error("Rotten Tomatoes is not currently loading the rating for %s", movieid)
#         return {}

#     # get title
#     indicator = "<title>"
#     terminator = " - Rotten Tomatoes"
#     title = find_substring(contents, indicator, terminator)
#     year = title[-5:-1]

#     # get critics consensus, if it exists.
#     indicator = '<span data-qa="critics-consensus">'
#     terminator = '</span>'
#     # will be None if there is no critic's consensus
#     consensus = find_substring(contents, indicator, terminator)
#     # replace <em> and </em> with '', which makes italics for Wikipedia
#     if consensus: # make sure consensus is not None
#         consensus = consensus.replace('<em>', "''").replace('</em>', "''")
#         consensus = consensus.replace("'''", r"''{{'}}") # apostrophe case

#     return {'title' : title,
#             'year' : year,
#             'url' : url,
#             'id' : movieid,
#             'score' : sd['score'],
#             'average' : sd['averageRating'],
#             'reviewCount' : str(sd['reviewCount']),
#             'ratingCount' : str(sd['ratingCount']),
#             'consensus' : consensus,
#             'accessDate' : date.today().strftime("%B %d, %Y"), # e.g. May 24, 2021
#         }


if __name__ == "__main__":
    # r = requests.get(rt_url('m/meadowland'))
    # soup = BeautifulSoup(r.text, "html.parser")
    # d = json.loads(str(soup.find('script', id='score-details-json')).split('>')[1].split('<')[0])
    # print(json.dumps(d, indent=4))

    movie = RTMovie('m/leap')
    print(movie)




