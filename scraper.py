# This module is for scraping rottentomatoes.com.
################################################################################
import json
import logging
import re
import sys

from dataclasses import dataclass, field
from datetime import date

import requests

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)
################################################################################
USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:92.0) Gecko/20100101 Firefox/92.0'
RT_HEADERS = {
    'Host': 'www.rottentomatoes.com',
    'User-Agent': USER_AGENT,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br',
    'DNT': '1',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    # 'Referer': 'https://www.rottentomatoes.com/',
    # 'Sec-Fetch-Dest': 'document',
    # 'Sec-Fetch-Mode': 'navigate',
    # 'Sec-Fetch-Site': 'none',
    # 'Sec-Fetch-User': '?1',
    # 'Sec-GPC': '1',
}

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
class RTmovie:
    short_url: str
    url: str = None
    access_date: str = None
    title: str = None
    year: str = None
    synopsis: str = None
    rating: str = None
    genre: str = None
    original_language: str = None
    director: list[str] = field(default_factory=list)
    producer: list[str] = field(default_factory=list)
    writer: list[str] = field(default_factory=list)
    release_date_theaters: str = None
    release_date_streaming: str = None
    box_office_gross_usa: str = None
    runtime: str = None
    production_co: list[str] = field(default_factory=list)
    sound_mix: list[str] = field(default_factory=list)
    aspect_ratio: list[str] = None
    view_the_collection: str = None

    tomatometer_score: tuple[str, str, str] = None
    audience_score: tuple[str, str, str] = None
    consensus: str = None
    audience_says: str = None

    def __post_init__(self):
        for attr in ('director', 'producer', 'writer', 'production_co',
                'sound_mix', 'aspect_ratio'):
            setattr(self, attr, [])

        try:
            html = url_contents(rt_url(self.short_url))
        except requests.exceptions.HTTPError as x:
            if x.response.status_code == 403:
                logger.exception("Probably blocked by Rotten Tomatoes. Exiting.")
                sys.exit()
            elif x.response.status_code == 404:
                logger.debug("404 Client Error", exc_info=True)
            elif x.response.status_code == 500:
                logger.debug("500 Server Error", exc_info=True)
            elif x.response.status_code == 503:
                logger.exception("Probably blocked by Rotten Tomatoes? Exiting.")
                sys.exit()
            elif x.response.status_code == 504:
                logger.debug("504 Server Error", exc_info=True)
            else:
                logger.exception(f"An unknown HTTPError occured for short url {self.short_url}. Exiting.")
                sys.exit()
            raise
        except requests.exceptions.TooManyRedirects as x:
            logger.exception("Too many redirects for %s", self.short_url)
            raise

        soup = BeautifulSoup(html, "html.parser")
        self.url = str(soup.find('link', rel='canonical')['href'])
        self.short_url = self.url.split('rottentomatoes.com/')[-1]
        self.access_date = date.today().strftime("%B %d, %Y")

        self.synopsis = str(soup.find('div', id="movieSynopsis").string.strip())

        for x in soup.find_all('li', attrs={'data-qa': "movie-info-item"}):
            item = x.div.string.rstrip(':')
            attr = item.lower().translate(str.maketrans(' ', '_', '()'))
            if item in ['Genre', 'Production Co', 'Sound Mix', 'Aspect Ratio']:
                setattr(self, attr, [str(s.strip()) for s in x('div')[1].string.split(',')])
            elif item in ['Director', 'Producer', 'Writer']:
                setattr(self, attr, [str(a.string) for a in x('a')])
            elif item == 'Release Date (Theaters)':
                setattr(self, attr,
                    f"{x.find('time').string} {x.find('span').string.strip().capitalize()}")
            else:
                setattr(self, attr, str(x('div')[1].get_text(strip=True)))

        x = soup.find_all('p', attrs={'class': "what-to-know__section-body"})
        if x:
            consensus = re.search(r'>(.*)</span', str(x[0].span))[1]
            consensus = re.sub(r'</?em>|</?i>', "''", consensus)
            consensus = consensus.replace("'''", r"''{{'}}")
            consensus = consensus.replace('"', "'")
            self.consensus = consensus
        if len(x) > 1:
            audience_says = re.search(r'>(.*)</span', str(x[1].span))[1]
            audience_says = re.sub(r'</?em>|</?i>', "''", audience_says)
            audience_says = audience_says.replace("'''", r"''{{'}}")
            audience_says = audience_says.replace('"', "'")
            self.audience_says = audience_says

        sd = str(soup.find('script', id='score-details-json'))
        self.score_data = json.loads(sd[sd.find('>')+1 : sd.rfind('</scr')])
        self.year = self.score_data["scoreboard"]["info"].split(',')[0]
        self.title = self.score_data["scoreboard"]["title"]
        #if self.score_data['modal']["hasTomatometerScoreAll"]:
        if sd := self.score_data['modal']["tomatometerScoreAll"]:
            s, c, a = sd["score"], sd["ratingCount"], sd["averageRating"] or ''
            if s is not None:
                self.tomatometer_score = (str(s), str(c), str(a))
        #if self.score_data['modal']["hasAudienceScoreAll"]:
        if sd := self.score_data['modal']["audienceScoreAll"]:
            s, c, a = sd["score"], sd["ratingCount"], sd["averageRating"]
            if s is not None:
                self.audience_score = (str(s), str(c), str(a))

if __name__ == "__main__":
    movie = RTmovie('m/wifemistress')
    print(movie)


