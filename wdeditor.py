# This module is for editing Rotten Tomatoes scores on Wikidata.
###############################################################################
import sys
import time
import calendar
import json

import requests
import regex as re
import pywikibot as pwb


from datetime import datetime

from scraper import RTMovie



# Q105584: Rotten Tomatoes
# Q108403393: Rotten Tomatoes score
# Q108403540: Rotten Tomatoes average rating
# Q5433722: Fandango
# Q1860: English language
# P444: review score
# P447: review score by
# P7887: number of ratings
# P585: point in time

# P854: reference URL
# P813: retrieved
# P1476: title
# P123: publisher
# P407: language of webpage
# P248: stated in

def score_claims_from_movie(rtmovie):
    score, count, average = movie.tomatometer_score
    # simplify average format
    if '00' in average:
        average = average[0]
    else:
        average = str(float(average))

    day, month, year = map(int, datetime.today().strftime('%d %m %Y').split())
    wbtimetoday = pwb.WbTime(
        year=year,
        month=month,
        day=day,
        site = site)

    # AVERAGE CLAIM
    #######################################################################
    average_claim = pwb.Claim(site, 'P444')
    average_claim.setTarget(average + '/10')

    # qualifiers
    method = pwb.Claim(site, 'P459')
    method.setTarget(pwb.page.ItemPage(site, 'Q108403540')) # RT average rating
    average_claim.addQualifier(method)

    review_score_by = pwb.Claim(site, 'P95855')
    review_score_by.setTarget(pwb.page.ItemPage(site, 'Q105584')) # Rotten Tomatoes
    average_claim.addQualifier(review_score_by)

    point_in_time = pwb.Claim(site, 'P585')
    point_in_time.setTarget(wbtimetoday)
    average_claim.addQualifier(point_in_time)
    
    # reference
    statedin = pwb.Claim(site, 'P248')
    statedin.setTarget(pwb.page.ItemPage(site, 'Q105584'))
    title = pwb.Claim(site, 'P1476')
    title.setTarget(pwb.WbMonolingualText(movie.title, 'en'))
    languageofwork = pwb.Claim(site, 'P407')
    languageofwork.setTarget(pwb.page.ItemPage(site, 'Q1860'))
    refURL = pwb.Claim(site, 'P854')
    refURL.setTarget(movie.url)
    retrieved = pwb.Claim(site, 'P813')
    retrieved.setTarget(wbtimetoday)
    percent_claim.addSources([statedin, title, languageofwork, refURL, retrieved])

    # PERCENT CLAIM
    #######################################################################
    percent_claim = average_claim.copy()
    percent_claim.setTarget('score' + '%')

    number_of_reviews = pwb.Claim(site, 'P7887')
    review_quantity = pwb.WbQuantity(amount=count,
        unit="http://www.wikidata.org/entity/Q80698083", # critic review
        site=site
    )
    number_of_reviews.setTarget(review_quantity)
    percent_claim.addQualifier(number_of_reviews)
    # change determination method to RT score
    percent_claim.qualifiers['P459'][0].setTarget(pwb.page.ItemPage(site, 'Q108403393'))

    return [percent_claim, average_claim]

def remove_old_RT_claims(item):
    """Delete all Rotten Tomatoes review score (P444) claims."""
    claims_to_remove = []
    for c in item.claims.get('P444', []):
        if 'P447' in c.qualifiers: # review by
            val = c.qualifiers['P447'][0].getTarget()
            # remove if value is Rotten Tomatoes item
            if isinstance(val, pwb.page.ItemPage) and val.getID() == 'Q105584':
                claims_to_remove.append(c)
    item.removeClaims(claims_to_remove, summary='Removing old Rotten Tomatoes review scores.')

def add_RT_claims_to_item(item_id):
    """
    Given ItemPage, adds/updates RT scores if page has movie Rotten Tomatoes ID
    and scores are currently available.
    Returns True if scores are added/updated.
    """

    # Check that this item has Rotten Tomatoes ID starting with 'm/' and that
    # the film has a currently available Tomatometer score
    item = pwb.page.ItemPage(site, item_id)
    if not (x := item.claims.get('P1258')):
        return False
    movieid = x[0].getTarget()
    if not movieid.startswith('m/'):
        return False
    movie = RTMovie(movieid)
    if not movie.tomatometer_score:
        return False

    remove_old_RT_claims(item)

    percent_claim, average_claim = score_claims_from_movie(movie)
    item.addClaim(percent_claim, summary='Adding current Rotten Tomatoes score.')
    item.addClaim(average_claim, summary='Adding current Rotten Tomatoes average rating.')
    return True


class P1258Page:
    def __init__(self):
        query_string = """SELECT ?item ?b WHERE{?item wdt:P1258 ?b FILTER (regex(?b, '^m/'))}"""
        data = requests.get("https://query.wikidata.org/sparql",
            params={"query": query_string, "format": "json"}).json()
        x = {}
        for d in data['results']['bindings']:
            rtid = d['b']['value'].lower()
            entity_uri = d['item']['value'] 
            x[rtid] = entity_uri
        self._data = x

    def f(self):
        return self._data



if __name__ == "__main__":
    site = pwb.Site('wikidata', 'wikidata')
    site.login()

    entityid = 'Q28936' # Cloud atlas
    add_RT_claims_to_item(entityid)


    # x = P1258Page()
    # json.dump(x.f(), open('/Users/winston/Downloads/asdf.json', 'w'))



