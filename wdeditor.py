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

from scraper import RTMovie, USER_AGENT
from patterns import *

Q_ROTTEN_TOMATOES           = 'Q105584'
Q_TOMATOMETER               = 'Q108403393'
Q_ROTTEN_TOMATOES_AVERAGE   = 'Q108403540'
Q_FANDANGO                  = 'Q5433722'
Q_ENGLISH                   = 'Q1860'

P_ROTTEN_TOMATOES_ID        = 'P1258'
P_REVIEW_SCORE              = 'P444'
P_REVIEW_SCORE_BY           = 'P447'
P_REVIEW_COUNT              = 'P7887'
P_POINT_IN_TIME             = 'P585'
P_DETERMINATION_METHOD      = 'P459'
P_REFERENCE_URL             = 'P854'
P_RETRIEVED                 = 'P813'
P_TITLE                     = 'P1476'
P_PUBLISHER                 = 'P123'
P_LANGUAGE                  = 'P407'
P_STATED_IN                 = 'P248'
P_REASON_FOR_PREFERRED_RANK = 'P7452'
P_REASON_FOR_DEPRECATION    = 'P2241'

def get_results(query):
    headers = {'User-Agent': USER_AGENT}
    data = requests.get(
        "https://query.wikidata.org/sparql",
        params={"query":query, "format":"json"},
        headers=headers).json()
    return data["results"]["bindings"]


def qid_from_movieid(movieid):
    query = "SELECT ?item ?b WHERE{?item wdt:P1258 ?b FILTER (regex(?b, '^movieid$', 'i'))}"
    query = query.replace('movieid', movieid)
    data = get_results(query)
    if data:
        return data[0]['item']['value'].split('/')[-1]
    # try:
    #     y = RTMovie(movieid).short_url
    # except:
    #     return None
    # if y.lower() == movieid.lower():
    #     return None
    # query = query.replace(movieid, y)
    # data = get_results(query)
    # if data:
    #     return data[0]['item']['value'].split('/')[-1]
    # return None

def most_recent_score_data(entity_id):
    query = """SELECT ?score ?count ?average
WHERE 
{
  ?item p:P444 ?reviewstatement.
  ?reviewstatement pq:P447 wd:Q105584.    # reviewed by Rotten Tomatoes.
  ?reviewstatement pq:P459 wd:Q108403393. # determination method
  ?reviewstatement ps:P444 ?score.
  ?reviewstatement pq:P7887 ?count.
  ?reviewstatement pq:P585 ?time1.
  OPTIONAL {?item p:P444 ?reviewstatement2.
  ?reviewstatement2 pq:P447 wd:Q105584.    # reviewed by Rotten Tomatoes.
  ?reviewstatement2 pq:P459 wd:Q108403540. # determination method
  ?reviewstatement2 ps:P444 ?average.
  ?reviewstatement2 pq:P585 ?time1.}
  # only get most recent point in time
  FILTER NOT EXISTS {
    ?item p:P444 ?reviewstatement3.
    ?reviewstatement3 pq:P447 wd:Q105584.   # reviewed by Rotten Tomatoes.
    ?reviewstatement3 pq:P585 ?time2.
    filter (?time2 > ?time1)
  }
}"""
    query = query.replace('?item', 'wd:'+entity_id)
    data = get_results(query)
    score, count, average = '','',''
    if data:
        data = data[0]
        score = data['score']['value']
        count = data['count']['value']
        if 'average' in data:
            average = data['average']['value']
    return score, count, average

def should_add_RT_claims(movie, qid):
    """
    If should add RT claims, return the two claims (percent and average)
    to be added.
    Otherwise return False.
    """
    if not movie.tomatometer_score:
        return False

    new_score, new_count, new_average = movie.tomatometer_score
    new_score = int(new_score)
    new_count = int(new_count)
    if new_average:
        new_average = float(new_average)

    old_score, old_count, old_average = most_recent_score_data(qid)
    print(old_score, old_count, old_average)
    if not old_score:
        return score_claims_from_movie(movie)

    if m := re.fullmatch(r'([0-9]|[1-9][0-9]|100)(%| percent)', old_score):
        old_score = int(m[1])
    else:
        return score_claims_from_movie(movie)


    if m := re.fullmatch(r'\d+', old_count):
        old_count = int(m[0])
    else:
        return score_claims_from_movie(movie)
    
    if old_average:
        if m := re.fullmatch(r'(([0-9]|10)(\.\d\d?)?)(?:/| out of )10', old_average):
            old_average = float(m[1])
        else:
            return score_claims_from_movie(movie)

    if (old_score, old_count, old_average) != (new_score, new_count, new_average):
        return score_claims_from_movie(movie)
    return False

def claim(pid, target):
    """
    Return pwb.Claim object for entity with pid and specified target.
    """
    c = pwb.Claim(pwb.Site('wikidata','wikidata'), pid)
    c.setTarget(target)
    return c

