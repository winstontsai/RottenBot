# This module is for editing Rotten Tomatoes scores on Wikidata.
###############################################################################
import json
import logging
import sys
import time

from concurrent.futures import as_completed, ThreadPoolExecutor
from datetime import date


import pywikibot as pwb
import pywikibot.data.sparql as sparql
import regex as re

from pywikibot import Claim, ItemPage, Site

from scraper import RTmovie, USER_AGENT

logger = logging.getLogger(__name__)
################################################################################
SITE = Site('wikidata', 'wikidata')
SITE.login(user='RottenBot')

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
P_NAMED_AS                  = 'P1810'

class RTID_to_QID:
    def __init__(self):
        query = "SELECT ?item ?itemLabel ?rtid WHERE{?item wdt:P1258 ?rtid.FILTER REGEX(?rtid, '^m/')}"
        data = dict()
        for z in get_results(query):
            qid = z['item']['value'].rpartition('/')[2]
            rtid = z['rtid']['value'].lower()
            data[rtid] = qid
        self.data = data

    def __getitem__(self, rtid):
        return self.data.get(rtid, None)

    def __setitem__(self, rtid, value):
        if type(rtid) != str or type(value) != str:
            return
        if not re.fullmatch('m/[-a-z0-9_]+', rtid) or not re.fullmatch('Q[0-9]+', value):
            return
        self.data[rtid] = value


def make_claim(pid, target):
    """
    Return pwb.Claim object for entity with pid and specified target.
    """
    c = Claim(SITE, pid)
    c.setTarget(target)
    return c

def make_item(qid):
    return ItemPage(SITE, qid)

def get_results(query):
    headers = dict(sparql.DEFAULT_HEADERS)
    headers['User-Agent'] = USER_AGENT
    data = sparql.SparqlQuery().query(query, headers)
    return data['results']['bindings']

def date_from_claim(c):
    """
    Returns "point in time" date, otherwise "retrieved" date, otherwise
    date(1, 1, 3) if rank is preferred, date(1,1,2) if  normal,
    and date(1, 1, 1) if deprecated.
    """
    q = c.qualifiers
    if P_POINT_IN_TIME in q:
            wbtime = q[P_POINT_IN_TIME][0].target
            y, m, d = wbtime.year or 1, wbtime.month or 1, wbtime.day or 1
            return date(y, m, d)

    if c.sources:
        retrieved = c.sources[0].get(P_RETRIEVED)
        if retrieved:
            wbtime = retrieved[0].target
            y, m, d = wbtime.year or 1, wbtime.month or 1, wbtime.day or 1
            return date(y, m, d)

    if c.rank == 'preferred':
        return date(1, 1, 3)
    if c.rank == 'normal':
        return date(1, 1, 2)
    return date(1, 1, 1)

def most_recent_score_data(item):
    """
    Returns most recent score, count, and average on Wikidata.
    Return value is a triple of strings (score, count, average),
    each being the value of the corresponding Wikidata claim,
    e.g. '69%' not '69'.
    Empty strings are used for missing data.
    """
    score, count, average = '', '', ''
    newest_date = date(1,1,1)
    for c in item.claims.get(P_REVIEW_SCORE, []):
        q = c.qualifiers
        if c.rank == 'deprecated' or c.snaktype != 'value':
            continue
        if P_REVIEW_COUNT not in q or P_DETERMINATION_METHOD not in q:
            continue
        if q[P_DETERMINATION_METHOD][0].target.id != Q_TOMATOMETER:
            continue

        if (review_date := date_from_claim(c)) >= newest_date:
            newest_date = review_date
            score = c.target
            count = q[P_REVIEW_COUNT][0].target.amount

    # find corresponding average rating, if it exists
    if score:
        for c in item.claims.get(P_REVIEW_SCORE, []):
            q = c.qualifiers
            if c.rank == 'deprecated' or c.snaktype != 'value':
                continue
            if P_DETERMINATION_METHOD not in q:
                continue
            if q[P_DETERMINATION_METHOD][0].target.id != Q_ROTTEN_TOMATOES_AVERAGE:
                continue

            if date_from_claim(c) == newest_date:
                average = c.target
                break
    return score, str(count), average

def score_claims_from_movie(movie):
    """
    Assuming that movie has tomatometer_score.
    """
    score, count, average = movie.tomatometer_score
    # manage average format
    if average == '': # in rare cases, no average is available
        pass
    elif '00' in average:
        average = average.partition('.')[0] + '/10'
    else:
        average = str(float(average)) + '/10'

    percent_claim = make_claim(P_REVIEW_SCORE, score + '%')
    average_claim = make_claim(P_REVIEW_SCORE, average)

    # set up qualifiers
    RTitem = make_item(Q_ROTTEN_TOMATOES)
    d, m, y = map(int, date.today().strftime('%d %m %Y').split())
    wbtimetoday = pwb.WbTime(y, m, d, site = SITE)
    review_score_by = make_claim(P_REVIEW_SCORE_BY, RTitem)
    review_quantity = pwb.WbQuantity(amount=count,
        unit="http://www.wikidata.org/entity/Q80698083", # unit = critic review
        site=SITE
    )
    number_of_reviews = make_claim(P_REVIEW_COUNT, review_quantity)
    point_in_time = make_claim(P_POINT_IN_TIME, wbtimetoday)
    percent_method = make_claim(P_DETERMINATION_METHOD, make_item(Q_TOMATOMETER))
    average_method = make_claim(P_DETERMINATION_METHOD, make_item(Q_ROTTEN_TOMATOES_AVERAGE))
    
    # set up reference
    statedin = make_claim(P_STATED_IN, RTitem)
    rtid_claim = make_claim(P_ROTTEN_TOMATOES_ID, movie.short_url)
    title = make_claim(P_TITLE, pwb.WbMonolingualText(movie.title, 'en'))
    languageofwork = make_claim(P_LANGUAGE, make_item(Q_ENGLISH))
    retrieved = make_claim(P_RETRIEVED, wbtimetoday)
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

