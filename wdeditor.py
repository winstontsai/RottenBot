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
from patterns import *

# Q105584: Rotten Tomatoes
# Q108403393: Rotten Tomatoes score
# Q108403540: Rotten Tomatoes average rating
# Q5433722: Fandango
# Q1860: English language
# P444: review score
# P447: review score by
# P7887: number of ratings
# P585: point in time
# P459: determination method

# P854: reference URL
# P813: retrieved
# P1476: title
# P123: publisher
# P407: language of webpage
# P248: stated in

def get_results(query):
    data = requests.get("https://query.wikidata.org/sparql",
        params={"query":query, "format":"json"}).json()
    return data["results"]["bindings"]


def entityid_from_movieid(movieid):
    query = f"SELECT ?item ?b WHERE{{?item wdt:P1258 ?b FILTER (regex(?b, '^{movieid}$', 'i'))}}"
    data = get_results(query)
    if data:
        return data[0]['item']['value'].split('/')[-1]
    try:
        y = RTMovie(movieid).short_url
    except:
        return None
    if y.lower() == movieid.lower():
        return None
    query = query.replace(movieid, y)
    data = get_results(query)
    if data:
        return data[0]['item']['value'].split('/')[-1]
    return None

def most_recent_score(entity_id, score_type = 'percent'):
    query = f"""SELECT ?reviewvalue
WHERE 
{{
  wd:{entity_id} p:P444 ?reviewstatement.
  ?reviewstatement pq:P447 wd:Q105584.    # reviewed by Rotten Tomatoes.
  ?reviewstatement pq:P459 wd:Q108403393. # determination method
  ?reviewstatement ps:P444 ?reviewvalue.
  ?reviewstatement pq:P585 ?time1
  # only get most recent point in time
  filter not exists {{
    ?reviewstatement pq:P585 ?time2
    filter (?time2 > ?time1)
  }}
}}"""
    if score_type == 'average':
        query = query.replace('Q108403393', 'Q108403540')
    elif score_type != 'percent':
        raise ValueError(f'Unknown score_type argument: {score_type}.')

    if data := get_results(query):
        return data[0]['reviewvalue']['value']


def should_add_RT_claims(item):
    """
    If should add RT claims, return the two claims (percent and average)
    to be added.
    Otherwise return False.
    """
    if not (x := item.claims.get('P1258')):
        return False
    movieid = x[0].getTarget()
    if not movieid.startswith('m/'):
        return False
    try:
        movie = RTMovie(movieid)
    except:
        return False
    if not movie.tomatometer_score:
        return False

    current_score, count, current_average = map(float, movie.tomatometer_score)

    old_score = most_recent_score(item.getID())
    old_average = most_recent_score(item.getID(), score_type='average')

    if old_score is None or old_average is None:
        return score_claims_from_movie(movie)

    if m := re.fullmatch(r'([0-9]|[1-9][0-9]|100)(%| percent)', old_score):
        old_score = float(m[1])
    else:
        return score_claims_from_movie(movie)
    
    if m := re.fullmatch(r'(([0-9]|10)(\.\d\d?)?)(?:/| out of )10', old_average):
        old_average = float(m[1])
    else:
        return score_claims_from_movie(movie)

    if old_score != current_score or old_average != current_average:
        return score_claims_from_movie(movie)
    
    return False

def score_claims_from_movie(movie):
    """
    Assume that movie has tomatometer_score.
    """
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
    review_score_by = pwb.Claim(site, 'P447')
    review_score_by.setTarget(pwb.page.ItemPage(site, 'Q105584')) # Rotten Tomatoes
    average_claim.addQualifier(review_score_by)

    point_in_time = pwb.Claim(site, 'P585')
    point_in_time.setTarget(wbtimetoday)
    average_claim.addQualifier(point_in_time)

    method = pwb.Claim(site, 'P459')
    method.setTarget(pwb.page.ItemPage(site, 'Q108403540')) # RT average rating
    average_claim.addQualifier(method)
    
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
    average_claim.addSources([statedin, title, languageofwork, refURL, retrieved])

    # PERCENT CLAIM
    #######################################################################
    percent_claim = average_claim.copy()
    percent_claim.setTarget(score + '%')

    number_of_reviews = pwb.Claim(site, 'P7887')
    review_quantity = pwb.WbQuantity(amount=count,
        unit="http://www.wikidata.org/entity/Q80698083", # critic review
        site=site
    )
    number_of_reviews.setTarget(review_quantity)
    percent_claim.addQualifier(number_of_reviews)

    # change determination method to RT score
    percent_claim.qualifiers['P459'][0].setTarget(pwb.page.ItemPage(site, 'Q108403393'))

    # newest scores are preferred
    percent_claim.setRank('preferred')
    average_claim.setRank('preferred')

    return [percent_claim, average_claim]


def add_RT_claims_to_item(item_id):
    time.sleep(10)  # slow down editing
    item = pwb.page.ItemPage(site, item_id)
    z = should_add_RT_claims(item)
    if z:
        percent_claim, average_claim = z
    else:
        return False

    # set rank of all existing RT score claims to 'normal'
    for c in item.claims.get('P444', []):
        if 'P447' in c.qualifiers: # review by
            # check that review is by Rotten Tomatoes
            val = c.qualifiers['P447'][0].getTarget()
            if not isinstance(val, pwb.page.ItemPage) or val.getID()!='Q105584':
                continue
            # changed 'preferred' ranks to 'normal'
            if c.rank == 'preferred':
                c.changeRank('normal')

    item.addClaim(percent_claim, summary='Add Rotten Tomatoes score. Test edit. See [[Wikidata:Requests for permissions/Bot/RottenBot]].')
    item.addClaim(average_claim, summary='Add Rotten Tomatoes average rating. Test edit. See [[Wikidata:Requests for permissions/Bot/RottenBot]].')
    return True


if __name__ == "__main__":
    site = pwb.Site('wikidata', 'wikidata')
    site.login()


    # count = 0
    # items_to_edit = ['Q728404', 'Q728485', 'Q728488', 'Q728499', 'Q728539', 'Q728555', 'Q728618', 'Q729026', 'Q729246', 'Q729297', 'Q729360', 'Q729666', 'Q729671', 'Q729788', 'Q729794', 'Q729807', 'Q729836', 'Q729980', 'Q729991', 'Q730164', 'Q730228', 'Q730321', 'Q730340', 'Q730370', 'Q730436', 'Q730473', 'Q730555', 'Q730584', 'Q730639', 'Q730765', 'Q730857', 'Q730888', 'Q731082', 'Q731164', 'Q731261', 'Q731310', 'Q731335', 'Q731401', 'Q731436', 'Q731555', 'Q731645', 'Q731646', 'Q731769', 'Q731776', 'Q731855', 'Q732022', 'Q732071', 'Q732130', 'Q732230', 'Q732241']
    # for entity_id in set(items_to_edit):
    #     z = add_RT_claims_to_item(entity_id)
    #     count += z
    #     print(z, entity_id)
    #     if count == 30:
    #         break



    # Q18152569 Meadowland
    # Q28936 Cloud Atlas
    print(most_recent_score('Q15154975'))
    print(most_recent_score('Q15154975', score_type='average'))
    print(entityid_from_movieid('m/maRVels_the_avengers'))