def score_claims_from_movie(movie):
    """
    Assuming that movie has tomatometer_score.
    """
    site = pwb.Site('wikidata','wikidata')
    score, count, average = movie.tomatometer_score
    # manage average format
    if average == '': # in rare cases, no average is available
        pass
    elif '00' in average:
        average = average[0] + '/10'
    else:
        average = str(float(average)) + '/10'

    percent_claim = claim(P_REVIEW_SCORE, score + '%')
    average_claim = claim(P_REVIEW_SCORE, average)

    # set up qualifiers
    RTitem = pwb.ItemPage(site, Q_ROTTEN_TOMATOES)
    day, month, year = map(int, datetime.today().strftime('%d %m %Y').split())
    wbtimetoday = pwb.WbTime(
        year=year,
        month=month,
        day=day,
        site = site)
    review_score_by = claim(P_REVIEW_SCORE_BY, RTitem)
    review_quantity = pwb.WbQuantity(amount=count,
        unit="http://www.wikidata.org/entity/Q80698083", # critic review
        site=site
    )
    number_of_reviews = claim(P_REVIEW_COUNT, review_quantity)
    point_in_time = claim(P_POINT_IN_TIME, wbtimetoday)
    percent_method = claim(P_DETERMINATION_METHOD, pwb.ItemPage(site, Q_TOMATOMETER))
    average_method = claim(P_DETERMINATION_METHOD, pwb.ItemPage(site, Q_ROTTEN_TOMATOES_AVERAGE))
    
    # set up reference
    statedin = claim(P_STATED_IN, RTitem)
    rtid_claim = claim(P_ROTTEN_TOMATOES_ID, movie.short_url)
    title = claim(P_TITLE, pwb.WbMonolingualText(movie.title, 'en'))
    # languageofwork = claim(P_LANGUAGE, pwb.ItemPage(site, Q_ENGLISH))
    retrieved = claim(P_RETRIEVED, wbtimetoday)

    source_order = [statedin, rtid_claim, title, retrieved]

    # add qualifiers, reference, and rank for percent claim
    for x in [review_score_by, number_of_reviews, point_in_time, percent_method]:
        percent_claim.addQualifier(x)
    percent_claim.addSources(source_order)
    percent_claim.setRank('normal')

    # add qualifiers, reference, and rank for average claim
    for x in [review_score_by, point_in_time, average_method]:
        average_claim.addQualifier(x)
    average_claim.addSources(source_order)
    average_claim.setRank('normal')

    if average == '': # special case when there is percent but no average
        average_claim.setSnakType('novalue')

    return percent_claim, average_claim

def add_RT_claims_to_item(movie, item):
    site = item.site
    if z := should_add_RT_claims(movie, item.getID()):
        percent_claim, average_claim = z
    else:
        return False

    # set rank of all existing non-deprecated RT score claims to 'normal'
    for c in item.claims.get(P_REVIEW_SCORE, []):
        if P_REVIEW_SCORE_BY in c.qualifiers: # review by
            val = c.qualifiers[P_REVIEW_SCORE_BY][0].getTarget()
            if val == pwb.ItemPage(site, Q_ROTTEN_TOMATOES) and c.rank == 'preferred':
                c.changeRank('normal')

    item.addClaim(percent_claim, summary='Add Rotten Tomatoes score. Test edit. See [[Wikidata:Requests for permissions/Bot/RottenBot]].')
    item.addClaim(average_claim, summary='Add Rotten Tomatoes average rating. Test edit. See [[Wikidata:Requests for permissions/Bot/RottenBot]].')
    return True

def add_RTmovie_data_to_item(movie, item):
    """
    Adds/updates the Rotten Tomatoes data in a Wikidata item.
    Currently this means the Rotten Tomatoes ID and the two score claims.
    """
    site = item.site
    day, month, year = map(int, datetime.today().strftime('%d %m %Y').split())
    wbtimetoday = pwb.WbTime(
        year=year,
        month=month,
        day=day,
        site = site)
    retrieved = claim(P_RETRIEVED, wbtimetoday)

    if P_ROTTEN_TOMATOES_ID in item.claims:
        rtid_claim = item.claims[P_ROTTEN_TOMATOES_ID][0]
        if rtid_claim.getTarget() != movie.short_url:
            rtid_claim.changeTarget(movie.short_url)
            rtid_claim.addSource(retrieved)
    else:
        rtid_claim = claim(P_ROTTEN_TOMATOES_I, movie.short_url)
        rtid_claim.addSource(retrieved)
        item.addClaim(rtid_claim)

    add_RT_claims_to_item(movie, item)


if __name__ == "__main__":
    site = pwb.Site('wikidata', 'wikidata')
    site.login()

    movie = RTMovie('m/veronika_voss')
    item = pwb.ItemPage(site, 'Q703188')
    add_RTmovie_data_to_item(movie, item)

    # print(most_recent_score_data('Q28936'))
    # print(qid_from_movieid('m/maRVels_the_avengers'))


