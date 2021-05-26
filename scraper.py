import urllib.request
import json
import re


from datetime import date
from bs4 import BeautifulSoup


def url_contents(url):
    with urllib.request.urlopen(url) as f:
        contents = f.read().decode()
    return contents

def find_substring(s, indicator, terminator):
    """
    Given a string, returns the substring of the string
    strictly between the indicator and terminator strings, if it exists.
    Otherwise returns None. It is possible that it
    returns an empty string if the indicator and terminator
    are adjacent.
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

    The keys are: 'score', 'average', 'count', and 'accessDate'
    """
    contents = url_contents(url)
    indicator = '<script id="score-details-json" type="application/json">'
    terminator = '</script>'
    score_data = find_substring(contents, indicator, terminator)
    sd = json.loads(score_data)['modal']

    if sd['hasTomatometerScoreAll'] == False:
        return None
    else:
        sd = sd['tomatometerScoreAll']

    return {'score' : sd['score'],
            'average' : sd['averageRating'],
            'count' : sd['reviewCount'],
            'count2' : sd['ratingCount'],
            'accessDate' : date.today().strftime("%B %d, %y") # e.g. May 24, 2021
        }




if __name__ == "__main__":
    print(BeautifulSoup(url_contents("https://www.rottentomatoes.com/m/us_2019"), 'html.parser').prettify())





