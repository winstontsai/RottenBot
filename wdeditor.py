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
# P585: point in time4
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
    query = f"SELECT ?item ?b WHERE{{?item wdt:P1258 '{movieid}'}}"
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
  ?item p:P444 ?reviewstatement2.
  ?reviewstatement2 pq:P447 wd:Q105584.    # reviewed by Rotten Tomatoes.
  ?reviewstatement2 pq:P459 wd:Q108403540. # determination method
  ?reviewstatement2 ps:P444 ?average.
  ?reviewstatement2 pq:P585 ?time1.
  # only get most recent point in time
  filter not exists {
    ?item p:P444 ?reviewstatement3.
    ?reviewstatement3 pq:P447 wd:Q105584.   # reviewed by Rotten Tomatoes.
    ?reviewstatement3 pq:P585 ?time2.
    filter (?time2 > ?time1)
  }
}"""
    query = query.replace('?item', 'wd:'+entity_id)
    data = get_results(query)
    if data:
        data = data[0]
        return data['score']['value'], data['count']['value'], data['average']['value']

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

    current_score, current_count, current_average = map(float, movie.tomatometer_score)
    old_score_data = most_recent_score_data(item.getID())
    if old_score_data is None:
        return score_claims_from_movie(movie)
    else:
        old_score, old_count, old_average = old_score_data

    if m := re.fullmatch(r'([0-9]|[1-9][0-9]|100)(%| percent)', old_score):
        old_score = float(m[1])
    else:
        return score_claims_from_movie(movie)
    
    if m := re.fullmatch(r'(([0-9]|10)(\.\d\d?)?)(?:/| out of )10', old_average):
        old_average = float(m[1])
    else:
        return score_claims_from_movie(movie)

    if m := re.fullmatch(r'\d+', old_count):
        old_count = float(m[0])
    else:
        return score_claims_from_movie(movie)

    if (old_score, old_count, old_average)!=(current_score, current_count, current_average):
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

    percent_claim = pwb.Claim(site, 'P444')
    percent_claim.setTarget(score + '%')
    average_claim = pwb.Claim(site, 'P444')
    average_claim.setTarget(average + '/10')

    # qualifiers
    review_score_by = pwb.Claim(site, 'P447')
    review_score_by.setTarget(pwb.ItemPage(site, 'Q105584')) # Rotten Tomatoes

    number_of_reviews = pwb.Claim(site, 'P7887')
    review_quantity = pwb.WbQuantity(amount=count,
        unit="http://www.wikidata.org/entity/Q80698083", # critic review
        site=site
    )
    number_of_reviews.setTarget(review_quantity)

    point_in_time = pwb.Claim(site, 'P585')
    point_in_time.setTarget(wbtimetoday)

    percent_method = pwb.Claim(site, 'P459')
    percent_method.setTarget(pwb.ItemPage(site, 'Q108403393')) # RT score
    average_method = pwb.Claim(site, 'P459')
    average_method.setTarget(pwb.ItemPage(site, 'Q108403540')) # RT average rating
    
    # reference
    statedin = pwb.Claim(site, 'P248')
    statedin.setTarget(pwb.ItemPage(site, 'Q105584'))
    title = pwb.Claim(site, 'P1476')
    title.setTarget(pwb.WbMonolingualText(movie.title, 'en'))
    languageofwork = pwb.Claim(site, 'P407')
    languageofwork.setTarget(pwb.ItemPage(site, 'Q1860'))
    publisher = pwb.Claim(site, 'P123')
    publisher.setTarget(pwb.ItemPage(site, 'Q5433722'))
    refURL = pwb.Claim(site, 'P854')
    refURL.setTarget(movie.url)
    retrieved = pwb.Claim(site, 'P813')
    retrieved.setTarget(wbtimetoday)
    source_order = [title, statedin, publisher, languageofwork, refURL, retrieved]

    # set up qualifiers, reference, and rank for percent claim
    for x in [review_score_by, number_of_reviews, point_in_time, percent_method]:
        percent_claim.addQualifier(x)
    percent_claim.addSources(source_order)
    percent_claim.setRank('preferred')

    # set up qualifiers, reference, and rank for average claim
    for x in [review_score_by, point_in_time, average_method]:
        average_claim.addQualifier(x)
    average_claim.addSources(source_order)
    average_claim.setRank('preferred')

    return [percent_claim, average_claim]


def add_RT_claims_to_item(item_id):
    time.sleep(5)  # slow down editing
    item = pwb.ItemPage(site, item_id)

    if z := should_add_RT_claims(item):
        percent_claim, average_claim = z
    else:
        return False

    # set rank of all existing RT score claims to 'normal'
    for c in item.claims.get('P444', []):
        if 'P447' in c.qualifiers: # review by
            # check that review is by Rotten Tomatoes
            val = c.qualifiers['P447'][0].getTarget()
            if not isinstance(val, pwb.ItemPage) or val.getID()!='Q105584':
                continue
            # changed 'preferred' ranks to 'normal'
            if c.rank == 'preferred':
                c.changeRank('normal')

    item.addClaim(percent_claim, summary='Add Rotten Tomatoes score. Test edit. See [[Wikidata:Requests for permissions/Bot/RottenBot]].')
    item.addClaim(average_claim, summary='Add Rotten Tomatoes average rating. Test edit. See [[Wikidata:Requests for permissions/Bot/RottenBot]].')
    return True


def add_RTmovie_data_to_item(movie, item):
    if 'P1258' in item.claims:
        item.claims['P1258'][0].changeTarget(movie.short_url)
    else:
        rtid_claim = pwb.Claim(site, 'P1258')
        rtid_claim.setTarget(movie.short_url)
        item.addClaim(rtid_claim)

    if not movie.tomatometer_score:
        return

    

def set_Rotten_Tomatoes_ID(item):
    pass


if __name__ == "__main__":
    site = pwb.Site('wikidata', 'wikidata')
    site.login()


    # count = 0
    # items_to_edit = ['Q2345' ]
    # for entity_id in items_to_edit:
    #     z = add_RT_claims_to_item(entity_id)
    #     count += z
    #     print(z, entity_id)
    #     if count == 30:
    #         break


    # print(most_recent_score_data('Q28936'))
    # print(entityid_from_movieid('m/maRVels_the_avengers'))


    x = json.load(open('/Users/winston/Downloads/query.json'))['results']['bindings']

    check_these = []
    for result in x[1136:5000]:
        movieid = result['rtid']['value']
        try:
            movie = RTMovie(movieid)
        except Exception:
            continue
        z = movie.tomatometer_score
        print(z, movie.title)
        if z and not re.fullmatch(average_re, z[2]+'/10'):
            check_these.append(movie.title)
            print("FOUND IT", movie.title)

    print(check_these)

