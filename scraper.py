# This module scrapes rottentomatoes.com for the desired data.

import urllib.request
import requests
import json
import sys
import logging
logger = logging.getLogger(__name__)

from datetime import date



SESSION = requests.Session()
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

def url_contents(url):
    logger.info("Scraping {}".format(url))
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


def get_rt_rating(url):
    """
    Given the url of a movie page from Rotten tomatoes,
    returns a dictionary containing the score, average rating, review count,
    and also the current date.
    All the values will be in string form.
    """
    contents = url_contents(url)

    indicator = '<script id="score-details-json" type="application/json">'
    terminator = '</script>'
    score_data = find_substring(contents, indicator, terminator)
    if not score_data:
        raise ValueError("Could not find score data at {}".format(url))

    sd = json.loads(score_data)['modal']
    if sd['hasTomatometerScoreAll'] == False:
        logger.info("Tomatometer not yet available for {}".format(url))
        return None

    sd = sd['tomatometerScoreAll']

    # When this occurs even though sd['hasTomatometerScoreAll'] == True,
    # it means that Rotten Tomatoes isn't loading the rating for whatever reason.
    # Not sure why this happens. Usually it loads if you try again later.
    if not sd:
        logger.error("Rotten Tomatoes is not currently loading the rating for {}".format(url))
        return {}

    # get title
    indicator = "<title>"
    terminator = " - Rotten Tomatoes"
    title = find_substring(contents, indicator, terminator)

    # get critics consensus, if it exists.
    indicator = '<span data-qa="critics-consensus">'
    terminator = '</span>'
    # will be None if there is no critic's consensus
    consensus = find_substring(contents, indicator, terminator)
    # replace <em> and </em> with '', which makes italics for Wikipedia
    if consensus: # make sure consensus is not None
        consensus = consensus.replace('<em>', "''")
        consensus = consensus.replace('</em>', "''")
        consensus = consensus.replace("'''", r"''{{'}}") # apostrophe case

    return {'title' : title,
            'url' : url,
            'score' : sd['score'],
            'average' : sd['averageRating'],
            'reviewCount' : str(sd['reviewCount']),
            'ratingCount' : str(sd['ratingCount']),
            'consensus' : consensus,
            'accessDate' : date.today().strftime("%B %d, %Y"), # e.g. May 24, 2021
        }


if __name__ == "__main__":
    pass