def should_add_RT_claims(movie, item):
    if not movie.tomatometer_score:
        return False
    new_score, new_count, new_average = movie.tomatometer_score
    new_score = int(new_score)
    new_count = int(new_count)
    if new_average:
        new_average = float(new_average)

    old_score, old_count, old_average = most_recent_score_data(item)

    if m := re.fullmatch(r'([0-9]|[1-9][0-9]|100)(%| percent)', old_score):
        old_score = int(m[1])
    else:
        return True

    if re.fullmatch(r'\d+', old_count):
        old_count = int(old_count)
    else:
        return True
    
    if old_average:
        if m := re.fullmatch(r'(([0-9]|10)(\.\d\d?)?)(?:/| out of )10', old_average):
            old_average = float(m[1])
        else:
            return True
    return (old_score, old_count, old_average)!=(new_score, new_count, new_average)

def add_RT_claims_to_item(movie, item):
    percent_claim, average_claim = score_claims_from_movie(movie)
    item.addClaim(percent_claim, summary='Add Rotten Tomatoes score.')
    item.addClaim(average_claim, summary='Add Rotten Tomatoes average rating.')

def update_RTmovie_data(movie, item):
    """
    Adds/updates the Rotten Tomatoes data in a Wikidata item.
    Currently this means the Rotten Tomatoes ID and the two score claims.
    """
    print(f"Checking item {item.id} aka {item.labels.get('en')}...",
        end='', flush=True)

    changed = False
    title = movie.title

    if 'en' not in item.labels:
        try:
            item.editLabels({'en': title},
                summary=f'Add English label "{title}".')
            changed = True
        except pwb.exceptions.OtherPageSaveError:
            pass
    en_label = item.labels.get('en', title)

    titlediff = title.lower() != en_label.lower()
    if titlediff:
        en_aliases = item.aliases.get('en', [])
        if title.lower() not in (x.lower() for x in en_aliases):
            item.editAliases({'en': en_aliases + [title]},
                summary=f'Add English alias "{title}".')
            changed = True

    # Ensure Rotten Tomatoes ID statement is up-to-date.
    # Also add P_NAMED_AS qualifier if needed.
    rtid_claims = item.claims.get(P_ROTTEN_TOMATOES_ID, [])
    if rtid_claims:
        x = rtid_claims[0]
        if x.target != movie.short_url:
            x.changeTarget(movie.short_url)
            changed = True
        if titlediff:
            if P_NAMED_AS in x.qualifiers:
                if x.qualifiers[P_NAMED_AS][0].target != title:
                    x.removeQualifiers(x.qualifiers[P_NAMED_AS])
            if P_NAMED_AS not in x.qualifiers:
                x.addQualifier(make_claim(P_NAMED_AS, title))
                changed = True
    else:
        new_claim = make_claim(P_ROTTEN_TOMATOES_ID, movie.short_url)
        if titlediff:
            new_claim.addQualifier(make_claim(P_NAMED_AS, title))
        item.addClaim(new_claim)
        changed = True

    if should_add_RT_claims(movie, item):
        add_RT_claims_to_item(movie, item)
        changed = True

    if changed:
        print(f" UPDATED.", flush=True)
    else:
        print()
    return changed


def update_film_items(id_pairs):
    """
    id_pairs should be list of (qid, rtid) pairs, which can be obtained
    from the Wikidata Query Service.
    """
    j = 0
    for qid, rtid in id_pairs:
        try:
            movie = RTmovie(rtid)
        except Exception:
            print(f'Failed to load {rtid} from item {qid}.')
            continue
        j += update_RTmovie_data(movie, make_item(qid))
    return j

def find_items_to_update():
    """
    Find film items to update by using the Wikidata Query Service to find
    items without a review score qualified by
    Q108403540 (Rotten Tomatoes average rating).
    For use with update_film_items.
    """
    q = """SELECT ?item ?rtid
WHERE 
{
  ?item wdt:P1258 ?rtid.
  FILTER(regex(?rtid, '^m/'))
  FILTER NOT EXISTS {
    ?item p:P444 ?reviewstatement.
    ?reviewstatement pq:P447 wd:Q105584.
    ?reviewstatement pq:P585 ?date.
    FILTER ((12*YEAR(NOW())+MONTH(NOW())) - (12*YEAR(?date)+MONTH(?date)) < 4)
  }
}"""
    p = []
    for r in get_results(q):
        qid = r['item']['value'].rpartition('/')[2]
        rtid = r['rtid']['value']
        p.append(qid, rtid)
    return p

if __name__ == "__main__":
    t0 = time.perf_counter()

    data = json.load(open('storage/film_items_to_update.json'))
    print(len(data))
    start = 0
    print(start)

    print(f'UPDATED {update_film_items(data[start : ])} ITEMS.')

    t1 = time.perf_counter()
    print("TIME ELAPSED =", t1-t0, file = sys.stderr)

