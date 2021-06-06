# This module scrapes rottentomatoes.com for the desired data.

import urllib.request
import json
import sys

from datetime import date


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
    """
    # print("URL =", url, flush=True, file=sys.stderr)
    contents = url_contents(url)

    indicator = '<script id="score-details-json" type="application/json">'
    terminator = '</script>'
    score_data = find_substring(contents, indicator, terminator)
    sd = json.loads(score_data)['modal']
    if sd['hasTomatometerScoreAll'] == False:
        return None
    else:
        sd = sd['tomatometerScoreAll']
    if not sd:
        print("There was a problem getting the Rotten Tomatoes rating from {}. Try again later.".format(url),
            file = sys.stderr)
        return sd

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

    #print(sd, file=sys.stderr, flush=True)
    return {'title' : title,
            'score' : sd['score'],
            'average' : sd['averageRating'],
            'reviewCount' : str(sd['reviewCount']),
            'ratingCount' : str(sd['ratingCount']),
            'consensus' : consensus,
            'accessDate' : date.today().strftime("%B %d, %Y"), # e.g. May 24, 2021
        }


if __name__ == "__main__":
    pass





