# This module scrapes rottentomatoes.com for the desired data.
################################################################################
import requests
import sys
import json
import logging
logger = logging.getLogger(__name__)
print_logger = logging.getLogger('print_logger')

from datetime import date
from dataclasses import dataclass
from threading import Lock

from bs4 import BeautifulSoup
################################################################################
USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:89.0) Gecko/20100101 Firefox/89.0'
RT_HEADERS = {
    'Host': 'www.rottentomatoes.com',
    'User-Agent': USER_AGENT,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br',
    'DNT': '1',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-GPC': '1',
}

BLOCKED_LOCK = Lock()

def rt_url(movieid):
    return "https://www.rottentomatoes.com/" + movieid

def url_contents(url):
    logger.debug("Scraping %s", url)
    r = requests.get(url, headers=RT_HEADERS)
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
    url: str = ''
    title: str = ''
    year: str = ''
    rtid: str = ''
    access_date: str = ''
    synopsis: str = ''
    rating: str = ''
    genre: str = ''
    original_language: str = ''
    director: list[str] = ''
    producer: list[str] = ''
    writer: list[str] = ''
    release_date_theaters: str = ''
    release_date_streaming: str = ''
    box_office_gross_usa: str = ''
    runtime: str = ''
    production_co: list[str] = ''
    sound_mix: list[str] = ''
    aspect_ratio: list[str] = ''
    view_the_collection: str = ''

    tomatometer_score: tuple[str, str, str] = None
    consensus: str = None

    def __post_init__(self):
        for attr in ('director', 'producer', 'writer', 'production_co',
                'sound_mix', 'aspect_ratio'):
            setattr(self, attr, [])

        try:
            html = url_contents(rt_url(self.short_url))
        except requests.exceptions.HTTPError as x:
            if x.response.status_code == 403:
                BLOCKED_LOCK.acquire(blocking=False)
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
        self.url = str(soup.find('link', rel='canonical')['href'])
        j = html.find(') - Rotten Tomatoes</title>')
        self.year = html[j-4 :j]
        self.access_date = date.today().strftime("%B %d, %Y")

        indicator = 'root.RottenTomatoes.context.movieDetails = '
        terminator = ';'
        d = json.loads(find_substring(html, indicator, terminator))
        self.short_url = d["movieDetailsURL"]
        self.title = d["movieTitle"]
        self.rtid = d["id"]
        self.synopsis = str(soup.find('div', id="movieSynopsis").string.strip())

        for x in soup.find_all('li', attrs={'data-qa': "movie-info-item"}):
            item = x.div.string
            attr = item.lower().translate(str.maketrans(' ', '_', ':()'))
            if item in ['Genre:', 'Production Co:', 'Sound Mix:', 'Aspect Ratio:']:
                setattr(self, attr, [str(s.strip()) for s in x('div')[1].string.split(',')])
            elif item in ['Director:', 'Producer:', 'Writer:']:
                setattr(self, attr, [str(a.string) for a in x('a')])
            elif item == 'Release Date (Theaters):':
                setattr(self, attr, f"{x.find('time').string} {x.find('span').string.strip().capitalize()}")
            else:
                setattr(self, attr, str(x('div')[1].get_text(strip=True)))

        consensus = str(soup.find('span', attrs={'data-qa': "critics-consensus"}))
        consensus = consensus[consensus.find('>')+1 : consensus.rfind('<')]
        consensus = consensus.replace('<em>',"''").replace('</em>',"''").replace("'''", r"''{{'}}")
        self.consensus = consensus

        sd = str(soup.find('script', id='score-details-json'))
        self.score_data = json.loads(sd[sd.find('>')+1 : sd.rfind('<')])["modal"]
        if self.score_data["hasTomatometerScoreAll"]:
            if sd := self.score_data["tomatometerScoreAll"]:
                average = sd["averageRating"]
                count = str(sd["ratingCount"])
                score = sd["score"]
                self.tomatometer_score = (score, count, average)


if __name__ == "__main__":
    # r = requests.get(rt_url('m/meadowland'))
    # soup = BeautifulSoup(r.text, "html.parser")
    # d = json.loads(str(soup.find('script', id='score-details-json')).split('>')[1].split('<')[0])
    # print(json.dumps(d, indent=4))
    print(RTMovie('m/the_tomorrow_war'))




